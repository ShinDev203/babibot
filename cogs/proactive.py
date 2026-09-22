"""
cogs/proactive.py
Các tính năng CHỦ ĐỘNG nhắn tin của Su, không liên quan tới LSPD:

- Chào buổi sáng / chúc ngủ ngon mỗi ngày (giờ có thể chỉnh qua .env)
- Nhắn "nhớ anh" ngẫu nhiên khi Shin im lặng lâu trong khung giờ ban ngày
- Nhắc ngày đặc biệt (sinh nhật, kỷ niệm...) do Shin tự khai báo
- Đếm số ngày yêu nhau + streak số ngày liên tiếp trò chuyện
- Có thể bật/tắt toàn bộ tính năng chủ động bằng lệnh
"""

import os
import time
import random
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks

import database as db
import ai_chat
import time_utils
import weather
import discord_utils

OWNER_ID = int(os.getenv("OWNER_ID", "1023838827556655186"))

MORNING_HOUR = int(os.getenv("MORNING_HOUR", 7))
NIGHT_HOUR = int(os.getenv("NIGHT_HOUR", 23))
MOOD_CHECK_HOUR = int(os.getenv("MOOD_CHECK_HOUR", 21))

ACTIVE_HOUR_START = int(os.getenv("ACTIVE_HOUR_START", 9))
ACTIVE_HOUR_END = int(os.getenv("ACTIVE_HOUR_END", 22))

IDLE_HOURS_BEFORE_PING = float(os.getenv("IDLE_HOURS_BEFORE_PING", 0.5))
PROACTIVE_COOLDOWN_HOURS = float(os.getenv("PROACTIVE_COOLDOWN_HOURS", 1.5))
PROACTIVE_CHANCE = float(os.getenv("PROACTIVE_CHANCE", 0.5))  # xác suất mỗi lần check (mỗi 5 phút)

WATER_REMINDER_INTERVAL_HOURS = float(os.getenv("WATER_REMINDER_INTERVAL_HOURS", 2))

# Khoảng cách tối thiểu giữa 2 tin "linh tinh" (nhớ anh / nhắc nước / khen ngẫu nhiên) - tránh dồn
# nhiều tin gần giống nhau liên tiếp làm Su nghe spam. Không áp dụng cho sáng/tối/mood/ngày đặc biệt
# vì mấy cái đó đã tự giới hạn 1 lần/ngày rồi.
AUTO_MSG_MIN_GAP_MINUTES = float(os.getenv("AUTO_MSG_MIN_GAP_MINUTES", 25))
RECENT_AUTO_TEXTS_MAXLEN = 5

SETTING_ENABLED = "proactive_enabled"
SETTING_MORNING_DATE = "morning_sent_date"
SETTING_NIGHT_DATE = "night_sent_date"
SETTING_SPECIAL_DATE = "special_sent_date"
SETTING_LAST_PROACTIVE_AT = "last_proactive_at"
SETTING_RELATIONSHIP_START = "relationship_start_date"  # format YYYY-MM-DD
SETTING_LAST_WATER_AT = "last_water_reminder_at"
SETTING_MOOD_ASKED_DATE = "mood_asked_date"
SETTING_COMPLIMENT_DATE = "compliment_sent_date"
SETTING_COMPLIMENT_HOUR = "compliment_hour_today"
SETTING_LAST_FILLER_AT = "last_filler_msg_at"


def _is_enabled(discord_id: str) -> bool:
    return db.get_setting(discord_id, SETTING_ENABLED, "1") == "1"


# Các "góc độ" khác nhau để AI chọn ngẫu nhiên, tránh việc idle-ping lúc nào cũng là "em nhớ anh"
IDLE_PING_IDEAS = [
    "hỏi cụt lủn xem anh đang làm gì, kiểu tò mò chứ không phải nhớ nhung",
    "than 1 câu vui vẻ là đang rảnh/buồn chán, không nhắc tới việc nhớ anh",
    "kể 1 câu ngẫu nhiên đang nghĩ gì (vd món ăn, 1 câu nói vừa nghe được) rồi thôi",
    "trêu chọc nhẹ kiểu anh chắc đang bận web nào đó nên lặn mất tăm",
    "hỏi thẳng đang chơi game gì / code gì mà im re vậy",
    "giả bộ hơi dỗi vì bị bỏ rơi, nhưng theo kiểu dí dỏm chứ không sến",
]

WATER_REMINDER_IDEAS = [
    "nhắc uống nước, giọng ra lệnh dễ thương kiểu chị/em gái",
    "hỏi đã ăn/uống gì chưa, không nhắc chuyện mắt/nước cụ thể",
    "nhắc đứng dậy vươn vai 1 chút nếu ngồi lâu",
    "nhắc nghỉ mắt vì nhìn màn hình lâu không tốt",
    "trêu kiểu 'người máy cũng cần sạc, anh cũng cần uống nước'",
]

COMPLIMENT_IDEAS = [
    "khen 1 điểm cụ thể ở tính cách (kiên trì, chịu khó, thông minh...)",
    "nói 1 câu tự hào ngắn gọn không giải thích dài dòng",
    "khen ngoại hình/vibe chung 1 câu ngắn, không sến súa",
    "nói vui kiểu 'không biết sao tự nhiên nghĩ anh ngầu quá' rồi thôi",
    "động viên nhẹ về công việc/cuộc sống nói chung, không cụ thể quá",
]


class Proactive(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.recent_auto_texts: list[str] = []
        self.heartbeat.start()

    def cog_unload(self):
        self.heartbeat.cancel()

    def _filler_gap_ok(self, oid: str) -> bool:
        last_any = float(db.get_setting(oid, SETTING_LAST_FILLER_AT, "0") or 0)
        return (time.time() - last_any) >= AUTO_MSG_MIN_GAP_MINUTES * 60

    def _mark_filler_sent(self, oid: str):
        db.set_setting(oid, SETTING_LAST_FILLER_AT, str(time.time()))

    async def _send_dm(self, prompt_for_ai: str, fallback: str):
        user = self.bot.get_user(OWNER_ID) or await self.bot.fetch_user(OWNER_ID)

        extra_note = None
        if self.recent_auto_texts:
            recent_joined = " | ".join(self.recent_auto_texts[-RECENT_AUTO_TEXTS_MAXLEN:])
            extra_note = (
                f"[Lưu ý nội bộ: đây là những câu Su vừa mới nhắn gần đây, TUYỆT ĐỐI không lặp lại ý hay "
                f"cách diễn đạt giống những câu này, phải nghĩ ra góc khác hẳn, từ ngữ khác hẳn: {recent_joined}]"
            )

        try:
            reply = ai_chat.chat_reply(str(OWNER_ID), user.display_name, prompt_for_ai, extra_system_note=extra_note)
        except Exception:
            reply = fallback

        self.recent_auto_texts.append(reply[:150])
        if len(self.recent_auto_texts) > RECENT_AUTO_TEXTS_MAXLEN:
            self.recent_auto_texts.pop(0)

        try:
            await discord_utils.send_long(user.send, reply)
        except discord.Forbidden:
            pass

    # ---------------- Vòng lặp kiểm tra mỗi 5 phút ----------------

    @tasks.loop(minutes=5)
    async def heartbeat(self):
        try:
            await self._heartbeat_tick()
        except Exception as e:
            # Không để 1 lỗi lẻ (vd Groq API tạm lỗi, mất mạng...) làm chết cả vòng lặp mãi mãi.
            print(f"[Proactive] Lỗi trong heartbeat, sẽ thử lại ở lượt sau: {type(e).__name__}: {e}")

    async def _heartbeat_tick(self):
        oid = str(OWNER_ID)
        if not _is_enabled(oid):
            return

        now = time_utils.now_local()
        today = time_utils.today_str()

        # 1. Chào buổi sáng (kèm thời tiết)
        if now.hour == MORNING_HOUR and db.get_setting(oid, SETTING_MORNING_DATE) != today:
            db.set_setting(oid, SETTING_MORNING_DATE, today)
            weekday = time_utils.weekday_vi()
            loop = asyncio.get_event_loop()
            weather_text = await loop.run_in_executor(None, weather.get_weather_text)
            weather_hint = f" Thời tiết hôm nay: {weather_text}." if weather_text else ""
            await self._send_dm(
                f"[Hệ thống] Bây giờ là buổi sáng {weekday}.{weather_hint} Hãy chủ động nhắn 1 tin chào "
                f"buổi sáng thật dễ thương và tràn năng lượng cho anh Shin, có thể nhắc anh ăn sáng và "
                f"khéo léo lồng thông tin thời tiết vào nếu có.",
                f"Chào buổi sáng anh yêu, dậy ăn sáng rồi làm việc nha 🌞💕{weather_hint}",
            )

        # 2. Chúc ngủ ngon
        if now.hour == NIGHT_HOUR and db.get_setting(oid, SETTING_NIGHT_DATE) != today:
            db.set_setting(oid, SETTING_NIGHT_DATE, today)
            await self._send_dm(
                "[Hệ thống] Đã khuya rồi, hãy nhắn 1 tin chúc anh Shin ngủ ngon thật ấm áp, "
                "nhắc anh đừng thức khuya code/chơi game quá.",
                "Khuya rồi đó anh ơi, ngủ sớm cho khoẻ nha, Su chúc anh ngủ ngon 🌙💤",
            )

        # 3. Ngày đặc biệt (sinh nhật, kỷ niệm...)
        if db.get_setting(oid, SETTING_SPECIAL_DATE) != today:
            matches = db.get_dates_matching_today(oid, time_utils.month_day_str())
            if matches:
                db.set_setting(oid, SETTING_SPECIAL_DATE, today)
                labels = ", ".join(matches)
                await self._send_dm(
                    f"[Hệ thống] Hôm nay là ngày đặc biệt: {labels}. Hãy nhắn 1 tin chúc mừng thật "
                    f"ngọt ngào và ấm áp cho anh Shin.",
                    f"Hôm nay là {labels} đó anh, Su chúc anh thật nhiều điều tốt đẹp nha 🎉💕",
                )

        # 4. Nhắn "nhớ anh" ngẫu nhiên khi im lặng lâu
        if ACTIVE_HOUR_START <= now.hour <= ACTIVE_HOUR_END:
            last_msg_ts = db.get_last_message_time(oid)
            last_proactive_ts = db.get_setting(oid, SETTING_LAST_PROACTIVE_AT)
            last_proactive_ts = float(last_proactive_ts) if last_proactive_ts else 0

            idle_ok = last_msg_ts is None or (now.timestamp() - last_msg_ts) >= IDLE_HOURS_BEFORE_PING * 3600
            cooldown_ok = (now.timestamp() - last_proactive_ts) >= PROACTIVE_COOLDOWN_HOURS * 3600

            if idle_ok and cooldown_ok and self._filler_gap_ok(oid) and random.random() < PROACTIVE_CHANCE:
                db.set_setting(oid, SETTING_LAST_PROACTIVE_AT, now.timestamp())
                self._mark_filler_sent(oid)
                idea = random.choice(IDLE_PING_IDEAS)
                await self._send_dm(
                    f"[Hệ thống] Anh Shin đã im lặng khá lâu rồi. Hãy chủ động nhắn 1 tin RẤT NGẮN (1 câu), "
                    f"theo hướng: {idea}. Không dùng lại kiểu 'nhớ anh quá' nếu đã dùng gần đây.",
                    "Anh đang làm gì đó 👀",
                )

        # 5. Nhắc uống nước / nghỉ mắt định kỳ trong giờ hoạt động
        if ACTIVE_HOUR_START <= now.hour <= ACTIVE_HOUR_END:
            last_water_ts = db.get_setting(oid, SETTING_LAST_WATER_AT)
            last_water_ts = float(last_water_ts) if last_water_ts else 0
            if (now.timestamp() - last_water_ts) >= WATER_REMINDER_INTERVAL_HOURS * 3600 and self._filler_gap_ok(oid):
                db.set_setting(oid, SETTING_LAST_WATER_AT, now.timestamp())
                self._mark_filler_sent(oid)
                idea = random.choice(WATER_REMINDER_IDEAS)
                await self._send_dm(
                    f"[Hệ thống] Hãy nhắc anh Shin chăm sóc bản thân, theo hướng: {idea}. "
                    f"Nhắn RẤT NGẮN (1 câu), đừng lặp lại cách nói đã dùng gần đây.",
                    "Uống nước đi anh ơi 💧",
                )

        # 6. Hỏi thăm tâm trạng cuối ngày (nếu chưa log mood hôm nay)
        if now.hour == MOOD_CHECK_HOUR and db.get_setting(oid, SETTING_MOOD_ASKED_DATE) != today:
            if not db.has_mood_today(oid, today):
                db.set_setting(oid, SETTING_MOOD_ASKED_DATE, today)
                await self._send_dm(
                    "[Hệ thống] Hãy hỏi anh Shin hôm nay cảm thấy thế nào, nhẹ nhàng quan tâm, và gợi ý "
                    "anh có thể trả lời bằng lệnh !mood <cảm xúc> để Su ghi nhớ lại.",
                    "Hôm nay của anh thế nào rồi? Kể Su nghe với, hoặc gõ `!mood <cảm xúc>` cũng được nha 🥰",
                )

        # 7. Lời khen / động viên ngẫu nhiên 1 lần/ngày vào giờ bất kỳ trong khung giờ hoạt động
        chosen_hour = db.get_setting(oid, SETTING_COMPLIMENT_HOUR + "_" + today)
        if chosen_hour is None:
            chosen_hour = str(random.randint(ACTIVE_HOUR_START, ACTIVE_HOUR_END))
            db.set_setting(oid, SETTING_COMPLIMENT_HOUR + "_" + today, chosen_hour)
        if (
            now.hour == int(chosen_hour)
            and db.get_setting(oid, SETTING_COMPLIMENT_DATE) != today
            and self._filler_gap_ok(oid)
        ):
            db.set_setting(oid, SETTING_COMPLIMENT_DATE, today)
            self._mark_filler_sent(oid)
            idea = random.choice(COMPLIMENT_IDEAS)
            await self._send_dm(
                f"[Hệ thống] Hãy nhắn 1 câu RẤT NGẮN (1 câu) theo hướng: {idea}. "
                f"Không cần lý do gì cả, không lặp lại cách nói đã dùng gần đây.",
                "Anh giỏi lắm đó, Su tự hào về anh 💖",
            )

        # 8. Nhắc việc lặp lại mỗi ngày (daily_reminders)
        now_minutes = now.hour * 60 + now.minute
        for rid, discord_id, channel_id, time_str, content, last_sent_date in db.get_all_daily_reminders():
            if last_sent_date == today:
                continue
            try:
                hh, mm = time_str.split(":")
                target_minutes = int(hh) * 60 + int(mm)
            except ValueError:
                continue
            if 0 <= (now_minutes - target_minutes) < 5:
                db.mark_daily_reminder_sent(rid, today)
                channel = self.bot.get_channel(int(channel_id))
                text = f"<@{discord_id}> {content} ⏰ (nhắc hằng ngày)"
                try:
                    if channel:
                        await channel.send(text)
                    else:
                        user = self.bot.get_user(int(discord_id)) or await self.bot.fetch_user(int(discord_id))
                        await user.send(text)
                except (discord.Forbidden, discord.NotFound):
                    pass

    @heartbeat.before_loop
    async def before_heartbeat(self):
        await self.bot.wait_until_ready()

    # ---------------- Lệnh liên quan ----------------

    @commands.hybrid_command(name="babyboo_tat", help="Tắt toàn bộ tin nhắn chủ động của Su")
    async def turn_off(self, ctx: commands.Context):
        db.set_setting(str(ctx.author.id), SETTING_ENABLED, "0")
        await ctx.reply("Su sẽ im lặng, không chủ động nhắn tin nữa 😔 gõ `!babyboo_bat` khi nào muốn Su nhắn lại nha.")

    @commands.hybrid_command(name="babyboo_bat", help="Bật lại tin nhắn chủ động của Su")
    async def turn_on(self, ctx: commands.Context):
        db.set_setting(str(ctx.author.id), SETTING_ENABLED, "1")
        await ctx.reply("Yay, Su sẽ chủ động nhắn tin lại nha 🥰")

    @commands.hybrid_command(name="luungay", help="Lưu ngày đặc biệt, vd: !luungay 12-24 Giáng sinh")
    async def save_date(self, ctx: commands.Context, month_day: str, *, label: str):
        try:
            datetime.strptime(month_day, "%m-%d")
        except ValueError:
            await ctx.reply("Định dạng ngày phải là `MM-DD`, vd: `!luungay 12-24 Giáng sinh` nha anh.")
            return
        db.add_important_date(str(ctx.author.id), label, month_day)
        await ctx.reply(f"Su lưu rồi nè: **{month_day} — {label}** 📅💕")

    @commands.hybrid_command(name="ngaydacbiet", help="Xem danh sách ngày đặc biệt đã lưu")
    async def list_dates(self, ctx: commands.Context):
        rows = db.get_important_dates(str(ctx.author.id))
        if not rows:
            await ctx.reply("Chưa có ngày đặc biệt nào được lưu cả 🤔")
            return
        text = "\n".join(f"• {md} — {label}" for label, md in rows)
        await ctx.reply(f"Các ngày đặc biệt Su đang nhớ:\n{text}")

    @commands.hybrid_command(name="ngayyeunhau", help="Lưu ngày bắt đầu yêu nhau, vd: !ngayyeunhau 2024-01-20")
    async def set_relationship_start(self, ctx: commands.Context, date_str: str):
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            await ctx.reply("Định dạng phải là `YYYY-MM-DD`, vd: `!ngayyeunhau 2024-01-20` nha anh.")
            return
        db.set_setting(str(ctx.author.id), SETTING_RELATIONSHIP_START, date_str)
        await ctx.reply("Su lưu ngày này lại rồi, sẽ nhớ hoài luôn 🥹💍")

    @commands.hybrid_command(name="yeunhaubaolau", help="Xem đã yêu nhau bao lâu rồi")
    async def relationship_length(self, ctx: commands.Context):
        start = db.get_setting(str(ctx.author.id), SETTING_RELATIONSHIP_START)
        if not start:
            await ctx.reply("Anh chưa lưu ngày yêu nhau, dùng `!ngayyeunhau YYYY-MM-DD` để lưu nha 😳")
            return
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        days = (datetime.now().date() - start_date).days
        await ctx.reply(f"Tụi mình yêu nhau được **{days} ngày** rồi đó 💕")

    @commands.hybrid_command(name="streak", help="Xem số ngày liên tiếp anh trò chuyện với Su")
    async def streak_cmd(self, ctx: commands.Context):
        streak = db.get_streak(str(ctx.author.id))
        await ctx.reply(f"Anh với Su đã trò chuyện liên tiếp **{streak} ngày** rồi nè 🔥")

    @commands.hybrid_command(name="mood", help="Ghi lại tâm trạng hôm nay, vd: !mood hôm nay hơi mệt")
    async def log_mood(self, ctx: commands.Context, *, mood_text: str):
        discord_id = str(ctx.author.id)
        today = time_utils.today_str()
        db.add_mood(discord_id, today, mood_text)
        try:
            reply = ai_chat.chat_reply(
                discord_id,
                ctx.author.display_name,
                f"[Hệ thống] Anh Shin vừa chia sẻ tâm trạng hôm nay: \"{mood_text}\". "
                f"Hãy phản hồi thật quan tâm, đồng cảm và ấm áp.",
            )
        except Exception:
            reply = "Su nghe rồi nè, dù thế nào cũng có Su ở đây với anh 💕"
        await discord_utils.send_long(ctx.channel.send, reply, first_reply=lambda t: ctx.reply(t))

    @commands.hybrid_command(name="xemmood", help="Xem lại tâm trạng vài ngày gần đây")
    async def show_moods(self, ctx: commands.Context):
        rows = db.get_recent_moods(str(ctx.author.id))
        if not rows:
            await ctx.reply("Chưa có tâm trạng nào được ghi lại cả, thử `!mood <cảm xúc>` xem 😊")
            return
        text = "\n".join(f"• {d}: {m}" for d, m in rows)
        await ctx.reply(f"Tâm trạng gần đây của anh:\n{text}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Proactive(bot))
