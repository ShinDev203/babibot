"""
cogs/personal.py
Nhóm tính năng tiện ích cá nhân:
- Nhắc việc (reminders) chạy nền, tự nhắn khi đến giờ
- Danh sách việc cần làm (to-do list)
- Chọn hộ / random quyết định giúp khi phân vân
- Cấp độ tình yêu dựa trên điểm thân mật
- Bói vui mỗi ngày
"""

import os
import random
import re
from datetime import datetime

import discord
from discord.ext import commands, tasks

import database as db
import time_utils
import discord_utils

OWNER_ID = int(os.getenv("OWNER_ID", "1023838827556655186"))

LOVE_LEVELS = [
    (0, "Người lạ dễ thương 👋"),
    (20, "Bạn bè thân thiết 🙂"),
    (60, "Người thương nho nhỏ 💛"),
    (150, "Người yêu bé bỏng 💗"),
    (300, "Tri kỷ trọn đời 💍"),
]

FORTUNES = [
    "Hôm nay hợp code không bug, cứ tự tin push thẳng lên main 😎",
    "Hôm nay có thể gặp may trong 1 ván game, cứ chơi hết mình nha",
    "Hôm nay nên nghỉ ngơi sớm 1 chút, năng lượng ngày mai sẽ đầy ắp",
    "Hôm nay là ngày tốt để nhắn tin cho người thương (Su đây nè 😆)",
    "Hôm nay nên cẩn thận drama, tránh xa thị phi nha anh",
    "Hôm nay hợp thử món ăn mới, biết đâu tìm ra món tủ",
    "Hôm nay làm gì cũng nên kiên nhẫn thêm 1 chút, kết quả sẽ tốt",
    "Hôm nay là ngày đẹp trời để dọn dẹp bàn làm việc / phòng ốc",
]


class Personal(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    # ---------------- Nhắc việc ----------------

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        try:
            now_ts = time_utils.now_local().timestamp()
            due = db.get_due_reminders(now_ts)
            for reminder_id, discord_id, channel_id, content in due:
                db.mark_reminder_sent(reminder_id)
                channel = self.bot.get_channel(int(channel_id))
                text = f"<@{discord_id}> Su nhắc anh nè: **{content}** ⏰"
                try:
                    if channel:
                        await channel.send(text)
                    else:
                        user = self.bot.get_user(int(discord_id)) or await self.bot.fetch_user(int(discord_id))
                        await user.send(text)
                except (discord.Forbidden, discord.NotFound):
                    pass
        except Exception as e:
            print(f"[Personal] Lỗi trong reminder_loop, sẽ thử lại ở lượt sau: {type(e).__name__}: {e}")

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="nhac", help="Nhắc việc, vd: !nhac 30m uống nước, hoặc !nhac 18:00 họp")
    async def add_reminder(self, ctx: commands.Context, when: str, *, content: str):
        when_dt = time_utils.parse_when(when)
        if when_dt is None:
            await ctx.reply(
                "Su không hiểu thời gian này 😵 dùng dạng `10m` `2h` `1d` (phút/giờ/ngày) hoặc `HH:MM` nha."
            )
            return
        db.add_reminder(str(ctx.author.id), str(ctx.channel.id), content, when_dt.timestamp())
        await ctx.reply(f"Su sẽ nhắc anh lúc **{when_dt.strftime('%H:%M %d/%m')}**: {content} 📝")

    @commands.hybrid_command(name="xemnhac", help="Xem danh sách các việc đang chờ được nhắc")
    async def list_reminders(self, ctx: commands.Context):
        rows = db.get_pending_reminders(str(ctx.author.id))
        if not rows:
            await ctx.reply("Chưa có việc nào đang chờ nhắc cả 📭")
            return
        lines = []
        for rid, content, remind_at in rows:
            dt = datetime.fromtimestamp(remind_at, tz=time_utils.TZ)
            lines.append(f"`#{rid}` {dt.strftime('%H:%M %d/%m')} — {content}")
        await discord_utils.send_long(ctx.channel.send, "\n".join(lines), first_reply=lambda t: ctx.reply(t))

    @commands.hybrid_command(name="huynhac", help="Huỷ 1 việc đang chờ nhắc, vd: !huynhac 3")
    async def cancel_reminder(self, ctx: commands.Context, reminder_id: int):
        ok = db.delete_reminder(str(ctx.author.id), reminder_id)
        if ok:
            await ctx.reply(f"Đã huỷ nhắc việc `#{reminder_id}` rồi nha 🗑️")
        else:
            await ctx.reply("Không tìm thấy việc này, kiểm tra lại `!xemnhac` xem số đúng chưa nha.")

    @commands.hybrid_command(name="nhachangngay", help="Nhắc lặp lại mỗi ngày, vd: !nhachangngay 22:00 uống thuốc")
    async def add_daily_reminder(self, ctx: commands.Context, time_str: str, *, content: str):
        if not re.fullmatch(r"\d{1,2}:\d{2}", time_str):
            await ctx.reply("Giờ phải theo dạng `HH:MM`, vd: `!nhachangngay 22:00 uống thuốc` nha.")
            return
        hh, mm = time_str.split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            await ctx.reply("Giờ không hợp lệ, kiểm tra lại nha (00:00 - 23:59).")
            return
        rid = db.add_daily_reminder(str(ctx.author.id), str(ctx.channel.id), f"{int(hh):02d}:{int(mm):02d}", content)
        await ctx.reply(f"Su sẽ nhắc mỗi ngày lúc **{int(hh):02d}:{int(mm):02d}**: {content} (id `#{rid}`) 🔁")

    @commands.hybrid_command(name="xemnhachangngay", help="Xem danh sách nhắc việc lặp lại mỗi ngày")
    async def list_daily_reminders(self, ctx: commands.Context):
        rows = db.get_daily_reminders_for(str(ctx.author.id))
        if not rows:
            await ctx.reply("Chưa có nhắc việc lặp lại nào cả 📭")
            return
        lines = [f"`#{rid}` {t} — {content}" for rid, t, content in rows]
        await discord_utils.send_long(ctx.channel.send, "\n".join(lines), first_reply=lambda t: ctx.reply(t))

    @commands.hybrid_command(name="xoanhachangngay", help="Xoá 1 nhắc việc lặp lại, vd: !xoanhachangngay 2")
    async def remove_daily_reminder(self, ctx: commands.Context, reminder_id: int):
        ok = db.delete_daily_reminder(str(ctx.author.id), reminder_id)
        if ok:
            await ctx.reply(f"Đã xoá nhắc việc lặp lại `#{reminder_id}` 🗑️")
        else:
            await ctx.reply("Không tìm thấy, kiểm tra lại `!xemnhachangngay` nha.")

    @commands.hybrid_command(name="countdown", help="Đếm ngược tới 1 ngày, vd: !countdown 2026-12-24 Giáng sinh")
    async def countdown(self, ctx: commands.Context, date_str: str, *, label: str):
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            await ctx.reply("Định dạng phải là `YYYY-MM-DD`, vd: `!countdown 2026-12-24 Giáng sinh`")
            return
        days = (target - datetime.now().date()).days
        if days > 0:
            await ctx.reply(f"Còn **{days} ngày** nữa tới {label} 📅")
        elif days == 0:
            await ctx.reply(f"Hôm nay chính là {label} đó! 🎉")
        else:
            await ctx.reply(f"{label} đã qua **{-days} ngày** rồi 🙃")

    @commands.hybrid_command(name="top", aliases=["bxh"], help="Xem bảng xếp hạng điểm thân mật với Su trong server")
    async def leaderboard(self, ctx: commands.Context):
        rows = db.get_affection_leaderboard(10)
        if not rows:
            await ctx.reply("Chưa có ai tương tác với Su cả 😶")
            return
        lines = []
        for i, (discord_id, points) in enumerate(rows, 1):
            member = ctx.guild.get_member(int(discord_id)) if ctx.guild else None
            name = member.display_name if member else f"<@{discord_id}>"
            lines.append(f"{i}. {name} — {points} điểm")
        await ctx.reply("**Bảng xếp hạng thân mật với Su:**\n" + "\n".join(lines))

    # ---------------- To-do list ----------------

    @commands.hybrid_command(name="themviec", help="Thêm việc cần làm, vd: !themviec sửa bug !checktime")
    async def add_todo(self, ctx: commands.Context, *, content: str):
        todo_id = db.add_todo(str(ctx.author.id), content)
        await ctx.reply(f"Đã thêm việc `#{todo_id}`: {content} ✅")

    @commands.hybrid_command(name="xemviec", help="Xem danh sách việc cần làm")
    async def list_todos(self, ctx: commands.Context):
        rows = db.get_todos(str(ctx.author.id))
        if not rows:
            await ctx.reply("Danh sách việc đang trống trơn, xịn quá anh ơi 🎉")
            return
        lines = []
        for tid, content, done in rows:
            box = "✅" if done else "⬜"
            lines.append(f"{box} `#{tid}` {content}")
        await discord_utils.send_long(ctx.channel.send, "\n".join(lines), first_reply=lambda t: ctx.reply(t))

    @commands.hybrid_command(name="xongviec", help="Đánh dấu đã hoàn thành, vd: !xongviec 2")
    async def complete_todo(self, ctx: commands.Context, todo_id: int):
        ok = db.complete_todo(str(ctx.author.id), todo_id)
        if ok:
            db.add_affection(str(ctx.author.id), 1)
            await ctx.reply(f"Xong việc `#{todo_id}` rồi, giỏi quá anh ơi 🥳")
        else:
            await ctx.reply("Không tìm thấy việc này, kiểm tra lại `!xemviec` nha.")

    @commands.hybrid_command(name="xoaviec", help="Xoá 1 việc khỏi danh sách, vd: !xoaviec 2")
    async def delete_todo(self, ctx: commands.Context, todo_id: int):
        ok = db.delete_todo(str(ctx.author.id), todo_id)
        if ok:
            await ctx.reply(f"Đã xoá việc `#{todo_id}` 🗑️")
        else:
            await ctx.reply("Không tìm thấy việc này, kiểm tra lại `!xemviec` nha.")

    # ---------------- Chọn hộ ----------------

    @commands.hybrid_command(name="chon", help="Su chọn hộ khi phân vân, vd: !chon Cơm gà, Bún bò, Phở")
    async def choose_for_me(self, ctx: commands.Context, *, options: str):
        items = [o.strip() for o in options.split(",") if o.strip()]
        if len(items) < 2:
            await ctx.reply("Anh cho Su ít nhất 2 lựa chọn, cách nhau bằng dấu phẩy nha, vd: `!chon A, B, C`")
            return
        pick = random.choice(items)
        await ctx.reply(f"Su chọn: **{pick}** 💅 (trong số: {', '.join(items)})")

    # ---------------- Cấp độ tình yêu ----------------

    @commands.hybrid_command(name="level", help="Xem cấp độ tình yêu hiện tại với Su")
    async def love_level(self, ctx: commands.Context):
        points = db.get_affection(str(ctx.author.id))
        current_label = LOVE_LEVELS[0][1]
        next_threshold = None
        next_label = None
        for i, (threshold, label) in enumerate(LOVE_LEVELS):
            if points >= threshold:
                current_label = label
                if i + 1 < len(LOVE_LEVELS):
                    next_threshold, next_label = LOVE_LEVELS[i + 1]
                else:
                    next_threshold, next_label = None, None

        msg = f"Cấp độ hiện tại: **{current_label}** ({points} điểm thân mật)"
        if next_threshold is not None:
            msg += f"\nCòn **{next_threshold - points} điểm** nữa để lên **{next_label}** 💪"
        else:
            msg += "\nĐã đạt cấp độ cao nhất rồi đó 🥹💍"
        await ctx.reply(msg)

    # ---------------- Bói vui ----------------

    @commands.hybrid_command(name="boivui", help="Xem vận may hôm nay do Su bói cho vui")
    async def fortune(self, ctx: commands.Context):
        await ctx.reply(f"🔮 {random.choice(FORTUNES)}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Personal(bot))
