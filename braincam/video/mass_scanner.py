import socket
import csv
import io
import asyncio
from typing import List, Dict, Any

class MassCameraIntegrator:
    """
    Mass Camera Onboarding & Discovery Service.
    Enables clients and merchants to rapidly connect tens or hundreds of cameras:
      1. Bulk CSV/Excel/JSON import
      2. Automated local network subnet scanner for RTSP / ONVIF ports (554, 8554, 80, 8000)
      3. Vendor RTSP URL template generator (Hikvision, Dahua, Uniview, Tiandy, XM, Generic)
    """

    VENDOR_TEMPLATES = {
        "hikvision": "rtsp://{user}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
        "dahua": "rtsp://{user}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
        "uniview": "rtsp://{user}:{password}@{ip}:{port}/unicast/c{channel}/s0/live",
        "xiongmai": "rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel={channel}&stream=0.sdp?",
        "generic": "rtsp://{user}:{password}@{ip}:{port}/live/ch{channel}"
    }

    @staticmethod
    def generate_rtsp_url(vendor: str, ip: str, port: int = 554, user: str = "admin", password: str = "admin", channel: int = 1) -> str:
        """Generates standard RTSP stream URL for common camera brands"""
        template = MassCameraIntegrator.VENDOR_TEMPLATES.get(vendor.lower(), MassCameraIntegrator.VENDOR_TEMPLATES["generic"])
        return template.format(user=user, password=password, ip=ip, port=port, channel=channel)

    @staticmethod
    async def scan_ip_port(ip: str, port: int, timeout: float = 0.4) -> bool:
        """Asynchronously checks if an IP port is open"""
        try:
            conn = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(conn, timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    @classmethod
    async def scan_subnet(cls, subnet_prefix: str = "192.168.1", start_host: int = 1, end_host: int = 50, ports: List[int] = [554, 8554, 8000]) -> List[Dict[str, Any]]:
        """
        Scans a local subnet range (e.g. 192.168.1.1 to 192.168.1.50) for camera ports.
        Returns list of discovered camera hosts.
        """
        discovered = []

        async def check_host(host_num: int):
            ip = f"{subnet_prefix}.{host_num}"
            open_ports = []
            for port in ports:
                if await cls.scan_ip_port(ip, port):
                    open_ports.append(port)
            if open_ports:
                discovered.append({
                    "ip": ip,
                    "ports": open_ports,
                    "probable_device": "IP Camera / NVR" if (554 in open_ports or 8554 in open_ports) else "Network Device",
                    "sample_rtsp": f"rtsp://admin:admin@{ip}:554/Streaming/Channels/101"
                })

        tasks = [check_host(i) for i in range(start_host, min(end_host + 1, 255))]
        await asyncio.gather(*tasks)
        return sorted(discovered, key=lambda x: x["ip"])

    @staticmethod
    def parse_csv_cameras(csv_content: str, default_org_id: int = 1) -> List[Dict[str, Any]]:
        """
        Parses a bulk CSV file containing camera configurations.
        Format expected:
        name,rtsp_url,camera_type,has_audio,location_name
        """
        cameras = []
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            name = row.get("name") or row.get("Name")
            rtsp = row.get("rtsp_url") or row.get("rtsp") or row.get("URL")
            cam_type = (row.get("camera_type") or row.get("type") or "entrance").lower()
            has_audio = str(row.get("has_audio", "false")).lower() in ["true", "1", "yes", "да"]
            location = row.get("location_name") or row.get("location") or "Главный филиал"

            if name and rtsp:
                cameras.append({
                    "name": name.strip(),
                    "rtsp_url": rtsp.strip(),
                    "camera_type": cam_type.strip(),
                    "has_audio": has_audio,
                    "location_name": location.strip()
                })
        return cameras

    @staticmethod
    def get_sample_csv_template() -> str:
        """Returns sample CSV template for merchants to download and fill out"""
        return """name,rtsp_url,camera_type,has_audio,location_name
Вход Главный,rtsp://admin:12345@192.168.1.101:554/Streaming/Channels/101,entrance,false,Магазин Чиланзар
Касса 1,rtsp://admin:12345@192.168.1.102:554/Streaming/Channels/101,checkout,true,Магазин Чиланзар
Касса 2,rtsp://admin:12345@192.168.1.103:554/Streaming/Channels/101,checkout,true,Магазин Чиланзар
Торговый зал,rtsp://admin:12345@192.168.1.104:554/Streaming/Channels/101,hall,false,Магазин Чиланзар
"""
