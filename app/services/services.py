"""
services.py  —  logika bisnis utama:
  - Kalkulasi NH3 dari pH + suhu (rumus kimiawi)
  - Kirim notifikasi Telegram
  - Scheduler notifikasi rutin
"""
import math
import json
import re
import requests
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)

DEFAULT_ALERT_TEMPLATE = (
    "{emoji} <b>Alert {kolam_nama}</b>\n"
    "NH3 : {nh3} mg/L\n"
    "pH  : {ph}\n"
    "Suhu: {suhu} °C\n"
    "Status: <b>{status}</b>\n"
    "⏰ {waktu}"
)
DEFAULT_ROUTIN_TEMPLATE = (
    "🐟 <b>Laporan {sesi} — {waktu}</b>\n"
    "{isi_kolam}\n"
    "\n— AmoniaLeleBot"
)
DEFAULT_RECOVERY_TEMPLATE = (
    "✅ <b>{kolam_nama} kembali normal</b>\n"
    "NH3 : {nh3} mg/L\n"
    "pH  : {ph}\n"
    "Suhu: {suhu} °C\n"
    "Status: <b>{status}</b>\n"
    "⏰ {waktu}"
)
DEFAULT_OFFLINE_TEMPLATE = (
    "📴 <b>{kolam_nama} offline</b>\n"
    "NH3 : {nh3} mg/L\n"
    "pH  : {ph}\n"
    "Suhu: {suhu} °C\n"
    "Status: <b>{status}</b>\n"
    "⏰ {waktu}"
)

DEFAULT_OFFLINE_TIMEOUT_MINUTES = 15


def render_message_template(template: str, **kwargs) -> str:
    """Ganti placeholder {nama} dalam template dengan nilai yang diberikan."""
    if not template:
        return ""

    def replace(match):
        key = match.group(1)
        value = kwargs.get(key)
        if value is None:
            return "—"
        return str(value)

    return re.sub(r"\{([a-zA-Z0-9_]+)\}", replace, template)


# ── Kalkulasi NH3 ─────────────────────────────────────────────────────────────
def hitung_nh3(ph: float, suhu: float) -> float:
    """
    Menghitung konsentrasi NH3 (amonia bebas) dari total ammonia nitrogen (TAN).
    Rumus: NH3 = TAN * f
    Dengan f = 1 / (1 + 10^(pKa - pH))
    pKa tergantung suhu: pKa = 0.09018 + 2729.92 / (273.15 + suhu)

    Asumsi: TAN = 1 mg/L (normalisasi). Hasilnya adalah fraksi NH3.
    Untuk nilai aktual, kalikan dengan TAN terukur.
    """
    try:
        pka = 0.09018 + (2729.92 / (273.15 + suhu))
        f   = 1 / (1 + 10 ** (pka - ph))
        return round(f, 4)
    except Exception as e:
        log.error(f"Gagal hitung NH3: {e}")
        return 0.0


def tentukan_status(nh3: float, suhu: float, ph: float, cfg: dict) -> str:
    """
    Tentukan status kolam berdasarkan nilai sensor vs threshold.
    cfg = {"nh3_warn": 0.5, "nh3_danger": 1.0, "suhu_min": 25, "suhu_max": 32, "ph_min": 6.5, "ph_max": 8.5}

    Prinsip baru:
    - NH3 di atas batas bahaya -> bahaya
    - NH3 di atas batas waspada atau pH/suhu di luar rentang aman -> waspada
    - Selain itu -> normal
    """
    nh3_warn = cfg.get("nh3_warn", 0.5)
    nh3_danger = cfg.get("nh3_danger", 1.0)
    suhu_min = cfg.get("suhu_min", 25)
    suhu_max = cfg.get("suhu_max", 32)
    ph_min = cfg.get("ph_min", 6.5)
    ph_max = cfg.get("ph_max", 8.5)

    if nh3 >= nh3_danger:
        return "bahaya"

    if (nh3 >= nh3_warn
            or suhu > suhu_max
            or suhu < suhu_min
            or ph > ph_max
            or ph < ph_min):
        return "waspada"

    return "normal"


# ── Telegram ──────────────────────────────────────────────────────────────────
def kirim_telegram(bot_token: str, chat_id: str, pesan: str) -> bool:
    """Kirim pesan ke satu chat_id. Return True jika sukses."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": pesan, "parse_mode": "HTML"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"Telegram error ke {chat_id}: {e}")
        return False


def kirim_alert(app, kolam_id: int, tipe: str, pesan: str):
    """
    Kirim notifikasi ke semua pemilik kolam.
    Dipanggil dari MQTT handler.
    """
    with app.app_context():
        from app.models.models import Kolam, TelegramLog, AppSetting, db
        kolam = Kolam.query.get(kolam_id)
        if not kolam:
            return

        bot_token = AppSetting.get("telegram_bot_token", "")
        if not bot_token:
            log.warning("Telegram bot token belum diset")
            return

        penerima_ids = []
        for user in kolam.pemilik_list:
            if user.telegram_id and user.tg_verified:
                sukses = kirim_telegram(bot_token, user.telegram_id, pesan)
                if sukses:
                    penerima_ids.append(user.telegram_id)

        tlog = TelegramLog(
            kolam_id=kolam_id,
            tipe=tipe,
            pesan=pesan,
            penerima=json.dumps(penerima_ids),
            sukses=bool(penerima_ids),
        )
        db.session.add(tlog)
        db.session.commit()


def should_send_alert(app, kolam_id: int, now: datetime | None = None) -> bool:
    """Cek apakah alerta boleh dikirim berdasarkan interval yang dikonfigurasi."""
    with app.app_context():
        from app.models.models import AppSetting, TelegramLog

        try:
            interval_minutes = int(AppSetting.get("notif_interval", "30") or "30")
        except (TypeError, ValueError):
            interval_minutes = 30

        if interval_minutes <= 0:
            return True

        if now is None:
            now = datetime.now()

        last_alert = (
            TelegramLog.query.filter_by(kolam_id=kolam_id)
            .filter(TelegramLog.tipe.in_(["alert", "waspada", "bahaya"]))
            .order_by(TelegramLog.created_at.desc())
            .first()
        )
        if not last_alert or not last_alert.created_at:
            return True

        return now - last_alert.created_at >= timedelta(minutes=interval_minutes)


def should_send_recovery_notification(app, kolam_id: int, previous_status: str | None, current_status: str | None) -> bool:
    """Cek apakah notifikasi pulih perlu dikirim."""
    with app.app_context():
        from app.models.models import AppSetting

        if AppSetting.get("notif_pulih", "1") != "1":
            return False

        recovery_targets = {"normal", "online"}
        return previous_status in {"waspada", "bahaya", "offline"} and current_status in recovery_targets


def buat_pesan_alert(app, kolam_nama: str, nh3: float, ph: float, suhu: float, status: str) -> str:
    from app.models.models import AppSetting

    emoji = "🔴" if status == "bahaya" else "⚠️"
    template = AppSetting.get("alert_message_template", DEFAULT_ALERT_TEMPLATE)
    return render_message_template(
        template,
        emoji=emoji,
        kolam_nama=kolam_nama,
        nh3=nh3,
        ph=ph,
        suhu=suhu,
        status=status.upper(),
        waktu=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    )


def buat_pesan_pulih(app, kolam_nama: str, nh3: float, ph: float, suhu: float, status: str = "normal") -> str:
    from app.models.models import AppSetting

    template = AppSetting.get("recovery_message_template", DEFAULT_RECOVERY_TEMPLATE)
    return render_message_template(
        template,
        emoji="✅",
        kolam_nama=kolam_nama,
        nh3=nh3,
        ph=ph,
        suhu=suhu,
        status=status.upper(),
        waktu=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    )


def buat_pesan_offline(app, kolam_nama: str, nh3: float, ph: float, suhu: float, status: str = "offline") -> str:
    from app.models.models import AppSetting

    template = AppSetting.get("offline_message_template", DEFAULT_OFFLINE_TEMPLATE)
    return render_message_template(
        template,
        emoji="📴",
        kolam_nama=kolam_nama,
        nh3=nh3,
        ph=ph,
        suhu=suhu,
        status=status.upper(),
        waktu=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    )


def buat_pesan_rutin(app, kolam_list: list, sesi: str = "pagi") -> str:
    """Buat pesan laporan rutin dari list kolam."""
    from app.models.models import AppSetting, SensorLog

    template = AppSetting.get("rutin_message_template", DEFAULT_ROUTIN_TEMPLATE)
    baris = []
    for k in kolam_list:
        last = k.sensor_logs.order_by(SensorLog.created_at.desc()).first()
        baris.append(f"📍 <b>{k.nama}</b>")
        if last:
            s = "✅" if last.status == "normal" else ("⚠️" if last.status == "waspada" else "🔴")
            baris.append(f"NH3: {last.nh3} {s} | pH: {last.ph} | Suhu: {last.suhu}°C")
        else:
            baris.append("— Tidak ada data —")
    isi_kolam = "\n".join(baris)
    return render_message_template(
        template,
        sesi=sesi.capitalize(),
        waktu=datetime.now().strftime("%H:%M %d/%m/%Y"),
        isi_kolam=isi_kolam,
    )


def serialize_kolam_dashboard_payload(kolam) -> dict:
    """Serialisasi data kolam untuk dikirim ke frontend dashboard."""
    from app.models.models import SensorLog

    last = kolam.sensor_logs.order_by(SensorLog.created_at.desc()).first()
    return {
        "id": kolam.id,
        "nama": kolam.nama,
        "status": kolam.status,
        "last_seen": kolam.last_seen.strftime("%H:%M:%S") if kolam.last_seen else None,
        "ph": last.ph if last else None,
        "suhu": last.suhu if last else None,
        "nh3": last.nh3 if last else None,
    }


def serialize_sensor_log_payload(log_item) -> dict:
    """Serialisasi satu baris log sensor untuk polling frontend."""
    return {
        "id": log_item.id,
        "created_at": log_item.created_at.strftime("%H:%M:%S") if log_item.created_at else None,
        "mqtt_topic": log_item.mqtt_topic,
        "ph": log_item.ph,
        "suhu": log_item.suhu,
        "nh3": log_item.nh3,
        "qos": log_item.qos,
        "status": log_item.status,
    }


def mark_stale_kolam_offline(app, timeout_minutes: int | None = None) -> int:
    """Ubah kolam yang sudah tidak update lebih dari timeout menjadi offline."""
    from app.models.models import AppSetting, Kolam, db

    if timeout_minutes is None:
        try:
            timeout_minutes = int(AppSetting.get("offline_timeout_minutes", str(DEFAULT_OFFLINE_TIMEOUT_MINUTES)) or str(DEFAULT_OFFLINE_TIMEOUT_MINUTES))
        except (TypeError, ValueError):
            timeout_minutes = DEFAULT_OFFLINE_TIMEOUT_MINUTES

    if timeout_minutes <= 0:
        return 0

    cutoff = datetime.now() - timedelta(minutes=timeout_minutes)
    stale_kolam = (
        Kolam.query.filter(Kolam.last_seen.isnot(None))
        .filter(Kolam.status != "offline")
        .filter(Kolam.last_seen <= cutoff)
        .all()
    )

    changed = 0
    for kolam in stale_kolam:
        kolam.status = "offline"
        pesan = buat_pesan_offline(app, kolam.nama, "—", "—", "—", "offline")
        kirim_alert(app, kolam.id, "offline", pesan)
        db.session.add(kolam)
        changed += 1
        log.info(f"Kolam stale -> offline: {kolam.nama}")

    if changed:
        db.session.commit()

    return changed


# ── Scheduler notif rutin ─────────────────────────────────────────────────────
_scheduler = BackgroundScheduler(timezone="Asia/Jakarta")


def _job_rutin(app, sesi: str):
    """Job yang dijalankan scheduler untuk satu sesi (pagi/siang/sore/malam)."""
    with app.app_context():
        from app.models.models import Kolam, SensorLog, TelegramLog, AppSetting, User, db

        bot_token = AppSetting.get("telegram_bot_token", "")
        if not bot_token:
            return

        # Kumpulkan semua user yang punya kolam
        semua_user = User.query.filter(User.telegram_id.isnot(None), User.tg_verified == True).all()

        for user in semua_user:
            if not user.kolam_list:
                continue

            pesan = buat_pesan_rutin(app, user.kolam_list, sesi=sesi)
            sukses = kirim_telegram(bot_token, user.telegram_id, pesan)

            tlog = TelegramLog(tipe="rutin", pesan=pesan, penerima=user.telegram_id, sukses=sukses)
            db.session.add(tlog)
        db.session.commit()


def _job_offline_timeout(app):
    """Job periodik untuk memaksa kolam yang stale menjadi offline."""
    with app.app_context():
        changed = mark_stale_kolam_offline(app)
        if changed:
            log.info(f"Offline timeout memproses {changed} kolam")


def setup_scheduler(app):
    """
    Baca jadwal dari AppSetting dan daftarkan job.
    Dipanggil saat app start. Bisa di-reload via halaman admin.
    """
    from app.models.models import AppSetting

    sesi_default = {
        "pagi":  "06:00",
        "siang": "12:00",
        "sore":  "17:00",
        "malam": "21:00",
    }

    with app.app_context():
        for sesi, default_jam in sesi_default.items():
            aktif = AppSetting.get(f"notif_rutin_{sesi}_aktif", "1")
            jam   = AppSetting.get(f"notif_rutin_{sesi}_jam", default_jam)
            if aktif != "1":
                continue
            h, m = jam.split(":")
            job_id = f"rutin_{sesi}"
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
            _scheduler.add_job(
                _job_rutin,
                CronTrigger(hour=int(h), minute=int(m)),
                args=[app, sesi],
                id=job_id,
                replace_existing=True,
            )
            log.info(f"Job rutin '{sesi}' dijadwalkan jam {jam}")

        offline_job_id = "offline_timeout"
        if _scheduler.get_job(offline_job_id):
            _scheduler.remove_job(offline_job_id)
        _scheduler.add_job(
            _job_offline_timeout,
            IntervalTrigger(minutes=1),
            args=[app],
            id=offline_job_id,
            replace_existing=True,
            max_instances=1,
        )
        timeout_minutes = AppSetting.get("offline_timeout_minutes", str(DEFAULT_OFFLINE_TIMEOUT_MINUTES))
        log.info(f"Job offline timeout dijadwalkan dengan ambang {timeout_minutes} menit")

    if not _scheduler.running:
        _scheduler.start()
