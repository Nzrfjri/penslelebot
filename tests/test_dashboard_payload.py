import unittest

from flask import Flask

from app.models.models import Kolam, SensorLog, db
from app.services.services import serialize_kolam_dashboard_payload, serialize_sensor_log_payload


class DashboardPayloadTests(unittest.TestCase):
    def test_serialize_kolam_dashboard_payload_uses_latest_sensor_log(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data", status="online")
            db.session.add(kolam)
            db.session.commit()

            old_log = SensorLog(kolam_id=kolam.id, ph=6.8, suhu=27.0, nh3=0.1, status="normal")
            db.session.add(old_log)
            db.session.commit()

            latest_log = SensorLog(kolam_id=kolam.id, ph=7.4, suhu=30.0, nh3=0.2, status="waspada")
            db.session.add(latest_log)
            db.session.commit()

            payload = serialize_kolam_dashboard_payload(kolam)

            self.assertEqual(payload["ph"], 7.4)
            self.assertEqual(payload["suhu"], 30.0)
            self.assertEqual(payload["nh3"], 0.2)
            self.assertEqual(payload["status"], "online")

            db.session.remove()
            db.drop_all()

    def test_serialize_sensor_log_payload_returns_display_fields(self):
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SECRET_KEY"] = "test"
        db.init_app(app)

        with app.app_context():
            db.create_all()
            kolam = Kolam(nama="Kolam A", mqtt_topic="lele/kolam-a/data", status="online")
            db.session.add(kolam)
            db.session.commit()

            log_item = SensorLog(
                kolam_id=kolam.id,
                mqtt_topic=kolam.mqtt_topic,
                ph=7.1,
                suhu=29.5,
                nh3=0.1234,
                qos=1,
                status="waspada",
            )
            db.session.add(log_item)
            db.session.commit()

            payload = serialize_sensor_log_payload(log_item)

            self.assertEqual(payload["mqtt_topic"], "lele/kolam-a/data")
            self.assertEqual(payload["ph"], 7.1)
            self.assertEqual(payload["suhu"], 29.5)
            self.assertEqual(payload["nh3"], 0.1234)
            self.assertEqual(payload["qos"], 1)
            self.assertEqual(payload["status"], "waspada")
            self.assertIsNotNone(payload["created_at"])

            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main()
