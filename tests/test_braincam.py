import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from braincam.db.session import init_db, async_session
from braincam.db.models import Organization, Camera, User, CameraEvent, EventTypeEnum, UserStatusEnum
from braincam.services.analytics_service import AnalyticsService
from braincam.services.notification_service import NotificationService
from braincam.services.scheduler_service import BrainCamScheduler
from braincam.ai.gemini_service import gemini_service
from braincam.video.mass_scanner import MassCameraIntegrator
from braincam.bot.keyboards import get_main_keyboard
from braincam.web.app import app

class TestBrainCamAI(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        await init_db()

    async def test_analytics_and_conversion_calculation(self):
        """Tests that footfall, purchases, and conversion rate calculate correctly"""
        async with async_session() as session:
            # Create test merchant organization
            org = Organization(name="Тестовый супермаркет", language="ru")
            session.add(org)
            await session.flush()

            cam = Camera(org_id=org.id, name="Камера Тест", rtsp_url="demo", camera_type="entrance")
            session.add(cam)
            await session.flush()

            # Record 100 visitors and 25 purchases
            await AnalyticsService.record_event(session, org.id, cam.id, EventTypeEnum.ENTRY.value, count=100)
            await AnalyticsService.record_event(session, org.id, cam.id, EventTypeEnum.PURCHASE.value, count=25)
            await AnalyticsService.record_event(session, org.id, cam.id, EventTypeEnum.COMPLAINT.value, count=1)

            # Compute daily metrics
            metrics = await AnalyticsService.get_daily_metrics(session, org.id)
            self.assertEqual(metrics["visitors_count"], 100)
            self.assertEqual(metrics["buyers_count"], 25)
            self.assertEqual(metrics["conversion_rate"], 25.0)
            self.assertEqual(metrics["complaints_count"], 1)

            # Test daily report generation
            report = await AnalyticsService.generate_or_update_daily_report(session, org.id)
            self.assertEqual(report.conversion_rate, 25.0)

            # Test Russian report format
            ru_text = NotificationService.format_daily_digest(report, store_name="Тестовый супермаркет", language="ru")
            self.assertIn("Конверсия", ru_text)
            self.assertIn("100", ru_text)
            self.assertIn("25", ru_text)

            # Test Uzbek report format
            uz_text = NotificationService.format_daily_digest(report, store_name="Тестовый супермаркет", language="uz")
            self.assertIn("Konversiya", uz_text)
            self.assertIn("Tashrif buyuruvchilar", uz_text)

    async def test_mass_camera_csv_parser(self):
        """Tests parsing CSV files for bulk camera onboarding"""
        csv_sample = """name,rtsp_url,camera_type,has_audio,location_name
Камера Вход,rtsp://192.168.1.10:554/live,entrance,false,Филиал 1
Камера Касса,rtsp://192.168.1.11:554/live,checkout,true,Филиал 1
"""
        cameras = MassCameraIntegrator.parse_csv_cameras(csv_sample)
        self.assertEqual(len(cameras), 2)
        self.assertEqual(cameras[0]["name"], "Камера Вход")
        self.assertTrue(cameras[1]["has_audio"])

    async def test_gemini_vision_and_audio_fallbacks(self):
        """Tests that AI service gracefully produces realistic structured data even without external internet"""
        v_res = await gemini_service.analyze_frame(b"dummy_bytes", camera_type="checkout", language="ru")
        self.assertIn("people_count", v_res)
        self.assertIn("employee_analysis", v_res)

        a_res = await gemini_service.analyze_audio(b"dummy_bytes", language="uz")
        self.assertIn("transcript_summary", a_res)
        self.assertIn("complaints_detected", a_res)

    def test_main_keyboard_layout(self):
        """Asserts that get_main_keyboard contains exactly 3 buttons in both RU and UZ layouts"""
        for lang in ["ru", "uz"]:
            for https_val in [True, False]:
                with patch("braincam.bot.keyboards.is_https_enabled", return_value=https_val):
                    kb = get_main_keyboard(language=lang, days_left=7)
                    all_buttons = [btn for row in kb.keyboard for btn in row]
                    self.assertEqual(
                        len(all_buttons),
                        3,
                        f"Expected exactly 3 buttons for lang='{lang}' (https={https_val}), found {len(all_buttons)}"
                    )
                    self.assertEqual(len(kb.keyboard), 3, "Keyboard must have 3 rows with 1 button each")

        # Verify button text specifics in Russian
        kb_ru = get_main_keyboard(language="ru", days_left=7)
        ru_texts = [btn.text for row in kb_ru.keyboard for btn in row]
        self.assertEqual(ru_texts[0], "📊 Отчет за сегодня")
        self.assertEqual(ru_texts[1], "💳 Сколько осталось оплата")
        self.assertEqual(ru_texts[2], "📱 Войти в Mini App")

        # Verify button text specifics in Uzbek
        kb_uz = get_main_keyboard(language="uz", days_left=7)
        uz_texts = [btn.text for row in kb_uz.keyboard for btn in row]
        self.assertEqual(uz_texts[0], "📊 Bugungi hisobot")
        self.assertEqual(uz_texts[1], "💳 Qolgan muddat va to'lov")
        self.assertEqual(uz_texts[2], "📱 Mini App-ga kirish")

    async def test_chat_message_endpoint(self):
        """Asserts valid response from AI chat endpoint POST /api/v1/chat/message"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # 1. Test endpoint with mocked AI answer to verify contract and response format
            with patch.object(gemini_service, "answer_merchant_question", return_value="Сегодня у вас 100 посетителей и 25 покупок. Конверсия 25.0%."):
                payload = {
                    "message": "Какая сегодня статистика и конверсия?",
                    "language": "ru",
                    "store_id": 1
                }
                res = await ac.post("/api/v1/chat/message", json=payload)
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data.get("status"), "ok")
                self.assertIn("reply", data)
                self.assertIsInstance(data["reply"], str)
                self.assertTrue(len(data["reply"]) > 0)
                self.assertIn("100 посетителей", data["reply"])

            # 2. Test fallback generation in Uzbek without mock
            payload_uz = {
                "message": "Bugungi xaridorlar soni qancha?",
                "language": "uz",
                "store_id": 1
            }
            res_uz = await ac.post("/api/v1/chat/message", json=payload_uz)
            self.assertEqual(res_uz.status_code, 200)
            data_uz = res_uz.json()
            self.assertEqual(data_uz.get("status"), "ok")
            self.assertIn("reply", data_uz)
            self.assertTrue(len(data_uz["reply"]) > 0)

    async def test_delete_camera_endpoint(self):
        """Asserts successful camera deletion via DELETE /api/v1/cameras/{id}"""
        async with async_session() as session:
            org = Organization(name="Магазин для удаления", language="ru")
            session.add(org)
            await session.flush()

            cam = Camera(
                org_id=org.id,
                name="Камера Удаления",
                rtsp_url="rtsp://192.168.1.150:554/ch0",
                camera_type="entrance"
            )
            session.add(cam)
            await session.commit()
            cam_id = cam.id

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Verify camera exists and delete it
            res = await ac.delete(f"/api/v1/cameras/{cam_id}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data.get("status"), "deleted")
            self.assertEqual(data.get("id"), cam_id)

            # Assert camera is removed from database
            async with async_session() as session:
                db_res = await session.execute(select(Camera).where(Camera.id == cam_id))
                self.assertIsNone(db_res.scalar_one_or_none())

            # Assert subsequent deletion returns 404
            res_404 = await ac.delete(f"/api/v1/cameras/{cam_id}")
            self.assertEqual(res_404.status_code, 404)

    async def test_offset_naive_datetime_calculations(self):
        """Asserts offset-naive datetime calculations for trial and subscription without TypeError"""
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        now_aware = datetime.now(timezone.utc)

        # 1. Active trial with offset-naive datetime
        user_naive_trial = User(
            full_name="Trial Naive",
            telegram_id=9001,
            status=UserStatusEnum.ACTIVE.value,
            trial_starts_at=now_naive - timedelta(days=2),
            trial_ends_at=now_naive + timedelta(days=5),
            is_paid=False
        )
        self.assertTrue(user_naive_trial.is_access_granted())
        self.assertGreaterEqual(user_naive_trial.days_left(), 4)

        # 2. Active trial with offset-aware datetime (verifies tzinfo compatibility)
        user_aware_trial = User(
            full_name="Trial Aware",
            telegram_id=9002,
            status=UserStatusEnum.ACTIVE.value,
            trial_starts_at=now_aware - timedelta(days=2),
            trial_ends_at=now_aware + timedelta(days=5),
            is_paid=False
        )
        self.assertTrue(user_aware_trial.is_access_granted())
        self.assertGreaterEqual(user_aware_trial.days_left(), 4)

        # 3. Expired trial (both naive and aware)
        user_expired_trial = User(
            full_name="Expired Trial",
            telegram_id=9003,
            status=UserStatusEnum.ACTIVE.value,
            trial_starts_at=now_naive - timedelta(days=10),
            trial_ends_at=now_naive - timedelta(days=1),
            is_paid=False
        )
        self.assertFalse(user_expired_trial.is_access_granted())
        self.assertEqual(user_expired_trial.days_left(), 0)

        # 4. Paid active subscription with naive datetime
        user_paid_naive = User(
            full_name="Paid Naive",
            telegram_id=9004,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=True,
            paid_until=now_naive + timedelta(days=30)
        )
        self.assertTrue(user_paid_naive.is_access_granted())
        self.assertGreaterEqual(user_paid_naive.days_left(), 29)

        # 5. Paid active subscription with aware datetime
        user_paid_aware = User(
            full_name="Paid Aware",
            telegram_id=9005,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=True,
            paid_until=now_aware + timedelta(days=30)
        )
        self.assertTrue(user_paid_aware.is_access_granted())
        self.assertGreaterEqual(user_paid_aware.days_left(), 29)

        # 6. Expired paid subscription
        user_paid_expired = User(
            full_name="Expired Paid",
            telegram_id=9006,
            status=UserStatusEnum.ACTIVE.value,
            is_paid=True,
            paid_until=now_naive - timedelta(days=2)
        )
        self.assertFalse(user_paid_expired.is_access_granted())
        self.assertEqual(user_paid_expired.days_left(), 0)

        # 7. Non-active statuses
        for i, st in enumerate([UserStatusEnum.PENDING.value, UserStatusEnum.EXPIRED.value, UserStatusEnum.REJECTED.value]):
            u = User(full_name=f"User {st}", telegram_id=9010 + i, status=st, trial_ends_at=now_naive + timedelta(days=5))
            self.assertFalse(u.is_access_granted())

        # 8. Integration test with BrainCamScheduler.check_trial_reminders
        async with async_session() as session:
            from sqlalchemy import delete
            await session.execute(delete(User).where(User.telegram_id.in_([990011, 990022])))
            await session.commit()

        async with async_session() as session:
            # Create user expiring soon and user already expired with mixed naive/aware datetimes
            u_remind = User(
                telegram_id=990011,
                full_name="Reminder User",
                status=UserStatusEnum.ACTIVE.value,
                is_paid=False,
                trial_ends_at=now_aware + timedelta(days=2, hours=1),
                reminders_sent=0
            )
            u_expired = User(
                telegram_id=990022,
                full_name="Already Expired User",
                status=UserStatusEnum.ACTIVE.value,
                is_paid=False,
                trial_ends_at=now_naive - timedelta(days=1),
                reminders_sent=3
            )
            session.add(u_remind)
            session.add(u_expired)
            await session.commit()

        mock_bot = AsyncMock()
        await BrainCamScheduler.check_trial_reminders(mock_bot)

        async with async_session() as session:
            res_remind = await session.execute(select(User).where(User.telegram_id == 990011))
            user_remind_db = res_remind.scalar_one()
            self.assertEqual(user_remind_db.reminders_sent, 1)

            res_expired = await session.execute(select(User).where(User.telegram_id == 990022))
            user_expired_db = res_expired.scalar_one()
            self.assertEqual(user_expired_db.status, UserStatusEnum.EXPIRED.value)

    async def test_mass_camera_csv_advanced(self):
        """Tests Excel CSV with BOM, semicolon delimiter, and multilingual headers"""
        # Russian Excel CSV format with semicolon and BOM
        excel_csv = "\ufeffНазвание;Ссылка;Тип;Микрофон;Филиал\n" \
                    "Камера Вход;rtsp://admin:pass@192.168.1.101:554/live;entrance;нет;Ташкент Центр\n" \
                    "Камера Касса 1;rtsp://admin:pass@192.168.1.102:554/live;checkout;да;Ташкент Центр\n"
        cameras = MassCameraIntegrator.parse_csv_cameras(excel_csv)
        self.assertEqual(len(cameras), 2)
        self.assertEqual(cameras[0]["name"], "Камера Вход")
        self.assertFalse(cameras[0]["has_audio"])
        self.assertEqual(cameras[1]["name"], "Камера Касса 1")
        self.assertTrue(cameras[1]["has_audio"])

    def test_vendor_rtsp_templates_and_instructions(self):
        """Tests RTSP template generator and vendor documentation"""
        # Hikvision main and sub-stream
        hik_main = MassCameraIntegrator.generate_rtsp_url("hikvision", "192.168.1.64", user="admin", password="123", substream=False)
        self.assertIn("/Streaming/Channels/101", hik_main)
        hik_sub = MassCameraIntegrator.generate_rtsp_url("hikvision", "192.168.1.64", user="admin", password="123", substream=True)
        self.assertIn("/Streaming/Channels/102", hik_sub)

        # Dahua
        dahua_main = MassCameraIntegrator.generate_rtsp_url("dahua", "192.168.1.108", user="admin", password="123", substream=False)
        self.assertIn("subtype=0", dahua_main)
        dahua_sub = MassCameraIntegrator.generate_rtsp_url("dahua", "192.168.1.108", user="admin", password="123", substream=True)
        self.assertIn("subtype=1", dahua_sub)

        # Uniview
        unv_sub = MassCameraIntegrator.generate_rtsp_url("uniview", "192.168.1.13", user="admin", password="123", substream=True)
        self.assertIn("unicast/c1/s1/live", unv_sub)

        # Xiongmai
        xm_sub = MassCameraIntegrator.generate_rtsp_url("xiongmai", "192.168.1.10", user="admin", password="123", substream=True)
        self.assertIn("stream=1.sdp?", xm_sub)

        # Vendor instructions
        guides = MassCameraIntegrator.get_vendor_instructions()
        self.assertIn("hikvision", guides)
        self.assertIn("dahua", guides)
        self.assertIn("uniview", guides)
        self.assertIn("xiongmai", guides)
        self.assertIn("edge_agent", guides)

    def test_edge_agent_and_api_endpoints(self):
        """Tests edge agent file delivery and heartbeat/upload API endpoints"""
        from fastapi.testclient import TestClient
        from braincam.web.app import app

        client = TestClient(app)

        # 1. Edge agent file download
        resp = client.get("/edge_agent/braincam_agent.py")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BrainCamEdgeAgent", resp.text)
        self.assertIn("Hikvision", resp.text)
        self.assertIn("Dahua", resp.text)

        # 2. Vendor templates endpoint
        resp_v = client.get("/api/v1/cameras/vendor-templates")
        self.assertEqual(resp_v.status_code, 200)
        self.assertIn("instructions", resp_v.json())

        # 3. Heartbeat endpoint
        resp_hb = client.post("/api/v1/cameras/1/heartbeat", json={"status": "online"})
        self.assertEqual(resp_hb.status_code, 200)
        self.assertEqual(resp_hb.json()["status"], "ok")

        # 4. Upload frame endpoint
        fake_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        resp_up = client.post("/api/v1/cameras/1/upload-frame", files={"file": ("snap.jpg", fake_jpg, "image/jpeg")})
        self.assertEqual(resp_up.status_code, 200)

        # 5. Snapshot retrieval returns edge agent frame
        resp_snap = client.get("/api/v1/cameras/1/snapshot")
        self.assertEqual(resp_snap.status_code, 200)
        self.assertEqual(resp_snap.content, fake_jpg)

if __name__ == "__main__":
    unittest.main()
