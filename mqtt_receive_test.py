#!/usr/bin/env python3
"""Simple MQTT receive test for the AmoniaLele server."""

import argparse
import json
import time
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt

from app import create_app
from app.models.models import SensorLog, Kolam
from config.settings import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a test MQTT payload and verify the server recorded it."
    )
    parser.add_argument("--host", default=Config.MQTT_HOST, help="MQTT broker host")
    parser.add_argument("--port", type=int, default=Config.MQTT_PORT, help="MQTT broker port")
    parser.add_argument("--username", default=Config.MQTT_USERNAME, help="MQTT username")
    parser.add_argument("--password", default=Config.MQTT_PASSWORD, help="MQTT password")
    parser.add_argument("--client-id", default="amonialele-test", help="MQTT client id")
    parser.add_argument("--topic", default="lele/test/data", help="MQTT topic to publish")
    parser.add_argument(
        "--payload",
        default=json.dumps({"ph": 7.2, "suhu": 28.5, "nh3": 0.6}),
        help="MQTT JSON payload",
    )
    parser.add_argument("--wait", type=float, default=5.0, help="Seconds to wait for server processing")
    return parser


def publish_test_message(args):
    client = mqtt.Client(client_id=args.client_id, protocol=mqtt.MQTTv5, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if args.username:
        client.username_pw_set(args.username, args.password)

    client.connect(args.host, args.port, keepalive=10)
    client.loop_start()
    result = client.publish(args.topic, args.payload, qos=1)
    result.wait_for_publish()
    print(f"[PUBLISH] topic={args.topic} payload={args.payload}")
    time.sleep(1)
    client.disconnect()
    client.loop_stop()


def check_server_received(args):
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=args.wait + 2)

    app = create_app()
    with app.app_context():
        topic_ok = Kolam.query.filter_by(mqtt_topic=args.topic).first() is not None
        latest_log = (
            SensorLog.query
            .filter_by(mqtt_topic=args.topic)
            .filter(SensorLog.created_at >= cutoff)
            .order_by(SensorLog.created_at.desc())
            .first()
        )

        if not topic_ok:
            print(f"[WARN] Topic '{args.topic}' tidak ditemukan di database Kolam.")
            print("Pastikan topic yang Anda publish cocok dengan kolam yang sudah terdaftar.")
        if latest_log:
            print("[OK] Server menerima pesan MQTT dan menyimpan log berikut:")
            print(f"  waktu   : {latest_log.created_at}")
            print(f"  topic   : {latest_log.mqtt_topic}")
            print(f"  payload : {latest_log.raw_payload}")
            print(f"  ph      : {latest_log.ph}")
            print(f"  suhu    : {latest_log.suhu}")
            print(f"  nh3     : {latest_log.nh3}")
            print(f"  status  : {latest_log.status}")
            return 0

        print("[FAIL] Tidak ada data terbaru untuk topic tersebut di database.")
        print(f"Pastikan server Flask sedang berjalan dan menerima pesan MQTT dalam {args.wait} detik.")
        return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        json.loads(args.payload)
    except Exception as exc:
        print(f"[ERROR] Payload bukan JSON valid: {exc}")
        return 1

    publish_test_message(args)
    print(f"[WAIT] Menunggu server memproses pesan selama {args.wait} detik...")
    time.sleep(args.wait)
    return check_server_received(args)


if __name__ == "__main__":
    raise SystemExit(main())
