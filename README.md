# AmoniaLele — Backend Server

Sistem monitoring amonia kolam lele berbasis Flask + MQTT + Telegram Bot.

## Struktur Proyek

```
amonialele/
├── run.py                      # Entry point
├── requirements.txt
├── .env.example                # Salin ke .env dan isi
├── config/
│   └── settings.py             # Konfigurasi dari .env
└── app/
    ├── __init__.py             # App factory (create_app)
    ├── models/
    │   └── models.py           # SQLAlchemy models (User, Kolam, SensorLog, dll)
    ├── routes/
    │   ├── auth.py             # Login / Logout
    │   ├── admin.py            # Semua halaman admin & super admin
    │   └── user.py             # Halaman user/pemilik
    ├── services/
    │   ├── services.py         # Kalkulasi NH3, kirim Telegram, scheduler rutin
    │   └── mqtt_client.py      # Koneksi MQTT & handler pesan IoT
    ├── templates/
    │   ├── base.html
    │   ├── auth/login.html
    │   ├── admin/              # dashboard, iot_log, kolam, user, alert,
    │   │                       # notif_rutin, telegram_log, api_setting
    │   └── user/               # dashboard, history, setting
    └── static/
        ├── css/style.css
        └── js/main.js
```

## Setup

### 1. Install dependensi
```bash
pip install -r requirements.txt
```

### 2. Konfigurasi environment
```bash
cp .env.example .env
# Edit .env sesuai konfigurasi kamu
```

### 3. Setup MySQL
```sql
CREATE DATABASE amonialele CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. Setup Mosquitto MQTT Broker
```bash
# Install (Ubuntu/Debian)
sudo apt install mosquitto mosquitto-clients

# Edit /etc/mosquitto/mosquitto.conf
listener 1883
allow_anonymous false
password_file /etc/mosquitto/passwd

# Buat user MQTT
sudo mosquitto_passwd -c /etc/mosquitto/passwd lele_server

# Restart
sudo systemctl restart mosquitto
```

### 5. Jalankan server
```bash
python run.py
```

Server berjalan di http://localhost:5000

### 6. Login pertama
- Email: `admin@lele.id`
- Password: `admin123`
- **Segera ganti password setelah login pertama!**

---

## Format payload MQTT dari ESP32

Kirim JSON ke topic `lele/kolam-a1/data`:

```json
{
  "ph": 7.2,
  "suhu": 28.5,
  "nh3": 0.6
}
```

Field `nh3` bersifat opsional. Server tetap akan menghitung nilai NH3 dari `ph` + `suhu` jika `nh3` tidak dikirim, tetapi juga menerima nilai NH3 yang dikirim perangkat.

Server akan otomatis menghitung NH3 dari nilai pH + suhu menggunakan rumus:
```
pKa = 0.09018 + (2729.92 / (273.15 + suhu))
NH3_fraction = 1 / (1 + 10^(pKa - pH))
```

### LWT (Last Will & Testament)
Konfigurasi di ESP32:
- LWT Topic: `lele/kolam-a1/status`
- LWT Message: `offline`
- LWT QoS: 1

---

## Alur Sistem

```
ESP32 → MQTT Broker (Mosquitto) → Flask Server
                                      ↓
                               Simpan ke MySQL
                                      ↓
                               Cek threshold NH3
                                      ↓
                        Kirim notif Telegram ke pemilik kolam
```

## Akun & Role

| Role       | Akses                                              |
|------------|----------------------------------------------------|
| superadmin | Semua fitur + API & Keamanan (MQTT, Telegram, DB) |
| admin      | Dashboard, kelola kolam/user, alert, log           |
| pemilik    | Hanya kolam miliknya, history, setting Telegram ID |
