"""
cogs/chat.py
- Lắng nghe tin nhắn (mention hoặc DM) để chat bằng AI (Groq).
- Lệnh ghi nhớ / quên / xem trí nhớ.
- Điểm thân mật đơn giản.
- Chào hỏi khi phát hiện Shin bắt đầu chơi GTA5VN / Liên Minh / Valorant qua Rich Presence.
"""

import os
import time
import random
import discord
from discord import app_commands
from discord.ext import commands

import database as db
import ai_chat
import time_utils
import discord_utils

OWNER_ID = int(os.getenv("OWNER_ID", "1023838827556655186"))

# Các game Su sẽ để ý và chào khi Shin bắt đầu chơi
WATCHED_GAMES = {
    "gta5vn": "GTA5VN",
    "grand theft auto v": "GTA5VN",
    "valorant": "Valorant",
    "league of legends": "Liên Minh Huyền Thoại",
}

GREET_COOLDOWN_SECONDS = 60 * 30  # 30 phút mới chào lại cùng 1 game

# Người không phải Shin bị giới hạn tốc độ chat để tránh 1 người spam làm hết quota Groq free
# (Shin dùng chung 1 GROQ_API_KEY cho toàn bộ server/DM).
NON_OWNER_CHAT_COOLDOWN_SECONDS = 8

# ---- Cấu hình tính năng "chen vào trò chuyện nhóm" ----
CHIME_WINDOW_SECONDS = 120       # chỉ xét các tin nhắn trong 2 phút gần nhất
CHIME_BUFFER_MAXLEN = 12         # giữ tối đa bao nhiêu tin nhắn gần đây / channel
CHIME_MIN_DISTINCT_AUTHORS = 2   # cần ít nhất 2 người khác nhau đang nói chuyện
CHIME_MIN_MENTION_EVENTS = 2     # cần ít nhất 2 lượt nhắc tên/mention nhau
CHIME_COOLDOWN_SECONDS = 300     # Su không chen vào quá 1 lần / 5 phút / channel
CHIME_CHANCE = 0.3               # xác suất Su chen vào khi điều kiện đủ
CHIME_SETTING_KEY = "chime_in_enabled"


class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_activity: dict[int, list[dict]] = {}
        self.last_chime_at: dict[int, float] = {}
        self.last_non_owner_chat_at: dict[int, float] = {}

    # ---------------- Chat AI ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Nếu tin nhắn là 1 lệnh bot (vd "!help", "!play ...") thì để hệ thống command xử lý riêng,
        # KHÔNG coi đây là chat thường hay tin nhắn nhóm - tránh AI trả lời lung tung vào lệnh.
        prefixes = await self.bot.get_prefix(message)
        if isinstance(prefixes, str):
            prefixes = (prefixes,)
        if any(message.content.startswith(p) for p in prefixes):
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.bot.user in message.mentions if self.bot.user else False

        # Tin nhắn thoại (voice message) hoặc file âm thanh đính kèm -> chuyển thành văn bản
        audio_attachment = None
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("audio"):
                audio_attachment = att
                break

        if audio_attachment and (is_dm or is_mentioned):
            try:
                audio_bytes = await audio_attachment.read()
                loop = self.bot.loop
                transcript = await loop.run_in_executor(
                    None, ai_chat.transcribe_audio, audio_bytes, audio_attachment.filename
                )
            except Exception as e:
                await message.reply(f"Su nghe không rõ voice message 😅 (lỗi: {type(e).__name__}: {e})", mention_author=False)
                return
            if transcript:
                await self._handle_chat(message, transcript, is_voice=True)
            return

        if not (is_dm or is_mentioned):
            if message.guild is not None:
                await self._maybe_chime_in(message)
            return

        content = message.content
        if is_mentioned and self.bot.user:
            content = content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()

        if not content:
            content = "Su ơi"

        await self._handle_chat(message, content, is_voice=False)

    def _record_activity(self, message: discord.Message):
        """Ghi lại tin nhắn vào bộ nhớ tạm theo channel để phát hiện trò chuyện nhóm."""
        channel_id = message.channel.id
        mentioned_ids = {m.id for m in message.mentions if not m.bot}
        buf = self.channel_activity.setdefault(channel_id, [])
        buf.append({
            "author_id": message.author.id,
            "mentions": mentioned_ids,
            "ts": time.time(),
            "content": message.content[:200],
            "author_name": message.author.display_name,
        })
        if len(buf) > CHIME_BUFFER_MAXLEN:
            buf.pop(0)

    async def _maybe_chime_in(self, message: discord.Message):
        """Nếu phát hiện 2-3 người đang nhắc tên/mention nhau trong đoạn chat, Su có thể chen vào."""
        self._record_activity(message)

        channel_id = message.channel.id
        now = time.time()

        if db.get_setting(str(message.guild.id), CHIME_SETTING_KEY, "1") == "0":
            return

        last_chime = self.last_chime_at.get(channel_id, 0)
        if (now - last_chime) < CHIME_COOLDOWN_SECONDS:
            return

        buf = self.channel_activity.get(channel_id, [])
        recent = [m for m in buf if (now - m["ts"]) <= CHIME_WINDOW_SECONDS]
        distinct_authors = {m["author_id"] for m in recent}
        mention_events = sum(1 for m in recent if m["mentions"])

        if len(distinct_authors) < CHIME_MIN_DISTINCT_AUTHORS or mention_events < CHIME_MIN_MENTION_EVENTS:
            return

        if random.random() > CHIME_CHANCE:
            return

        self.last_chime_at[channel_id] = now

        contains_owner = OWNER_ID in distinct_authors
        context_lines = [f"{m['author_name']}: {m['content']}" for m in recent[-6:]]

        try:
            reply = ai_chat.group_chime_reply(context_lines, contains_owner)
        except Exception:
            return  # không chen vào nếu lỗi, tránh spam tin nhắn lỗi giữa nhóm

        if reply:
            await discord_utils.send_long(message.channel.send, reply)

    async def _handle_chat(self, message: discord.Message, content: str, is_voice: bool = False):
        discord_id = str(message.author.id)
        is_owner = message.author.id == OWNER_ID

        if not is_owner:
            now = time.time()
            last = self.last_non_owner_chat_at.get(message.author.id, 0)
            if (now - last) < NON_OWNER_CHAT_COOLDOWN_SECONDS:
                return  # bỏ qua lặng lẽ, tránh spam làm hết quota Groq free
            self.last_non_owner_chat_at[message.author.id] = now

        # Ghi nhớ nếu người dùng yêu cầu
        ai_chat.try_extract_and_save_fact(discord_id, content)

        if is_owner:
            db.add_affection(discord_id, 1)
            db.bump_streak(discord_id, time_utils.today_str(), time_utils.yesterday_str())

        async with message.channel.typing():
            try:
                reply = ai_chat.chat_reply(discord_id, message.author.display_name, content)
            except Exception as e:
                reply = f"Su bị lag não xíu, thử lại giúp Su nha 🥲 (lỗi: {e})"

        prefix = f"🎙️ *(nghe được: \"{content}\")*\n" if is_voice else ""
        await discord_utils.send_long(
            message.channel.send, prefix + reply, first_reply=lambda t: message.reply(t, mention_author=False)
        )

        # Nếu Shin đang bật chế độ Su tự nói trong voice, và Su đang ở voice cùng server
        if is_owner and message.guild and db.get_setting(discord_id, "voice_reply_enabled", "0") == "1":
            music_cog = self.bot.get_cog("Music")
            if music_cog:
                await music_cog.speak_text(message.guild, reply)

    # ---------------- Lệnh trí nhớ ----------------

    @commands.hybrid_command(name="quenanh", help="Xoá toàn bộ trí nhớ hội thoại và fact của bạn với Su")
    async def forget_me(self, ctx: commands.Context):
        discord_id = str(ctx.author.id)
        db.clear_messages(discord_id)
        db.clear_facts(discord_id)
        await ctx.reply("Su xoá hết trí nhớ về những gì mình từng nói rồi đó 🫧 (nhưng vẫn nhớ anh là ai nha)")

    @commands.hybrid_command(name="trinho", help="Xem những điều Su đang nhớ về bạn")
    async def show_memory(self, ctx: commands.Context):
        facts = db.get_facts(str(ctx.author.id))
        if not facts:
            await ctx.reply("Su chưa ghi nhớ điều gì đặc biệt về bạn cả 🤔")
            return
        text = "\n".join(f"• {f}" for f in facts)
        await ctx.reply(f"Su đang nhớ:\n{text}")

    @commands.hybrid_command(name="nhomgiup", help="Bảo Su ghi nhớ 1 điều gì đó, vd: !nhomgiup anh thích rank Radiant")
    async def remember_this(self, ctx: commands.Context, *, fact: str):
        db.add_fact(str(ctx.author.id), fact)
        await ctx.reply("Su ghi nhớ rồi nè 📝💕")

    @commands.hybrid_command(name="yeu", help="Xem điểm thân mật giữa bạn và Su")
    async def affection(self, ctx: commands.Context):
        points = db.get_affection(str(ctx.author.id))
        await ctx.reply(f"Điểm thân mật của tụi mình: **{points}** 💗")

    @commands.hybrid_command(name="gioithieu", help="Su tự giới thiệu bản thân")
    async def introduce(self, ctx: commands.Context):
        if ctx.author.id == OWNER_ID:
            await ctx.reply("Su là BabyBoo nè, người yêu bé nhỏ của anh Shin đó 💕")
        else:
            await ctx.reply(
                "Chào bạn! Mình là **BabyBoo**, hay được gọi thân mật là **Su**. "
                "Mình là bạn gái của Shin đó nha 😊 Rất vui được nói chuyện với bạn!"
            )

    @commands.hybrid_command(name="su_chenvao_on", help="Bật việc Su chen vào khi thấy nhóm đang nói chuyện rôm rả")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def chime_on(self, ctx: commands.Context):
        db.set_setting(str(ctx.guild.id), CHIME_SETTING_KEY, "1")
        await ctx.reply("Ok, Su sẽ chen vào chat khi thấy mọi người nói chuyện rôm rả nha 👀")

    @commands.hybrid_command(name="su_chenvao_off", help="Tắt việc Su tự chen vào trò chuyện nhóm")
    @app_commands.default_permissions(manage_guild=True)
    @commands.has_permissions(manage_guild=True)
    async def chime_off(self, ctx: commands.Context):
        db.set_setting(str(ctx.guild.id), CHIME_SETTING_KEY, "0")
        await ctx.reply("Ok Su sẽ im lặng, chỉ trả lời khi được mention/DM thôi 🤐")

    # ---------------- Chào theo game (Rich Presence) ----------------

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.id != OWNER_ID:
            return
        if after.bot:
            return

        game_name = None
        for activity in after.activities:
            if activity.type == discord.ActivityType.playing and activity.name:
                lowered = activity.name.lower()
                for key, label in WATCHED_GAMES.items():
                    if key in lowered:
                        game_name = label
                        break
            if game_name:
                break

        if not game_name:
            return

        row = db.get_last_game(str(after.id))
        now = time.time()
        if row:
            last_game, last_greet_at = row
            if last_game == game_name and last_greet_at and (now - last_greet_at) < GREET_COOLDOWN_SECONDS:
                return

        db.set_last_game(str(after.id), game_name)

        try:
            reply = ai_chat.chat_reply(
                str(after.id),
                after.display_name,
                f"[Hệ thống] Anh Shin vừa bắt đầu chơi {game_name}. Hãy nhắn 1 câu ngắn động viên/chào hỏi dễ thương.",
            )
        except Exception:
            reply = f"Chúc anh chơi {game_name} vui vẻ nha, đừng tạch quá nhiều 😘"

        try:
            await after.send(reply)
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Chat(bot))
