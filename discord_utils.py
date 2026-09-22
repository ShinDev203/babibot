"""
discord_utils.py
Discord giới hạn mỗi tin nhắn tối đa 2000 ký tự. Các hàm ở đây tự động chia
tin nhắn dài thành nhiều phần, ưu tiên ngắt ở dấu xuống dòng / dấu câu để
đọc tự nhiên, rồi gửi liên tiếp.
"""

DISCORD_LIMIT = 2000
SAFE_CHUNK_SIZE = 1900  # để dư khoảng trống an toàn


def chunk_text(text: str, chunk_size: int = SAFE_CHUNK_SIZE):
    """Chia text thành list các đoạn <= chunk_size, ưu tiên ngắt tại xuống dòng/khoảng trắng."""
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []

    chunks = []
    while len(text) > chunk_size:
        window = text[:chunk_size]
        split_at = window.rfind("\n\n")
        if split_at == -1:
            split_at = window.rfind("\n")
        if split_at == -1:
            split_at = window.rfind(". ")
        if split_at == -1 or split_at < chunk_size * 0.4:
            split_at = chunk_size  # không tìm được điểm ngắt hợp lý, cắt cứng
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


async def send_long(send_func, text: str, first_reply=None):
    """
    Gửi 1 đoạn text dài qua nhiều tin nhắn nếu cần.
    - send_func: coroutine nhận (content:str) -> gửi tin nhắn (vd: channel.send)
    - first_reply: nếu có, dùng cho tin nhắn đầu tiên (vd: message.reply), các phần
      còn lại sẽ dùng send_func.
    """
    parts = chunk_text(text)
    if not parts:
        return
    if first_reply is not None:
        await first_reply(parts[0])
        for part in parts[1:]:
            await send_func(part)
    else:
        for part in parts:
            await send_func(part)
