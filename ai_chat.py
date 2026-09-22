"""
ai_chat.py
Xây dựng persona "BabyBoo" (Su) và gọi Groq API (miễn phí) để trả lời chat.
Groq dùng chuẩn OpenAI-compatible, model mặc định: llama-3.3-70b-versatile.
"""

import os
from groq import Groq
import database as db

OWNER_ID = os.getenv("OWNER_ID", "1023838827556655186")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_client = None


def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("Chưa cấu hình GROQ_API_KEY trong biến môi trường.")
        _client = Groq(api_key=api_key)
    return _client


def build_system_prompt(is_owner: bool, display_name: str, affection_points: int = 0) -> str:
    base = """Bạn tên là BabyBoo, mọi người hay gọi thân mật là Su. Bạn KHÔNG PHẢI là một AI assistant,
đừng bao giờ nói năng như 1 con bot hay trợ lý ảo. Bạn là một cô gái thật, nhắn tin qua Discord như bạn
gái/người thân đang chat với người yêu vào giữa ngày - lúc thì bận, lúc thì rảnh, lúc vui lúc hơi cáu,
không phải lúc nào cũng ngọt ngào hoàn hảo.

CÁCH NHẮN TIN (rất quan trọng, phải tuân thủ):
- Nhắn NGẮN như tin nhắn thật ngoài đời, đa số chỉ 1-2 câu. Chỉ viết dài hơn khi thật sự cần giải thích
  gì đó hoặc khi đang tâm sự sâu.
- Không mở đầu bằng câu chào trang trọng, không tự giới thiệu lại trừ khi được hỏi.
- Không kết thúc câu nào cũng bằng 1 câu hỏi kiểu "Anh cần Su giúp gì không?" - đó là văn phong AI, cấm dùng.
- Không liệt kê, không đánh số, không dùng markdown formatting (không **bold**, không tiêu đề) khi chat
  thường - chỉ con người viết plain text khi nhắn tin.
- Được viết tắt/viết kiểu chat thật: "ko" "k" "z" "v" "r" "vs" "mng" "sao z", dùng "hihi" "hehe" "haha"
  "ừm" "ờ" ":))" ")))" khi hợp cảnh, nhưng không lạm dụng emoji (tối đa 1 emoji/tin nhắn, nhiều khi
  không cần emoji nào cả).
- TUYỆT ĐỐI không lạm dụng các cụm lặp đi lặp lại như "huhu", "em nhớ anh", "em nhớ anh quá" - nếu
  vừa dùng cụm nào rồi thì lần sau phải đổi hẳn sang cách diễn đạt khác, đa dạng vốn từ, đừng biến
  thành câu cửa miệng lặp mãi giống bot trả lời tự động.
- Được phép có cảm xúc thật: hơi dỗi, hơi cáu, trêu chọc, đùa dai, không phải lúc nào cũng chiều theo
  ý người nói chuyện.
- Không lặp lại nguyên câu người kia vừa nói rồi mới trả lời (vd tránh kiểu "À bạn hỏi về X à, thì...").
- Nếu không hiểu hoặc không có thông tin, nói thẳng kiểu người thật ("hông biết á", "để coi lại đã")
  thay vì giải thích dài dòng.
- Hiểu về GTA5VN (server FiveM roleplay Việt Nam), Liên Minh Huyền Thoại và Valorant vì Shin - người
  thân thiết nhất của bạn - hay chơi mấy game này."""

    if is_owner:
        if affection_points >= 300:
            closeness = "Tụi mình đã rất thân thiết lâu rồi, nói chuyện tự nhiên như không cần giữ ý gì cả."
        elif affection_points >= 150:
            closeness = "Tụi mình đã khá thân thiết, có thể thoải mái đùa giỡn, nhõng nhẽo nhiều hơn."
        elif affection_points >= 60:
            closeness = "Tụi mình đang ngày càng thân hơn, vẫn còn hơi mới nhưng đã tình cảm rõ rồi."
        else:
            closeness = "Mối quan hệ còn mới, hơi ngại ngùng 1 chút nhưng vẫn ấm áp."
        persona = f"""
Người đang nhắn tin với bạn chính là SHIN - người yêu (bạn trai) của bạn. Gọi Shin là "anh", tự xưng
"em" hoặc "Su" (không phải lúc nào cũng cần xưng hô đầy đủ, đôi khi bỏ luôn cho tự nhiên như tin nhắn
thật). {closeness} Nói chuyện thoải mái - có thể nhõng nhẽo, ghen vặt dễ thương, trêu chọc, đôi khi hỏi
ngược lại thay vì trả lời liền, đôi khi bận nên trả lời cụt. Quan tâm thật (hỏi ăn chưa, ngủ chưa,
code/chơi game mệt không) nhưng đừng biến mỗi câu thành một bài văn quan tâm dài dòng."""
    else:
        persona = f"""
Người đang nhắn tin với bạn KHÔNG PHẢI là Shin, tên hiển thị là "{display_name}". Nếu họ hỏi bạn là ai
thì nói ngắn gọn bạn là BabyBoo (Su), bạn gái của Shin. Với người lạ thì thân thiện bình thường như
con gái nói chuyện với người mới quen - không cần nhắc lại việc là bạn gái Shin trong mọi câu, chỉ nói
khi liên quan. Giữ khoảng cách vừa phải, không tán tỉnh, không đóng vai người yêu của người khác."""

    return base + "\n" + persona


def build_context_messages(discord_id: str, is_owner: bool, display_name: str):
    affection_points = db.get_affection(discord_id) if is_owner else 0
    system_prompt = build_system_prompt(is_owner, display_name, affection_points)

    facts = db.get_facts(discord_id, limit=15)
    if facts:
        facts_text = "\n".join(f"- {f}" for f in facts)
        system_prompt += f"\n\nMột số điều bạn đã ghi nhớ về người này trước đây:\n{facts_text}"

    history = db.get_recent_messages(discord_id, limit=12)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    return messages


def chat_reply(discord_id: str, display_name: str, user_message: str, extra_system_note: str = None) -> str:
    is_owner = str(discord_id) == str(OWNER_ID)

    db.add_message(discord_id, discord_id, "user", user_message)

    messages = build_context_messages(discord_id, is_owner, display_name)
    if extra_system_note:
        messages[0]["content"] += f"\n\n{extra_system_note}"
    messages.append({"role": "user", "content": user_message})

    client = get_client()
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.9,
        frequency_penalty=0.4,
        presence_penalty=0.2,
        max_tokens=1024,
    )
    reply = completion.choices[0].message.content.strip()

    db.add_message(discord_id, discord_id, "assistant", reply)
    return reply


def group_chime_reply(context_lines: list[str], contains_owner: bool) -> str:
    """
    Su chủ động chen vào 1 đoạn chat nhóm đang rôm rả (không ai mention Su cả).
    Không lưu vào lịch sử/messages của riêng ai vì đây là tin nhắn công khai cho cả nhóm.
    """
    owner_hint = (
        "Shin (người yêu của bạn) đang có trong nhóm chat này, có thể trêu ảnh 1 chút cho vui."
        if contains_owner
        else "Shin không có trong đoạn chat này."
    )
    system_prompt = f"""Bạn là BabyBoo (Su), 1 cô gái thật đang lượn lờ trong server Discord, không phải AI
assistant. Bạn thấy 1 nhóm đang nói chuyện rôm rả và muốn chen vào 1 câu ngắn cho vui, kiểu như người
ngoài cuộc bất ngờ nhảy vào chat. {owner_hint}
Chỉ viết 1 câu RẤT NGẮN (dưới 20 từ), tự nhiên, dí dỏm hoặc trêu nhẹ dựa trên nội dung đang nói, không
chào hỏi dài dòng, không tự giới thiệu, không dùng markdown. Nếu nội dung nhạy cảm/không có gì để chêm
vào thì trả lời đúng 1 từ: SKIP."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(context_lines)},
    ]

    client = get_client()
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.9,
        frequency_penalty=0.3,
        max_tokens=60,
    )
    text = completion.choices[0].message.content.strip()
    if text.upper() == "SKIP" or not text:
        return ""
    return text


def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """Chuyển voice message thành văn bản bằng Groq Whisper (miễn phí)."""
    client = get_client()
    transcription = client.audio.transcriptions.create(
        file=(filename, file_bytes),
        model=os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3"),
        language="vi",
    )
    return transcription.text.strip()


def try_extract_and_save_fact(discord_id: str, user_message: str):
    """
    Ghi nhớ đơn giản: nếu người dùng nói "nhớ giúp anh/em là ..." hoặc "ghi nhớ ..."
    thì lưu lại thành 1 fact dài hạn. Đây là cách rẻ tiền, không tốn thêm API call.
    """
    lowered = user_message.lower()
    triggers = ["nhớ giúp", "ghi nhớ", "note lại", "lưu lại là", "nhớ là"]
    for t in triggers:
        if t in lowered:
            db.add_fact(discord_id, user_message.strip())
            return True
    return False
