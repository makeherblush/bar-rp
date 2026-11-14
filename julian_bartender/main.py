import html
import random
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReactionTypeEmoji,
)
from aiogram.enums import ParseMode

import shared.database as db
import shared.config as cfg
from hans_concierge.webapp_server import start_webapp_server

logging.basicConfig(level=logging.INFO)

bot = Bot(token=cfg.TOKEN_JULIAN)
dp = Dispatcher(storage=MemoryStorage())

OWNER_ID = cfg.OWNER_ID
GROUP_ID = cfg.GROUP_ID
MINIAPP_MENU_URL = "https://t.me/JulianVanceVH_bot/menu"

DEFAULT_SERVICE_GIFS = {
    "drink": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbGZ4eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l41lJ8ywG1ncm9FXW/giphy.gif",
    "food": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExd2J4cW12bG14Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7TKP9ln2Dr6ze6f6/giphy.gif",
}

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
    "waiter": {"title": "Waiter / Server", "quota": 4, "cmds": "/welcome @user & /dish Nama Makanan"},
    "bartender": {"title": "Bartender", "quota": 2, "cmds": "/mix Nama Minuman & /sober @user"},
    "host": {"title": "Lounge Host", "quota": 2, "cmds": "/ambience & /toastall"},
}

_last_chat_earn: dict[int, datetime] = {}


def styled_btn(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
    icon_emoji_id: str | None = None,
) -> InlineKeyboardButton:
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


async def react_msg(chat_id: int, message_id: int, emoji: str = "🥂"):
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass


async def _schedule_delete(chat_id: int, message_ids: list[int], delay: int = 45):
    async def _worker():
        await asyncio.sleep(delay)
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    asyncio.create_task(_worker())


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
                last_thread_id BIGINT,
                is_admin BOOLEAN DEFAULT FALSE
            );
        """)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS charm_points INTEGER DEFAULT 0;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_booth_name TEXT;")
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_thread_id BIGINT;")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bar_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
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


async def _get_setting(key: str) -> str | None:
    async with db.pool.acquire() as conn:
        return await conn.fetchval("SELECT value FROM bar_settings WHERE key = $1", key)


async def _set_setting(key: str, value: str):
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bar_settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, key, value)


async def _sync_tg_user(conn, tg_user: types.User, thread_id: int | None = None):
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


async def _resolve_target_smart(conn, message: types.Message, ident: str | None = None):
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        ru = message.reply_to_message.from_user
        await _sync_tg_user(conn, ru, message.message_thread_id)
        return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", ru.id)

    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user and not ent.user.is_bot:
                await _sync_tg_user(conn, ent.user, message.message_thread_id)
                return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", ent.user.id)

    if not ident:
        return None

    clean = ident.strip().lstrip("@")
    if clean.isdigit():
        return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", int(clean))
    return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE LOWER(username) = $1", clean.lower())


async def _log_tx(conn, user_id: int, amount: int, reason: str):
    await conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
        user_id, amount, reason
    )


async def _add_bar_quest(conn, user_id: int):
    today = datetime.utcnow().date()
    await conn.execute("""
        INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
        VALUES ($1, $2, 'bar_social', 1, FALSE)
        ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
        SET progress = LEAST(daily_quests.progress + 1, 1);
    """, user_id, today)


def _mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'


def miniapp_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [styled_btn("🍸 Buka Buku Menu & Jukebox", url=MINIAPP_MENU_URL, style="primary")]
    ])


async def _get_service_media(category: str) -> tuple[str, str]:
    key = f"menu_{category}"
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT file_id, media_type FROM gift_custom_media WHERE gift_code = $1", key)
        if row:
            return row["file_id"], row["media_type"]
    return DEFAULT_SERVICE_GIFS.get(category, DEFAULT_SERVICE_GIFS["drink"]), "animation"


# --- KONFIGURASI MEDIA GIF/FOTO MENU & GIFT (OWNER) ---
@dp.message(Command("setmenumedia"))
async def cmd_set_menu_media(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    valid = {"drink", "custom_mix", "food", "song"}
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in valid:
        return await message.reply(
            "Reply GIF atau Foto dengan:\n<code>/setmenumedia <kategori></code>\n\n"
            "Kategori: <code>drink</code>, <code>custom_mix</code>, <code>food</code>, <code>song</code>",
            parse_mode=ParseMode.HTML,
        )

    rep = message.reply_to_message
    if not rep or (not rep.photo and not rep.animation):
        return await message.reply("Harap <b>reply</b> pesan berisi GIF atau Foto.", parse_mode=ParseMode.HTML)

    cat = parts[1].lower()
    if rep.animation:
        file_id, mtype = rep.animation.file_id, "animation"
    else:
        file_id, mtype = rep.photo[-1].file_id, "photo"

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gift_custom_media (gift_code, file_id, media_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (gift_code) DO UPDATE SET file_id = EXCLUDED.file_id, media_type = EXCLUDED.media_type;
        """, f"menu_{cat}", file_id, mtype)

    await message.reply(f"✅ Media <code>{cat}</code> diperbarui.", parse_mode=ParseMode.HTML)


@dp.message(Command("setgiftimg"))
async def cmd_set_gift_image(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in GIFTS_CATALOG:
        codes = ", ".join(f"<code>{k}</code>" for k in GIFTS_CATALOG.keys())
        return await message.reply(
            f"Reply foto atau GIF dengan:\n<code>/setgiftimg <kode></code>\n\nKode: {codes}",
            parse_mode=ParseMode.HTML,
        )

    rep = message.reply_to_message
    if not rep or (not rep.photo and not rep.animation):
        return await message.reply("Harap <b>reply</b> pesan berisi Foto atau GIF.", parse_mode=ParseMode.HTML)

    code = parts[1].lower()
    if rep.animation:
        file_id, mtype = rep.animation.file_id, "animation"
    else:
        file_id, mtype = rep.photo[-1].file_id, "photo"

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gift_custom_media (gift_code, file_id, media_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (gift_code) DO UPDATE SET file_id = EXCLUDED.file_id, media_type = EXCLUDED.media_type;
        """, code, file_id, mtype)

    await message.reply(
        f"✅ Media hadiah <b>{GIFTS_CATALOG[code]['name']}</b> (<code>{code}</code>) diperbarui.",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("setgiftch"))
async def cmd_set_gift_channel(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        cur = await _get_setting("gift_channel_id") or getattr(cfg, "GIFT_CHANNEL_ID", "Belum diatur")
        return await message.reply(
            f"Format: <code>/setgiftch -1001234567890</code> (atau <code>off</code>).\nChannel saat ini: <code>{cur}</code>",
            parse_mode=ParseMode.HTML,
        )

    val = parts[1].strip()
    if val.lower() == "off":
        await _set_setting("gift_channel_id", "")
        return await message.reply("✅ Channel hadiah istimewa dimatikan.")

    await _set_setting("gift_channel_id", val)
    await message.reply(f"✅ Channel hadiah istimewa diatur ke: <code>{html.escape(val)}</code>", parse_mode=ParseMode.HTML)


# --- KATALOG & KIRIM HADIAH MEWAH (/gift) ---
@dp.message(Command("gift"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_send_gift(message: types.Message):
    sender = message.from_user
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot)

    if (has_reply and len(parts) < 2) or (not has_reply and len(parts) < 3):
        reg_lines = []
        sp_lines = []
        for code, g in GIFTS_CATALOG.items():
            line = f"• <code>{code}</code> — {g['emoji']} {g['name']} ({g['price']} VC | +{g['charm']} ✨)"
            if g["special"]:
                sp_lines.append(line)
            else:
                reg_lines.append(line)

        catalog_text = (
            "🎁 <b>Katalog Hadiah The Velvet Hour</b>\n\n"
            + "\n".join(reg_lines)
            + "\n\n👑 <b>Hadiah Istimewa</b> <i>(Auto-Pin & Channel)</i>\n"
            + "\n".join(sp_lines)
            + "\n\nCara kirim: <code>/gift @username kode</code> atau reply pesan target dengan <code>/gift kode</code>"
        )
        cat_msg = await message.reply(catalog_text, parse_mode=ParseMode.HTML)
        await _schedule_delete(message.chat.id, [message.message_id, cat_msg.message_id], delay=45)
        return

    if has_reply:
        target_ident = None
        gift_code = parts[1].lower().strip()
        custom_note = " ".join(parts[2:]).strip()[:80] if len(parts) > 2 else ""
    else:
        target_ident = parts[1]
        gift_code = parts[2].lower().strip()
        custom_note = " ".join(parts[3:]).strip()[:80] if len(parts) > 3 else ""

    if gift_code not in GIFTS_CATALOG:
        err_msg = await message.reply(
            f"Kode hadiah <code>{html.escape(gift_code)}</code> tidak ditemukan. Ketik <code>/gift</code> untuk melihat daftar kode.",
            parse_mode=ParseMode.HTML,
        )
        await _schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
        return

    gift = GIFTS_CATALOG[gift_code]
    cost = gift["price"]
    charm_gain = gift["charm"]
    is_special = gift["special"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, sender, message.message_thread_id)
            target = await _resolve_target_smart(conn, message, target_ident)
            if not target:
                err_msg = await message.reply(
                    f"Penerima belum tercatat. Reply salah satu pesannya dengan <code>/gift {gift_code}</code>.",
                    parse_mode=ParseMode.HTML,
                )
                await _schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            if target["user_id"] == sender.id:
                err_msg = await message.reply("Kamu tidak bisa mengirim hadiah untuk dirimu sendiri.")
                await _schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
                return

            s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if not s_row or (s_row["coins"] or 0) < cost:
                err_msg = await message.reply(
                    f"Saldo tidak cukup untuk <b>{gift['name']}</b> (butuh <b>{cost} VC</b>, saldo kamu: <b>{(s_row['coins'] or 0) if s_row else 0} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )
                await _schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, sender.id)
            await conn.execute(
                "UPDATE users SET charm_points = COALESCE(charm_points, 0) + $1 WHERE user_id = $2",
                charm_gain, target["user_id"]
            )
            await _log_tx(conn, sender.id, -cost, f"Kirim Gift {gift['name']} ke {target['full_name']}")
            await _add_bar_quest(conn, sender.id)

        custom_media = await conn.fetchrow(
            "SELECT file_id, media_type FROM gift_custom_media WHERE gift_code = $1",
            gift_code
        )

    await react_msg(message.chat.id, message.message_id, gift["emoji"])

    note_line = f"\n\n<i>\"{html.escape(custom_note)}\"</i>" if custom_note else ""
    if is_special:
        caption = (
            f"👑 {gift['emoji']} <b>{gift['name']}</b>\n"
            f"{_mention(sender.id, sender.first_name)} mempersembahkan {gift['desc']} kepada {_mention(target['user_id'], target['full_name'])} (<b>+{charm_gain} Charm ✨</b>)."
            f"{note_line}"
        )
    else:
        caption = (
            f"{gift['emoji']} <b>{gift['name']}</b>\n"
            f"{_mention(sender.id, sender.first_name)} mengirimkan {gift['desc']} untuk {_mention(target['user_id'], target['full_name'])} (<b>+{charm_gain} Charm ✨</b>)."
            f"{note_line}"
        )

    send_kwargs = {"message_thread_id": message.message_thread_id} if message.message_thread_id else {}
    sent_msg = None
    try:
        if custom_media and custom_media["media_type"] == "animation":
            sent_msg = await bot.send_animation(
                chat_id=message.chat.id,
                animation=custom_media["file_id"],
                caption=caption,
                parse_mode=ParseMode.HTML,
                **send_kwargs,
            )
        else:
            media_source = custom_media["file_id"] if custom_media else gift["default_img"]
            sent_msg = await bot.send_photo(
                chat_id=message.chat.id,
                photo=media_source,
                caption=caption,
                parse_mode=ParseMode.HTML,
                **send_kwargs,
            )
    except Exception:
        sent_msg = await bot.send_message(
            chat_id=message.chat.id,
            text=caption,
            parse_mode=ParseMode.HTML,
            **send_kwargs,
        )

    await _schedule_delete(message.chat.id, [message.message_id], delay=5)

    if is_special and sent_msg:
        try:
            await bot.pin_chat_message(
                chat_id=message.chat.id,
                message_id=sent_msg.message_id,
                disable_notification=True,
            )
        except Exception:
            pass

        ch_id_raw = await _get_setting("gift_channel_id") or getattr(cfg, "GIFT_CHANNEL_ID", None)
        if ch_id_raw:
            ch_caption = (
                f"👑 {gift['emoji']} <b>{gift['name']}</b>\n"
                f"{_mention(sender.id, sender.first_name)} → {_mention(target['user_id'], target['full_name'])} (<b>+{charm_gain} Charm ✨</b>)"
                f"{note_line}"
            )
            try:
                ch_target = int(ch_id_raw) if str(ch_id_raw).lstrip("-").isdigit() else str(ch_id_raw)
                if custom_media and custom_media["media_type"] == "animation":
                    await bot.send_animation(ch_target, animation=custom_media["file_id"], caption=ch_caption, parse_mode=ParseMode.HTML)
                else:
                    media_source = custom_media["file_id"] if custom_media else gift["default_img"]
                    await bot.send_photo(ch_target, photo=media_source, caption=ch_caption, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await bot.send_message(ch_target, text=ch_caption, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
    elif sent_msg:
        await _schedule_delete(message.chat.id, [sent_msg.message_id], delay=45)


# --- BUKA MINI APP MENU & JUKEBOX (/menu, /order, /eat) ---
@dp.message(Command("menu"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_menu_miniapp(message: types.Message):
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, message.from_user, message.message_thread_id)
    await react_msg(message.chat.id, message.message_id, "🥂")
    msg = await message.reply(
        "🥂 <i>Julian meletakkan tablet menu beludru di atas meja bar.</i>\n"
        "Silakan pilih minuman, racik koktail, hidangan, atau lagu jukebox:",
        parse_mode=ParseMode.HTML,
        reply_markup=miniapp_menu_kb(),
    )
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)


@dp.message(Command("order"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_order_drink(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, user, message.message_thread_id)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await react_msg(message.chat.id, message.message_id, "🍸")
        msg = await message.reply(
            "🍸 <i>Julian menyodorkan kartu menu ke hadapanmu.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(),
        )
        await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)
        return

    raw_arg = parts[1].strip()
    key = raw_arg.lower()

    if key in DRINKS_CATALOG:
        item_name, base_price, is_vip_item = DRINKS_CATALOG[key]
    else:
        item_name, base_price, is_vip_item = html.escape(raw_arg[:60]), 0, False

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else base_price
            coins = (row["coins"] or 0) if row else 0

            if coins < cost:
                return await message.reply(
                    f"Saldo VC tidak cukup untuk memesan <b>{item_name}</b> (butuh <b>{cost} VC</b>, saldo kamu: <b>{coins} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await _log_tx(conn, user.id, -cost, f"Pesan minuman: {item_name}")
            await _add_bar_quest(conn, user.id)

    await react_msg(message.chat.id, message.message_id, "🍸")
    send_kwargs = {"message_thread_id": message.message_thread_id} if message.message_thread_id else {}
    try:
        await bot.send_chat_action(message.chat.id, "typing", **send_kwargs)
    except Exception:
        pass

    prep_msg = await message.reply(
        f"🧊 <i>Julian menyiapkan gelas kristal dingin dan mengocok shaker untuk {_mention(user.id, user.first_name)}...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.5)
    try:
        await prep_msg.delete()
    except Exception:
        pass

    vip_tag = " 👑" if (is_vip_item or is_vip) else ""
    caption = (
        f"🍸 Julian menggeser segelas <b>{item_name}</b> di atas meja bar mahoni menuju {_mention(user.id, user.first_name)}{vip_tag}.\n\n"
        f"<i>\"Silakan dinikmati malam ini.\"</i>"
    )
    media_src, mtype = await _get_service_media("drink")
    try:
        if mtype == "photo":
            await bot.send_photo(message.chat.id, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        else:
            await bot.send_animation(message.chat.id, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
    except Exception:
        await bot.send_message(message.chat.id, caption, parse_mode=ParseMode.HTML, **send_kwargs)


@dp.message(Command("eat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_eat_food(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, user, message.message_thread_id)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await react_msg(message.chat.id, message.message_id, "🍽️")
        msg = await message.reply(
            "🍽️ <i>Julian membukakan daftar hidangan dapur malam ini.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(),
        )
        await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)
        return

    raw_arg = parts[1].strip()
    key = raw_arg.lower()

    if key in FOODS_CATALOG:
        item_name, base_price, is_vip_item = FOODS_CATALOG[key]
    else:
        item_name, base_price, is_vip_item = html.escape(raw_arg[:60]), 0, False

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else base_price
            coins = (row["coins"] or 0) if row else 0

            if coins < cost:
                return await message.reply(
                    f"Saldo VC tidak cukup untuk memesan <b>{item_name}</b> (butuh <b>{cost} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await _log_tx(conn, user.id, -cost, f"Pesan makanan: {item_name}")
            await _add_bar_quest(conn, user.id)

    await react_msg(message.chat.id, message.message_id, "🍽️")
    send_kwargs = {"message_thread_id": message.message_thread_id} if message.message_thread_id else {}
    try:
        await bot.send_chat_action(message.chat.id, "typing", **send_kwargs)
    except Exception:
        pass

    prep_msg = await message.reply(
        f"🔥 <i>Chef di dapur sedang menata hidangan hangat untuk {_mention(user.id, user.first_name)}...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.6)
    try:
        await prep_msg.delete()
    except Exception:
        pass

    vip_tag = " 👑" if (is_vip_item or is_vip) else ""
    caption = (
        f"🍽️ Hidangan hangat <b>{item_name}</b> baru saja keluar dari dapur dan disajikan ke meja {_mention(user.id, user.first_name)}{vip_tag}.\n\n"
        f"<i>\"Selamat menikmati santapan malam Anda.\"</i>"
    )
    media_src, mtype = await _get_service_media("food")
    try:
        if mtype == "photo":
            await bot.send_photo(message.chat.id, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        else:
            await bot.send_animation(message.chat.id, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
    except Exception:
        await bot.send_message(message.chat.id, caption, parse_mode=ParseMode.HTML, **send_kwargs)


# --- TRAKTIR TAMU (/treat @user [menu] atau reply pesan target) ---
@dp.message(Command("treat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_treat_guest(message: types.Message):
    sender = message.from_user
    parts = (message.text or "").split(maxsplit=2)
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        return await message.reply(
            "Format: <code>/treat @username [nama menu]</code> atau reply pesan temanmu dengan <code>/treat [nama menu]</code> (20 VC, +5 Charm).",
            parse_mode=ParseMode.HTML,
        )

    target_ident = None if has_reply else parts[1]
    if has_reply:
        menu_text = html.escape((message.text or "").split(maxsplit=1)[1][:60]) if len(parts) >= 2 else "Signature Velvet Cocktail"
    else:
        menu_text = html.escape(parts[2].strip()[:60]) if len(parts) >= 3 else "Signature Velvet Cocktail"

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, sender, message.message_thread_id)
            target = await _resolve_target_smart(conn, message, target_ident)
            if not target:
                return await message.reply(
                    "Tamu tujuan belum tercatat. Reply langsung salah satu chat dia dengan <code>/treat</code>.",
                    parse_mode=ParseMode.HTML,
                )
            if target["user_id"] == sender.id:
                return await message.reply("Kamu tidak bisa mentraktir dirimu sendiri.")

            s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if not s_row or (s_row["coins"] or 0) < 20:
                return await message.reply("Saldo kamu kurang dari <b>20 VC</b> untuk mentraktir tamu.", parse_mode=ParseMode.HTML)

            await conn.execute("UPDATE users SET coins = coins - 20 WHERE user_id = $1", sender.id)
            await conn.execute("UPDATE users SET charm_points = COALESCE(charm_points, 0) + 5 WHERE user_id = $1", target["user_id"])
            await _log_tx(conn, sender.id, -20, f"Traktir {target['full_name']} ({menu_text})")
            await _add_bar_quest(conn, sender.id)

    await react_msg(message.chat.id, message.message_id, "🥂")
    await message.reply(
        f"🥂 {_mention(sender.id, sender.first_name)} mentraktir <b>{menu_text}</b> untuk {_mention(target['user_id'], target['full_name'])} (<b>+5 Charm ✨</b>).",
        parse_mode=ParseMode.HTML,
    )


# --- RESERVASI VIP BOOTH (/booth) ---
@dp.message(Command("booth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_vip_booth(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply("Format: <code>/booth Nama Booth Eksklusif</code> (Khusus pemegang VIP Pass)", parse_mode=ParseMode.HTML)

    booth_name = parts[1].strip()[:32]
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, user, message.message_thread_id)
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user.id)
        is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
        if not is_vip:
            return await message.reply("🔒 Reservasi Booth hanya tersedia untuk tamu dengan <b>VIP Reserve Pass</b>.", parse_mode=ParseMode.HTML)
        await conn.execute("UPDATE users SET vip_booth_name = $1 WHERE user_id = $2", booth_name, user.id)

    await react_msg(message.chat.id, message.message_id, "👑")
    await message.reply(
        f"🍾 Julian memasang papan nama emas <b>{html.escape(booth_name)}</b> di area balkon VIP untuk {_mention(user.id, user.first_name)}.",
        parse_mode=ParseMode.HTML,
    )


# --- MINI-GAME: MYSTERY BOX (/mystery) ---
@dp.message(Command("mystery"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_mystery_box(message: types.Message):
    user = message.from_user
    cost = 40
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, user, message.message_thread_id)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            if not row or (row["coins"] or 0) < cost:
                return await message.reply("Butuh <b>40 VC</b> untuk membuka Velvet Mystery Box.", parse_mode=ParseMode.HTML)

            roll = random.randint(1, 100)
            if roll <= 35:
                prize_vc, prize_charm, label = 20, 2, "Gelang Beludru (+20 VC & +2 Charm)"
            elif roll <= 70:
                prize_vc, prize_charm, label = 45, 5, "Kunci Gudang Anggur (+45 VC & +5 Charm)"
            elif roll <= 92:
                prize_vc, prize_charm, label = 75, 10, "Koin Emas Antik (+75 VC & +10 Charm)"
            else:
                prize_vc, prize_charm, label = 150, 20, "JACKPOT! Mahkota Velvet (+150 VC & +20 Charm)"

            net = prize_vc - cost
            await conn.execute(
                "UPDATE users SET coins = coins + $1, charm_points = COALESCE(charm_points, 0) + $2 WHERE user_id = $3",
                net, prize_charm, user.id
            )
            await _log_tx(conn, user.id, net, f"Velvet Mystery Box ({label})")

    await react_msg(message.chat.id, message.message_id, "🎁")
    await message.reply(
        f"🎁 {_mention(user.id, user.first_name)} membuka kotak beludru hitam dan mendapatkan <b>{label}</b>!",
        parse_mode=ParseMode.HTML,
    )


# --- NATIVE TELEGRAM SLOT MACHINE (/slot [taruhan 10-100]) ---
@dp.message(Command("slot"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_slot_machine(message: types.Message):
    parts = (message.text or "").split()
    bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 15
    if not (10 <= bet <= 100):
        return await message.reply("Taruhan mesin slot harus antara <b>10 hingga 100 VC</b>. Contoh: <code>/slot 20</code>", parse_mode=ParseMode.HTML)

    user = message.from_user
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, user, message.message_thread_id)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            if not row or (row["coins"] or 0) < bet:
                return await message.reply(f"Saldo kamu kurang dari <b>{bet} VC</b> untuk memutar mesin slot.", parse_mode=ParseMode.HTML)
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, user.id)

    dice_msg = await message.reply_dice(emoji="🎰")
    val = dice_msg.dice.value
    await asyncio.sleep(2.2)

    if val == 64:
        payout = bet * 5
        outcome = f"🎉 <b>JACKPOT 777!</b> {_mention(user.id, user.first_name)} menang besar <b>+{payout} VC</b> (5x)!"
    elif val in (1, 22, 43):
        payout = bet * 3
        outcome = f"✨ <b>TRIPLE MATCH!</b> {_mention(user.id, user.first_name)} memenangkan <b>+{payout} VC</b> (3x)!"
    elif val in (2, 3, 4, 16, 17, 32, 48, 60, 61, 62, 63):
        payout = int(bet * 1.5)
        outcome = f"🥂 <b>DOUBLE PAIR!</b> {_mention(user.id, user.first_name)} mendapat <b>+{payout} VC</b>!"
    else:
        payout = 0
        outcome = f"🥀 Belum beruntung kali ini, {_mention(user.id, user.first_name)} (<b>-{bet} VC</b>)."

    async with db.pool.acquire() as conn:
        if payout > 0:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", payout, user.id)
            await _log_tx(conn, user.id, payout - bet, f"Menang Slot Machine (+{payout - bet} VC bersih)")
        else:
            await _log_tx(conn, user.id, -bet, "Taruhan Slot Machine")

    await dice_msg.reply(outcome, parse_mode=ParseMode.HTML)


# --- NATIVE TELEGRAM DART DUEL (/dart @username [taruhan] atau reply pesan target) ---
@dp.message(Command("dart"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dart_challenge(message: types.Message):
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        return await message.reply("Format: <code>/dart @username [taruhan 10-100]</code> atau reply pesan lawanmu.", parse_mode=ParseMode.HTML)

    if has_reply:
        bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        target_ident = None
    else:
        bet = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20
        target_ident = parts[1]

    if not (10 <= bet <= 100):
        return await message.reply("Taruhan dart harus antara <b>10 hingga 100 VC</b>.", parse_mode=ParseMode.HTML)

    challenger = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, challenger, message.message_thread_id)
        target = await _resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            return await message.reply(
                "Lawan dart tidak ditemukan. Reply langsung pesan lawanmu dengan <code>/dart 20</code>.",
                parse_mode=ParseMode.HTML,
            )

        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id) or 0
        t_coins = target["coins"] or 0
        if c_coins < bet or t_coins < bet:
            return await message.reply("Saldo salah satu pemain tidak mencukupi.")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        styled_btn(f"🎯 Lempar Dart ({bet} VC)", callback_data=f"playdart_{challenger.id}_{target['user_id']}_{bet}", style="success"),
        styled_btn("❌ Tolak", callback_data=f"canceldart_{target['user_id']}", style="danger"),
    ]])
    await message.reply(
        f"🎯 {_mention(challenger.id, challenger.first_name)} menantang {_mention(target['user_id'], target['full_name'])} duel dart (<b>{bet} VC</b>).",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("playdart_"))
async def cb_play_dart(call: types.CallbackQuery):
    _, c_str, t_str, bet_str = call.data.split("_")
    c_id, t_id, bet = int(c_str), int(t_str), int(bet_str)

    if call.from_user.id != t_id:
        return await call.answer("Hanya pemain yang ditantang yang bisa memulai lemparan!", show_alert=True)

    await call.answer("Melempar anak panah...")
    await call.message.edit_text("🎯 Pertandingan dart dimulai...", parse_mode=ParseMode.HTML)

    d1_msg = await call.message.answer_dice(emoji="🎯")
    await asyncio.sleep(1.5)
    d2_msg = await call.message.answer_dice(emoji="🎯")
    await asyncio.sleep(2.2)

    s1, s2 = d1_msg.dice.value, d2_msg.dice.value

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", c_id)
            t_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", t_id)

            if (c_user["coins"] or 0) < bet or (t_user["coins"] or 0) < bet:
                return await d2_msg.reply("Pertandingan dibatalkan karena saldo salah satu pemain berubah.")

            if s1 == s2:
                return await d2_msg.reply(
                    f"🎯 Seri! Kedua pemain mencetak skor <b>{s1}/6</b>. Taruhan <b>{bet} VC</b> dikembalikan.",
                    parse_mode=ParseMode.HTML,
                )

            winner = c_user if s1 > s2 else t_user
            loser = t_user if s1 > s2 else c_user

            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, winner["user_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, loser["user_id"])
            await _log_tx(conn, winner["user_id"], bet, f"Menang Dart vs {loser['full_name']}")
            await _log_tx(conn, loser["user_id"], -bet, f"Kalah Dart vs {winner['full_name']}")

    bullseye_note = " 🔥 <b>BULLSEYE!</b>" if max(s1, s2) == 6 else ""
    await d2_msg.reply(
        f"🎯 <b>Hasil Dart</b>{bullseye_note}\n"
        f"• {_mention(c_user['user_id'], c_user['full_name'])}: <b>{s1}/6</b>\n"
        f"• {_mention(t_user['user_id'], t_user['full_name'])}: <b>{s2}/6</b>\n"
        f"🏆 Pemenang: {_mention(winner['user_id'], winner['full_name'])} (<b>+{bet} VC</b>)",
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("canceldart_"))
async def cb_cancel_dart(call: types.CallbackQuery):
    t_id = int(call.data.replace("canceldart_", ""))
    if call.from_user.id != t_id:
        return await call.answer("Bukan tantangan untukmu!", show_alert=True)
    await call.answer("Ditolak.")
    await call.message.edit_text("❌ Tantangan dart ditolak.")


# --- DUEL DADU NATIVE TELEGRAM (/dice @username [taruhan] atau reply pesan target) ---
@dp.message(Command("dice"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dice_duel(message: types.Message):
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        return await message.reply("Format: <code>/dice @username [taruhan 10-100]</code> atau reply pesan lawanmu.", parse_mode=ParseMode.HTML)

    if has_reply:
        bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        target_ident = None
    else:
        bet = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20
        target_ident = parts[1]

    if not (10 <= bet <= 100):
        return await message.reply("Taruhan duel dadu harus antara <b>10 hingga 100 VC</b>.", parse_mode=ParseMode.HTML)

    challenger = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, challenger, message.message_thread_id)
        target = await _resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            return await message.reply(
                "Lawan duel tidak ditemukan. Reply langsung pesan lawanmu dengan <code>/dice 20</code>.",
                parse_mode=ParseMode.HTML,
            )

        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id) or 0
        t_coins = target["coins"] or 0
        if c_coins < bet or t_coins < bet:
            return await message.reply("Saldo VC salah satu pemain tidak mencukupi.")

        duel_id = await conn.fetchval("""
            INSERT INTO duel_challenges (challenger_id, target_id, bet_vc)
            VALUES ($1, $2, $3) RETURNING id
        """, challenger.id, target["user_id"], bet)

    await react_msg(message.chat.id, message.message_id, "🎲")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        styled_btn(f"🎲 Lempar Dadu ({bet} VC)", callback_data=f"accept_duel_{duel_id}", style="success"),
        styled_btn("❌ Tolak", callback_data=f"decline_duel_{duel_id}", style="danger"),
    ]])
    await message.reply(
        f"🎲 {_mention(challenger.id, challenger.first_name)} menantang {_mention(target['user_id'], target['full_name'])} duel dadu (<b>{bet} VC</b>).",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("accept_duel_"))
async def cb_accept_duel(call: types.CallbackQuery):
    duel_id = int(call.data.replace("accept_duel_", ""))
    async with db.pool.acquire() as conn:
        duel = await conn.fetchrow("SELECT * FROM duel_challenges WHERE id = $1", duel_id)
        if not duel:
            return await call.answer("Tantangan duel sudah selesai.", show_alert=True)
        if call.from_user.id != duel["target_id"]:
            return await call.answer("Bukan tantangan untukmu!", show_alert=True)
        await conn.execute("DELETE FROM duel_challenges WHERE id = $1", duel_id)

    await call.answer("Melempar dadu...")
    await call.message.edit_text("🎲 Duel dadu dimulai...", parse_mode=ParseMode.HTML)

    dice1 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(1.4)
    dice2 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(2.2)

    d1, d2 = dice1.dice.value, dice2.dice.value
    bet = duel["bet_vc"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", duel["challenger_id"])
            t_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", duel["target_id"])

            if (c_user["coins"] or 0) < bet or (t_user["coins"] or 0) < bet:
                return await dice2.reply("Duel dibatalkan karena saldo salah satu pemain tidak mencukupi.")

            if d1 == d2:
                return await dice2.reply(
                    f"🎲 Seri! Kedua pemain melempar angka <b>{d1}</b>. Taruhan <b>{bet} VC</b> dikembalikan.",
                    parse_mode=ParseMode.HTML,
                )

            winner = c_user if d1 > d2 else t_user
            loser = t_user if d1 > d2 else c_user

            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, winner["user_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, loser["user_id"])
            await _log_tx(conn, winner["user_id"], bet, f"Menang Duel Dadu vs {loser['full_name']}")
            await _log_tx(conn, loser["user_id"], -bet, f"Kalah Duel Dadu vs {winner['full_name']}")

    await dice2.reply(
        f"🎲 <b>Hasil Duel Dadu</b>\n"
        f"• {_mention(c_user['user_id'], c_user['full_name'])}: <b>{d1}</b>\n"
        f"• {_mention(t_user['user_id'], t_user['full_name'])}: <b>{d2}</b>\n"
        f"🏆 Pemenang: {_mention(winner['user_id'], winner['full_name'])} (<b>+{bet} VC</b>)",
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("decline_duel_"))
async def cb_decline_duel(call: types.CallbackQuery):
    duel_id = int(call.data.replace("decline_duel_", ""))
    async with db.pool.acquire() as conn:
        duel = await conn.fetchrow("SELECT target_id FROM duel_challenges WHERE id = $1", duel_id)
        if not duel:
            return await call.answer("Sudah selesai.", show_alert=True)
        if call.from_user.id != duel["target_id"]:
            return await call.answer("Bukan tantangan untukmu!", show_alert=True)
        await conn.execute("DELETE FROM duel_challenges WHERE id = $1", duel_id)
    await call.answer("Duel ditolak.")
    await call.message.edit_text("❌ Tantangan duel dadu ditolak.")


# --- STATISTIK TAMU (/bill, /topcharm) ---
@dp.message(Command("bill"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_check_bill(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, user, message.message_thread_id)
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )

    if not row:
        return await message.reply("Kirim 1 pesan di grup terlebih dahulu untuk membuka tab tamu.")

    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    status = f"👑 VIP (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "Reguler"
    booth = f"\n• VIP Booth: <b>{html.escape(row['vip_booth_name'])}</b>" if row["vip_booth_name"] else ""
    msg = await message.reply(
        f"🧾 <b>Tab {html.escape(user.first_name)}</b>\n"
        f"• Saldo: <b>{row['coins'] or 0} VC</b>\n"
        f"• Charm: <b>{row['charm_points'] or 0} ✨</b>\n"
        f"• Status: {status}{booth}",
        parse_mode=ParseMode.HTML,
    )
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=45)


@dp.message(Command("topcharm"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top_charm(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT full_name, charm_points FROM users ORDER BY COALESCE(charm_points, 0) DESC LIMIT 10")
    lines = [
        f"{idx}. {html.escape(r['full_name'])} — <b>{r['charm_points'] or 0} ✨</b>"
        for idx, r in enumerate(rows, start=1)
    ] or ["<i>Belum ada data.</i>"]
    msg = await message.reply(
        "✨ <b>Top 10 Most Charming Guests</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)


# --- SISTEM SHIFT KERJA ---
@dp.message(Command("apply"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_apply_shift(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in SHIFT_ROLES:
        return await message.reply(
            "💼 Pilih shift (20 menit — upah 50 VC): <code>/apply waiter</code>, <code>/apply bartender</code>, atau <code>/apply host</code>",
            parse_mode=ParseMode.HTML,
        )

    role_key = parts[1].lower()
    meta = SHIFT_ROLES[role_key]
    user = message.from_user
    today = datetime.utcnow().date()
    now = datetime.utcnow()

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, user, message.message_thread_id)
            await conn.execute("DELETE FROM active_shifts WHERE ends_at <= $1", now)
            existing = await conn.fetchrow("SELECT role_name FROM active_shifts WHERE user_id = $1", user.id)
            if existing:
                return await message.reply(f"Kamu sedang menjalani shift sebagai <b>{existing['role_name']}</b>.", parse_mode=ParseMode.HTML)

            active_count = await conn.fetchval("SELECT COUNT(*) FROM active_shifts WHERE role_name = $1", role_key) or 0
            if active_count >= meta["quota"]:
                return await message.reply(f"Kuota shift <b>{meta['title']}</b> sedang penuh ({meta['quota']}/{meta['quota']}).", parse_mode=ParseMode.HTML)

            daily_cnt = await conn.fetchval(
                "SELECT count FROM shift_daily_counts WHERE user_id = $1 AND shift_date = $2",
                user.id, today
            ) or 0
            if daily_cnt >= 3:
                return await message.reply("Kamu sudah mencapai batas maksimal <b>3x shift</b> hari ini.", parse_mode=ParseMode.HTML)

            ends_at = now + timedelta(minutes=20)
            await conn.execute("""
                INSERT INTO active_shifts (user_id, role_name, started_at, ends_at, service_count)
                VALUES ($1, $2, $3, $4, 0)
            """, user.id, role_key, now, ends_at)

    await react_msg(message.chat.id, message.message_id, "💼")
    await message.reply(
        f"💼 {_mention(user.id, user.first_name)} mulai bertugas sebagai <b>{meta['title']}</b> (20 menit).\n"
        f"Tugas: {meta['cmds']} (minimal 5x layanan lalu <code>/endshift</code>).",
        parse_mode=ParseMode.HTML,
    )


async def _record_shift_service(message: types.Message, allowed_role: str, action_text: str):
    user = message.from_user
    async with db.pool.acquire() as conn:
        shift = await conn.fetchrow("SELECT * FROM active_shifts WHERE user_id = $1", user.id)
        if not shift or shift["role_name"] != allowed_role:
            return await message.reply(f"Perintah ini khusus staf yang sedang shift <b>{allowed_role}</b>.", parse_mode=ParseMode.HTML)
        new_cnt = (shift["service_count"] or 0) + 1
        await conn.execute("UPDATE active_shifts SET service_count = $1 WHERE user_id = $2", new_cnt, user.id)

    await react_msg(message.chat.id, message.message_id, "✅")
    await message.reply(f"{action_text} <i>({new_cnt}/5)</i>", parse_mode=ParseMode.HTML)


@dp.message(Command("mix"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_shift_mix(message: types.Message):
    drink = html.escape((message.text or "").split(maxsplit=1)[1][:50]) if len((message.text or "").split()) > 1 else "Velvet Signature Cocktail"
    await _record_shift_service(message, "bartender", f"🍸 Bartender {_mention(message.from_user.id, message.from_user.first_name)} meracik <b>{drink}</b> dengan gerakan shaker presisi!")


@dp.message(Command("sober"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_shift_sober(message: types.Message):
    target = html.escape((message.text or "").split(maxsplit=1)[1][:40]) if len((message.text or "").split()) > 1 else "tamu lounge"
    await _record_shift_service(message, "bartender", f"🧊 Bartender {_mention(message.from_user.id, message.from_user.first_name)} menyajikan segelas air dingin & tonik segar untuk <b>{target}</b>.")


@dp.message(Command("welcome"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_shift_welcome(message: types.Message):
    target = html.escape((message.text or "").split(maxsplit=1)[1][:40]) if len((message.text or "").split()) > 1 else "tamu baru"
    await _record_shift_service(message, "waiter", f"🥂 Waiter {_mention(message.from_user.id, message.from_user.first_name)} menyambut hangat <b>{target}</b> dan mengantarnya ke meja terbaik.")


@dp.message(Command("dish"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_shift_dish(message: types.Message):
    dish = html.escape((message.text or "").split(maxsplit=1)[1][:50]) if len((message.text or "").split()) > 1 else "Chef's Platter"
    await _record_shift_service(message, "waiter", f"🍽️ Waiter {_mention(message.from_user.id, message.from_user.first_name)} mengantarkan hidangan <b>{dish}</b> ke meja tamu.")


@dp.message(Command("ambience"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_shift_ambience(message: types.Message):
    await _record_shift_service(message, "host", f"🕯️ Host {_mention(message.from_user.id, message.from_user.first_name)} meredupkan lampu kristal dan menyalakan lilin aromaterapi di seluruh ruangan.")


@dp.message(Command("toastall"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_shift_toastall(message: types.Message):
    await _record_shift_service(message, "host", f"🥂 Host {_mention(message.from_user.id, message.from_user.first_name)} mengangkat gelas tinggi-tinggi mengajak seluruh tamu bersulang untuk malam yang indah!")


@dp.message(Command("myshift"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_my_shift(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        shift = await conn.fetchrow("SELECT * FROM active_shifts WHERE user_id = $1", user.id)
    if not shift:
        return await message.reply("Kamu sedang tidak dalam jadwal shift aktif.")
    rem = max(0, int((shift["ends_at"] - datetime.utcnow()).total_seconds() // 60))
    await message.reply(
        f"📋 Shift <b>{shift['role_name'].upper()}</b> — Layanan: <b>{shift['service_count']}/5</b> (sisa ~{rem} menit)",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("endshift"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_end_shift(message: types.Message):
    user = message.from_user
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            shift = await conn.fetchrow("SELECT * FROM active_shifts WHERE user_id = $1 FOR UPDATE", user.id)
            if not shift:
                return await message.reply("Tidak ada shift aktif yang perlu diselesaikan.")
            await conn.execute("DELETE FROM active_shifts WHERE user_id = $1", user.id)

            if (shift["service_count"] or 0) < 5:
                return await message.reply(
                    f"Shift diakhiri lebih awal dengan layanan <b>{shift['service_count']}/5</b> (belum memenuhi syarat upah 50 VC).",
                    parse_mode=ParseMode.HTML,
                )

            await conn.execute("UPDATE users SET coins = coins + 50 WHERE user_id = $1", user.id)
            await conn.execute("""
                INSERT INTO shift_daily_counts (user_id, shift_date, count)
                VALUES ($1, $2, 1)
                ON CONFLICT (user_id, shift_date) DO UPDATE SET count = shift_daily_counts.count + 1;
            """, user.id, today)
            await _log_tx(conn, user.id, 50, f"Upah Shift {shift['role_name'].upper()}")

    await react_msg(message.chat.id, message.message_id, "💰")
    await message.reply(
        f"💰 Shift selesai! {_mention(user.id, user.first_name)} menerima upah <b>+50 Velvet Coins</b>.",
        parse_mode=ParseMode.HTML,
    )


# --- EARNING +1 VC/MENIT, AUTO-SYNC USERNAME & TOPIK AKTIF ---
@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def passive_rp_coin_earner(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return
    if message.text.startswith("/"):
        return

    uid = message.from_user.id
    now = datetime.utcnow()
    last = _last_chat_earn.get(uid)
    earn_delta = 1 if (len(message.text.split()) >= 3 and (not last or (now - last).total_seconds() >= 60)) else 0
    if earn_delta:
        _last_chat_earn[uid] = now

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name, coins, charm_points, last_thread_id)
            VALUES ($1, $2, $3, $4, 0, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                username = COALESCE(EXCLUDED.username, users.username),
                full_name = EXCLUDED.full_name,
                coins = users.coins + $6,
                last_thread_id = COALESCE($5, users.last_thread_id);
        """, uid, message.from_user.username, message.from_user.full_name, 50 + earn_delta, message.message_thread_id, earn_delta)


async def register_julian_commands():
    group_cmds = [
        BotCommand(command="menu", description="Buka Buku Menu & Jukebox Interaktif (Mini App)"),
        BotCommand(command="gift", description="Kirim hadiah mewah bergambar (+Charm & Auto-Pin)"),
        BotCommand(command="order", description="Pesan minuman (atau buka menu)"),
        BotCommand(command="eat", description="Pesan hidangan dapur (atau buka menu)"),
        BotCommand(command="treat", description="Traktir tamu lain (+5 Charm untuk penerima)"),
        BotCommand(command="booth", description="[VIP] Reservasi meja booth eksklusif"),
        BotCommand(command="slot", description="Putar mesin slot bar (10-100 VC)"),
        BotCommand(command="dart", description="Duel lempar dart 1v1 berhadiah VC"),
        BotCommand(command="dice", description="Duel dadu 1v1 berhadiah VC"),
        BotCommand(command="mystery", description="Buka Velvet Mystery Box (40 VC)"),
        BotCommand(command="bill", description="Cek saldo VC, Charm & status VIP"),
        BotCommand(command="topcharm", description="Lihat Top 10 Tamu Paling Memesona"),
        BotCommand(command="apply", description="Ambil shift kerja (waiter/bartender/host)"),
    ]
    await bot.set_my_commands(group_cmds, scope=BotCommandScopeAllGroupChats())


async def main():
    await db.init_db()
    await ensure_julian_schema()
    await register_julian_commands()
    await start_webapp_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
