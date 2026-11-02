import asyncio
import socket
import unittest
from httpx import AsyncClient, ASGITransport

from main import find_available_port
from braincam.web.app import app
from braincam.config import settings
from braincam.db.session import init_db

class TestSystemIntegrationAndLaunch(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        await init_db()

    def test_find_available_port_prevents_winerror_10048(self):
        """Verifies that find_available_port safely skips occupied ports without Errno 10048"""
        # 1. Bind port 8000
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock1.bind(("0.0.0.0", 8000))

        # Check port detection
        resolved_port = find_available_port(8000)
        self.assertNotEqual(resolved_port, 8000)
        self.assertEqual(resolved_port, 8001)

        # 2. Also bind port 8001
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock2.bind(("0.0.0.0", 8001))

        resolved_port_2 = find_available_port(8000)
        self.assertEqual(resolved_port_2, 8002)

        sock1.close()
        sock2.close()

    async def test_health_check_endpoint_and_registered_components(self):
        """Verifies /health endpoint returns HTTP 200 and all components are registered"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.get("/health")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["service"], "BrainCam AI")
            self.assertIn("components", data)

            comps = data["components"]
            self.assertEqual(comps["database"]["status"], "healthy")
            self.assertEqual(comps["fastapi_web"]["status"], "running")
            self.assertEqual(comps["scheduler"]["status"], "registered")
            self.assertIn("ai_vision_and_audio", comps)
            self.assertIn("camera_integrator", comps)
            self.assertIn("telegram_bot", comps)

if __name__ == "__main__":
    unittest.main()
