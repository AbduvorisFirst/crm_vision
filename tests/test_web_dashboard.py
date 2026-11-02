import asyncio
import unittest
from httpx import AsyncClient, ASGITransport
from braincam.web.app import app
from braincam.db.session import init_db

class TestWebDashboardPortal(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        await init_db()

    async def test_dashboard_html_rendering_and_elements(self):
        """Verifies dashboard.html renders and contains all required features"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            self.assertEqual(resp.status_code, 200)
            html = resp.text

            # 1. Retail KPIs (Traffic, Sales, Conversion, Complaints, Staff Score)
            self.assertIn('kpi-visitors', html)
            self.assertIn('kpi-buyers', html)
            self.assertIn('kpi-conversion', html)
            self.assertIn('kpi-employee', html)
            self.assertIn('kpi-complaints', html)
            self.assertIn('kpi-peak', html)

            # 2. Interactive AI Chat section / modal connecting to /api/v1/chat/message
            self.assertIn('section-ai-chat', html)
            self.assertIn('/api/v1/chat/message', html)
            self.assertIn('chat-input', html)
            self.assertIn('chat-send-btn', html)
            self.assertIn('chat-messages', html)
            self.assertIn('askQuickPrompt', html)

            # 3. Live RTSP camera snapshot and camera management
            self.assertIn('section-cameras', html)
            self.assertIn('add-camera-modal', html)
            self.assertIn('camera-ai-modal', html)
            self.assertIn('openAddCameraModal', html)
            self.assertIn('loadCameras', html)
            self.assertIn('/api/v1/cameras', html)
            self.assertIn('snapshot', html)

            # 4. Check no broken JS function calls
            self.assertIn('function refreshAnalytics', html)
            self.assertIn('function loadCameras', html)
            self.assertIn('function openAddCameraModal', html)
            self.assertIn('function closeAddCameraModal', html)
            self.assertIn('function saveNewCamera', html)
            self.assertIn('function deleteCamera', html)
            self.assertIn('function addFoundCamera', html)
            self.assertIn('function uploadCsvCameras', html)
            self.assertIn('function runCameraAiAnalysis', html)

    async def test_api_chat_message(self):
        """Tests POST /api/v1/chat/message for merchant inquiry on traffic, conversion, and staff"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Query about footfall and conversion
            payload = {
                "message": "Какой трафик посетителей и конверсия за сегодня?",
                "language": "ru",
                "store_id": 1
            }
            resp = await client.post("/api/v1/chat/message", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("reply", data)
            self.assertTrue(len(data["reply"]) > 10)

            # Query in Uzbek about staff
            payload_uz = {
                "message": "Kassada xodimlar intizomi va ishi qanday?",
                "language": "uz",
                "store_id": 1
            }
            resp_uz = await client.post("/api/v1/chat/message", json=payload_uz)
            self.assertEqual(resp_uz.status_code, 200)
            data_uz = resp_uz.json()
            self.assertIn("reply", data_uz)
            self.assertTrue(len(data_uz["reply"]) > 10)

    async def test_camera_crud_and_snapshot(self):
        """Tests camera listing, creation, snapshot, and analysis"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create camera
            new_cam = {
                "name": "Тестовая Камера Зал",
                "rtsp_url": "demo://hall",
                "camera_type": "hall",
                "has_audio": True
            }
            create_resp = await client.post("/api/v1/cameras", json=new_cam)
            self.assertEqual(create_resp.status_code, 200)
            cam_data = create_resp.json()
            cam_id = cam_data["id"]

            # 2. List cameras
            list_resp = await client.get("/api/v1/cameras")
            self.assertEqual(list_resp.status_code, 200)
            cameras = list_resp.json()
            self.assertTrue(any(c["id"] == cam_id for c in cameras))

            # 3. Snapshot
            snap_resp = await client.get(f"/api/v1/cameras/{cam_id}/snapshot")
            self.assertEqual(snap_resp.status_code, 200)
            self.assertEqual(snap_resp.headers["content-type"], "image/jpeg")

            # 4. Instant AI analysis
            ai_resp = await client.post(f"/api/v1/cameras/{cam_id}/analyze")
            self.assertEqual(ai_resp.status_code, 200)
            ai_data = ai_resp.json()
            self.assertIn("analysis", ai_data)
            self.assertIn("people_count", ai_data["analysis"])

            # 5. Delete camera
            del_resp = await client.delete(f"/api/v1/cameras/{cam_id}")
            self.assertEqual(del_resp.status_code, 200)

    async def test_retail_kpis_endpoint(self):
        """Tests GET /api/v1/analytics/daily for all required retail KPIs"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/analytics/daily")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("visitors_count", data)
            self.assertIn("buyers_count", data)
            self.assertIn("conversion_rate", data)
            self.assertIn("complaints_count", data)
            self.assertIn("employee_score", data)
            self.assertIn("peak_hour", data)

if __name__ == "__main__":
    unittest.main()
