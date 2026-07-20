import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from flask import Flask

from app.models.models import AppSetting, Kolam, SensorLog, TelegramLog, db
from app.services.services import (
    buat_pesan_rutin,
    mark_stale_kolam_offline,
    render_message_template,
    should_send_alert,
    should_send_recovery_notification,
    tentukan_status,
)
from app.services import mqtt_client


class MessageTemplateTests(unittest.TestCase):
    def test_kolam_status_accepts_bahaya_value(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data", status="bahaya")
            db.session.add(kolam)
            db.session.commit()

            self.assertEqual(kolam.status, "bahaya")
            db.session.remove()
            db.drop_all()

    def test_render_message_template_replaces_placeholders(self):
        template = "Alert {kolam_nama} | {status} | {waktu}"
        rendered = render_message_template(template, kolam_nama="A-1", status="BAHAYA", waktu="10:00")
        self.assertEqual(rendered, "Alert A-1 | BAHAYA | 10:00")

    def test_tentukan_status_uses_waspada_for_minor_threshold_exceedance(self):
        cfg = {"nh3_warn": 0.5, "nh3_danger": 1.0, "suhu_min": 25, "suhu_max": 32, "ph_min": 6.5, "ph_max": 8.5}
        self.assertEqual(tentukan_status(0.6, 27.0, 7.0, cfg), "waspada")

    def test_tentukan_status_uses_bahaya_for_large_nh3_exceedance(self):
        cfg = {"nh3_warn": 0.5, "nh3_danger": 1.0, "suhu_min": 25, "suhu_max": 32, "ph_min": 6.5, "ph_max": 8.5}
        self.assertEqual(tentukan_status(1.5, 27.0, 7.0, cfg), "bahaya")

    def test_tentukan_status_uses_waspada_for_out_of_range_ph_or_suhu(self):
        cfg = {"nh3_warn": 0.5, "nh3_danger": 1.0, "suhu_min": 25, "suhu_max": 32, "ph_min": 6.5, "ph_max": 8.5}
        self.assertEqual(tentukan_status(0.2, 23.0, 7.0, cfg), "waspada")
        self.assertEqual(tentukan_status(0.2, 27.0, 5.0, cfg), "waspada")

    def test_render_message_template_leaves_unknown_placeholders_unchanged(self):
        template = "Hello {nama}"
        rendered = render_message_template(template, nama="Admin")
        self.assertEqual(rendered, "Hello Admin")

    def test_buat_pesan_rutin_uses_sqlalchemy_order_by_column(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data")
            db.session.add(kolam)
            db.session.commit()

            log = SensorLog(kolam_id=kolam.id, ph=7.0, suhu=28.0, nh3=0.2, status="normal")
            db.session.add(log)
            db.session.commit()

            pesan = buat_pesan_rutin(app, [kolam], sesi="pagi")

            self.assertIn("Kolam A", pesan)
            self.assertIn("NH3:", pesan)
            db.session.remove()
            db.drop_all()

    def test_should_send_alert_honors_30_minute_interval(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            AppSetting.set("notif_interval", "30")
            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data")
            db.session.add(kolam)
            db.session.commit()

            recent_log = TelegramLog(
                kolam_id=kolam.id,
                tipe="bahaya",
                pesan="alert",
                penerima="[]",
                sukses=True,
                created_at=datetime.now() - timedelta(minutes=10),
            )
            db.session.add(recent_log)
            db.session.commit()

            self.assertFalse(should_send_alert(app, kolam.id, now=datetime.now()))

            old_log = TelegramLog(
                kolam_id=kolam.id,
                tipe="bahaya",
                pesan="alert",
                penerima="[]",
                sukses=True,
                created_at=datetime.now() - timedelta(minutes=31),
            )
            db.session.add(old_log)
            db.session.commit()

            self.assertFalse(should_send_alert(app, kolam.id, now=datetime.now()))
            db.session.remove()
            db.drop_all()

    def test_should_send_recovery_notification_when_status_returns_to_normal(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            AppSetting.set("notif_pulih", "1")

            self.assertTrue(should_send_recovery_notification(app, 1, "bahaya", "normal"))
            self.assertFalse(should_send_recovery_notification(app, 1, "normal", "normal"))
            db.session.remove()
            db.drop_all()

    def test_should_send_recovery_notification_when_offline_returns_to_online(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            AppSetting.set("notif_pulih", "1")

            self.assertTrue(should_send_recovery_notification(app, 1, "offline", "online"))
            self.assertFalse(should_send_recovery_notification(app, 1, "online", "online"))
            db.session.remove()
            db.drop_all()

    def test_mark_stale_kolam_offline_uses_existing_offline_notification_path(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            stale_kolam = Kolam(
                nama="Kolam A",
                mqtt_topic="lele/kolam-a/data",
                status="waspada",
                last_seen=datetime.now() - timedelta(minutes=16),
            )
            fresh_kolam = Kolam(
                nama="Kolam B",
                mqtt_topic="lele/kolam-b/data",
                status="bahaya",
                last_seen=datetime.now() - timedelta(minutes=10),
            )
            db.session.add_all([stale_kolam, fresh_kolam])
            db.session.commit()

            with patch("app.services.services.kirim_alert") as mock_kirim_alert:
                changed = mark_stale_kolam_offline(app, timeout_minutes=15)

            db.session.refresh(stale_kolam)
            db.session.refresh(fresh_kolam)

            self.assertEqual(changed, 1)
            self.assertEqual(stale_kolam.status, "offline")
            self.assertEqual(fresh_kolam.status, "bahaya")

            self.assertEqual(mock_kirim_alert.call_count, 1)
            call_args = mock_kirim_alert.call_args[0]
            self.assertEqual(call_args[0], app)
            self.assertEqual(call_args[1], stale_kolam.id)
            self.assertEqual(call_args[2], "offline")
            self.assertIn("OFFLINE", call_args[3])

            db.session.remove()
            db.drop_all()

    def test_mark_stale_kolam_offline_reads_timeout_from_app_setting(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            AppSetting.set("offline_timeout_minutes", "5")
            kolam = Kolam(
                nama="Kolam A",
                mqtt_topic="lele/kolam-a/data",
                status="waspada",
                last_seen=datetime.now() - timedelta(minutes=6),
            )
            db.session.add(kolam)
            db.session.commit()

            with patch("app.services.services.kirim_alert") as mock_kirim_alert:
                changed = mark_stale_kolam_offline(app)

            db.session.refresh(kolam)

            self.assertEqual(changed, 1)
            self.assertEqual(kolam.status, "offline")
            self.assertEqual(mock_kirim_alert.call_count, 1)

            db.session.remove()
            db.drop_all()

    def test_lwt_offline_uses_offline_template_not_alert_template(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        class Message:
            topic = "lele/kolam-a/status"
            payload = b"offline"
            qos = 1

        with app.app_context():
            db.create_all()
            AppSetting.set("telegram_bot_token", "token")
            AppSetting.set("alert_message_template", "ALERT {kolam_nama}")
            AppSetting.set("offline_message_template", "OFFLINE {kolam_nama}")

            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data", lwt_topic="lele/kolam-a/status", status="online")
            db.session.add(kolam)
            db.session.commit()

            userdata = {"app": app, "config": app.config}

            with patch("app.services.services.kirim_alert") as mock_kirim_alert:
                mqtt_client._on_message(None, userdata, Message())

            self.assertEqual(mock_kirim_alert.call_count, 1)
            call_args = mock_kirim_alert.call_args[0]
            self.assertEqual(call_args[2], "offline")
            self.assertEqual(call_args[3], "OFFLINE Kolam A")

            db.session.remove()
            db.drop_all()

    def test_lwt_normal_uses_recovery_template_after_offline(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        class Message:
            topic = "lele/kolam-a/status"
            payload = b"normal"
            qos = 1

        with app.app_context():
            db.create_all()
            AppSetting.set("telegram_bot_token", "token")
            AppSetting.set("notif_pulih", "1")
            AppSetting.set("recovery_message_template", "RECOVERY {kolam_nama}")

            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data", lwt_topic="lele/kolam-a/status", status="offline")
            db.session.add(kolam)
            db.session.commit()

            userdata = {"app": app, "config": app.config}

            with patch("app.services.services.kirim_alert") as mock_kirim_alert:
                mqtt_client._on_message(None, userdata, Message())

            self.assertEqual(mock_kirim_alert.call_count, 1)
            call_args = mock_kirim_alert.call_args[0]
            self.assertEqual(call_args[2], "recovery")
            self.assertEqual(call_args[3], "RECOVERY Kolam A")

            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main()
