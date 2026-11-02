import os
import io
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from braincam.config import settings
from braincam.db.session import get_db, init_db, async_session
from braincam.db.models import Organization, Camera, User, CameraEvent, DailyReport, EventTypeEnum
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

# Request schemas
class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    camera_type: str = "entrance"
    has_audio: bool = False
    location_name: Optional[str] = "Главный филиал"

class LanguageUpdate(BaseModel):
    language: str # "ru" or "uz"

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

@app.get("/api/v1/cameras/{camera_id}/snapshot")
async def get_camera_snapshot(camera_id: int, db: AsyncSession = Depends(get_db)):
    """Returns single frame snapshot from camera stream"""
    res = await db.execute(select(Camera).where(Camera.id == camera_id))
    cam = res.scalar_one_or_none()
    url = cam.rtsp_url if cam else "demo"
    title = cam.name if cam else f"Camera #{camera_id}"

    frame_bytes = RTSPCaptureService.get_snapshot(url)
    return Response(content=frame_bytes, media_type="image/jpeg")

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
    """Bulk imports cameras from CSV file"""
    content = (await file.read()).decode("utf-8")
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
    """Updates language preference (ru or uz) for organization and dashboard"""
    res = await db.execute(select(Organization).limit(1))
    org = res.scalar_one_or_none()
    if org:
        org.language = data.language
        await db.commit()
    return {"status": "ok", "language": data.language}

@app.post("/api/v1/reports/dispatch-telegram")
async def dispatch_telegram_report(db: AsyncSession = Depends(get_db)):
    """Forces daily KPI report dispatch to merchant's Telegram"""
    res = await db.execute(select(Organization).limit(1))
    org = res.scalar_one_or_none()
    lang = org.language if org else "ru"
    report = await AnalyticsService.generate_or_update_daily_report(db, org_id=1)

    # If Telegram bot is active, send it
    if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        try:
            from aiogram import Bot
            bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
            user_res = await db.execute(select(User).where(User.org_id == 1).limit(1))
            user = user_res.scalar_one_or_none()
            if user and user.telegram_id:
                text = NotificationService.format_daily_digest(report, store_name=org.name, language=lang)
                await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
                return {"message": "Отчет отправлен в Telegram!"}
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

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "BrainCam AI",
        "gemini_model": settings.GEMINI_MODEL
    }
