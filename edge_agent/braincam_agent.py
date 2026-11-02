#!/usr/bin/env python3
"""
BrainCam AI — Local Edge Agent
==============================
This lightweight agent runs inside the customer's / merchant's local network (LAN).
It solves the problem where security cameras are behind a local router without a public white IP.

Supported Cameras:
- Hikvision / HiWatch / Ezviz:
    rtsp://admin:password@192.168.1.64:554/Streaming/Channels/102 (Sub-stream recommended)
- Dahua / Imou:
    rtsp://admin:password@192.168.1.108:554/cam/realmonitor?channel=1&subtype=1
- Uniview (UNV):
    rtsp://admin:password@192.168.1.13:554/unicast/c1/s1/live
- Xiongmai / XM / XMeye:
    rtsp://admin:password@192.168.1.10:554/user=admin&password=password&channel=1&stream=1.sdp?

Capabilities:
1. Connects to local RTSP streams (192.168.x.x) on private LAN
2. Decodes periodic snapshots with low latency
3. Securely pushes frames and heartbeats to the BrainCam AI cloud server
"""

import time
import sys
import argparse
import logging

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BrainCamEdgeAgent")

def parse_args():
    parser = argparse.ArgumentParser(
        description="BrainCam AI Edge Agent for Local Network IP Cameras (Hikvision, Dahua, Uniview, XM)",
        epilog="""
Examples:
  Hikvision Sub-stream:
    python braincam_agent.py --server http://127.0.0.1:8000 --camera-id 1 --rtsp "rtsp://admin:12345@192.168.1.64:554/Streaming/Channels/102"

  Dahua Sub-stream:
    python braincam_agent.py --server http://127.0.0.1:8000 --camera-id 2 --rtsp "rtsp://admin:12345@192.168.1.108:554/cam/realmonitor?channel=1&subtype=1"

  Uniview Sub-stream:
    python braincam_agent.py --server http://127.0.0.1:8000 --camera-id 3 --rtsp "rtsp://admin:12345@192.168.1.13:554/unicast/c1/s1/live"

  XM / Xiongmai:
    python braincam_agent.py --server http://127.0.0.1:8000 --camera-id 4 --rtsp "rtsp://admin:12345@192.168.1.10:554/user=admin&password=12345&channel=1&stream=1.sdp?"

  Demo Simulation:
    python braincam_agent.py --server http://127.0.0.1:8000 --camera-id 1 --rtsp demo
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--server", type=str, default="http://localhost:8000", help="BrainCam AI Server URL")
    parser.add_argument("--camera-id", type=int, required=False, default=1, help="Camera ID registered in BrainCam")
    parser.add_argument("--rtsp", type=str, required=False, default="demo", help="Local RTSP Stream URL")
    parser.add_argument("--fps", type=float, default=1.0, help="Snapshot capture interval in seconds (default 1.0s)")
    parser.add_argument("--token", type=str, required=False, default="", help="Optional API Auth Token")
    return parser.parse_args()

def main():
    if not HAS_REQUESTS:
        print("ERROR: 'requests' package is required. Run: pip install requests")
        sys.exit(1)

    args = parse_args()
    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    logger.info("==========================================")
    logger.info(" BrainCam AI — Edge Agent Initializing")
    logger.info(f" Server:     {args.server}")
    logger.info(f" Camera ID:  {args.camera_id}")
    logger.info(f" RTSP URL:   {args.rtsp}")
    logger.info(f" Interval:   {args.fps}s")
    logger.info("==========================================")

    cap = None
    last_reconnect_time = 0

    while True:
        try:
            if args.rtsp == "demo":
                logger.info("Demo mode: Sending heartbeat to BrainCam AI server...")
                resp = requests.post(
                    f"{args.server.rstrip('/')}/api/v1/cameras/{args.camera_id}/heartbeat",
                    json={"status": "online"},
                    headers=headers,
                    timeout=5
                )
                logger.info(f"Server response: {resp.status_code}")
                time.sleep(args.fps)
                continue

            if not HAS_CV2:
                logger.error("OpenCV (cv2) is not installed. Run: pip install opencv-python")
                time.sleep(5)
                continue

            # Maintain persistent VideoCapture connection
            current_time = time.time()
            if cap is None or not cap.isOpened():
                if current_time - last_reconnect_time > 3:
                    logger.info(f"Connecting to RTSP stream: {args.rtsp} ...")
                    cap = cv2.VideoCapture(args.rtsp, cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    last_reconnect_time = current_time

            if cap and cap.isOpened():
                # Grab latest frame (skip stale buffered frames)
                for _ in range(2):
                    cap.grab()
                ret, frame = cap.read()

                if ret and frame is not None and frame.size > 0:
                    _, img_encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    files = {"file": ("frame.jpg", img_encoded.tobytes(), "image/jpeg")}
                    resp = requests.post(
                        f"{args.server.rstrip('/')}/api/v1/cameras/{args.camera_id}/upload-frame",
                        files=files,
                        headers=headers,
                        timeout=10
                    )
                    if resp.status_code == 200:
                        logger.info(f"Frame uploaded successfully. Status: {resp.status_code}")
                    else:
                        logger.warning(f"Server returned status {resp.status_code}: {resp.text}")
                else:
                    logger.warning("Could not read frame from stream. Reconnecting...")
                    cap.release()
                    cap = None
            else:
                logger.warning("RTSP stream is not open. Retrying in 5 seconds...")

            time.sleep(args.fps)
        except KeyboardInterrupt:
            logger.info("Agent stopped by user.")
            if cap:
                cap.release()
            break
        except Exception as e:
            logger.error(f"Error during agent loop: {e}")
            if cap:
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
            time.sleep(5)

if __name__ == "__main__":
    main()
