from flask import Flask, request
from threading import Thread
from datetime import datetime

app = Flask('')

@app.route('/')
def home():
    print(f"[{datetime.utcnow()}] Ping received from UptimeRobot — IP: {request.remote_addr}")
    return "✅ Bot läuft. Ping OK."

def keep_alive():
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=8080))
    t.start()
