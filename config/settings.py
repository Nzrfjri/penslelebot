import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{os.getenv('DB_USER','root')}:{os.getenv('DB_PASSWORD','')}"
        f"@{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','3306')}/{os.getenv('DB_NAME','amonialele')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # MQTT
    MQTT_HOST            = os.getenv("MQTT_HOST", "localhost")
    MQTT_PORT            = int(os.getenv("MQTT_PORT", 1883))
    MQTT_USERNAME        = os.getenv("MQTT_USERNAME", "")
    MQTT_PASSWORD        = os.getenv("MQTT_PASSWORD", "")
    MQTT_CLIENT_ID       = os.getenv("MQTT_CLIENT_ID", "amonialele-server")
    MQTT_TOPIC_SUBSCRIBE = os.getenv("MQTT_TOPIC_SUBSCRIBE", "lele/+/data")
    MQTT_TOPIC_LWT       = os.getenv("MQTT_TOPIC_LWT", "lele/+/status")

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_API_URL   = "https://api.telegram.org/bot"
