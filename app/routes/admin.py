import json
from datetime import datetime
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user

from app.models.models import db, User, Kolam, SensorLog, TelegramLog, AppSetting
from app.services.services import (
    DEFAULT_ALERT_TEMPLATE,
    DEFAULT_OFFLINE_TEMPLATE,
    DEFAULT_RECOVERY_TEMPLATE,
    DEFAULT_ROUTIN_TEMPLATE,
    serialize_sensor_log_payload,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            flash("Halaman ini hanya untuk Super Admin.", "danger")
            return redirect(url_for("admin.dashboard"))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────────────────────────
@admin_bp.route("/")
@admin_required
def dashboard():
    kolam_list  = Kolam.query.all()
    total_alert = sum(1 for k in kolam_list if k.status in ("alert","bahaya","waspada"))
    total_user  = User.query.count()
    
    # Hitung last sensor log untuk setiap kolam
    for k in kolam_list:
        k.last_log = k.sensor_logs.order_by(SensorLog.created_at.desc()).first()
    
    return render_template("admin/dashboard.html",
                           kolam_list=kolam_list,
                           total_alert=total_alert,
                           total_user=total_user)


# ── Log IoT ───────────────────────────────────────────────────────────────────
@admin_bp.route("/iot-log")
@admin_required
def iot_log():
    kolam_filter  = request.args.get("kolam_id", "")
    status_filter = request.args.get("status", "")
    query = SensorLog.query.order_by(SensorLog.created_at.desc())
    if kolam_filter:
        query = query.filter_by(kolam_id=int(kolam_filter))
    if status_filter:
        query = query.filter_by(status=status_filter)
    logs = query.limit(200).all()
    kolam_list = Kolam.query.all()
    return render_template("admin/iot_log.html", logs=logs, kolam_list=kolam_list)


@admin_bp.route("/api/iot-logs")
@admin_required
def iot_logs_live():
    kolam_filter  = request.args.get("kolam_id", "")
    status_filter = request.args.get("status", "")
    query = SensorLog.query.order_by(SensorLog.created_at.desc())
    if kolam_filter:
        query = query.filter_by(kolam_id=int(kolam_filter))
    if status_filter:
        query = query.filter_by(status=status_filter)

    logs = query.limit(200).all()
    return jsonify({
        "count": len(logs),
        "logs": [serialize_sensor_log_payload(log_item) for log_item in logs],
    })


# ── Kelola Kolam ──────────────────────────────────────────────────────────────
@admin_bp.route("/kolam")
@admin_required
def kelola_kolam():
    kolam_list = Kolam.query.all()
    user_list  = User.query.filter_by(role="pemilik").all()
    return render_template("admin/kolam.html", kolam_list=kolam_list, user_list=user_list)


@admin_bp.route("/kolam/tambah", methods=["POST"])
@admin_required
def tambah_kolam():
    nama  = request.form.get("nama","").strip()
    topic = request.form.get("mqtt_topic","").strip()
    if not nama or not topic:
        flash("Nama dan MQTT Topic wajib diisi.", "danger")
        return redirect(url_for("admin.kelola_kolam"))
    lwt = topic.replace("/data", "/status")
    k   = Kolam(nama=nama, mqtt_topic=topic, lwt_topic=lwt)
    db.session.add(k)
    db.session.commit()
    flash(f"Kolam '{nama}' berhasil ditambahkan.", "success")
    return redirect(url_for("admin.kelola_kolam"))


@admin_bp.route("/kolam/<int:kolam_id>/edit", methods=["POST"])
@admin_required
def edit_kolam(kolam_id):
    k = Kolam.query.get_or_404(kolam_id)
    k.nama        = request.form.get("nama", k.nama).strip()
    k.mqtt_topic  = request.form.get("mqtt_topic", k.mqtt_topic).strip()
    k.lwt_topic   = request.form.get("lwt_topic", k.lwt_topic).strip()
    db.session.commit()
    flash("Kolam diperbarui.", "success")
    return redirect(url_for("admin.kelola_kolam"))


@admin_bp.route("/kolam/<int:kolam_id>/assign", methods=["POST"])
@admin_required
def assign_pemilik(kolam_id):
    """Tambah atau hapus pemilik dari kolam."""
    k       = Kolam.query.get_or_404(kolam_id)
    user_id = int(request.form.get("user_id", 0))
    aksi    = request.form.get("aksi", "tambah")  # tambah | hapus
    user    = User.query.get_or_404(user_id)
    if aksi == "tambah" and user not in k.pemilik_list:
        k.pemilik_list.append(user)
    elif aksi == "hapus" and user in k.pemilik_list:
        k.pemilik_list.remove(user)
    db.session.commit()
    return jsonify({"ok": True})


@admin_bp.route("/kolam/<int:kolam_id>/hapus", methods=["POST"])
@admin_required
def hapus_kolam(kolam_id):
    k = Kolam.query.get_or_404(kolam_id)
    db.session.delete(k)
    db.session.commit()
    flash("Kolam dihapus.", "success")
    return redirect(url_for("admin.kelola_kolam"))


# ── Kelola User ───────────────────────────────────────────────────────────────
@admin_bp.route("/user")
@admin_required
def kelola_user():
    user_list = User.query.all()
    return render_template("admin/user.html", user_list=user_list)


@admin_bp.route("/user/tambah", methods=["POST"])
@admin_required
def tambah_user():
    nama     = request.form.get("nama","").strip()
    email    = request.form.get("email","").strip()
    password = request.form.get("password","")
    role     = request.form.get("role","pemilik")
    tg_id    = request.form.get("telegram_id","").strip()
    if User.query.filter_by(email=email).first():
        flash("Email sudah terdaftar.", "danger")
        return redirect(url_for("admin.kelola_user"))
    u = User(nama=nama, email=email, role=role, telegram_id=tg_id or None)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    flash(f"User '{nama}' berhasil ditambahkan.", "success")
    return redirect(url_for("admin.kelola_user"))


@admin_bp.route("/user/<int:user_id>/edit", methods=["POST"])
@admin_required
def edit_user(user_id):
    u = User.query.get_or_404(user_id)
    u.nama        = request.form.get("nama", u.nama)
    u.email       = request.form.get("email", u.email)
    u.role        = request.form.get("role", u.role)
    u.telegram_id = request.form.get("telegram_id", u.telegram_id) or None
    new_pw        = request.form.get("password","")
    if new_pw:
        u.set_password(new_pw)
    db.session.commit()
    flash("User diperbarui.", "success")
    return redirect(url_for("admin.kelola_user"))


@admin_bp.route("/user/<int:user_id>/hapus", methods=["POST"])
@admin_required
def hapus_user(user_id):
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash("User dihapus.", "success")
    return redirect(url_for("admin.kelola_user"))


# ── Alert & Threshold ─────────────────────────────────────────────────────────
@admin_bp.route("/alert", methods=["GET","POST"])
@admin_required
def atur_alert():
    if request.method == "POST":
        keys = ["nh3_warn","nh3_danger","suhu_min","suhu_max","ph_min","ph_max","notif_interval","offline_timeout_minutes"]
        for k in keys:
            val = request.form.get(k,"")
            if val:
                AppSetting.set(k, val)
        notif_pulih = "1" if request.form.get("notif_pulih") else "0"
        AppSetting.set("notif_pulih", notif_pulih)
        section = request.form.get("template_section", "")
        if section == "alert":
            alert_template = request.form.get("alert_template", "").strip() or DEFAULT_ALERT_TEMPLATE
            AppSetting.set("alert_message_template", alert_template)
            flash("Format pesan alert disimpan.", "success")
        elif section == "recovery":
            recovery_template = request.form.get("recovery_template", "").strip() or DEFAULT_RECOVERY_TEMPLATE
            AppSetting.set("recovery_message_template", recovery_template)
            flash("Format pesan recovery disimpan.", "success")
        elif section == "offline":
            offline_template = request.form.get("offline_template", "").strip() or DEFAULT_OFFLINE_TEMPLATE
            AppSetting.set("offline_message_template", offline_template)
            flash("Format pesan offline disimpan.", "success")
        else:
            flash("Threshold disimpan.", "success")
        return redirect(url_for("admin.atur_alert"))

    cfg = {k: AppSetting.get(k, "") for k in
            [
                "nh3_warn",
                "nh3_danger",
                "suhu_min",
                "suhu_max",
                "ph_min",
                "ph_max",
                "notif_interval",
                "offline_timeout_minutes",
                "notif_pulih",
                "alert_message_template",
                "recovery_message_template",
                "offline_message_template",
            ]}
    return render_template("admin/alert.html", cfg=cfg)


# ── Notifikasi Rutin ──────────────────────────────────────────────────────────
@admin_bp.route("/notif-rutin", methods=["GET","POST"])
@admin_required
def notif_rutin():
    sesi_list = ["pagi","siang","sore","malam"]
    if request.method == "POST":
        for sesi in sesi_list:
            jam   = request.form.get(f"jam_{sesi}", "06:00")
            aktif = "1" if request.form.get(f"aktif_{sesi}") else "0"
            AppSetting.set(f"notif_rutin_{sesi}_jam",   jam)
            AppSetting.set(f"notif_rutin_{sesi}_aktif", aktif)
        # Isi laporan
        for field in ["isi_nh3","isi_ph","isi_suhu","isi_status_mqtt","isi_jumlah_alert"]:
            AppSetting.set(field, "1" if request.form.get(field) else "0")
        rutin_template = request.form.get("rutin_template", "").strip() or DEFAULT_ROUTIN_TEMPLATE
        AppSetting.set("rutin_message_template", rutin_template)
        # Re-setup scheduler
        from app.services.services import setup_scheduler
        from flask import current_app
        setup_scheduler(current_app._get_current_object())
        flash("Jadwal notifikasi rutin disimpan.", "success")
        return redirect(url_for("admin.notif_rutin"))

    jadwal = {}
    for sesi in sesi_list:
        jadwal[sesi] = {
            "jam":   AppSetting.get(f"notif_rutin_{sesi}_jam",   "06:00" if sesi=="pagi" else "12:00"),
            "aktif": AppSetting.get(f"notif_rutin_{sesi}_aktif", "1"),
        }
    isi = {f: AppSetting.get(f,"1") for f in ["isi_nh3","isi_ph","isi_suhu","isi_status_mqtt","isi_jumlah_alert"]}
    cfg = {"rutin_message_template": AppSetting.get("rutin_message_template", DEFAULT_ROUTIN_TEMPLATE)}
    return render_template("admin/notif_rutin.html", jadwal=jadwal, isi=isi, cfg=cfg)


# ── Log Telegram ──────────────────────────────────────────────────────────────
@admin_bp.route("/telegram-log")
@admin_required
def telegram_log():
    logs = TelegramLog.query.order_by(TelegramLog.created_at.desc()).limit(200).all()
    return render_template("admin/telegram_log.html", logs=logs)


# ── API & Keamanan (Super Admin) ──────────────────────────────────────────────
@admin_bp.route("/api-setting", methods=["GET","POST"])
@superadmin_required
def api_setting():
    if request.method == "POST":
        section = request.form.get("section","")

        if section == "mqtt":
            for k in ["mqtt_host","mqtt_port","mqtt_username","mqtt_password",
                      "mqtt_client_id","mqtt_keepalive","mqtt_topic_sub","mqtt_topic_lwt"]:
                val = request.form.get(k,"")
                if val:
                    AppSetting.set(k, val)
            flash("Konfigurasi MQTT disimpan. Restart server untuk menerapkan.", "success")

        elif section == "telegram":
            token = request.form.get("telegram_bot_token","")
            if token:
                AppSetting.set("telegram_bot_token", token)
            flash("Token Telegram disimpan.", "success")

        elif section == "database":
            db_uri = request.form.get("db_uri","")
            if db_uri:
                AppSetting.set("db_uri", db_uri)
            flash("Konfigurasi database disimpan. Restart server untuk menerapkan.", "warning")

        return redirect(url_for("admin.api_setting"))

    keys = ["mqtt_host","mqtt_port","mqtt_username","mqtt_client_id",
            "mqtt_keepalive","mqtt_topic_sub","mqtt_topic_lwt","telegram_bot_token"]
    cfg  = {k: AppSetting.get(k,"") for k in keys}
    return render_template("admin/api_setting.html", cfg=cfg)


@admin_bp.route("/api-setting/hapus-log", methods=["POST"])
@superadmin_required
def hapus_log():
    SensorLog.query.delete()
    TelegramLog.query.delete()
    db.session.commit()
    flash("Semua log berhasil dihapus.", "success")
    return redirect(url_for("admin.api_setting"))


# ── API endpoint untuk live data (WebSocket polling fallback) ─────────────────
@admin_bp.route("/api/live-data")
@admin_required
def live_data():
    kolam_list = Kolam.query.all()
    result = []
    for k in kolam_list:
        last = k.sensor_logs.order_by(SensorLog.created_at.desc()).first()
        result.append({
            "id": k.id, "nama": k.nama, "status": k.status,
            "mqtt_topic": k.mqtt_topic,
            "last_seen": k.last_seen.strftime("%H:%M:%S") if k.last_seen else None,
            "ph":   last.ph   if last else None,
            "suhu": last.suhu if last else None,
            "nh3":  last.nh3  if last else None,
        })
    return jsonify(result)
