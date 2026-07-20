from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    # Nonaktifkan reloader supaya MQTT hanya diinisialisasi sekali.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)
