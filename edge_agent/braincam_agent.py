#!/usr/bin/env python3
"""
BrainCam AI — Local Edge Agent
==============================
This lightweight agent runs inside the customer's / merchant's local network (LAN).
It solves the problem where security cameras are behind a local router without a public white IP.

Capabilities:
1. Connects to local RTSP streams (192.168.x.x)
2. Decodes periodic snapshots or event clips
3. Securely pushes frames and metrics to the BrainCam AI cloud server
"""

import time
import argparse
import logging
import cv2
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BrainCamEdgeAgent")

def parse_args():
    parser = argparse.ArgumentParser(description="BrainCam AI Edge Agent for Local Network Cameras")
    parser.add_argument("--server", type=str, default="http://localhost:8000", help="BrainCam AI Server URL")
    parser.add_argument("--camera-id", type=int, required=False, default=1, help="Camera ID registered in BrainCam")
    parser.add_argument("--rtsp", type=str, required=False, default="demo", help="Local RTSP Stream URL")
    parser.add_argument("--fps", type=float, default=1.0, help="Snapshot capture interval (seconds)")
    return parser.parse_args()

def main():
    args = parse_args()
    logger.info(f"Starting BrainCam Edge Agent for camera ID: {args.camera_id}")
    logger.info(f"Target RTSP: {args.rtsp} | Server: {args.server}")

    while True:
        try:
            if args.rtsp == "demo":
                logger.info("Demo mode: Sending heartbeat to BrainCam AI server...")
                resp = requests.post(
                    f"{args.server}/api/v1/cameras/{args.camera_id}/heartbeat",
                    json={"status": "online"},
                    timeout=5
                )
                logger.info(f"Server response: {resp.status_code}")
            else:
                cap = cv2.VideoCapture(args.rtsp)
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    _, img_encoded = cv2.imencode(".jpg", frame)
                    files = {"file": ("frame.jpg", img_encoded.tobytes(), "image/jpeg")}
                    resp = requests.post(
                        f"{args.server}/api/v1/cameras/{args.camera_id}/upload-frame",
                        files=files,
                        timeout=10
                    )
                    logger.info(f"Frame uploaded successfully. Status: {resp.status_code}")
                else:
                    logger.warning("Failed to grab frame from RTSP stream. Retrying in 5 seconds...")

            time.sleep(args.fps)
        except KeyboardInterrupt:
            logger.info("Agent stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error during agent loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
