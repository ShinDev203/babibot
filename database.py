"""
database.py
Quản lý toàn bộ dữ liệu SQLite cho BabyBoo (Su):
- messages: lịch sử chat để làm bộ nhớ ngắn hạn (context cho AI)
- facts: những điều quan trọng cần nhớ lâu dài (vd: "Shin thích rank Immortal")
- affection: điểm thân mật / mood đơn giản theo từng người dùng
- last_game: game gần nhất phát hiện qua Rich Presence, để tránh chào lặp lại
"""

import sqlite3
import time
import threading

DB_PATH = "babyboo.db"

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


_conn = _connect()


def get_connection():
    """Trả về connection sqlite đang dùng, cho module backup.py dùng để backup/restore."""
    return _conn


def get_db_path() -> str:
    return DB_PATH


def get_lock():
    return _lock


def init_db():
    with _lock:
        cur = _conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                role TEXT NOT NULL,          -- 'user' hoặc 'assistant'
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                fact TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS affection (
                discord_id TEXT PRIMARY KEY,
                points INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS presence_state (
                discord_id TEXT PRIMARY KEY,
                last_game TEXT,
                last_greet_at REAL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                discord_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (discord_id, key)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS important_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                label TEXT NOT NULL,
                month_day TEXT NOT NULL,   -- format 'MM-DD'
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS streak (
                discord_id TEXT PRIMARY KEY,
                current_streak INTEGER NOT NULL DEFAULT 0,
                last_chat_date TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mood_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                mood_date TEXT NOT NULL,
                mood_text TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS diary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                content TEXT NOT NULL,
                remind_at REAL NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                content TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                time_str TEXT NOT NULL,   -- format 'HH:MM'
                content TEXT NOT NULL,
                last_sent_date TEXT,
                created_at REAL NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guess_game (
                discord_id TEXT PRIMARY KEY,
                secret_number INTEGER NOT NULL,
                low INTEGER NOT NULL,
                high INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0
            )
        """)
        _conn.commit()


# ---------- MESSAGES (bộ nhớ hội thoại) ----------

MAX_MESSAGES_PER_USER = 300


def add_message(discord_id: str, channel_id: str, role: str, content: str):
    with _lock:
        _conn.execute(
            "INSERT INTO messages (discord_id, channel_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(discord_id), str(channel_id), role, content, time.time()),
        )
        # Dọn bớt lịch sử cũ, chỉ giữ tối đa MAX_MESSAGES_PER_USER tin/người để DB không phình vô hạn
        _conn.execute(
            """DELETE FROM messages WHERE discord_id = ? AND id NOT IN (
                   SELECT id FROM messages WHERE discord_id = ? ORDER BY id DESC LIMIT ?
               )""",
            (str(discord_id), str(discord_id), MAX_MESSAGES_PER_USER),
        )
        _conn.commit()


def get_recent_messages(discord_id: str, limit: int = 12):
    """Lấy `limit` tin nhắn gần nhất của 1 người dùng, trả về theo thứ tự thời gian tăng dần."""
    with _lock:
        cur = _conn.execute(
            "SELECT role, content FROM messages WHERE discord_id = ? ORDER BY id DESC LIMIT ?",
            (str(discord_id), limit),
        )
        rows = cur.fetchall()
    rows.reverse()
    return [{"role": r, "content": c} for r, c in rows]


def clear_messages(discord_id: str):
    with _lock:
        _conn.execute("DELETE FROM messages WHERE discord_id = ?", (str(discord_id),))
        _conn.commit()


# ---------- FACTS (trí nhớ dài hạn) ----------

def add_fact(discord_id: str, fact: str):
    with _lock:
        _conn.execute(
            "INSERT INTO facts (discord_id, fact, created_at) VALUES (?, ?, ?)",
            (str(discord_id), fact, time.time()),
        )
        _conn.commit()


def get_facts(discord_id: str, limit: int = 20):
    with _lock:
        cur = _conn.execute(
            "SELECT fact FROM facts WHERE discord_id = ? ORDER BY id DESC LIMIT ?",
            (str(discord_id), limit),
        )
        return [row[0] for row in cur.fetchall()]


def clear_facts(discord_id: str):
    with _lock:
        _conn.execute("DELETE FROM facts WHERE discord_id = ?", (str(discord_id),))
        _conn.commit()


# ---------- AFFECTION (điểm thân mật) ----------

def add_affection(discord_id: str, amount: int = 1):
    with _lock:
        _conn.execute(
            """INSERT INTO affection (discord_id, points) VALUES (?, ?)
               ON CONFLICT(discord_id) DO UPDATE SET points = points + excluded.points""",
            (str(discord_id), amount),
        )
        _conn.commit()


def get_affection(discord_id: str) -> int:
    with _lock:
        cur = _conn.execute("SELECT points FROM affection WHERE discord_id = ?", (str(discord_id),))
        row = cur.fetchone()
        return row[0] if row else 0


# ---------- PRESENCE (chào theo game đang chơi) ----------

def get_last_game(discord_id: str):
    with _lock:
        cur = _conn.execute("SELECT last_game, last_greet_at FROM presence_state WHERE discord_id = ?", (str(discord_id),))
        return cur.fetchone()


def set_last_game(discord_id: str, game: str):
    with _lock:
        _conn.execute(
            """INSERT INTO presence_state (discord_id, last_game, last_greet_at) VALUES (?, ?, ?)
               ON CONFLICT(discord_id) DO UPDATE SET last_game = excluded.last_game, last_greet_at = excluded.last_greet_at""",
            (str(discord_id), game, time.time()),
        )
        _conn.commit()


# ---------- SETTINGS (cờ trạng thái / bật-tắt tính năng) ----------

def get_setting(discord_id: str, key: str, default=None):
    with _lock:
        cur = _conn.execute(
            "SELECT value FROM settings WHERE discord_id = ? AND key = ?", (str(discord_id), key)
        )
        row = cur.fetchone()
        return row[0] if row else default


def set_setting(discord_id: str, key: str, value: str):
    with _lock:
        _conn.execute(
            """INSERT INTO settings (discord_id, key, value) VALUES (?, ?, ?)
               ON CONFLICT(discord_id, key) DO UPDATE SET value = excluded.value""",
            (str(discord_id), key, str(value)),
        )
        _conn.commit()


# ---------- IMPORTANT DATES (sinh nhật, kỷ niệm...) ----------

def add_important_date(discord_id: str, label: str, month_day: str):
    with _lock:
        _conn.execute(
            "INSERT INTO important_dates (discord_id, label, month_day, created_at) VALUES (?, ?, ?, ?)",
            (str(discord_id), label, month_day, time.time()),
        )
        _conn.commit()


def get_important_dates(discord_id: str):
    with _lock:
        cur = _conn.execute(
            "SELECT label, month_day FROM important_dates WHERE discord_id = ? ORDER BY id",
            (str(discord_id),),
        )
        return cur.fetchall()


def get_dates_matching_today(discord_id: str, month_day_today: str):
    with _lock:
        cur = _conn.execute(
            "SELECT label FROM important_dates WHERE discord_id = ? AND month_day = ?",
            (str(discord_id), month_day_today),
        )
        return [row[0] for row in cur.fetchall()]


# ---------- STREAK (số ngày liên tiếp trò chuyện) ----------

def bump_streak(discord_id: str, today_str: str, yesterday_str: str) -> int:
    """Cập nhật streak khi có tin nhắn hôm nay, trả về streak hiện tại."""
    with _lock:
        cur = _conn.execute(
            "SELECT current_streak, last_chat_date FROM streak WHERE discord_id = ?", (str(discord_id),)
        )
        row = cur.fetchone()
        if row is None:
            new_streak = 1
        else:
            current_streak, last_chat_date = row
            if last_chat_date == today_str:
                return current_streak  # đã tính hôm nay rồi
            elif last_chat_date == yesterday_str:
                new_streak = current_streak + 1
            else:
                new_streak = 1
        _conn.execute(
            """INSERT INTO streak (discord_id, current_streak, last_chat_date) VALUES (?, ?, ?)
               ON CONFLICT(discord_id) DO UPDATE SET current_streak = excluded.current_streak, last_chat_date = excluded.last_chat_date""",
            (str(discord_id), new_streak, today_str),
        )
        _conn.commit()
        return new_streak


def get_streak(discord_id: str) -> int:
    with _lock:
        cur = _conn.execute("SELECT current_streak FROM streak WHERE discord_id = ?", (str(discord_id),))
        row = cur.fetchone()
        return row[0] if row else 0


# ---------- Thời điểm tin nhắn cuối cùng (để phát hiện im lặng lâu) ----------

def get_last_message_time(discord_id: str):
    with _lock:
        cur = _conn.execute(
            "SELECT created_at FROM messages WHERE discord_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (str(discord_id),),
        )
        row = cur.fetchone()
        return row[0] if row else None


# ---------- MOOD LOG ----------

def add_mood(discord_id: str, mood_date: str, mood_text: str):
    with _lock:
        _conn.execute(
            "INSERT INTO mood_log (discord_id, mood_date, mood_text, created_at) VALUES (?, ?, ?, ?)",
            (str(discord_id), mood_date, mood_text, time.time()),
        )
        _conn.commit()


def has_mood_today(discord_id: str, mood_date: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "SELECT 1 FROM mood_log WHERE discord_id = ? AND mood_date = ? LIMIT 1",
            (str(discord_id), mood_date),
        )
        return cur.fetchone() is not None


def get_recent_moods(discord_id: str, limit: int = 7):
    with _lock:
        cur = _conn.execute(
            "SELECT mood_date, mood_text FROM mood_log WHERE discord_id = ? ORDER BY id DESC LIMIT ?",
            (str(discord_id), limit),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


# ---------- DIARY (nhật ký) ----------

def add_diary(discord_id: str, entry_date: str, content: str):
    with _lock:
        _conn.execute(
            "INSERT INTO diary (discord_id, entry_date, content, created_at) VALUES (?, ?, ?, ?)",
            (str(discord_id), entry_date, content, time.time()),
        )
        _conn.commit()


def get_recent_diary(discord_id: str, limit: int = 5):
    with _lock:
        cur = _conn.execute(
            "SELECT entry_date, content FROM diary WHERE discord_id = ? ORDER BY id DESC LIMIT ?",
            (str(discord_id), limit),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


# ---------- REMINDERS (nhắc việc) ----------

def add_reminder(discord_id: str, channel_id: str, content: str, remind_at: float):
    with _lock:
        cur = _conn.execute(
            "INSERT INTO reminders (discord_id, channel_id, content, remind_at, sent, created_at) VALUES (?, ?, ?, ?, 0, ?)",
            (str(discord_id), str(channel_id), content, remind_at, time.time()),
        )
        _conn.commit()
        return cur.lastrowid


def get_due_reminders(now_ts: float):
    with _lock:
        cur = _conn.execute(
            "SELECT id, discord_id, channel_id, content FROM reminders WHERE sent = 0 AND remind_at <= ?",
            (now_ts,),
        )
        return cur.fetchall()


def mark_reminder_sent(reminder_id: int):
    with _lock:
        _conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        _conn.commit()


def get_pending_reminders(discord_id: str):
    with _lock:
        cur = _conn.execute(
            "SELECT id, content, remind_at FROM reminders WHERE discord_id = ? AND sent = 0 ORDER BY remind_at",
            (str(discord_id),),
        )
        return cur.fetchall()


def delete_reminder(discord_id: str, reminder_id: int) -> bool:
    with _lock:
        cur = _conn.execute(
            "DELETE FROM reminders WHERE id = ? AND discord_id = ?", (reminder_id, str(discord_id))
        )
        _conn.commit()
        return cur.rowcount > 0


# ---------- TODOS (danh sách việc cần làm) ----------

def add_todo(discord_id: str, content: str):
    with _lock:
        cur = _conn.execute(
            "INSERT INTO todos (discord_id, content, done, created_at) VALUES (?, ?, 0, ?)",
            (str(discord_id), content, time.time()),
        )
        _conn.commit()
        return cur.lastrowid


def get_todos(discord_id: str, include_done: bool = True):
    with _lock:
        if include_done:
            cur = _conn.execute(
                "SELECT id, content, done FROM todos WHERE discord_id = ? ORDER BY id", (str(discord_id),)
            )
        else:
            cur = _conn.execute(
                "SELECT id, content, done FROM todos WHERE discord_id = ? AND done = 0 ORDER BY id",
                (str(discord_id),),
            )
        return cur.fetchall()


def complete_todo(discord_id: str, todo_id: int) -> bool:
    with _lock:
        cur = _conn.execute(
            "UPDATE todos SET done = 1 WHERE id = ? AND discord_id = ?", (todo_id, str(discord_id))
        )
        _conn.commit()
        return cur.rowcount > 0


def delete_todo(discord_id: str, todo_id: int) -> bool:
    with _lock:
        cur = _conn.execute(
            "DELETE FROM todos WHERE id = ? AND discord_id = ?", (todo_id, str(discord_id))
        )
        _conn.commit()
        return cur.rowcount > 0


# ---------- DAILY REMINDERS (nhắc việc lặp lại mỗi ngày) ----------

def add_daily_reminder(discord_id: str, channel_id: str, time_str: str, content: str):
    with _lock:
        cur = _conn.execute(
            "INSERT INTO daily_reminders (discord_id, channel_id, time_str, content, last_sent_date, created_at) "
            "VALUES (?, ?, ?, ?, NULL, ?)",
            (str(discord_id), str(channel_id), time_str, content, time.time()),
        )
        _conn.commit()
        return cur.lastrowid


def get_all_daily_reminders():
    with _lock:
        cur = _conn.execute(
            "SELECT id, discord_id, channel_id, time_str, content, last_sent_date FROM daily_reminders"
        )
        return cur.fetchall()


def get_daily_reminders_for(discord_id: str):
    with _lock:
        cur = _conn.execute(
            "SELECT id, time_str, content FROM daily_reminders WHERE discord_id = ? ORDER BY time_str",
            (str(discord_id),),
        )
        return cur.fetchall()


def mark_daily_reminder_sent(reminder_id: int, date_str: str):
    with _lock:
        _conn.execute("UPDATE daily_reminders SET last_sent_date = ? WHERE id = ?", (date_str, reminder_id))
        _conn.commit()


def delete_daily_reminder(discord_id: str, reminder_id: int) -> bool:
    with _lock:
        cur = _conn.execute(
            "DELETE FROM daily_reminders WHERE id = ? AND discord_id = ?", (reminder_id, str(discord_id))
        )
        _conn.commit()
        return cur.rowcount > 0


# ---------- GUESS GAME (đoán số) ----------

def start_guess_game(discord_id: str, secret_number: int, low: int, high: int):
    with _lock:
        _conn.execute(
            """INSERT INTO guess_game (discord_id, secret_number, low, high, attempts) VALUES (?, ?, ?, ?, 0)
               ON CONFLICT(discord_id) DO UPDATE SET secret_number = excluded.secret_number,
               low = excluded.low, high = excluded.high, attempts = 0""",
            (str(discord_id), secret_number, low, high),
        )
        _conn.commit()


def get_guess_game(discord_id: str):
    with _lock:
        cur = _conn.execute(
            "SELECT secret_number, low, high, attempts FROM guess_game WHERE discord_id = ?",
            (str(discord_id),),
        )
        return cur.fetchone()


def increment_guess_attempt(discord_id: str):
    with _lock:
        _conn.execute("UPDATE guess_game SET attempts = attempts + 1 WHERE discord_id = ?", (str(discord_id),))
        _conn.commit()


def end_guess_game(discord_id: str):
    with _lock:
        _conn.execute("DELETE FROM guess_game WHERE discord_id = ?", (str(discord_id),))
        _conn.commit()


# ---------- LEADERBOARD (bảng xếp hạng thân mật toàn server) ----------

def get_affection_leaderboard(limit: int = 10):
    with _lock:
        cur = _conn.execute(
            "SELECT discord_id, points FROM affection ORDER BY points DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()
