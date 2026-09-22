"""
bot.py
Entry point cho bot Discord BabyBoo (Su) của Shin.

Deploy trên Render:
1. Push code này lên GitHub.
2. Tạo Web Service mới trên Render, trỏ vào repo.
3. Build command:  pip install -r requirements.txt
   Start command:  python bot.py
4. Thêm biến môi trường (Environment) theo file .env.example.
5. Sau khi deploy xong, lấy URL public (vd: https://babyboo-bot.onrender.com)
   rồi tạo monitor trên https://uptimerobot.com ping URL đó (hoặc /health) mỗi 5 phút
   để Render không cho service ngủ -> bot online 24/7.
"""

import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

import database as db
from keep_alive import keep_alive

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")
OWNER_ID = int(os.getenv("OWNER_ID", "1023838827556655186"))
GUILD_ID = os.getenv("GUILD_ID")  # optional: nếu có, sync slash command nhanh cho riêng server này

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True  # cần để phát hiện Shin đang chơi game gì

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f"[BabyBoo] Đã đăng nhập với tên {bot.user} (ID: {bot.user.id})")

    if not discord.opus.is_loaded():
        for candidate in ("libopus.so.0", "libopus.so", "opus", "libopus-0.dll"):
            try:
                discord.opus.load_opus(candidate)
                print(f"[BabyBoo] Đã load opus bằng '{candidate}'")
                break
            except OSError:
                continue
        if not discord.opus.is_loaded():
            print(
                "[BabyBoo] CẢNH BÁO: không load được thư viện opus -> voice/nhạc sẽ không có tiếng. "
                "Kiểm tra lại đã cài libopus0 (apt-get install libopus0) chưa."
            )

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Shin code LSPD 💻💕")
    )

    # Đồng bộ slash command (/play, /mood...). Sync global mất tới 1h để lan ra hết,
    # nếu có GUILD_ID thì sync riêng cho server đó để thấy ngay lập tức.
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"[BabyBoo] Đã sync {len(synced)} slash command cho guild {GUILD_ID} (tức thì)")
        else:
            synced = await bot.tree.sync()
            print(f"[BabyBoo] Đã sync {len(synced)} slash command (global, có thể mất tới 1h để hiện hết)")
    except Exception as e:
        print(f"[BabyBoo] Lỗi khi sync slash command: {e}")


@bot.hybrid_command(name="help", description="Xem danh sách tất cả lệnh của Su")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="BabyBoo (Su) 💕",
        description=(
            "Bạn gái AI nhỏ của Shin, đây là những gì Su biết làm. "
            f"Mọi lệnh dùng được cả 2 kiểu: gõ `{COMMAND_PREFIX}lệnh` hoặc gõ `/lệnh` (slash command)."
        ),
        color=discord.Color.pink(),
    )
    embed.add_field(
        name="💬 Trò chuyện",
        value="Mention Su hoặc nhắn tin riêng (DM) để chat bất cứ lúc nào.",
        inline=False,
    )
    embed.add_field(
        name="🧠 Trí nhớ",
        value=(
            f"`{COMMAND_PREFIX}nhomgiup <điều cần nhớ>` - bảo Su ghi nhớ\n"
            f"`{COMMAND_PREFIX}trinho` - xem Su đang nhớ gì\n"
            f"`{COMMAND_PREFIX}quenanh` - xoá hết trí nhớ hội thoại"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎵 Nhạc & Giọng nói",
        value=(
            f"`{COMMAND_PREFIX}play <tên bài/link>` - phát nhạc\n"
            f"`{COMMAND_PREFIX}skip` `{COMMAND_PREFIX}pause` `{COMMAND_PREFIX}resume` `{COMMAND_PREFIX}stop`\n"
            f"`{COMMAND_PREFIX}queue` - xem hàng chờ\n"
            f"`{COMMAND_PREFIX}leave` - Su rời voice\n"
            f"`{COMMAND_PREFIX}noi <câu>` - Su đọc to bằng giọng nói trong voice"
        ),
        inline=False,
    )
    embed.add_field(
        name="💗 Khác",
        value=f"`{COMMAND_PREFIX}yeu` - xem điểm thân mật\n`{COMMAND_PREFIX}gioithieu` - Su tự giới thiệu",
        inline=False,
    )
    embed.add_field(
        name="🌞 Chủ động nhắn tin",
        value=(
            "Su tự chào buổi sáng (kèm thời tiết), chúc ngủ ngon, nhắc uống nước, hỏi tâm trạng, "
            "nhắn khi nhớ anh và nhắc ngày đặc biệt.\n"
            f"`{COMMAND_PREFIX}babyboo_tat` / `{COMMAND_PREFIX}babyboo_bat` - tắt/bật tính năng này\n"
            f"`{COMMAND_PREFIX}luungay MM-DD <tên>` - lưu ngày đặc biệt\n"
            f"`{COMMAND_PREFIX}ngaydacbiet` - xem các ngày đã lưu\n"
            f"`{COMMAND_PREFIX}ngayyeunhau YYYY-MM-DD` - lưu ngày yêu nhau\n"
            f"`{COMMAND_PREFIX}yeunhaubaolau` - xem đã yêu nhau bao lâu\n"
            f"`{COMMAND_PREFIX}streak` - xem streak trò chuyện"
        ),
        inline=False,
    )
    embed.add_field(
        name="📝 Tâm trạng & Nhật ký",
        value=(
            f"`{COMMAND_PREFIX}mood <cảm xúc>` - ghi tâm trạng hôm nay\n"
            f"`{COMMAND_PREFIX}xemmood` - xem lại tâm trạng gần đây\n"
            f"`{COMMAND_PREFIX}nhatky <nội dung>` - viết nhật ký, Su sẽ đọc và phản hồi\n"
            f"`{COMMAND_PREFIX}xemnhatky` - xem lại nhật ký gần đây"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎮 Mini-game",
        value=f"`{COMMAND_PREFIX}oan <bua/keo/bao>` - chơi oẳn tù tì với Su",
        inline=False,
    )
    embed.add_field(
        name="⏰ Nhắc việc & To-do",
        value=(
            f"`{COMMAND_PREFIX}nhac <10m/2h/1d/HH:MM> <nội dung>` - nhắc việc 1 lần\n"
            f"`{COMMAND_PREFIX}xemnhac` `{COMMAND_PREFIX}huynhac <số>`\n"
            f"`{COMMAND_PREFIX}nhachangngay HH:MM <nội dung>` - nhắc lặp lại mỗi ngày\n"
            f"`{COMMAND_PREFIX}xemnhachangngay` `{COMMAND_PREFIX}xoanhachangngay <số>`\n"
            f"`{COMMAND_PREFIX}countdown YYYY-MM-DD <tên>` - đếm ngược tới 1 ngày\n"
            f"`{COMMAND_PREFIX}themviec` `{COMMAND_PREFIX}xemviec` `{COMMAND_PREFIX}xongviec <số>` `{COMMAND_PREFIX}xoaviec <số>`"
        ),
        inline=False,
    )
    embed.add_field(
        name="✨ Khác",
        value=(
            f"`{COMMAND_PREFIX}chon A, B, C` - Su chọn hộ khi phân vân\n"
            f"`{COMMAND_PREFIX}level` - xem cấp độ tình yêu\n"
            f"`{COMMAND_PREFIX}boivui` - xem vận may hôm nay\n"
            f"`{COMMAND_PREFIX}top` - bảng xếp hạng thân mật cả server"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎮 Mini-game",
        value=(
            f"`{COMMAND_PREFIX}oan <bua/keo/bao>` - oẳn tù tì\n"
            f"`{COMMAND_PREFIX}thatthach that/thach` - thật hay thách\n"
            f"`{COMMAND_PREFIX}doanso` rồi `{COMMAND_PREFIX}doan <số>` - đoán số 1-100"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎙️ Giọng nói",
        value=(
            f"Gửi voice message (mention Su hoặc DM) - Su nghe hiểu và trả lời bằng chữ\n"
            f"`{COMMAND_PREFIX}su_noi_on` / `{COMMAND_PREFIX}su_noi_off` - Su tự đọc to câu trả lời trong voice"
        ),
        inline=False,
    )
    embed.add_field(
        name="👥 Trò chuyện nhóm",
        value=(
            "Nếu thấy 2-3 người đang nhắc/mention nhau rôm rả, Su có thể tự chen vào 1 câu cho vui "
            "(không cần mention Su).\n"
            f"`{COMMAND_PREFIX}su_chenvao_on` / `{COMMAND_PREFIX}su_chenvao_off` - bật/tắt (cần quyền quản lý server)"
        ),
        inline=False,
    )
    embed.add_field(
        name="💾 Backup dữ liệu",
        value=(
            f"`{COMMAND_PREFIX}backup` - Su gửi file backup toàn bộ dữ liệu (chỉ Shin)\n"
            f"`{COMMAND_PREFIX}restore XACNHAN` (đính kèm file .db) - khôi phục dữ liệu (chỉ Shin)\n"
            "⚠️ Nên backup định kỳ vì Render có thể xoá dữ liệu khi redeploy"
        ),
        inline=False,
    )
    await ctx.reply(embed=embed)


async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("Chưa cấu hình DISCORD_TOKEN trong biến môi trường.")

    db.init_db()
    keep_alive()

    async with bot:
        await bot.load_extension("cogs.chat")
        await bot.load_extension("cogs.music")
        await bot.load_extension("cogs.proactive")
        await bot.load_extension("cogs.extras")
        await bot.load_extension("cogs.personal")
        await bot.load_extension("cogs.backup")
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
