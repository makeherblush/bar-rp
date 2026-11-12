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

# --- KONFIGURASI FITUR BARU HANS ---
REFERRAL_BONUS_VC = 50  # Bonus untuk pengundang & tamu baru setelah lolos CN

DAILY_QUESTS = {
    "daily_checkin": {
        "title": "Absen Harian di Pintu Utama",
        "desc": "Klaim /daily atau tombol Absen Harian",
        "target": 1,
        "reward": 15,
    },
    "bar_social": {
        "title": "Interaksi di Meja Bar",
        "desc": "Kirim 1 pesanan (/order, /eat, atau /treat) di grup",
        "target": 1,
        "reward": 20,
    },
    "music_vibe": {
        "title": "Penikmat Alunan Lounge",
        "desc": "Putar 1 lagu (/reqsong atau /myearphone)",
        "target": 1,
        "reward": 20,
    },
}

async def ensure_hans_schema():
    """Memastikan tabel & kolom referral, misi harian, dan mutasi dompet tersedia."""
    async with db.pool.acquire() as conn:
        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE,
            ADD COLUMN IF NOT EXISTS referred_by BIGINT,
            ADD COLUMN IF NOT EXISTS referral_rewarded BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;
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

def _generate_ref_code(user_id: int) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"VH{str(user_id)[-4:]}{suffix}"

async def get_or_create_referral_code(user_id: int) -> str:
    async with db.pool.acquire() as conn:
        code = await conn.fetchval("SELECT referral_code FROM users WHERE user_id = $1", user_id)
        if code:
            return code
        for _ in range(5):
            candidate = _generate_ref_code(user_id)
            exists = await conn.fetchval("SELECT 1 FROM users WHERE referral_code = $1", candidate)
            if not exists:
                await conn.execute("UPDATE users SET referral_code = $1 WHERE user_id = $2", candidate, user_id)
                return candidate
    return f"VH{user_id}"

async def log_wallet_tx(conn, user_id: int, amount: int, reason: str):
    """Mencatat mutasi masuk/keluar Velvet Coins ke riwayat dompet."""
    await conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
        user_id, amount, reason
    )

async def add_quest_progress(user_id: int, quest_key: str, step: int = 1):
    """Menambah progres misi harian tamu."""
    if quest_key not in DAILY_QUESTS:
        return
    today = datetime.utcnow().date()
    target = DAILY_QUESTS[quest_key]["target"]
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
            VALUES ($1, $2, $3, LEAST($4, $5), FALSE)
            ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
            SET progress = LEAST(daily_quests.progress + $4, $5);
        """, user_id, today, quest_key, step, target)

async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

# --- KEYBOARD UTAMA & PANDUAN INFORMASI ---
def main_lobby_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚪 Masuk ke Ruang Utama (Cek Atribut CN)", callback_data="enter_bar")],
        [
            InlineKeyboardButton(text="💰 Dompet & Mutasi", callback_data="my_wallet"),
            InlineKeyboardButton(text="📅 Absen Harian", callback_data="claim_daily"),
        ],
        [
            InlineKeyboardButton(text="🎯 Misi Harian", callback_data="daily_quests"),
            InlineKeyboardButton(text="🎟️ Undang Teman (+50 VC)", callback_data="my_referral"),
        ],
        [
            InlineKeyboardButton(text="🍾 VIP Pass (24 Jam)", callback_data="buy_vip"),
            InlineKeyboardButton(text="🎁 Kirim Gift", callback_data="menu_gift"),
        ],
        [
            InlineKeyboardButton(text="🏪 Pojok Lapak Partner", callback_data="browse_lapak"),
            InlineKeyboardButton(text="📖 Panduan & Command Lengkap", callback_data="info_menu"),
        ],
    ])

def info_categories_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥂 Command Bar, Booth & Dice (Julian)", callback_data="info_cmd_bar")],
        [InlineKeyboardButton(text="🎶 Command Musik & Radio (Kaelen)", callback_data="info_cmd_music")],
        [InlineKeyboardButton(text="💼 Sistem Shift Kerja & Upah VC", callback_data="info_cmd_shift")],
        [InlineKeyboardButton(text="🎯 Ekonomi, Misi Harian & Referral", callback_data="info_economy")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Lobi Utama", callback_data="back_lobby")],
    ])

def back_info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali ke Daftar Panduan", callback_data="info_menu")],
        [InlineKeyboardButton(text="🏠 Lobi Utama Hans", callback_data="back_lobby")],
    ])
