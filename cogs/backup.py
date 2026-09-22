"""
cogs/backup.py
Render Web Service có ổ đĩa "ephemeral" - dữ liệu SQLite (babyboo.db) CÓ THỂ bị mất khi redeploy
nếu không dùng Persistent Disk (trả phí). Đây là giải pháp free: backup/restore thủ công.

Cách dùng định kỳ (khuyên dùng hàng tuần hoặc trước khi deploy code mới):
1. Gõ !backup -> Su gửi file .db, tải về lưu ở máy/Google Drive.
2. Khi cần khôi phục (vd sau khi Render xoá sạch dữ liệu): đính kèm file đó và gõ !restore <file> XACNHAN
"""

import os
import sqlite3
import tempfile
import time

import discord
from discord.ext import commands

import database as db

OWNER_ID = int(os.getenv("OWNER_ID", "1023838827556655186"))


def _is_shin(ctx: commands.Context) -> bool:
    return ctx.author.id == OWNER_ID


class Backup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="backup", help="Xuất file backup toàn bộ dữ liệu của Su (chỉ Shin dùng được)"
    )
    async def backup_cmd(self, ctx: commands.Context):
        if not _is_shin(ctx):
            await ctx.reply("Lệnh này chỉ Shin dùng được thôi 😅")
            return

        tmp_path = os.path.join(tempfile.gettempdir(), f"babyboo_backup_{int(time.time())}.db")
        try:
            backup_conn = sqlite3.connect(tmp_path)
            with db.get_lock():
                db.get_connection().backup(backup_conn)
            backup_conn.close()
        except Exception as e:
            await ctx.reply(f"Su backup bị lỗi rồi 😢 (`{type(e).__name__}: {e}`)")
            return

        try:
            await ctx.reply(
                "Đây là file backup toàn bộ dữ liệu (trí nhớ, nhật ký, mood, todo, nhắc việc...). "
                "Anh lưu lại cẩn thận nha, định kỳ backup 1 lần để phòng Render redeploy mất dữ liệu 💾",
                file=discord.File(tmp_path, filename="babyboo_backup.db"),
            )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    @commands.hybrid_command(
        name="restore",
        help="Khôi phục dữ liệu từ file backup .db (chỉ Shin, XOÁ SẠCH dữ liệu hiện tại)",
    )
    async def restore_cmd(self, ctx: commands.Context, file: discord.Attachment, confirm: str = ""):
        if not _is_shin(ctx):
            await ctx.reply("Lệnh này chỉ Shin dùng được thôi 😅")
            return

        if confirm.strip().upper() != "XACNHAN":
            await ctx.reply(
                "⚠️ Restore sẽ **XOÁ SẠCH** dữ liệu hiện tại và thay bằng file backup này, không hoàn tác "
                "được. Nếu chắc chắn, gõ lại lệnh kèm `XACNHAN` ở cuối, vd:\n"
                "`!restore XACNHAN` (đính kèm file .db)"
            )
            return

        if not file.filename.endswith(".db"):
            await ctx.reply("File đính kèm phải là file `.db` (đúng file Su xuất ra từ `!backup`).")
            return

        tmp_path = os.path.join(tempfile.gettempdir(), f"babyboo_restore_{int(time.time())}.db")
        try:
            await file.save(tmp_path)
            source_conn = sqlite3.connect(tmp_path)
            with db.get_lock():
                source_conn.backup(db.get_connection())
            source_conn.close()
        except Exception as e:
            await ctx.reply(f"Restore bị lỗi rồi, dữ liệu cũ vẫn còn nguyên 😌 (`{type(e).__name__}: {e}`)")
            return
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        await ctx.reply("Đã khôi phục dữ liệu từ file backup rồi nha 🔄")


async def setup(bot: commands.Bot):
    await bot.add_cog(Backup(bot))
