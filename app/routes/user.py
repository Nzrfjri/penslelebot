from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.models.models import db, SensorLog, Kolam
from app.services.services import serialize_kolam_dashboard_payload

user_bp = Blueprint("user", __name__, url_prefix="/user")


def user_only(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@user_bp.route("/")
@user_only
def dashboard():
    kolam_list = current_user.kolam_list
    
    # Hitung last sensor log untuk setiap kolam
    for k in kolam_list:
        k.last_log = k.sensor_logs.order_by(SensorLog.created_at.desc()).first()
    
    return render_template("user/dashboard.html", kolam_list=kolam_list)


@user_bp.route("/api/live-data")
@user_only
def live_data():
    kolam_list = current_user.kolam_list
    return jsonify([serialize_kolam_dashboard_payload(k) for k in kolam_list])


@user_bp.route("/history")
@user_only
def history():
    kolam_id   = request.args.get("kolam_id", "")
    tgl_dari   = request.args.get("dari", "")
    tgl_sampai = request.args.get("sampai", "")
    kolam_list = current_user.kolam_list
    logs       = []

    if kolam_id:
        # Pastikan kolam milik user ini
        kolam_ids = [k.id for k in kolam_list]
        if int(kolam_id) in kolam_ids:
            query = SensorLog.query.filter_by(kolam_id=int(kolam_id))
            if tgl_dari:
                query = query.filter(SensorLog.created_at >= tgl_dari)
            if tgl_sampai:
                query = query.filter(SensorLog.created_at <= tgl_sampai + " 23:59:59")
            logs = query.order_by(SensorLog.created_at.desc()).limit(500).all()

    return render_template("user/history.html",
                           kolam_list=kolam_list,
                           logs=logs,
                           selected_kolam=kolam_id)


@user_bp.route("/setting", methods=["GET","POST"])
@user_only
def setting():
    if request.method == "POST":
        current_user.nama        = request.form.get("nama", current_user.nama)
        current_user.telegram_id = request.form.get("telegram_id","").strip() or None
        new_pw = request.form.get("password","")
        if new_pw:
            current_user.set_password(new_pw)
        db.session.commit()
        flash("Pengaturan disimpan.", "success")
        return redirect(url_for("user.setting"))
    return render_template("user/setting.html")
