from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ── Many-to-many: User <-> Kolam ─────────────────────────────────────────────
kolam_user = db.Table(
    "kolam_user",
    db.Column("kolam_id", db.Integer, db.ForeignKey("kolam.id"), primary_key=True),
    db.Column("user_id",  db.Integer, db.ForeignKey("user.id"),  primary_key=True),
)


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id           = db.Column(db.Integer, primary_key=True)
    nama         = db.Column(db.String(100), nullable=False)
    email        = db.Column(db.String(150), unique=True, nullable=False)
    password_hash= db.Column(db.String(255), nullable=False)
    role         = db.Column(db.Enum("superadmin", "admin", "pemilik"), default="pemilik")
    telegram_id  = db.Column(db.String(50), nullable=True)
    tg_verified  = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=datetime.now)

    kolam_list   = db.relationship("Kolam", secondary=kolam_user, back_populates="pemilik_list")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role in ("admin", "superadmin")

    @property
    def is_superadmin(self):
        return self.role == "superadmin"


class Kolam(db.Model):
    __tablename__ = "kolam"

    id           = db.Column(db.Integer, primary_key=True)
    nama         = db.Column(db.String(100), nullable=False)
    mqtt_topic   = db.Column(db.String(200), unique=True, nullable=False)  # lele/kolam-a1/data
    lwt_topic    = db.Column(db.String(200), nullable=True)                # lele/kolam-a1/status
    status       = db.Column(db.String(20), default="offline")
    last_seen    = db.Column(db.DateTime, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.now)
    pemilik_list = db.relationship("User", secondary=kolam_user, back_populates="kolam_list")
    sensor_logs  = db.relationship("SensorLog", backref="kolam", lazy="dynamic", cascade="all, delete-orphan")


class SensorLog(db.Model):
    """Setiap baris = satu pesan MQTT yang masuk dari IoT."""
    __tablename__ = "sensor_log"

    id         = db.Column(db.Integer, primary_key=True)
    kolam_id   = db.Column(db.Integer, db.ForeignKey("kolam.id"), nullable=False)
    mqtt_topic = db.Column(db.String(200))
    ph         = db.Column(db.Float, nullable=True)
    suhu       = db.Column(db.Float, nullable=True)
    nh3        = db.Column(db.Float, nullable=True)   # hasil kalkulasi dari pH + suhu
    qos        = db.Column(db.Integer, default=1)
    status     = db.Column(db.String(20), default="normal")
    raw_payload= db.Column(db.Text, nullable=True)    # simpan payload mentah untuk debug
    created_at = db.Column(db.DateTime, default=datetime.now)


class TelegramLog(db.Model):
    """Log setiap notifikasi yang dikirim via Telegram."""
    __tablename__ = "telegram_log"

    id         = db.Column(db.Integer, primary_key=True)
    kolam_id   = db.Column(db.Integer, db.ForeignKey("kolam.id"), nullable=True)
    tipe       = db.Column(db.String(20), default="alert")
    pesan      = db.Column(db.Text)
    penerima   = db.Column(db.String(500))  # JSON list telegram_id
    sukses     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class AppSetting(db.Model):
    """Key-value store untuk semua konfigurasi sistem."""
    __tablename__ = "app_setting"

    id    = db.Column(db.Integer, primary_key=True)
    key   = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

    @staticmethod
    def get(key, default=None):
        row = AppSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = AppSetting.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = AppSetting(key=key, value=value)
            db.session.add(row)
        db.session.commit()
