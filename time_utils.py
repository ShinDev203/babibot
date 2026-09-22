"""
time_utils.py
Tiện ích lấy giờ theo múi giờ Việt Nam (Asia/Ho_Chi_Minh) cho các tính năng
chủ động nhắn tin (chào buổi sáng, buổi tối, nhắc nhở...).
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_NAME = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
TZ = ZoneInfo(TZ_NAME)


def now_local() -> datetime:
    return datetime.now(TZ)


def today_str() -> str:
    return now_local().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    return (now_local() - timedelta(days=1)).strftime("%Y-%m-%d")


def month_day_str() -> str:
    return now_local().strftime("%m-%d")


WEEKDAY_VI = {
    0: "Thứ Hai",
    1: "Thứ Ba",
    2: "Thứ Tư",
    3: "Thứ Năm",
    4: "Thứ Sáu",
    5: "Thứ Bảy",
    6: "Chủ Nhật",
}


def weekday_vi() -> str:
    return WEEKDAY_VI[now_local().weekday()]


import re


def parse_when(text: str):
    """
    Phân tích chuỗi thời gian cho lệnh nhắc việc.
    Hỗ trợ:
      - Khoảng thời gian tương đối: '10m', '2h', '1d', '45s' (m=phút, h=giờ, d=ngày, s=giây)
      - Giờ tuyệt đối trong ngày: 'HH:MM' (nếu giờ đó đã qua trong hôm nay thì hiểu là ngày mai)
    Trả về datetime (có timezone) hoặc None nếu không parse được.
    """
    text = text.strip().lower()

    m = re.fullmatch(r"(\d+)\s*(s|m|h|d)", text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return now_local() + timedelta(seconds=amount * seconds)

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            candidate = now_local().replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now_local():
                candidate += timedelta(days=1)
            return candidate

    return None
