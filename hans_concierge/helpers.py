import random
import string
from datetime import datetime
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReactionTypeEmoji

import shared.database as db
import shared.config as cfg

bot = Bot(token=cfg.TOKEN_HANS)

OWNER_ID = cfg.OWNER_ID
GROUP_ID = cfg.GROUP_ID
CH_INFO_ID = getattr(cfg, "CH_INFO_ID", 0)
CH_PROMOTE_ID = getattr(cfg, "CH_PROMOTE_ID", 0)
CH_INFO_LINK = getattr(cfg, "CH_INFO_LINK", "")
CH_PROMOTE_LINK = getattr(cfg, "CH_PROMOTE_LINK", "")
CHANNEL_ID = CH_INFO_ID

REQUIRED_CN_SYMBOL = getattr(cfg, "REQUIRED_CN_SYMBOL", "🥂")
WELCOME_BONUS = getattr(cfg, "WELCOME_BONUS", 200)
VIP_COST_24H = getattr(cfg, "VIP_COST_24H", 300)
DAILY_REWARD_VC = getattr(cfg, "DAILY_COIN", 30)
REFERRAL_BONUS_VC = 50
CONFESS_COST_VC = 5
PM_COST_VC = 10

DAILY_QUESTS = {
    "daily_checkin": {
        "title": "Absen Malam Lounge",
        "desc": "Klaim jatah absen harian /daily di lobi Hans.",
        "target": 1,
        "reward": 15,
    },
    "bar_social": {
        "title": "Penikmat Suasana Bar",
        "desc": "Pesan minuman/makanan lewat /order, /eat atau traktir tamu lewat /treat di grup.",
        "target": 1,
        "reward": 20,
    },
    "music_vibe": {
        "title": "Kurator Nada Malam",
        "desc": "Request lagu di jukebox grup lewat /reqsong atau dengarkan lewat /myearphone.",
        "target": 1,
        "reward": 20,
    },
}


async def react_message(chat_id: int, message_id: int, emoji: str = "🥂"):
    """Memberikan auto-reaction emoji resmi Telegram pada pesan user."""
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass


def styled_btn(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
    icon_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    """Membuat InlineKeyboardButton dengan dukungan warna primary/success/danger & custom emoji ID."""
    data = {"text": text}
    if callback_data:
        data["callback_data"] = callback_data
    if url:
        data["url"] = url
    if style:
        data["style"] = style
    if icon_emoji_id:
        data["icon_custom_emoji_id"] = icon_emoji_id
    return InlineKeyboardButton.model_construct(**data)


def normalize_tg_link(link: str | None) -> str | None:
    """Menormalisasi format @username, t.me/..., atau http:// menjadi https://t.me/... yang valid."""
    if not link:
        return None
    cleaned = str(link).strip().strip('"').strip("'").strip()
    if not cleaned:
        return None

    if cleaned.startswith("@"):
        username = cleaned.lstrip("@")
        return f"https://t.me/{username}" if username else None

    if cleaned.startswith("http://"):
        cleaned = "https://" + cleaned[len("http://"):]
    elif cleaned.startswith("t.me/") or cleaned.startswith("telegram.me/"):
        cleaned = "https://" + cleaned
    elif not cleaned.startswith("https://"):
        cleaned = f"https://t.me/{cleaned.lstrip('/')}"

    if cleaned.rstrip("/") in ("https://t.me", "https://telegram.me"):
        return None
    return cleaned


def _is_valid_tg_link(link: str | None) -> bool:
    return normalize_tg_link(link) is not None


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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_shops (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                owner_username TEXT,
                shop_name TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id SERIAL PRIMARY KEY,
                shop_id INTEGER NOT NULL REFERENCES partner_shops(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL DEFAULT 'photo',
                price_vc INTEGER NOT NULL,
                is_sold BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bar_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                post_type TEXT NOT NULL,
                target_to TEXT,
                content TEXT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)


async def get_bar_setting(key: str, default: str | None = None) -> str | None:
    async with db.pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM bar_settings WHERE key = $1", key)
        return val if val is not None else default


async def set_bar_setting(key: str, value: str | None):
    async with db.pool.acquire() as conn:
        if value is None:
            await conn.execute("DELETE FROM bar_settings WHERE key = $1", key)
        else:
            await conn.execute("""
                INSERT INTO bar_settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
            """, key, value)


async def resolve_target_user(conn, identifier: str):
    clean = identifier.strip().lstrip("@")
    if clean.isdigit():
        return await conn.fetchrow(
            "SELECT user_id, username, full_name, coins, is_admin FROM users WHERE user_id = $1",
            int(clean)
        )
    return await conn.fetchrow(
        "SELECT user_id, username, full_name, coins, is_admin FROM users WHERE LOWER(username) = $1",
        clean.lower()
    )


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


async def _btn_label_and_icon(setting_key: str, default_emoji: str, label: str) -> tuple[str, str | None]:
    custom_id = await get_bar_setting(setting_key)
    if custom_id:
        return label, custom_id
    return f"{default_emoji} {label}", None


def insufficient_vc_kb(current_vc: int, needed_vc: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            styled_btn(f"📅 Klaim Absen Harian +{DAILY_REWARD_VC} VC", callback_data="claim_daily", style="success"),
            styled_btn("🎯 Cek Misi Harian", callback_data="daily_quests"),
        ],
        [styled_btn("🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
    ])


async def main_lobby_kb(user_id: int | None = None) -> InlineKeyboardMarkup:
    is_admin_or_owner = await is_staff_or_owner(user_id) if user_id else False

    lbl_enter, ico_enter = await _btn_label_and_icon("ico_enter", "🚪", "Verifikasi & Masuk ke Bar")
    lbl_confess, ico_confess = await _btn_label_and_icon("ico_confess", "🕯️", "Curhat Confess")
    lbl_promote, ico_promote = await _btn_label_and_icon("ico_pm", "📣", "Kirim Promote")
    lbl_wallet, ico_wallet = await _btn_label_and_icon("ico_wallet", "💳", "Kartu Member & Mutasi")
    lbl_daily, ico_daily = await _btn_label_and_icon("ico_daily", "📅", "Absen Harian")
    lbl_vip, ico_vip = await _btn_label_and_icon("ico_vip", "🍾", "Beli VIP Pass 24 Jam")
    lbl_lapak, ico_lapak = await _btn_label_and_icon("ico_lapak", "🏪", "Pojok Lapak Partner")

    rows = [
        [styled_btn(lbl_enter, callback_data="enter_bar", style="primary", icon_emoji_id=ico_enter)],
        [
            styled_btn(lbl_confess, callback_data="menu_confess", icon_emoji_id=ico_confess),
            styled_btn(lbl_promote, callback_data="menu_promote", icon_emoji_id=ico_promote),
        ],
    ]

    # Baris pintasan URL menuju CH_INFO_LINK dan CH_PROMOTE_LINK (otomatis dinormalisasi)
    channel_links_row = []
    norm_info_link = normalize_tg_link(CH_INFO_LINK)
    norm_promote_link = normalize_tg_link(CH_PROMOTE_LINK)
    if norm_info_link:
        channel_links_row.append(styled_btn("📢 Channel Info", url=norm_info_link))
    if norm_promote_link:
        channel_links_row.append(styled_btn("📣 Channel Promote", url=norm_promote_link))
    if channel_links_row:
        rows.append(channel_links_row)

    rows.extend([
        [
            styled_btn(lbl_wallet, callback_data="my_wallet", icon_emoji_id=ico_wallet),
            styled_btn(lbl_daily, callback_data="claim_daily", style="success", icon_emoji_id=ico_daily),
        ],
        [
            styled_btn("🎯 Misi Harian", callback_data="daily_quests"),
            styled_btn("🎟️ Undang Teman", callback_data="my_referral"),
        ],
        [
            styled_btn(lbl_vip, callback_data="buy_vip", style="success", icon_emoji_id=ico_vip),
            styled_btn(lbl_lapak, callback_data="browse_lapak", icon_emoji_id=ico_lapak),
        ],
        [
            styled_btn("🎁 Kirim Gift / Hadiah", callback_data="menu_gift"),
            styled_btn("📖 Buku Panduan Bar", callback_data="info_menu"),
        ],
    ])

    if is_admin_or_owner:
        rows.insert(0, [styled_btn("🛡️ Panel Kontrol Admin / Owner", callback_data="open_admin_panel", style="danger")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def info_categories_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_btn("🥂 Command Bar, Menu VIP & Mini-Game", callback_data="info_cmd_bar")],
        [styled_btn("🎶 Command Musik & Jukebox Kaelen", callback_data="info_cmd_music")],
        [styled_btn("💼 Panduan Shift Kerja 50 VC", callback_data="info_cmd_shift")],
        [styled_btn("🎯 Ekonomi VC, Misi & Referral", callback_data="info_economy")],
        [styled_btn("🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
    ])


def back_info_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_btn("⬅️ Kembali ke Kategori Panduan", callback_data="info_menu")],
        [styled_btn("🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
    ])
