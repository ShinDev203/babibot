"""
cogs/music.py
Phát nhạc trong voice channel Discord bằng yt-dlp + ffmpeg.
Có queue riêng cho từng server (guild).
"""

import asyncio
import os
import tempfile
import uuid
import discord
from discord.ext import commands
import yt_dlp
from gtts import gTTS

import database as db

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
    "executable": FFMPEG_PATH,
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)


def friendly_voice_error(e: Exception) -> str:
    text = str(e)
    if "davey" in text.lower():
        return (
            "thiếu thư viện `davey` (Discord bắt buộc DAVE/E2EE cho voice từ 1/3/2026 rồi). "
            "Thêm `davey` vào requirements.txt, rebuild lại image là hết lỗi nha."
        )
    if "opus" in text.lower():
        return "thiếu thư viện `libopus` (cài `libopus0` qua apt trong Dockerfile)."
    if "pynacl" in text.lower() or "nacl" in text.lower():
        return "thiếu thư viện `PyNaCl` (thêm `PyNaCl` vào requirements.txt)."
    return f"`{type(e).__name__}: {e}`"


class Song:
    def __init__(self, title, url, stream_url, requester):
        self.title = title
        self.url = url
        self.stream_url = stream_url
        self.requester = requester


class GuildMusicState:
    def __init__(self):
        self.queue: list[Song] = []
        self.voice_client: discord.VoiceClient | None = None
        self.current: Song | None = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    async def _extract(self, query: str) -> Song | None:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if data is None:
            return None
        if "entries" in data:
            data = data["entries"][0]
        return Song(title=data.get("title", "Unknown"), url=data.get("webpage_url", query),
                     stream_url=data["url"], requester=None)

    async def _play_next(self, guild: discord.Guild):
        state = self.get_state(guild.id)
        if not state.queue:
            state.current = None
            return
        song = state.queue.pop(0)
        state.current = song
        try:
            source = discord.FFmpegPCMAudio(song.stream_url, **FFMPEG_OPTS)
        except Exception as e:
            print(f"[music] Không tạo được audio source (thiếu ffmpeg?): {e}")
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send(
                        f"Su không phát được nhạc vì thiếu `ffmpeg` trên server 😢 "
                        f"(lỗi: `{type(e).__name__}: {e}`). Kiểm tra lại Dockerfile đã cài ffmpeg chưa."
                    )
                    break
            state.current = None
            return

        def _after(err):
            if err:
                print(f"[music] Lỗi khi phát: {err}")
            fut = self._play_next(guild)
            asyncio.run_coroutine_threadsafe(fut, self.bot.loop)

        state.voice_client.play(source, after=_after)

    @commands.hybrid_command(name="join")
    async def join(self, ctx: commands.Context):
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.reply("Anh phải vào 1 voice channel trước đã chứ 🥺")
            return
        channel = ctx.author.voice.channel
        state = self.get_state(ctx.guild.id)
        try:
            if state.voice_client is None or not state.voice_client.is_connected():
                state.voice_client = await channel.connect(timeout=20, reconnect=True)
            else:
                await state.voice_client.move_to(channel)
        except discord.ClientException as e:
            await ctx.reply(f"Su bị lỗi khi vào voice: `{e}` (có thể Su đã ở voice khác rồi)")
            return
        except asyncio.TimeoutError:
            await ctx.reply(
                "Su connect voice bị timeout 😢 thường là do host (Render) chặn UDP hoặc mạng chập chờn. "
                "Kiểm tra lại xem server Render có cho outbound UDP không nha."
            )
            return
        except Exception as e:
            await ctx.reply(f"Su không vào voice được, lỗi: {friendly_voice_error(e)}")
            return
        await ctx.reply(f"Su vào **{channel.name}** với anh nè 🎶")

    @commands.hybrid_command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str):
        if ctx.author.voice is None:
            await ctx.reply("Anh vào voice channel đi rồi Su phát nhạc cho 🎧")
            return

        state = self.get_state(ctx.guild.id)
        try:
            if state.voice_client is None or not state.voice_client.is_connected():
                state.voice_client = await ctx.author.voice.channel.connect(timeout=20, reconnect=True)
        except discord.ClientException as e:
            await ctx.reply(f"Su bị lỗi khi vào voice: `{e}`")
            return
        except asyncio.TimeoutError:
            await ctx.reply(
                "Su connect voice bị timeout 😢 kiểm tra lại xem host (Render/Docker) có chặn outbound "
                "UDP không, đây là nguyên nhân phổ biến nhất khiến bot không vào được voice."
            )
            return
        except Exception as e:
            await ctx.reply(f"Su không vào voice được, lỗi: {friendly_voice_error(e)}")
            return

        async with ctx.typing():
            search = query if query.startswith("http") else f"ytsearch:{query}"
            try:
                song = await self._extract(search)
            except Exception as e:
                await ctx.reply(f"Su tìm nhạc bị lỗi rồi 😢 (`{type(e).__name__}: {e}`)")
                return

        if song is None:
            await ctx.reply("Su tìm không ra bài này 😢 thử lại tên khác xem.")
            return

        song.requester = ctx.author.display_name
        state.queue.append(song)
        await ctx.reply(f"Đã thêm vào hàng chờ: **{song.title}** 🎵")

        if not state.voice_client.is_playing() and state.current is None:
            await self._play_next(ctx.guild)

    async def speak_text(self, guild: discord.Guild, text: str) -> str | None:
        """Đọc to `text` bằng giọng nói trong voice channel hiện tại của guild.
        Trả về None nếu thành công, hoặc chuỗi lỗi nếu thất bại (để nơi gọi tự xử lý im lặng nếu cần)."""
        state = self.get_state(guild.id)
        if state.voice_client is None or not state.voice_client.is_connected():
            return "Su chưa ở trong voice channel nào cả."
        if state.voice_client.is_playing():
            return "Su đang phát nhạc/nói rồi."

        loop = asyncio.get_event_loop()
        tmp_path = os.path.join(tempfile.gettempdir(), f"su_tts_{uuid.uuid4().hex}.mp3")
        try:
            await loop.run_in_executor(None, lambda: gTTS(text=text, lang="vi").save(tmp_path))
            source = discord.FFmpegPCMAudio(tmp_path, executable=FFMPEG_PATH)
        except Exception as e:
            return f"{type(e).__name__}: {e}"

        def _after(err):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            if err:
                print(f"[music] Lỗi khi đọc TTS: {err}")

        state.voice_client.play(source, after=_after)
        return None

    @commands.hybrid_command(name="noi", help="Su đọc to nội dung này trong voice channel, vd: !noi anh giỏi lắm")
    async def speak(self, ctx: commands.Context, *, text: str):
        if ctx.author.voice is None:
            await ctx.reply("Anh vào voice channel trước đi rồi Su nói cho nghe 🎤")
            return

        state = self.get_state(ctx.guild.id)
        try:
            if state.voice_client is None or not state.voice_client.is_connected():
                state.voice_client = await ctx.author.voice.channel.connect(timeout=20, reconnect=True)
        except Exception as e:
            await ctx.reply(f"Su không vào voice được: {friendly_voice_error(e)}")
            return

        error = await self.speak_text(ctx.guild, text)
        if error:
            await ctx.reply(f"Su không nói được 😢 ({error})")
        else:
            await ctx.reply("Su đang nói nè 🎤")

    @commands.hybrid_command(name="su_noi_on", help="Bật chế độ Su tự đọc to câu trả lời chat trong voice hiện tại")
    async def voice_reply_on(self, ctx: commands.Context):
        db.set_setting(str(ctx.author.id), "voice_reply_enabled", "1")
        await ctx.reply("Từ giờ Su sẽ đọc to câu trả lời trong voice (nếu Su đang ở trong voice) nha 🎤")

    @commands.hybrid_command(name="su_noi_off", help="Tắt chế độ Su tự đọc to câu trả lời chat")
    async def voice_reply_off(self, ctx: commands.Context):
        db.set_setting(str(ctx.author.id), "voice_reply_enabled", "0")
        await ctx.reply("Ok Su thôi đọc to nữa, chỉ nhắn chữ thôi nha 📝")

    @commands.hybrid_command(name="skip")
    async def skip(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.stop()
            await ctx.reply("Skip bài này luôn nha ⏭️")
        else:
            await ctx.reply("Có bài nào đang phát đâu mà skip 😅")

    @commands.hybrid_command(name="pause")
    async def pause(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            await ctx.reply("Tạm dừng nha, gọi `!resume` khi nào nghe tiếp ⏸️")

    @commands.hybrid_command(name="resume")
    async def resume(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            await ctx.reply("Phát tiếp nè ▶️")

    @commands.hybrid_command(name="stop")
    async def stop(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        if state.voice_client:
            state.voice_client.stop()
        await ctx.reply("Dừng nhạc và xoá hàng chờ rồi đó 🛑")

    @commands.hybrid_command(name="leave", aliases=["dc"])
    async def leave(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client:
            await state.voice_client.disconnect()
            state.voice_client = None
            state.queue.clear()
            state.current = None
        await ctx.reply("Su ra khỏi voice rồi nè, nhớ Su thì gọi lại nhé 👋")

    @commands.hybrid_command(name="queue", aliases=["q"])
    async def queue_cmd(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not state.queue and not state.current:
            await ctx.reply("Hàng chờ trống trơn nè 📭")
            return
        lines = []
        if state.current:
            lines.append(f"▶️ Đang phát: **{state.current.title}**")
        for i, s in enumerate(state.queue, 1):
            lines.append(f"{i}. {s.title} (yêu cầu bởi {s.requester})")
        await ctx.reply("\n".join(lines))

    @commands.hybrid_command(name="nowplaying", aliases=["np"])
    async def now_playing(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.current:
            await ctx.reply(f"Đang phát: **{state.current.title}** 🎶")
        else:
            await ctx.reply("Chưa có bài nào đang phát cả 😴")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
