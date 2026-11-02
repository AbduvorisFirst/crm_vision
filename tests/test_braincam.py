import asyncio
import unittest
from datetime import datetime, timezone
from braincam.db.session import init_db, async_session
from braincam.db.models import Organization, Camera, User, CameraEvent, EventTypeEnum
from braincam.services.analytics_service import AnalyticsService
from braincam.services.notification_service import NotificationService
from braincam.ai.gemini_service import gemini_service
from braincam.video.mass_scanner import MassCameraIntegrator

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

if __name__ == "__main__":
    unittest.main()
