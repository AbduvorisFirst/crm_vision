import os
import io
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from braincam.config import settings
from braincam.db.session import get_db, init_db, async_session
from braincam.db.models import Organization, Camera, User, CameraEvent, DailyReport, EventTypeEnum, Alert
from braincam.video.rtsp_capture import RTSPCaptureService
from braincam.video.mass_scanner import MassCameraIntegrator
from braincam.ai.gemini_service import gemini_service
from braincam.services.analytics_service import AnalyticsService
from braincam.services.notification_service import NotificationService

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI Video & Audio Analytics SaaS for Retail, Cafes and Stores",
    version="1.0.0"
)

# Template engine
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# In-memory storage for live snapshots pushed by Local Edge Agents
LATEST_EDGE_FRAMES: Dict[int, bytes] = {}

# Request schemas
class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    camera_type: str = "entrance"
    has_audio: bool = False
    location_name: Optional[str] = "Главный филиал"

class LanguageUpdate(BaseModel):
    language: str # "ru" or "uz"
    telegram_id: Optional[int] = None
    org_id: Optional[int] = None

class ChatMessageRequest(BaseModel):
    message: str
    language: Optional[str] = "ru"
    store_id: Optional[int] = 1

@app.on_event("startup")
async def on_startup():
    await init_db()
    # Ensure default organization and demo cameras exist
    async with async_session() as session:
        stmt = select(Organization).limit(1)
        res = await session.execute(stmt)
        org = res.scalar_one_or_none()
        if not org:
            org = Organization(name="Магазин №1 Чиланзар", language="ru")
            session.add(org)
            await session.flush()

            cam1 = Camera(
                org_id=org.id,
                name="Камера 1 — Главный Вход",
                rtsp_url="demo://entrance",
                camera_type="entrance",
                has_audio=False,
                status="online"
            )
            cam2 = Camera(
                org_id=org.id,
                name="Камера 2 — Зона Кассы",
                rtsp_url="demo://checkout",
                camera_type="checkout",
                has_audio=True,
                status="online"
            )
            session.add_all([cam1, cam2])

            # Seed sample events for today so dashboard has live realistic analytics
            await AnalyticsService.record_event(session, org.id, 1, EventTypeEnum.ENTRY.value, count=148)
            await AnalyticsService.record_event(session, org.id, 2, EventTypeEnum.PURCHASE.value, count=41)
            await AnalyticsService.record_event(session, org.id, 2, EventTypeEnum.COMPLAINT.value, count=1)
            await session.commit()

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Renders Merchant Web Dashboard"""
    return templates.TemplateResponse(request=request, name="dashboard.html", context={})

@app.get("/miniapp", response_class=HTMLResponse)
async def get_miniapp(request: Request):
    """Renders Mobile Telegram Mini App"""
    return templates.TemplateResponse(request=request, name="miniapp.html", context={})

class MiniAppRegistration(BaseModel):
    full_name: str
    phone: str
    store_name: str
    business_category: str
    city: str
    instagram: str
    camera_count: int = 1
    telegram_id: Optional[int] = None
    username: Optional[str] = None

class ReportTimeUpdate(BaseModel):
    report_time: str

@app.post("/api/v1/miniapp/register")
async def register_from_miniapp(data: MiniAppRegistration, db: AsyncSession = Depends(get_db)):
    """Handles registration directly from the smartphone Mini App"""
    org = Organization(name=data.store_name, language="ru")
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        telegram_id=data.telegram_id or 12345678,
        username=data.username,
        full_name=data.full_name,
        phone=data.phone,
        store_name=data.store_name,
        business_category=data.business_category,
        city=data.city,
        instagram=data.instagram,
        camera_count=data.camera_count,
        status="pending"
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Notify admin @abdvoris07
    if settings.TELEGRAM_BOT_TOKEN:
        try:
            from aiogram import Bot
            from braincam.bot.main_bot import notify_admin
            from braincam.bot.keyboards import get_admin_approval_keyboard
            bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
            admin_text = (
                f"🔔 <b>НОВАЯ ЗАЯВКА ИЗ TELEGRAM MINI APP!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>ФИО:</b> {data.full_name}\n"
                f"📞 <b>Телефон:</b> {data.phone}\n"
                f"🏬 <b>Магазин:</b> {data.store_name}\n"
                f"🏷 <b>Категория:</b> {data.business_category}\n"
                f"📍 <b>Локация:</b> {data.city}\n"
                f"📸 <b>Instagram:</b> {data.instagram}\n"
                f"📹 <b>Камер:</b> {data.camera_count} шт.\n"
                f"💬 <b>Telegram:</b> @{data.username or 'без_юзернейма'} (ID: <code>{data.telegram_id}</code>)\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"Одобрите или отклоните заявку:"
            )
            await notify_admin(bot, admin_text, reply_markup=get_admin_approval_keyboard(user.id))
        except Exception as e:
            pass

    return {"status": "success", "user_id": user.id}

@app.post("/api/v1/settings/report-time")
async def update_report_time(data: ReportTimeUpdate, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(User).limit(1))
    u = res.scalar_one_or_none()
    if u:
        u.daily_report_time = data.report_time
        await db.commit()
    return {"status": "ok", "report_time": data.report_time}

@app.get("/edge_agent/braincam_agent.py")
async def download_edge_agent():
    """Serves downloadable Edge Agent script for local camera network onboarding"""
    agent_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "edge_agent", "braincam_agent.py")
    if os.path.exists(agent_path):
        return FileResponse(agent_path, filename="braincam_agent.py")
    raise HTTPException(status_code=404, detail="Agent file not found")

# ================= REST API /api/v1 =================

@app.get("/api/v1/cameras")
async def list_cameras(db: AsyncSession = Depends(get_db)):
    """Returns list of cameras"""
    res = await db.execute(select(Camera))
    return res.scalars().all()

@app.post("/api/v1/cameras")
async def create_camera(data: CameraCreate, db: AsyncSession = Depends(get_db)):
    """Registers a new camera"""
    cam = Camera(
        org_id=1,
        name=data.name,
        rtsp_url=data.rtsp_url,
        camera_type=data.camera_type,
        has_audio=data.has_audio,
        status="online"
    )
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return cam

@app.delete("/api/v1/cameras/{camera_id}")
async def delete_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    """Deletes a camera from the database"""
    res = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = res.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    await db.execute(delete(Alert).where(Alert.camera_id == camera_id))
    await db.delete(cam)
    await db.commit()
    return {"status": "deleted", "id": camera_id}

@app.get("/api/v1/cameras/{camera_id}/snapshot")
async def get_camera_snapshot(camera_id: int, db: AsyncSession = Depends(get_db)):
    """Returns single frame snapshot from camera stream or edge agent buffer"""
    if camera_id in LATEST_EDGE_FRAMES:
        return Response(content=LATEST_EDGE_FRAMES[camera_id], media_type="image/jpeg")

    res = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = res.scalar_one_or_none()
    url = cam.rtsp_url if cam else "demo"
    title = cam.name if cam else f"Camera #{camera_id}"

    frame_bytes = RTSPCaptureService.get_snapshot(url)
    return Response(content=frame_bytes, media_type="image/jpeg")

@app.post("/api/v1/cameras/{camera_id}/heartbeat")
async def camera_heartbeat(camera_id: int, payload: Optional[Dict[str, Any]] = None, db: AsyncSession = Depends(get_db)):
    """Receives heartbeat signal from Local Edge Agent"""
    res = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = res.scalar_one_or_none()
    if cam:
        cam.status = "online"
        await db.commit()
    return {"status": "ok", "camera_id": camera_id, "state": "online"}

@app.post("/api/v1/cameras/{camera_id}/upload-frame")
async def upload_camera_frame(camera_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Receives live snapshot pushed from Local Edge Agent on private LAN"""
    content = await file.read()
    if content:
        LATEST_EDGE_FRAMES[camera_id] = content
        res = await db.execute(select(Camera).where(Camera.id == camera_id))
        cam = res.scalar_one_or_none()
        if cam and cam.status != "online":
            cam.status = "online"
            await db.commit()
    return {"status": "ok", "camera_id": camera_id, "bytes_received": len(content)}

@app.get("/api/v1/cameras/vendor-templates")
async def get_vendor_templates():
    """Returns vendor connection guides and RTSP templates for Hikvision, Dahua, Uniview, XM"""
    return {
        "templates": MassCameraIntegrator.VENDOR_TEMPLATES,
        "instructions": MassCameraIntegrator.get_vendor_instructions()
    }

@app.post("/api/v1/cameras/{camera_id}/analyze")
async def analyze_camera(camera_id: int, db: AsyncSession = Depends(get_db)):
    """Runs instant Gemini AI analysis on camera live snapshot"""
    res = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = res.scalar_one_or_none()
    url = cam.rtsp_url if cam else "demo"
    cam_type = cam.camera_type if cam else "entrance"
    
    org_res = await db.execute(select(Organization).limit(1))
    org = org_res.scalar_one_or_none()
    lang = org.language if org else "ru"
    
    frame_bytes = RTSPCaptureService.get_snapshot(url)
    analysis = await gemini_service.analyze_frame(frame_bytes, camera_type=cam_type, language=lang)
    return {
        "status": "success",
        "camera_id": camera_id,
        "camera_name": cam.name if cam else f"Camera #{camera_id}",
        "camera_type": cam_type,
        "analysis": analysis
    }

@app.get("/api/v1/cameras/scan-subnet")
async def scan_subnet(subnet: str = "192.168.1"):
    """Scans local subnet for RTSP cameras"""
    devices = await MassCameraIntegrator.scan_subnet(subnet_prefix=subnet, start_host=1, end_host=25)
    return {"subnet": subnet, "devices": devices}

@app.get("/api/v1/cameras/template.csv")
async def download_csv_template():
    """Downloads sample CSV for bulk camera import"""
    csv_text = MassCameraIntegrator.get_sample_csv_template()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cameras_template.csv"}
    )

@app.post("/api/v1/cameras/bulk-upload")
async def bulk_upload_cameras(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Bulk imports cameras from CSV file with encoding autodetection"""
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = raw_bytes.decode("cp1251", errors="replace")

    parsed_cameras = MassCameraIntegrator.parse_csv_cameras(content)

    created = []
    for c in parsed_cameras:
        cam = Camera(
            org_id=1,
            name=c["name"],
            rtsp_url=c["rtsp_url"],
            camera_type=c["camera_type"],
            has_audio=c["has_audio"],
            status="online"
        )
        db.add(cam)
        created.append(c["name"])

    await db.commit()
    return {"message": f"Успешно импортировано {len(created)} камер", "cameras": created}

@app.get("/api/v1/analytics/daily")
async def get_daily_analytics(db: AsyncSession = Depends(get_db)):
    """Returns today's retail KPI analytics for dashboard"""
    return await AnalyticsService.get_daily_metrics(db, org_id=1)

@app.post("/api/v1/settings/language")
async def update_language(data: LanguageUpdate, db: AsyncSession = Depends(get_db)):
    """Updates language preference (ru or uz) for organization and dashboard and user"""
    if data.language not in ["ru", "uz"]:
        raise HTTPException(status_code=400, detail="Language must be 'ru' or 'uz'")

    # 1. Update Organization
    org_stmt = select(Organization)
    if data.org_id:
        org_stmt = org_stmt.where(Organization.id == data.org_id)
    org_res = await db.execute(org_stmt)
    org = org_res.scalars().first()
    if org:
        org.language = data.language

    # 2. Update User(s) so future Telegram daily reports and notifications use chosen language
    user_stmt = select(User)
    if data.telegram_id:
        user_stmt = user_stmt.where(User.telegram_id == data.telegram_id)
    elif org:
        user_stmt = user_stmt.where(User.org_id == org.id)

    user_res = await db.execute(user_stmt)
    users = user_res.scalars().all()
    for u in users:
        u.language = data.language

    await db.commit()
    return {"status": "ok", "language": data.language}

@app.post("/api/v1/reports/dispatch-telegram")
async def dispatch_telegram_report(db: AsyncSession = Depends(get_db)):
    """Forces daily KPI report dispatch to merchant's Telegram"""
    res = await db.execute(select(Organization).limit(1))
    org = res.scalar_one_or_none()
    user_res = await db.execute(select(User).where(User.org_id == (org.id if org else 1)).limit(1))
    user = user_res.scalar_one_or_none()

    lang = (user.language if user else None) or (org.language if org else None) or "ru"
    report = await AnalyticsService.generate_or_update_daily_report(db, org_id=(org.id if org else 1))

    # If Telegram bot is active, send it
    if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        try:
            from aiogram import Bot
            bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
            if user and user.telegram_id:
                store_name = user.store_name or (org.name if org else "Магазин")
                text = NotificationService.format_daily_digest(report, store_name=store_name, language=lang)
                await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
                return {"message": f"Отчет отправлен в Telegram на языке: {lang.upper()}!"}
        except Exception as e:
            return {"message": f"Ошибка отправки Telegram: {e}"}

    return {"message": f"Отчет сгенерирован (Язык: {lang.upper()})! Настройте TELEGRAM_BOT_TOKEN в .env для автодоставки."}

@app.post("/api/v1/audio/analyze-demo")
async def analyze_audio_demo(db: AsyncSession = Depends(get_db)):
    """Demonstrates audio complaints analysis using Gemini"""
    res = await db.execute(select(Organization).limit(1))
    org = res.scalar_one_or_none()
    lang = org.language if org else "ru"
    return await gemini_service.analyze_audio(b"sample_audio_bytes", language=lang)

@app.post("/api/v1/chat/message")
async def chat_message(data: ChatMessageRequest, db: AsyncSession = Depends(get_db)):
    """Conversational AI assistant for merchant inquiries and recommendations"""
    metrics = await AnalyticsService.get_daily_metrics(db, org_id=data.store_id or 1)
    answer = await gemini_service.answer_merchant_question(
        question=data.message,
        store_context=metrics,
        language=data.language or "ru"
    )
    return {"reply": answer, "status": "ok"}

@app.get("/health")
async def health_check():
    """Health status endpoint reporting status of all system components"""
    db_status = "healthy"
    try:
        async with async_session() as session:
            await session.execute(select(1))
    except Exception as e:
        db_status = f"unhealthy: {e}"

    bot_configured = bool(settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your_"))
    ai_configured = bool(settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("your_"))
    all_healthy = db_status == "healthy"

    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": "BrainCam AI",
        "gemini_model": settings.GEMINI_MODEL,
        "components": {
            "database": {
                "status": db_status,
                "url": settings.DATABASE_URL.split("///")[-1]
            },
            "fastapi_web": {
                "status": "running",
                "host": settings.HOST,
                "port": settings.PORT
            },
            "telegram_bot": {
                "status": "configured" if bot_configured else "skipped (token unconfigured)",
                "admin_username": settings.ADMIN_TELEGRAM_USERNAME
            },
            "scheduler": {
                "status": "registered",
                "features": ["daily_kpi_reports", "trial_reminders", "auto_expiry"]
            },
            "ai_vision_and_audio": {
                "status": "ready" if ai_configured else "ready (fallback/demo mode)",
                "primary_model": settings.GEMINI_MODEL,
                "fallback_model": settings.GEMINI_FALLBACK_MODEL
            },
            "camera_integrator": {
                "status": "ready",
                "rtsp_capture": "active",
                "mass_subnet_scanner": "active",
                "csv_bulk_import": "active"
            }
        }
    }
