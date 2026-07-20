"""
mqtt_client.py  —  koneksi ke MQTT broker & handler pesan masuk dari IoT.
"""
import json
import logging
from datetime import datetime

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)
_mqtt_client = None


def get_threshold(app) -> dict:
    """Ambil threshold dari database."""
    with app.app_context():
        from app.models.models import AppSetting
        return {
            "nh3_warn":   float(AppSetting.get("nh3_warn",   0.5)),
            "nh3_danger": float(AppSetting.get("nh3_danger", 1.0)),
            "suhu_min":   float(AppSetting.get("suhu_min",   25)),
            "suhu_max":   float(AppSetting.get("suhu_max",   32)),
            "ph_min":     float(AppSetting.get("ph_min",     6.5)),
            "ph_max":     float(AppSetting.get("ph_max",     8.5)),
        }


def _on_connect(client, userdata, flags, rc, properties=None):
    app = userdata["app"]
    cfg = userdata["config"]
    if rc == 0:
        log.info("MQTT terhubung ke broker")
        client.subscribe(cfg["MQTT_TOPIC_SUBSCRIBE"], qos=1)
        client.subscribe(cfg["MQTT_TOPIC_LWT"], qos=1)
    else:
        log.error(f"MQTT gagal connect, rc={rc}")


def _on_disconnect(client, userdata, rc, properties=None, reason_code=None):
    log.warning(f"MQTT terputus, rc={rc}. Reconnect otomatis...")


def _on_message(client, userdata, msg):
    app    = userdata["app"]
    topic  = msg.topic
    payload= msg.payload.decode("utf-8", errors="replace")
    qos    = msg.qos

    with app.app_context():
        from app.models.models import Kolam, SensorLog, db
        from app.services.services import (
            hitung_nh3,
            tentukan_status,
            kirim_alert,
            buat_pesan_alert,
            buat_pesan_offline,
            buat_pesan_pulih,
            should_send_alert,
            should_send_recovery_notification,
        )

        # ── LWT / status topic ────────────────────────────────────────────────
        if "/status" in topic:
            kolam = Kolam.query.filter_by(lwt_topic=topic).first()
            if kolam and payload.lower() == "offline":
                previous_status = kolam.status
                kolam.status = "offline"
                kolam.last_seen = datetime.now()
                db.session.commit()

                pesan = buat_pesan_offline(app, kolam.nama, "—", "—", "—", "offline")
                kirim_alert(app, kolam.id, "offline", pesan)
                log.info(f"LWT offline: {kolam.nama}")
            elif kolam and payload.lower() == "normal":
                previous_status = kolam.status
                kolam.status = "online"
                kolam.last_seen = datetime.now()
                db.session.commit()

                if should_send_recovery_notification(app, kolam.id, previous_status, "normal"):
                    pesan = buat_pesan_pulih(app, kolam.nama, "—", "—", "—", "normal")
                    kirim_alert(app, kolam.id, "recovery", pesan)
                    log.info(f"LWT normal recovery: {kolam.nama}")
            return

        # ── Data topic ────────────────────────────────────────────────────────
        kolam = Kolam.query.filter_by(mqtt_topic=topic).first()
        if not kolam:
            log.warning(f"Topic tidak dikenal: {topic}")
            return

        # Parse payload JSON
        ph = suhu = nh3 = None
        parse_ok = False
        try:
            data  = json.loads(payload)
            ph    = float(data["ph"])
            suhu  = float(data["suhu"])
            calculated_nh3 = hitung_nh3(ph, suhu)
            if "nh3" in data and data["nh3"] not in (None, ""):
                try:
                    nh3 = float(data["nh3"])
                except Exception:
                    nh3 = calculated_nh3
            else:
                nh3 = calculated_nh3
            parse_ok = True
        except Exception as e:
            log.error(f"Parse error topic {topic}: {e} | payload: {payload}")

        # Tentukan status
        if parse_ok:
            cfg    = get_threshold(app)
            status = tentukan_status(nh3, suhu, ph, cfg)
        else:
            status = "parse_error"

        # Simpan log
        slog = SensorLog(
            kolam_id=kolam.id,
            mqtt_topic=topic,
            ph=ph, suhu=suhu, nh3=nh3,
            qos=qos,
            status=status,
            raw_payload=payload,
        )
        db.session.add(slog)

        previous_status = kolam.status

        # Update kolam
        if parse_ok:
            kolam.status    = status if status in ("waspada","bahaya") else "online"
            kolam.last_seen = datetime.now()
        db.session.commit()

        # Kirim alert Telegram jika perlu
        if status in ("waspada", "bahaya"):
            if should_send_alert(app, kolam.id):
                pesan = buat_pesan_alert(app, kolam.nama, nh3, ph, suhu, status)
                kirim_alert(app, kolam.id, status, pesan)
        elif should_send_recovery_notification(app, kolam.id, previous_status, status):
            pesan = buat_pesan_pulih(app, kolam.nama, nh3, ph, suhu, status)
            kirim_alert(app, kolam.id, "recovery", pesan)

        log.info(f"[{topic}] pH={ph} suhu={suhu} NH3={nh3} → {status}")


def init_mqtt(app):
    """Inisialisasi koneksi MQTT. Dipanggil dari create_app()."""
    global _mqtt_client
    cfg = app.config

    client = mqtt.Client(
        client_id=cfg["MQTT_CLIENT_ID"],
        userdata={"app": app, "config": app.config},
        protocol=mqtt.MQTTv311,
    )
    
    if cfg["MQTT_USERNAME"]:
        client.username_pw_set(cfg["MQTT_USERNAME"], cfg["MQTT_PASSWORD"])

    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    try:
        client.connect(cfg["MQTT_HOST"], cfg["MQTT_PORT"], keepalive=60)
        client.loop_start()
        _mqtt_client = client
        log.info(f"MQTT loop dimulai → {cfg['MQTT_HOST']}:{cfg['MQTT_PORT']}")
    except Exception as e:
        log.error(f"Gagal konek MQTT: {e}")

    return client


def get_mqtt_client():
    return _mqtt_client
