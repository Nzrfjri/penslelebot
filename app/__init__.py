from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_socketio import SocketIO
from sqlalchemy import inspect, text

from config.settings import Config
from app.models.models import db, User

socketio = SocketIO()


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    # Extensions
    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")

    # Flask-Login
    login_manager = LoginManager()
    login_manager.login_view     = "auth.login"
    login_manager.login_message  = "Silakan login terlebih dahulu."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Blueprints
    from app.routes.auth  import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.user  import user_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)

    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    # Init database & seed superadmin
    with app.app_context():
        db.create_all()
        _ensure_status_schema()
        _seed_superadmin()
        _seed_default_settings()

    # MQTT
    from app.services.mqtt_client import init_mqtt
    init_mqtt(app)

    # Scheduler notif rutin
    from app.services.services import setup_scheduler
    setup_scheduler(app)

    return app


def _ensure_status_schema():
    """Perbaiki kolom status pada database MySQL agar menerima nilai seperti 'bahaya'."""
    if db.engine.dialect.name != "mysql":
        return

    try:
        with db.engine.begin() as conn:
            inspector = inspect(conn)
            tables = set(inspector.get_table_names())
            if "kolam" in tables:
                conn.execute(text("ALTER TABLE kolam MODIFY COLUMN status VARCHAR(20) DEFAULT 'offline'"))
            if "sensor_log" in tables:
                conn.execute(text("ALTER TABLE sensor_log MODIFY COLUMN status VARCHAR(20) DEFAULT 'normal'"))
            if "telegram_log" in tables:
                conn.execute(text("ALTER TABLE telegram_log MODIFY COLUMN tipe VARCHAR(20) DEFAULT 'alert'"))
    except Exception as exc:
        print(f"⚠️ Gagal memperbarui skema status: {exc}")


def _seed_superadmin():
    """Buat akun superadmin default jika belum ada."""
    if not User.query.filter_by(role="superadmin").first():
        u = User(nama="Super Admin", email="admin@lele.id", role="superadmin")
        u.set_password("admin123")
        db.session.add(u)
        db.session.commit()
        print("✅ Superadmin default dibuat: admin@lele.id / admin123")


def _seed_default_settings():
    """Isi setting default jika belum ada."""
    from app.models.models import AppSetting
    defaults = {
        "nh3_warn":   "0.5",
        "nh3_danger": "1.0",
        "suhu_min":   "25",
        "suhu_max":   "32",
        "ph_min":     "6.5",
        "ph_max":     "8.5",
        "notif_interval": "30",
        "offline_timeout_minutes": "15",
        "notif_pulih": "1",
        "alert_message_template": "{emoji} <b>Alert Kolam {kolam_nama}</b>\nNH3 : {nh3} mg/L\npH  : {ph}\nSuhu: {suhu} °C\nStatus: <b>{status}</b>\n⏰ {waktu}",
        "recovery_message_template": "✅ <b>{kolam_nama} kembali normal</b>\nNH3 : {nh3} mg/L\npH  : {ph}\nSuhu: {suhu} °C\nStatus: <b>{status}</b>\n⏰ {waktu}",
        "offline_message_template": "📴 <b>{kolam_nama} offline</b>\nNH3 : {nh3} mg/L\npH  : {ph}\nSuhu: {suhu} °C\nStatus: <b>{status}</b>\n⏰ {waktu}",
        "notif_rutin_pagi_jam":   "06:00",
        "notif_rutin_pagi_aktif": "1",
        "notif_rutin_siang_jam":  "12:00",
        "notif_rutin_siang_aktif":"1",
        "notif_rutin_sore_jam":   "17:00",
        "notif_rutin_sore_aktif": "1",
        "notif_rutin_malam_jam":  "21:00",
        "notif_rutin_malam_aktif":"0",
        "isi_nh3":"1","isi_ph":"1","isi_suhu":"1","isi_status_mqtt":"1","isi_jumlah_alert":"0",
        "mqtt_topic_sub": "lele/+/data",
        "mqtt_topic_lwt": "lele/+/status",
    }
    for k, v in defaults.items():
        if not AppSetting.query.filter_by(key=k).first():
            db.session.add(AppSetting(key=k, value=v))
    db.session.commit()
