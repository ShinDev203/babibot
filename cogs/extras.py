"""
cogs/extras.py
Các tính năng thêm cho vui:
- Mini-game oẳn tù tì (kéo búa bao) với Su, thắng thì cộng điểm thân mật
- Nhật ký cá nhân: !nhatky để ghi lại một ngày của mình, Su phản hồi đồng cảm
- Chào mừng thành viên mới vào server, Su tự giới thiệu bản thân
"""

import os
import random

import discord
from discord.ext import commands

import database as db
import ai_chat
import time_utils
import discord_utils

OWNER_ID = int(os.getenv("OWNER_ID", "1023838827556655186"))

RPS_CHOICES = {"bua": "✊ Búa", "keo": "✌️ Kéo", "bao": "✋ Bao"}
RPS_BEATS = {"bua": "keo", "keo": "bao", "bao": "bua"}  # key thắng value

TRUTHS = [
    "Lần gần nhất anh nói dối là khi nào?",
    "Điều anh sợ nhất khi code/deploy là gì?",
    "Kỷ niệm vui nhất khi chơi GTA5VN của anh là gì?",
    "Nếu được nghỉ 1 tuần không làm gì, anh sẽ làm gì?",
    "Điều gì ở Su khiến anh thấy dễ chịu nhất?",
]

DARES = [
    "Gửi 1 câu hát bất kỳ đang nghĩ trong đầu vào chat.",
    "Đổi status Discord thành thứ gì đó vui trong 10 phút.",
    "Kể 1 câu chuyện cười (dở cũng được) cho Su nghe.",
    "Gửi 3 emoji miêu tả tâm trạng hiện tại, không giải thích.",
    "Nhắn khen 1 người bạn trong server 1 câu thật lòng.",
]


class Extras(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- Mini-game: Oẳn tù tì ----------------

    @commands.hybrid_command(name="oan", help="Chơi oẳn tù tì với Su: !oan bua/keo/bao")
    async def rock_paper_scissors(self, ctx: commands.Context, choice: str):
        choice = choice.lower().strip()
        if choice not in RPS_CHOICES:
            await ctx.reply("Chọn 1 trong 3: `bua`, `keo`, hoặc `bao` nha anh 😄")
            return

        su_choice = random.choice(list(RPS_CHOICES.keys()))

        if choice == su_choice:
            result = "Hoà rồi! Chơi lại xem ai thắng nào 😆"
        elif RPS_BEATS[choice] == su_choice:
            result = "Anh thắng rồi đó! Su chịu thua 🥹"
            db.add_affection(str(ctx.author.id), 2)
        else:
            result = "Su thắng nha, hihi 😏 lần sau ráng đoán ý Su đi"
            db.add_affection(str(ctx.author.id), 1)

        await ctx.reply(f"Anh ra {RPS_CHOICES[choice]} — Su ra {RPS_CHOICES[su_choice]}\n{result}")

    # ---------------- Thật hay thách ----------------

    @commands.hybrid_command(name="thatthach", aliases=["tot"], help="Chơi thật hay thách với Su")
    async def truth_or_dare(self, ctx: commands.Context, choice: str = None):
        choice = (choice or "").lower().strip()
        if choice in ("thach", "thách", "dare"):
            await ctx.reply(f"🔥 Thách: {random.choice(DARES)}")
        elif choice in ("that", "thật", "truth"):
            await ctx.reply(f"🧐 Thật: {random.choice(TRUTHS)}")
        else:
            await ctx.reply("Chọn `!thatthach that` hoặc `!thatthach thach` nha 😏")

    # ---------------- Đoán số ----------------

    @commands.hybrid_command(name="doanso", help="Bắt đầu game đoán số 1-100 với Su")
    async def start_guess(self, ctx: commands.Context):
        secret = random.randint(1, 100)
        db.start_guess_game(str(ctx.author.id), secret, 1, 100)
        await ctx.reply("Su đã nghĩ ra 1 số từ **1 đến 100**, đoán bằng `!doan <số>` nha! 🎯")

    @commands.hybrid_command(name="doan", help="Đoán số trong game !doanso, vd: !doan 50")
    async def guess_number(self, ctx: commands.Context, number: int):
        row = db.get_guess_game(str(ctx.author.id))
        if row is None:
            await ctx.reply("Chưa có game nào đang chơi, gõ `!doanso` để bắt đầu nha.")
            return
        secret, low, high, attempts = row
        db.increment_guess_attempt(str(ctx.author.id))
        if number == secret:
            db.end_guess_game(str(ctx.author.id))
            db.add_affection(str(ctx.author.id), 3)
            await ctx.reply(f"Đúng rồi đó!! 🎉 Số là **{secret}**, anh đoán đúng sau {attempts + 1} lần thử!")
        elif number < secret:
            await ctx.reply(f"Lớn hơn {number} nữa nha 📈 (đang đoán trong khoảng {max(low, number)}-{high})")
        else:
            await ctx.reply(f"Nhỏ hơn {number} nữa nha 📉 (đang đoán trong khoảng {low}-{min(high, number)})")

    @commands.hybrid_command(name="bocuoc", help="Bỏ cuộc game đoán số hiện tại")
    async def give_up_guess(self, ctx: commands.Context):
        row = db.get_guess_game(str(ctx.author.id))
        if row is None:
            await ctx.reply("Đâu có game nào đang chơi đâu 😄")
            return
        secret = row[0]
        db.end_guess_game(str(ctx.author.id))
        await ctx.reply(f"Thôi được, số đó là **{secret}**. Chơi lại thì gõ `!doanso` nha 😌")

    # ---------------- Nhật ký cá nhân ----------------

    @commands.hybrid_command(name="nhatky", help="Viết nhật ký hôm nay, vd: !nhatky hôm nay mệt nhưng vui")
    async def write_diary(self, ctx: commands.Context, *, content: str):
        discord_id = str(ctx.author.id)
        today = time_utils.today_str()
        db.add_diary(discord_id, today, content)
        try:
            reply = ai_chat.chat_reply(
                discord_id,
                ctx.author.display_name,
                f"[Hệ thống] Anh Shin vừa viết nhật ký hôm nay: \"{content}\". "
                f"Hãy đọc và phản hồi thật nhẹ nhàng, đồng cảm, như một người bạn gái luôn lắng nghe, "
                f"không cần phán xét hay đưa lời khuyên trừ khi được hỏi.",
            )
        except Exception:
            reply = "Su đọc rồi nè, cảm ơn anh đã chia sẻ với Su 🥰 Su luôn ở đây nghe anh kể."
        await discord_utils.send_long(ctx.channel.send, reply, first_reply=lambda t: ctx.reply(t))

    @commands.hybrid_command(name="xemnhatky", help="Xem lại vài trang nhật ký gần đây")
    async def show_diary(self, ctx: commands.Context):
        rows = db.get_recent_diary(str(ctx.author.id))
        if not rows:
            await ctx.reply("Chưa có trang nhật ký nào cả, thử `!nhatky <nội dung>` xem sao 📖")
            return
        text = "\n\n".join(f"**{d}**\n{c}" for d, c in rows)
        await discord_utils.send_long(ctx.channel.send, text, first_reply=lambda t: ctx.reply(t))

    # ---------------- Chào thành viên mới ----------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        channel = member.guild.system_channel
        if channel is None:
            return
        try:
            reply = ai_chat.chat_reply(
                str(member.id),
                member.display_name,
                f"[Hệ thống] Có thành viên mới tên \"{member.display_name}\" vừa vào server. "
                f"Hãy chào mừng thật thân thiện, tự giới thiệu ngắn gọn bạn là ai.",
            )
        except Exception:
            reply = (
                f"Chào mừng {member.mention} đến với server nha! Mình là BabyBoo (hay gọi là Su), "
                f"bạn gái của Shin, rất vui được gặp bạn 😊"
            )
        await channel.send(reply)


async def setup(bot: commands.Bot):
    await bot.add_cog(Extras(bot))
