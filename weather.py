"""
weather.py
Lấy thời tiết hiện tại bằng Open-Meteo (https://open-meteo.com) - HOÀN TOÀN MIỄN PHÍ,
không cần API key. Dùng để chèn vào tin chào buổi sáng cho sinh động.
"""

import os
import requests

LAT = float(os.getenv("WEATHER_LAT", 18.6796))   # mặc định: Vinh, Nghệ An
LON = float(os.getenv("WEATHER_LON", 105.6813))
LOCATION_NAME = os.getenv("WEATHER_LOCATION_NAME", "Vinh")

WEATHER_CODE_VI = {
    0: "trời quang",
    1: "trời quang, ít mây",
    2: "trời có mây",
    3: "trời nhiều mây, âm u",
    45: "sương mù",
    48: "sương mù đóng băng",
    51: "mưa phùn nhẹ",
    53: "mưa phùn",
    55: "mưa phùn dày",
    61: "mưa nhỏ",
    63: "mưa vừa",
    65: "mưa to",
    71: "tuyết nhẹ",
    80: "mưa rào nhẹ",
    81: "mưa rào",
    82: "mưa rào lớn",
    95: "có dông",
    96: "dông kèm mưa đá",
}


def get_weather_text() -> str | None:
    """Trả về mô tả thời tiết ngắn gọn bằng tiếng Việt, hoặc None nếu lỗi."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            "&current=temperature_2m,precipitation,weathercode"
            "&timezone=Asia%2FHo_Chi_Minh"
        )
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        temp = current.get("temperature_2m")
        code = current.get("weathercode")
        precipitation = current.get("precipitation", 0)

        desc = WEATHER_CODE_VI.get(code, "thời tiết bình thường")
        text = f"{LOCATION_NAME} hiện khoảng {temp}°C, {desc}"
        if precipitation and precipitation > 0:
            text += ", có mưa nên nhớ mang áo mưa/ô nha"
        return text
    except Exception:
        return None
