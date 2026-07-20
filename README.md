# PENSLeleBot

Aplikasi monitoring kualitas air kolam lele berbasis Flask dengan integrasi MQTT, MySQL, dan Telegram. Aplikasi ini menerima data sensor dari perangkat IoT seperti ESP32, menyimpan log ke database, menilai status kolam, dan mengirim notifikasi otomatis ke pemilik kolam.

## Fitur yang tersedia saat ini

- Dashboard admin untuk mengelola kolam, user, log IoT, alert, log Telegram, serta konfigurasi MQTT/Telegram/database.
- Dashboard pemilik kolam untuk melihat data kolam yang menjadi tanggung jawabnya, riwayat data, dan pengaturan Telegram ID.
- Penerimaan data sensor melalui MQTT dari topik seperti `lele/kolam-a1/data`.
- Penilaian status kolam menjadi `normal`, `waspada`, `bahaya`, atau `offline` berdasarkan nilai NH3, pH, dan suhu.
- Notifikasi Telegram untuk alert, recovery, offline, dan laporan rutin.
- Scheduler otomatis untuk mengirim laporan rutin dan menandai kolam yang sudah lama tidak update sebagai offline.
- Seed otomatis akun superadmin default dan setting aplikasi saat aplikasi pertama kali dijalankan.

## Struktur proyek

```text
amonialele-fromclaudev2/
├── run.py
├── requirements.txt
├── config/
│   └── settings.py
├── app/
│   ├── __init__.py
│   ├── models/
│   │   └── models.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── admin.py
│   │   └── user.py
│   ├── services/
│   │   ├── mqtt_client.py
│   │   └── services.py
│   ├── static/
│   └── templates/
└── tests/
```

## Persyaratan

- Python 3.10+
- MySQL Server
- Broker MQTT (contoh: Mosquitto)
- Optional: token bot Telegram untuk mengirim notifikasi

## Setup

### 1. Buat environment virtual

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. Install dependency

```bash
pip install -r requirements.txt
```

### 3. Siapkan database MySQL

```sql
CREATE DATABASE amonialele CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. Konfigurasi environment

Buat variabel environment berikut sebelum menjalankan aplikasi:

```bash
set SECRET_KEY=dev-secret-key
set DB_HOST=localhost
set DB_PORT=3306
set DB_USER=root
set DB_PASSWORD=
set DB_NAME=amonialele
set MQTT_HOST=localhost
set MQTT_PORT=1883
set MQTT_USERNAME=
set MQTT_PASSWORD=
set MQTT_CLIENT_ID=amonialele-server
set MQTT_TOPIC_SUBSCRIBE=lele/+/data
set MQTT_TOPIC_LWT=lele/+/status
set TELEGRAM_BOT_TOKEN=
```

Jika menggunakan PowerShell, gunakan `$env:NAME = "value"`.

### 5. Jalankan aplikasi

```bash
python run.py
```

Aplikasi akan berjalan di:

```text
http://localhost:5000
```

### 6. Login pertama

Akun superadmin default akan dibuat otomatis saat aplikasi pertama kali dijalankan:

- Email: `admin@lele.id`
- Password: `admin123`

Disarankan untuk segera mengubah password setelah login pertama.

## Format payload MQTT dari ESP32

Kirim data JSON ke topik MQTT yang sudah ditentukan, misalnya `lele/kolam-a1/data`:

```json
{
  "ph": 7.2,
  "suhu": 28.5,
  "nh3": 0.6
}
```

Catatan:
- Field `nh3` bersifat opsional.
- Jika `nh3` tidak dikirim, server akan menghitung nilai NH3 dari pH dan suhu.
- Topik LWT yang umum dipakai untuk perangkat adalah `lele/kolam-a1/status` dengan pesan `offline`.

## Alur sistem

```text
ESP32 / IoT Device → MQTT Broker → Flask App
                                ↓
                           Simpan ke MySQL
                                ↓
                      Cek threshold dan status kolam
                                ↓
                     Kirim notifikasi Telegram ke pemilik
```

## Role pengguna

- `superadmin`: akses penuh, termasuk pengaturan MQTT, Telegram, database, dan fitur admin lainnya.
- `admin`: mengelola kolam, user, alert, log, dan notifikasi rutin.
- `pemilik`: melihat data kolam miliknya, riwayat data, dan mengatur Telegram ID.

## Catatan penting

- Aplikasi akan membuat tabel database secara otomatis saat dijalankan.
- Konfigurasi threshold dan template pesan dapat diubah melalui halaman admin.
- Jika Telegram bot token belum diatur, fitur notifikasi Telegram akan dinonaktifkan sampai token tersedia.
