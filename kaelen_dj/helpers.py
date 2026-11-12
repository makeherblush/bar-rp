import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, types
from aiogram.types import BotCommand, BotCommandScopeChatMember

import shared.database as db
from shared.config import TOKEN_KAELEN, OWNER_ID, GROUP_ID

bot = Bot(token=TOKEN_KAELEN)

SHIFT_MAX_MINUTES = 20
SHIFT_REQUIRED_ACTIONS = 5
VOTESKIP_REQUIRED = 3

ALL_GROUP_COMMANDS = [
    BotCommand(command="reqsong", description="Putar lagu di bar — Contoh: /reqsong Apocalypse - Cigarettes After Sex"),
    BotCommand(command="nowplaying", description="Lihat info lagu yang sedang diputar — Contoh: /nowplaying"),
    BotCommand(command="queue", description="Lihat daftar antrean jukebox — Contoh: /queue"),
    BotCommand(command="voteskip", description="Voting lewati lagu saat ini (3 suara) — Contoh: /voteskip"),
    BotCommand(command="myearphone", description="Kirim lagu pribadi ke PC — Contoh: /myearphone Sunsetz - CAS"),
    BotCommand(command="spinmusic", description="[Shift DJ] Putar lagu prioritas — Contoh: /spinmusic Sunsetz - CAS"),
    BotCommand(command="dedicate", description="[Shift DJ] Dedikasi lagu — Contoh: /dedicate @clara Perfect - Ed Sheeran | Buat kamu"),
    BotCommand(command="skip", description="[Shift DJ] Lewati lagu yang sedang diputar — Contoh: /skip"),
    BotCommand(command="stopmusic", description="[Shift DJ] Hentikan musik & bersihkan antrean — Contoh: /stopmusic"),
]

DJ_PRIORITY_COMMANDS = [
    BotCommand(command="spinmusic", description="[Tugas DJ] Putar lagu prioritas — Contoh: /spinmusic Sunsetz - CAS"),
    BotCommand(command="dedicate", description="[Tugas DJ] Dedikasi lagu — Contoh: /dedicate @clara Perfect - Ed Sheeran | Buat kamu"),
    BotCommand(command="skip", description="[Tugas DJ] Lewati lagu yang sedang diputar — Contoh: /skip"),
    BotCommand(command="stopmusic", description="[Tugas DJ] Hentikan musik & bersihkan antrean — Contoh: /stopmusic"),
    BotCommand(command="nowplaying", description="Lihat lagu yang sedang diputar — Contoh: /nowplaying"),
    BotCommand(command="queue", description="Lihat daftar antrean jukebox — Contoh: /queue"),
    BotCommand(command="reqsong", description="Putar lagu di bar — Contoh: /reqsong Apocalypse - Cigarettes After Sex"),
    BotCommand(command="myearphone", description="Kirim lagu pribadi ke PC — Contoh: /myearphone Sunsetz - CAS"),
]

async def ensure_kaelen_schema():
    """Memastikan tabel mutasi dompet & misi harian tersedia jika Kaelen menyala lebih dulu."""
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_quests (
                user_id BIGINT NOT NULL,
                quest_date DATE NOT NULL,
                quest_key TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                claimed BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, quest_date, quest_key)
            );
        """)

async def log_music_tx_and_quest(user_id: int, cost: int, song_title: str):
    """Mencatat pemotongan VC (jika berbayar) dan progres misi harian 'music_vibe'."""
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        if cost > 0:
            await conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
                user_id, -cost, f"Request lagu: {song_title[:30]}"
            )
        await conn.execute("""
            INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
            VALUES ($1, $2, 'music_vibe', 1, FALSE)
            ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
            SET progress = LEAST(daily_quests.progress + 1, 1);
        """, user_id, today)

async def schedule_delete(msg: types.Message, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

async def sync_dj_member_commands(user_id: int, active: bool):
    scope = BotCommandScopeChatMember(chat_id=GROUP_ID, user_id=user_id)
    try:
        if active:
            await bot.set_my_commands(DJ_PRIORITY_COMMANDS, scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception as e:
        logging.warning(f"Gagal sync DJ commands untuk {user_id}: {e}")

async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def is_vip_user(user_id: int) -> bool:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())

async def is_active_dj(user_id: int) -> bool:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM active_shifts WHERE role = 'dj' AND user_id = $1 AND started_at > $2",
            user_id, datetime.utcnow() - timedelta(minutes=SHIFT_MAX_MINUTES)
        )
        return bool(row)

async def add_dj_shift_action(user_id: int) -> int:
    async with db.pool.acquire() as conn:
        new_val = await conn.fetchval(
            "UPDATE active_shifts SET actions_count = actions_count + 1 WHERE role = 'dj' AND user_id = $1 RETURNING actions_count",
            user_id
        )
        return new_val or 0

async def has_active_guests_in_bar() -> bool:
    async with db.pool.acquire() as conn:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE is_in_bar = TRUE AND last_active > $1",
            datetime.utcnow() - timedelta(minutes=30)
        )
        return (cnt or 0) > 0
