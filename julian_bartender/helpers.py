import os
import html
import asyncio
import logging
from datetime import datetime

from pydantic import Field
from aiogram import Bot, types
from aiogram.methods import TelegramMethod
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReactionTypeEmoji,
    WebAppInfo,
)

import shared.database as db
import shared.config as cfg

bot = Bot(token=cfg.TOKEN_JULIAN)

OWNER_ID = cfg.OWNER_ID
GROUP_ID = cfg.GROUP_ID
MINIAPP_MENU_URL = "https://t.me/JulianVanceVH_bot/menu"
WEBAPP_DIRECT_URL = (
    getattr(cfg, "WEBAPP_URL", None)
    or os.environ.get("WEBAPP_URL")
    or MINIAPP_MENU_URL
)

DEFAULT_SERVICE_GIFS = {
    "drink": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbGZ4eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l41lJ8ywG1ncm9FXW/giphy.gif",
    "food": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExd2J4cW12bG14Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7TKP9ln2Dr6ze6f6/giphy.gif",
}

BARTENDER_GREETINGS = [
    "🍸 <i>Julian menghentikan sejenak gerakan shaker-nya, mengelap gelas kristal dengan kain linen bersih, lalu menatap ke arah pintu masuk.</i>\n\n\"Selamat malam, {mention}. Selamat datang di <b>The Velvet Hour</b>. Duduklah di mana pun Anda merasa nyaman—gelas pertama selalu siap diracik untuk tamu baru.\"",
    "🥂 <i>Dentingan lembut es batu di dalam gelas menyambut langkah kaki yang baru tiba di lantai lounge. Julian tersenyum tipis dari balik meja bar mahoni.</i>\n\n\"Malam yang indah untuk singgah, {mention}. Silakan lihat buku menu kami jika ingin memesan minuman atau sekadar menikmati alunan musik malam ini.\"",
    "🕯️ <i>Cahaya lampu gantung temaram memantul di permukaan botol-botol kristal saat pintu beludru terbuka. Julian mengangguk sopan menyambut kedatangan tamu baru.</i>\n\n\"Selamat datang di <b>The Velvet Hour</b>, {mention}. Meja bar selalu terbuka—beri tahu saya jika Anda butuh sesuatu untuk menghangatkan suasana.\"",
]

DRINKS_CATALOG = {
    "espresso": ("Double Espresso", 0, False),
    "latte": ("Caramel Latte", 0, False),
    "negroni": ("Classic Negroni", 0, False),
    "whisky": ("Smoked Whisky", 0, False),
    "mojito": ("Velvet Mojito", 0, False),
    "mocktail": ("Crimson Sunset Mocktail", 0, False),
    "tea": ("Earl Grey Reserve Tea", 0, False),
    "water": ("Sparkling Mineral Water", 0, False),
    "vip_dom": ("Dom Pérignon Vintage", 15, True),
    "vip_blue": ("Blue Label Reserve", 15, True),
    "vip_absinthe": ("Emerald Absinthe", 15, True),
    "vip_royal": ("Velvet Royal Martini", 15, True),
}

FOODS_CATALOG = {
    "fries": ("Truffle Parmesan Fries", 0, False),
    "steak": ("Ribeye Steak", 0, False),
    "pasta": ("Truffle Carbonara", 0, False),
    "croissant": ("Butter Croissant", 0, False),
    "platter": ("Charcuterie Board", 0, False),
    "cake": ("Velvet Lava Cake", 0, False),
    "tiramisu": ("Espresso Tiramisu", 0, False),
    "vip_caviar": ("Beluga Caviar Blinis", 15, True),
    "vip_lobster": ("Butter Poached Lobster", 15, True),
    "vip_a5": ("Miyazaki Wagyu A5", 15, True),
    "vip_gold": ("24K Gold Dark Truffle", 15, True),
}

GIFTS_CATALOG = {
    "rose": {
        "name": "Single Velvet Rose",
        "emoji": "🥀",
        "price": 30,
        "charm": 6,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=800&q=80",
        "desc": "setangkai mawar merah beludru dengan pita sutra hitam",
    },
    "choco": {
        "name": "Artisan Dark Truffles",
        "emoji": "🍫",
        "price": 50,
        "charm": 10,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1549007994-cb92caebd54b?w=800&q=80",
        "desc": "sekotak cokelat hitam Belgia berlapis bubuk kakao emas",
    },
    "perfume": {
        "name": "Midnight Oud Elixir",
        "emoji": "🧴",
        "price": 80,
        "charm": 18,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1594035910387-fea47794261f?w=800&q=80",
        "desc": "parfum kristal beraroma kayu gaharu dan amber malam",
    },
    "bouquet": {
        "name": "Crimson Midnight Bouquet",
        "emoji": "💐",
        "price": 120,
        "charm": 28,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1561181286-d3fee7d55364?w=800&q=80",
        "desc": "buket besar berisi 24 mawar merah gelap eksklusif",
    },
    "watch": {
        "name": "Chronograph Gold Watch",
        "emoji": "⌚",
        "price": 250,
        "charm": 60,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1523170335258-f5ed11844a49?w=800&q=80",
        "desc": "jam tangan mekanik emas klasik edisi kolektor",
    },
    "key": {
        "name": "VIP Penthouse Suite Key",
        "emoji": "🗝️",
        "price": 400,
        "charm": 100,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1582139329536-e7284fece509?w=800&q=80",
        "desc": "kunci emas akses suite pribadi di lantai teratas lounge",
    },
    "champagne": {
        "name": "Imperial Champagne Tower",
        "emoji": "🍾",
        "price": 600,
        "charm": 155,
        "special": False,
        "default_img": "https://images.unsplash.com/photo-1514362545857-3bc16c4c7d1b?w=800&q=80",
        "desc": "menara gelas kristal dengan tuangan sampanye vintage",
    },
    "ring": {
        "name": "Velvet Crimson Diamond Ring",
        "emoji": "💍",
        "price": 1000,
        "charm": 270,
        "special": True,
        "default_img": "https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=800&q=80",
        "desc": "cincin berlian potongan solitaire dengan kilau rubi langka",
    },
    "necklace": {
        "name": "Starlight Sapphire Necklace",
        "emoji": "📿",
        "price": 1800,
        "charm": 500,
        "special": True,
        "default_img": "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?w=800&q=80",
        "desc": "kalung safir biru kerajaan yang dirangkai dengan emas putih",
    },
    "crown": {
        "name": "Sovereign Velvet Crown",
        "emoji": "👑",
        "price": 3000,
        "charm": 900,
        "special": True,
        "default_img": "https://images.unsplash.com/photo-1589656966895-2f33e7653819?w=800&q=80",
        "desc": "mahkota kehormatan tertinggi bagi bintang utama The Velvet Hour",
    },
}

SHIFT_ROLES = {
    "waiter": {
        "title": "Waiter / Server",
        "tag": "🥂 Waiter On-Duty",
        "quota": 4,
        "cmds": "/welcome @user & /dish Nama Makanan",
    },
    "bartender": {
        "title": "Bartender",
        "tag": "🍸 Bartender",
        "quota": 2,
        "cmds": "/mix Nama Minuman & /sober @user",
    },
    "host": {
        "title": "Lounge Host",
        "tag": "🕯️ Lounge Host",
        "quota": 2,
        "cmds": "/ambience & /toastall",
    },
}

VIP_DEFAULT_TAG = "👑 VIP Guest"
booth_access_cache: dict[int, dict] = {}


class SetChatMemberTag(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "setChatMemberTag"

    chat_id: int | str
    user_id: int
    tag: str | None = Field(default=None)


async def set_guest_tag(chat_id: int, user_id: int, tag: str | None) -> bool:
    if user_id == OWNER_ID:
        return False
    clean_tag = tag[:16] if tag else ""
    try:
        return await bot(SetChatMemberTag(chat_id=chat_id, user_id=user_id, tag=clean_tag))
    except Exception as e:
        logging.debug("Gagal setChatMemberTag untuk %s: %s", user_id, e)
        return False


async def restore_default_guest_tag(conn, chat_id: int, user_id: int):
    row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
    is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    await set_guest_tag(chat_id, user_id, VIP_DEFAULT_TAG if is_vip else None)


def styled_btn(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    web_app: WebAppInfo | None = None,
    style: str | None = None,
    icon_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    data = {"text": text}
    if callback_data:
        data["callback_data"] = callback_data
    if url:
        data["url"] = url
    if web_app:
        data["web_app"] = web_app
    if style:
        data["style"] = style
    if icon_emoji_id:
        data["icon_custom_emoji_id"] = icon_emoji_id
    return InlineKeyboardButton.model_construct(**data)


async def react_msg(chat_id: int, message_id: int, emoji: str = "🥂"):
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass


async def schedule_delete(chat_id: int, message_ids: list[int], delay: int = 45):
    async def _worker():
        await asyncio.sleep(delay)
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    asyncio.create_task(_worker())


def mention_user(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'


def miniapp_menu_kb(is_private: bool = False) -> InlineKeyboardMarkup:
    if is_private and WEBAPP_DIRECT_URL.startswith("https://") and not WEBAPP_DIRECT_URL.startswith("https://t.me/"):
        btn = styled_btn("🍸 Buka Buku Menu & Jukebox", web_app=WebAppInfo(url=WEBAPP_DIRECT_URL), style="primary")
    else:
        btn = styled_btn("🍸 Buka Buku Menu & Jukebox", url=MINIAPP_MENU_URL, style="primary")
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


async def reload_booth_cache():
    booth_access_cache.clear()
    async with db.pool.acquire() as conn:
        owners = await conn.fetch(
            "SELECT user_id, vip_booth_name, vip_booth_thread_id FROM users WHERE vip_booth_thread_id IS NOT NULL"
        )
        for o in owners:
            tid = int(o["vip_booth_thread_id"])
            booth_access_cache[tid] = {
                "owner_id": int(o["user_id"]),
                "booth_name": o["vip_booth_name"] or "VIP Booth",
                "guests": set(),
            }
        invites = await conn.fetch("SELECT thread_id, guest_id FROM vip_booth_invites")
        for inv in invites:
            tid = int(inv["thread_id"])
            if tid in booth_access_cache:
                booth_access_cache[tid]["guests"].add(int(inv["guest_id"]))


async def ensure_julian_schema():
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                coins INTEGER DEFAULT 50,
                charm_points INTEGER DEFAULT 0,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP WITHOUT TIME ZONE,
                vip_booth_name TEXT,
                vip_booth_thread_id BIGINT,
                last_thread_id BIGINT,
                is_admin BOOLEAN DEFAULT FALSE
            );
        """)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS charm_points INTEGER DEFAULT 0;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_booth_name TEXT;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_booth_thread_id BIGINT;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_thread_id BIGINT;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vip_booth_invites (
                thread_id BIGINT NOT NULL,
                guest_id BIGINT NOT NULL,
                invited_by BIGINT NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                PRIMARY KEY (thread_id, guest_id)
            );
        """)
        await conn.execute("CREATE TABLE IF NOT EXISTS bar_settings (key TEXT PRIMARY KEY, value TEXT);")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_custom_media (
                gift_code TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'photo'
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_shifts (
                user_id BIGINT PRIMARY KEY,
                role_name TEXT NOT NULL,
                started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                ends_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                service_count INTEGER DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shift_daily_counts (
                user_id BIGINT NOT NULL,
                shift_date DATE NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, shift_date)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS duel_challenges (
                id SERIAL PRIMARY KEY,
                challenger_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                bet_vc INTEGER NOT NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)
    await reload_booth_cache()


async def get_setting(key: str) -> str | None:
    async with db.pool.acquire() as conn:
        return await conn.fetchval("SELECT value FROM bar_settings WHERE key = $1", key)


async def set_setting(key: str, value: str):
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bar_settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, key, value)


async def sync_tg_user(conn, tg_user: types.User, thread_id: int | None = None):
    if not tg_user or tg_user.is_bot:
        return
    await conn.execute("""
        INSERT INTO users (user_id, username, full_name, coins, charm_points, last_thread_id)
        VALUES ($1, $2, $3, 50, 0, $4)
        ON CONFLICT (user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            full_name = EXCLUDED.full_name,
            last_thread_id = COALESCE($4, users.last_thread_id);
    """, tg_user.id, tg_user.username, tg_user.full_name, thread_id)


async def resolve_target_smart(conn, message: types.Message, ident: str | None = None):
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        ru = message.reply_to_message.from_user
        await sync_tg_user(conn, ru, message.message_thread_id)
        return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", ru.id)

    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user and not ent.user.is_bot:
                await sync_tg_user(conn, ent.user, message.message_thread_id)
                return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", ent.user.id)

    if not ident:
        return None

    clean = ident.strip().lstrip("@")
    if clean.isdigit():
        return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", int(clean))
    return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE LOWER(username) = $1", clean.lower())


async def log_tx(conn, user_id: int, amount: int, reason: str):
    await conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
        user_id, amount, reason
    )


async def add_bar_quest(conn, user_id: int):
    today = datetime.utcnow().date()
    await conn.execute("""
        INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
        VALUES ($1, $2, 'bar_social', 1, FALSE)
        ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
        SET progress = LEAST(daily_quests.progress + 1, 1);
    """, user_id, today)


async def get_service_media(category: str) -> tuple[str, str]:
    key = f"menu_{category}"
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT file_id, media_type FROM gift_custom_media WHERE gift_code = $1", key)
        if row:
            return row["file_id"], row["media_type"]
    return DEFAULT_SERVICE_GIFS.get(category, DEFAULT_SERVICE_GIFS["drink"]), "animation"
