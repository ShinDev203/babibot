"""
keep_alive.py
Render free tier sẽ "ngủ" web service nếu không có traffic.
Chạy 1 server Flask nhỏ, rồi dùng UptimeRobot (hoặc cron-job.org) ping vào
URL public của Render mỗi 5 phút để giữ bot luôn online 24/7.
"""

import os
import threading
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "BabyBoo (Su) is alive and thinking about Shin 💕"


@app.route("/health")
def health():
    return {"status": "ok"}


def _run():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = threading.Thread(target=_run, daemon=True)
    t.start()
