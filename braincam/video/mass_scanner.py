import socket
import csv
import io
import asyncio
from typing import List, Dict, Any, Optional

class MassCameraIntegrator:
    """
    Mass Camera Onboarding & Discovery Service.
    Enables clients and merchants to rapidly connect tens or hundreds of cameras:
      1. Bulk CSV/Excel/JSON import (supports Russian & English headers, UTF-8 BOM, comma/semicolon)
      2. Automated local network subnet scanner for RTSP / ONVIF ports (554, 8554, 80, 8000, 37777, 34567)
      3. Vendor RTSP URL template generator & connection instructions for:
         - Hikvision / HiWatch / Ezviz
         - Dahua / Imou
         - Uniview (UNV)
         - Xiongmai (XM / XMeye)
         - Tiandy
         - Generic ONVIF / RTSP
    """

    VENDOR_TEMPLATES = {
        "hikvision": "rtsp://{user}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
        "hikvision_sub": "rtsp://{user}:{password}@{ip}:{port}/Streaming/Channels/{channel}02",
        "hiwatch": "rtsp://{user}:{password}@{ip}:{port}/Streaming/Channels/{channel}01",
        "ezviz": "rtsp://{user}:{password}@{ip}:{port}/h264/ch{channel}/main/av_stream",
        "dahua": "rtsp://{user}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
        "dahua_sub": "rtsp://{user}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=1",
        "imou": "rtsp://{user}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0",
        "uniview": "rtsp://{user}:{password}@{ip}:{port}/unicast/c{channel}/s0/live",
        "uniview_sub": "rtsp://{user}:{password}@{ip}:{port}/unicast/c{channel}/s1/live",
        "unv": "rtsp://{user}:{password}@{ip}:{port}/unicast/c{channel}/s0/live",
        "xiongmai": "rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel={channel}&stream=0.sdp?",
        "xiongmai_sub": "rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel={channel}&stream=1.sdp?",
        "xm": "rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel={channel}&stream=0.sdp?",
        "xmeye": "rtsp://{user}:{password}@{ip}:{port}/user={user}&password={password}&channel={channel}&stream=0.sdp?",
        "tiandy": "rtsp://{user}:{password}@{ip}:{port}/video1",
        "generic": "rtsp://{user}:{password}@{ip}:{port}/live/ch{channel}"
    }

    @classmethod
    def generate_rtsp_url(
        cls,
        vendor: str,
        ip: str,
        port: int = 554,
        user: str = "admin",
        password: str = "admin",
        channel: int = 1,
        substream: bool = False
    ) -> str:
        """Generates standard RTSP stream URL for common camera brands with substream support"""
        key = vendor.lower().strip()
        if substream:
            sub_key = f"{key}_sub"
            if sub_key in cls.VENDOR_TEMPLATES:
                key = sub_key

        template = cls.VENDOR_TEMPLATES.get(key, cls.VENDOR_TEMPLATES["generic"])
        return template.format(user=user, password=password, ip=ip, port=port, channel=channel)

    @staticmethod
    def get_vendor_instructions() -> Dict[str, Any]:
        """
        Returns structured documentation and cheat-sheet for connecting all major camera brands.
        """
        return {
            "hikvision": {
                "name": "Hikvision / HiWatch / Ezviz",
                "default_ip": "192.168.1.64",
                "default_port": 554,
                "default_user": "admin",
                "main_stream": "rtsp://{user}:{password}@{ip}:554/Streaming/Channels/{channel}01",
                "sub_stream": "rtsp://{user}:{password}@{ip}:554/Streaming/Channels/{channel}02",
                "notes_ru": "Для AI рекомендуется субпоток (Channels/102). В веб-интерфейсе камеры: Настройки -> Сеть -> Доп. настройки -> Протокол интеграции -> Включить ONVIF и создать пользователя.",
                "notes_uz": "AI uchun sub-oqim (Channels/102) tavsiya etiladi. Kamera veb-panelida: Sozlamalar -> Tarmoq -> ONVIF-ni yoqish kerak."
            },
            "dahua": {
                "name": "Dahua / Imou",
                "default_ip": "192.168.1.108",
                "default_port": 554,
                "default_user": "admin",
                "main_stream": "rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
                "sub_stream": "rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel={channel}&subtype=1",
                "notes_ru": "Субпоток (subtype=1) экономит трафик при аналитике. Убедитесь, что порт 554 не блокируется брандмауэром.",
                "notes_uz": "Sub-oqim (subtype=1) tahlil vaqtida internet trafigini tejaydi. 554 port ochiqligini tekshiring."
            },
            "uniview": {
                "name": "Uniview (UNV)",
                "default_ip": "192.168.1.13",
                "default_port": 554,
                "default_user": "admin",
                "main_stream": "rtsp://{user}:{password}@{ip}:554/unicast/c{channel}/s0/live",
                "sub_stream": "rtsp://{user}:{password}@{ip}:554/unicast/c{channel}/s1/live",
                "notes_ru": "Канал c1 соответствует первой камере/линзе, s0 - основной поток, s1 - субпоток.",
                "notes_uz": "c1 - birinchi kamera, s0 - asosiy oqim, s1 - ikkinchi (sub) oqim."
            },
            "xiongmai": {
                "name": "Xiongmai / XM / XMeye (NETSurveillance)",
                "default_ip": "192.168.1.10",
                "default_port": 554,
                "default_user": "admin",
                "main_stream": "rtsp://{user}:{password}@{ip}:554/user={user}&password={password}&channel={channel}&stream=0.sdp?",
                "sub_stream": "rtsp://{user}:{password}@{ip}:554/user={user}&password={password}&channel={channel}&stream=1.sdp?",
                "notes_ru": "Популярные бюджетные китайские регистраторы и камеры XMeye. Порт по умолчанию 554 или 34567.",
                "notes_uz": "Ommabop hamyonbop XMeye kameralari va NVR registratorlari. Odatiy port 554 yoki 34567."
            },
            "edge_agent": {
                "name": "Local Edge Agent (Без белого IP)",
                "description_ru": "Если камеры находятся внутри закрытой локальной сети магазина (192.168.x.x) и у роутера нет статического белого IP, запускается легковесный BrainCam Edge Agent.",
                "description_uz": "Agar kameralar do'konning yopiq lokal tarmog'ida bo'lsa va oq statik IP bo'lmasa, BrainCam Edge Agent ishga tushiriladi.",
                "quick_start": [
                    "1. Скачайте agent: GET /edge_agent/braincam_agent.py",
                    "2. Установите зависимости: pip install opencv-python requests",
                    "3. Запустите: python braincam_agent.py --server http://<SERVER_IP>:8000 --camera-id <ID> --rtsp rtsp://admin:pass@192.168.1.101:554/..."
                ]
            }
        }

    @staticmethod
    async def scan_ip_port(ip: str, port: int, timeout: float = 0.4) -> bool:
        """Asynchronously checks if an IP port is open with safe cleanup"""
        try:
            conn = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(conn, timeout=timeout)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=0.2)
            except Exception:
                pass
            return True
        except Exception:
            return False

    @classmethod
    async def scan_subnet(
        cls,
        subnet_prefix: str = "192.168.1",
        start_host: int = 1,
        end_host: int = 50,
        ports: List[int] = [554, 8554, 8000, 37777, 34567]
    ) -> List[Dict[str, Any]]:
        """
        Scans a local subnet range (e.g. 192.168.1.1 to 192.168.1.50) for camera ports.
        Returns list of discovered camera hosts with brand hints.
        """
        discovered = []

        async def check_host(host_num: int):
            ip = f"{subnet_prefix}.{host_num}"
            open_ports = []
            for port in ports:
                if await cls.scan_ip_port(ip, port):
                    open_ports.append(port)
            if open_ports:
                # Brand heuristic
                brand_guess = "Generic RTSP IP Camera"
                if 8000 in open_ports or ip.endswith(".64"):
                    brand_guess = "Hikvision / HiWatch"
                elif 37777 in open_ports or ip.endswith(".108"):
                    brand_guess = "Dahua / Imou"
                elif 34567 in open_ports or ip.endswith(".10"):
                    brand_guess = "Xiongmai (XM / XMeye)"
                elif ip.endswith(".13"):
                    brand_guess = "Uniview (UNV)"

                sample_rtsp = f"rtsp://admin:admin@{ip}:554/Streaming/Channels/101"
                if "Dahua" in brand_guess:
                    sample_rtsp = f"rtsp://admin:admin@{ip}:554/cam/realmonitor?channel=1&subtype=0"
                elif "Uniview" in brand_guess:
                    sample_rtsp = f"rtsp://admin:admin@{ip}:554/unicast/c1/s0/live"
                elif "Xiongmai" in brand_guess:
                    sample_rtsp = f"rtsp://admin:admin@{ip}:554/user=admin&password=admin&channel=1&stream=0.sdp?"

                discovered.append({
                    "ip": ip,
                    "ports": open_ports,
                    "brand_guess": brand_guess,
                    "probable_device": "IP Camera / NVR" if any(p in open_ports for p in [554, 8554, 37777, 34567]) else "Network Device",
                    "sample_rtsp": sample_rtsp
                })

        tasks = [check_host(i) for i in range(start_host, min(end_host + 1, 255))]
        await asyncio.gather(*tasks)
        return sorted(discovered, key=lambda x: [int(p) for p in x["ip"].split(".")])

    @staticmethod
    def parse_csv_cameras(csv_content: str, default_org_id: int = 1) -> List[Dict[str, Any]]:
        """
        Parses bulk camera configuration CSV files.
        Robustly handles:
          - UTF-8 with BOM (\ufeff)
          - Comma (,) and semicolon (;) separators
          - Russian, Uzbek, and English column headers
          - Leading/trailing whitespace
        """
        if not csv_content:
            return []

        # Strip UTF-8 BOM if present
        clean_content = csv_content.lstrip("\ufeff").strip()
        if not clean_content:
            return []

        # Detect delimiter (semicolon is standard in Russian Excel)
        first_line = clean_content.splitlines()[0]
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","

        cameras = []
        reader = csv.DictReader(io.StringIO(clean_content), delimiter=delimiter)
        for raw_row in reader:
            if not raw_row:
                continue

            # Normalize keys to lowercase stripped
            row = {str(k).strip().lower(): str(v).strip() for k, v in raw_row.items() if k is not None and v is not None}

            # Flexible column lookup
            name = (
                row.get("name") or row.get("название") or row.get("имя") or
                row.get("камера") or row.get("camera") or row.get("title")
            )
            rtsp = (
                row.get("rtsp_url") or row.get("rtsp") or row.get("url") or
                row.get("stream") or row.get("ссылка") or row.get("поток") or
                row.get("rtsp_link")
            )
            cam_type = (
                row.get("camera_type") or row.get("type") or row.get("тип") or
                row.get("зона") or row.get("zone") or "entrance"
            ).lower()

            has_audio_val = (
                row.get("has_audio") or row.get("audio") or row.get("микрофон") or
                row.get("звук") or row.get("mic") or "false"
            ).lower()
            has_audio = has_audio_val in ["true", "1", "yes", "да", "ha", "bor"]

            location = (
                row.get("location_name") or row.get("location") or row.get("филиал") or
                row.get("локация") or row.get("магазин") or row.get("store") or "Главный филиал"
            )

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
Вход Главный (Hikvision),rtsp://admin:12345@192.168.1.101:554/Streaming/Channels/101,entrance,false,Магазин Чиланзар
Касса 1 (Dahua),rtsp://admin:12345@192.168.1.102:554/cam/realmonitor?channel=1&subtype=0,checkout,true,Магазин Чиланзар
Касса 2 (Uniview),rtsp://admin:12345@192.168.1.103:554/unicast/c1/s0/live,checkout,true,Магазин Чиланзар
Торговый зал (XMeye),rtsp://admin:12345@192.168.1.104:554/user=admin&password=12345&channel=1&stream=0.sdp?,hall,false,Магазин Чиланзар
Склад (HiWatch),rtsp://admin:12345@192.168.1.105:554/Streaming/Channels/101,hall,false,Магазин Чиланзар
"""
