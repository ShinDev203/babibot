# Dockerfile cho BabyBoo (Su)
# Quan trọng: Discord voice cần ffmpeg (phát nhạc/TTS), libopus (mã hoá âm thanh cũ),
# VÀ từ 1/3/2026 Discord bắt buộc DAVE (E2EE) cho MỌI kết nối voice/video - discord.py
# cần thêm gói Python "davey" (đã có trong requirements.txt) để join voice không bị lỗi
# "RuntimeError: davey library needed in order to use voice".

FROM python:3.11-slim

# Cài ffmpeg + libopus0 (voice codec) + các lib build cần cho PyNaCl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libffi-dev \
    libnacl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Kiểm tra ffmpeg có cài đúng không (sẽ fail build sớm nếu thiếu, dễ debug hơn)
RUN ffmpeg -version && python3 -c "import ctypes.util; assert ctypes.util.find_library('opus'), 'libopus KHONG duoc tim thay'"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kiểm tra davey import được không (fail sớm nếu wheel không khớp kiến trúc/CPU)
RUN python3 -c "import davey; print('davey OK:', davey.__file__)"

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "bot.py"]
