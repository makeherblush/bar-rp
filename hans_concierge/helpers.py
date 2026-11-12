import random
import string
from datetime import datetime, date
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import shared.database as db
import shared.config as cfg

bot = Bot(token=cfg.TOKEN_HANS)

OWNER_ID = cfg.OWNER_ID
GROUP_ID = cfg.GROUP_ID
REQUIRED_CN_SYMBOL = getattr(cfg, "REQUIRED_CN_SYMBOL", "🥂")
VIP_COST_24H = getattr(cfg, "VIP_COST_24H", 150)
DAILY_REWARD_VC = getattr(cfg, "DAILY_REWARD_VC", 20)
REFERRAL_BONUS_VC = 50

DAILY_QUESTS = {
    "daily_checkin": {
        "title": "Absen Malam Lounge",
        "desc": "Klaim jatah absen harian (/daily) di lobi Hans.",
        "target": 1,
        "reward": 15,
    },
    "bar_social": {
        "title": "Penikmat Suasana Bar",
        "desc": "Pesan minuman/makanan (/order, /eat) atau traktir tamu (/treat) di grup.",
        "target": 1,
        "reward": 20,
    },
    "music_vibe": {
        "title": "Kurator Nada Malam",
        "desc": "Request lagu di jukebox grup (/reqsong) atau dengarkan lewat /myearphone.",
        "target": 1,
        "reward": 20,
    },
}

async def ensure_hans_schema():
    async with db.pool.acquire() as conn:
        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE,
            ADD COLUMN IF NOT EXISTS referred_by BIGINT,
            ADD COLUMN IF NOT EXISTS referral_rewarded BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS vip_booth_name TEXT;
        """)
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

async def log_wallet_tx(conn, user_id: int, amount: int, reason: str):
    await conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
        user_id, amount, reason
    )

async def add_quest_progress(user_id: int, quest_key: str, inc: int = 1):
    meta = DAILY_QUESTS.get(quest_key)
    if not meta:
        return
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
            VALUES ($1, $2, $3, $4, FALSE)
            ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
            SET progress = LEAST(daily_quests.progress + $4, $5);
        """, user_id, today, quest_key, inc, meta["target"])

async def get_or_create_referral_code(user_id: int) -> str:
    async with db.pool.acquire() as conn:
        code = await conn.fetchval("SELECT referral_code FROM users WHERE user_id = $1", user_id)
        if code:
            return code
        while True:
            new_code = "VH" + "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
            exists = await conn.fetchval("SELECT 1 FROM users WHERE referral_code = $1", new_code)
            if not exists:
                await conn.execute("UPDATE users SET referral_code = $1 WHERE user_id = $2", new_code, user_id)
                return new_code

async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def main_lobby_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    is_admin_or_owner = await is_staff_or_owner(user_id) if user_id else False

    rows = [
        [InlineKeyboardButton(text="🚪 Verifikasi & Masuk ke Bar", callback_data="enter_bar")],
        [
            InlineKeyboardButton(text="💰 Dompet & Mutasi", callback_data="my_wallet"),
            InlineKeyboardButton(text="📅 Absen Harian", callback_data="claim_daily"),
        ],
        [
            InlineKeyboardButton(text="🎯 Misi Harian", callback_data="daily_quests"),
            InlineKeyboardButton(text="🎟️ Undang Teman", callback_data="my_referral"),
        ],
        [
            InlineKeyboardButton(text="🍾 Beli VIP Pass (24 Jam)", callback_data="buy_vip"),
            InlineKeyboardButton(text="🏪 Pojok Lapak Partner", callback_data="browse_lapak"),
        ],
        [
            InlineKeyboardButton(text="🎁 Kirim Gift / Hadiah", callback_data="menu_gift"),
            InlineKeyboardButton(text="📖 Buku Panduan Bar", callback_data="info_menu"),
        ],
    ]

    if is_admin_or_owner:
        rows.insert(0, [InlineKeyboardButton(text="🛡️ Panel Kontrol Admin / Owner", callback_data="open_admin_panel")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

def info_categories_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥂 Command Bar, Menu VIP & Mini-Game", callback_data="info_cmd_bar")],
        [InlineKeyboardButton(text="🎶 Command Musik & Jukebox (Kaelen)", callback_data="info_cmd_music")],
        [InlineKeyboardButton(text="💼 Panduan Shift Kerja (50 VC)", callback_data="info_cmd_shift")],
        [InlineKeyboardButton(text="🎯 Ekonomi VC, Misi & Referral", callback_data="info_economy")],
        [InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
    ])

def back_info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali ke Kategori Panduan", callback_data="info_menu")],
        [InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
    ])
