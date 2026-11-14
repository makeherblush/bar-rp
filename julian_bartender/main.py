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

logging.basicConfig(level=logging.INFO)

bot = Bot(token=cfg.TOKEN_JULIAN)
dp = Dispatcher(storage=MemoryStorage())

OWNER_ID = cfg.OWNER_ID
GROUP_ID = cfg.GROUP_ID
MINIAPP_MENU_URL = getattr(cfg, "MINIAPP_MENU_URL", "https://t.me/JulianVanceVH_bot/menu")

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


async def ensure_julian_schema():
    async with db.pool.acquire() as conn:
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


async def _sync_tg_user(conn, tg_user: types.User):
    """Pastikan pengirim selalu terdaftar & username-nya sinkron di tabel users."""
    if not tg_user or tg_user.is_bot:
        return
    await conn.execute("""
        INSERT INTO users (user_id, username, full_name, coins, charm_points, joined_at)
        VALUES ($1, $2, $3, 50, 0, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            full_name = EXCLUDED.full_name;
    """, tg_user.id, tg_user.username, tg_user.full_name)


async def _resolve_target_smart(conn, message: types.Message, ident: str | None = None):
    """Cari target lewat: (1) Reply pesan target, (2) Text mention entity, (3) @username atau ID di DB."""
    if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        ru = message.reply_to_message.from_user
        await _sync_tg_user(conn, ru)
        return await conn.fetchrow("SELECT user_id, username, full_name, coins, charm_points FROM users WHERE user_id = $1", ru.id)

    if message.entities:
        for ent in message.entities:
            if ent.type == "text_mention" and ent.user and not ent.user.is_bot:
                await _sync_tg_user(conn, ent.user)
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


# --- BUKA MINI APP MENU & JUKEBOX (/menu, /order, /eat) ---
@dp.message(Command("menu"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_menu_miniapp(message: types.Message):
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, message.from_user)
    await react_msg(message.chat.id, message.message_id, "🥂")
    await message.reply(
        "🥂 <i>Julian meletakkan tablet menu beludru di atas meja bar.</i>\n"
        "Pilih minuman, racik koktail sendiri, hidangan dapur, atau request lagu jukebox melalui tombol di bawah:",
        parse_mode=ParseMode.HTML,
        reply_markup=miniapp_menu_kb(),
    )


@dp.message(Command("order"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_order_drink(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, user)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await react_msg(message.chat.id, message.message_id, "🍸")
        return await message.reply(
            "🍸 <i>Julian menyodorkan kartu menu digital ke hadapanmu.</i>\n"
            "Silakan pilih minuman atau racik koktail sendiri lewat Mini App di bawah ini:",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(),
        )

    raw_arg = parts[1].strip()
    key = raw_arg.lower()

    if key in DRINKS_CATALOG:
        item_name, base_price, is_vip_item = DRINKS_CATALOG[key]
    else:
        item_name, base_price, is_vip_item = html.escape(raw_arg[:60]), 0, False

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else base_price
            coins = row["coins"] or 0

            if coins < cost:
                return await message.reply(
                    f"💸 Saldo VC tidak cukup untuk memesan <b>{item_name}</b> (butuh <b>{cost} VC</b>, saldo kamu: <b>{coins} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await _log_tx(conn, user.id, -cost, f"Pesan minuman: {item_name}")
            await _add_bar_quest(conn, user.id)

    await react_msg(message.chat.id, message.message_id, "🍸")
    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    vip_note = " 👑 <i>(VIP Reserve)</i>" if is_vip_item else ""
    step_msg = await message.reply(
        f"🧊 <i>Julian menyiapkan gelas kristal dingin untuk {_mention(user.id, user.first_name)}...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.2)
    await step_msg.edit_text(
        "🍸 <i>Julian mengocok shaker dengan presisi dan menuangkannya perlahan...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.2)
    await step_msg.edit_text(
        f"🍸 <b>JULIAN — BARTENDER SERVICE</b>\n\n"
        f"<i>Julian menggeser gelas di atas meja bar mahoni menuju {_mention(user.id, user.first_name)}{vip_note}.</i>\n"
        f"• <b>Pesanan:</b> <b>{item_name}</b>\n"
        f"<i>\"Silakan dinikmati malam ini.\"</i>",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("eat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_eat_food(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await _sync_tg_user(conn, user)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await react_msg(message.chat.id, message.message_id, "🍽️")
        return await message.reply(
            "🍽️ <i>Julian membukakan daftar hidangan dapur malam ini.</i>\n"
            "Silakan pilih menu makanan langsung lewat Mini App di bawah ini:",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(),
        )

    raw_arg = parts[1].strip()
    key = raw_arg.lower()

    if key in FOODS_CATALOG:
        item_name, base_price, is_vip_item = FOODS_CATALOG[key]
    else:
        item_name, base_price, is_vip_item = html.escape(raw_arg[:60]), 0, False

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else base_price
            coins = row["coins"] or 0

            if coins < cost:
                return await message.reply(
                    f"💸 Saldo VC tidak cukup untuk memesan <b>{item_name}</b> (butuh <b>{cost} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await _log_tx(conn, user.id, -cost, f"Pesan makanan: {item_name}")
            await _add_bar_quest(conn, user.id)

    await react_msg(message.chat.id, message.message_id, "🍽️")
    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    vip_note = " 👑 <i>(VIP Gastronomy)</i>" if is_vip_item else ""
    step_msg = await message.reply(
        f"🔥 <i>Pesanan dapur untuk {_mention(user.id, user.first_name)} sedang disiapkan...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.5)
    await step_msg.edit_text(
        f"🍽️ <b>JULIAN — MIDNIGHT KITCHEN</b>\n\n"
        f"<i>Hidangan hangat disajikan ke meja {_mention(user.id, user.first_name)}{vip_note}.</i>\n"
        f"• <b>Hidangan:</b> <b>{item_name}</b>",
        parse_mode=ParseMode.HTML,
    )


# --- TRAKTIR TAMU (/treat @user [menu] atau reply pesan target) ---
@dp.message(Command("treat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_treat_guest(message: types.Message):
    sender = message.from_user
    parts = (message.text or "").split(maxsplit=2)
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        return await message.reply(
            "Format: <code>/treat @username [nama menu]</code> atau <b>reply</b> pesan temanmu dengan <code>/treat [nama menu]</code> (Biaya: 20 VC, +5 Charm).",
            parse_mode=ParseMode.HTML,
        )

    target_ident = None if has_reply else parts[1]
    if has_reply:
        menu_text = html.escape((message.text or "").split(maxsplit=1)[1][:60]) if len(parts) >= 2 else "Signature Velvet Cocktail"
    else:
        menu_text = html.escape(parts[2].strip()[:60]) if len(parts) >= 3 else "Signature Velvet Cocktail"

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, sender)
            target = await _resolve_target_smart(conn, message, target_ident)
            if not target:
                return await message.reply(
                    "⚠️ Tamu tujuan belum tercatat di database bar.\n"
                    "<i>Tips: Reply langsung salah satu chat dia dengan</i> <code>/treat</code><i>, atau minta dia kirim 1 chat di grup ini terlebih dahulu.</i>",
                    parse_mode=ParseMode.HTML,
                )
            if target["user_id"] == sender.id:
                return await message.reply("Kamu tidak bisa mentraktir dirimu sendiri.")

            s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if not s_row or (s_row["coins"] or 0) < 20:
                return await message.reply("💸 Saldo kamu kurang dari <b>20 VC</b> untuk mentraktir tamu.", parse_mode=ParseMode.HTML)

            await conn.execute("UPDATE users SET coins = coins - 20 WHERE user_id = $1", sender.id)
            await conn.execute("UPDATE users SET charm_points = COALESCE(charm_points, 0) + 5 WHERE user_id = $1", target["user_id"])
            await _log_tx(conn, sender.id, -20, f"Traktir {target['full_name']} ({menu_text})")
            await _add_bar_quest(conn, sender.id)

    await react_msg(message.chat.id, message.message_id, "🥂")
    await message.reply(
        f"🥂 <b>COMPLIMENTARY TREAT</b>\n\n"
        f"{_mention(sender.id, sender.first_name)} mengirimkan <b>{menu_text}</b> untuk {_mention(target['user_id'], target['full_name'])}!\n"
        f"✨ <i>Pesona {_mention(target['user_id'], target['full_name'])} bertambah <b>+5 Charm</b>.</i>",
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
        await _sync_tg_user(conn, user)
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user.id)
        is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
        if not is_vip:
            return await message.reply("🔒 Reservasi Booth hanya tersedia untuk tamu dengan <b>VIP Reserve Pass</b>.", parse_mode=ParseMode.HTML)
        await conn.execute("UPDATE users SET vip_booth_name = $1 WHERE user_id = $2", booth_name, user.id)

    await react_msg(message.chat.id, message.message_id, "👑")
    await message.reply(
        f"🍾 <b>VIP BOOTH RESERVED</b>\n\n"
        f"<i>Julian memasang papan nama emas di area balkon eksklusif untuk {_mention(user.id, user.first_name)}:</i>\n"
        f"• <b>Nama Booth:</b> <b>{html.escape(booth_name)}</b>",
        parse_mode=ParseMode.HTML,
    )


# --- MINI-GAME: MYSTERY BOX (/mystery) ---
@dp.message(Command("mystery"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_mystery_box(message: types.Message):
    user = message.from_user
    cost = 40
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, user)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            if not row or (row["coins"] or 0) < cost:
                return await message.reply("💸 Butuh <b>40 VC</b> untuk membuka Velvet Mystery Box.", parse_mode=ParseMode.HTML)

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
        f"🎁 <b>VELVET MYSTERY BOX</b>\n\n"
        f"{_mention(user.id, user.first_name)} membuka kotak beludru hitam seharga <b>40 VC</b>...\n"
        f"✨ <b>Isi Kotak:</b> <b>{label}</b>!",
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
            await _sync_tg_user(conn, user)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            if not row or (row["coins"] or 0) < bet:
                return await message.reply(f"💸 Saldo kamu kurang dari <b>{bet} VC</b> untuk memutar mesin slot.", parse_mode=ParseMode.HTML)
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

    await dice_msg.reply(f"🎰 <b>VELVET SLOT MACHINE</b>\n\n{outcome}", parse_mode=ParseMode.HTML)


# --- NATIVE TELEGRAM DART DUEL (/dart @username [taruhan] atau reply pesan target) ---
@dp.message(Command("dart"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dart_challenge(message: types.Message):
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        return await message.reply("Format: <code>/dart @username [taruhan 10-100]</code> atau <b>reply</b> pesan lawanmu.", parse_mode=ParseMode.HTML)

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
        await _sync_tg_user(conn, challenger)
        target = await _resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            return await message.reply(
                "⚠️ Lawan dart tidak ditemukan.\n"
                "<i>Tips: Reply langsung pesan lawanmu dengan</i> <code>/dart 20</code> <i>agar otomatis terdeteksi!</i>",
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
        f"🎯 <b>TANTANGAN DART LOUNGE</b>\n\n"
        f"{_mention(challenger.id, challenger.first_name)} menantang {_mention(target['user_id'], target['full_name'])}!\n"
        f"• <b>Taruhan:</b> <b>{bet} VC</b> (Skor 6 = Bullseye 🎯)",
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
    await call.message.edit_text("🎯 <b>Pertandingan Dart Dimulai!</b> Kedua pemain bersiap melempar ke papan target...", parse_mode=ParseMode.HTML)

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
                return await d2_msg.reply("⚠️ Pertandingan dibatalkan karena saldo salah satu pemain berubah.")

            if s1 == s2:
                return await d2_msg.reply(
                    f"🎯 <b>SERI!</b> Kedua pemain mencetak skor <b>{s1}/6</b>. Taruhan <b>{bet} VC</b> dikembalikan utuh.",
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
        f"🎯 <b>HASIL PERTANDINGAN DART</b>{bullseye_note}\n\n"
        f"• {_mention(c_user['user_id'], c_user['full_name'])}: <b>{s1}/6</b>\n"
        f"• {_mention(t_user['user_id'], t_user['full_name'])}: <b>{s2}/6</b>\n\n"
        f"🏆 <b>Pemenang:</b> {_mention(winner['user_id'], winner['full_name'])} meraih <b>+{bet} VC</b>!",
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
        return await message.reply("Format: <code>/dice @username [taruhan 10-100]</code> atau <b>reply</b> pesan lawanmu.", parse_mode=ParseMode.HTML)

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
        await _sync_tg_user(conn, challenger)
        target = await _resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            return await message.reply(
                "⚠️ Lawan duel tidak ditemukan.\n"
                "<i>Tips: Reply langsung pesan lawanmu dengan</i> <code>/dice 20</code> <i>agar otomatis terdeteksi!</i>",
                parse_mode=ParseMode.HTML,
            )

        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id) or 0
        t_coins = target["coins"] or 0
        if c_coins < bet or t_coins < bet:
            return await message.reply("Saldo VC salah satu pemain tidak mencukupi untuk taruhan tersebut.")

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
        f"🎲 <b>TANTANGAN DUEL DADU MEJA BAR</b>\n\n"
        f"{_mention(challenger.id, challenger.first_name)} menantang {_mention(target['user_id'], target['full_name'])}!\n"
        f"• <b>Taruhan:</b> <b>{bet} VC</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("accept_duel_"))
async def cb_accept_duel(call: types.CallbackQuery):
    duel_id = int(call.data.replace("accept_duel_", ""))
    async with db.pool.acquire() as conn:
        duel = await conn.fetchrow("SELECT * FROM duel_challenges WHERE id = $1", duel_id)
        if not duel:
            return await call.answer("Tantangan duel sudah kedaluwarsa atau selesai.", show_alert=True)
        if call.from_user.id != duel["target_id"]:
            return await call.answer("Bukan tantangan untukmu!", show_alert=True)
        await conn.execute("DELETE FROM duel_challenges WHERE id = $1", duel_id)

    await call.answer("Melempar dadu...")
    await call.message.edit_text("🎲 <b>Duel Dadu Dimulai!</b> Julian mengocok dua dadu kristal di atas meja...", parse_mode=ParseMode.HTML)

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
                return await dice2.reply("⚠️ Duel dibatalkan karena saldo salah satu pemain tidak mencukupi.")

            if d1 == d2:
                return await dice2.reply(
                    f"🎲 <b>SERI!</b> Kedua pemain melempar angka <b>{d1}</b>. Taruhan <b>{bet} VC</b> dikembalikan utuh.",
                    parse_mode=ParseMode.HTML,
                )

            winner = c_user if d1 > d2 else t_user
            loser = t_user if d1 > d2 else c_user

            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, winner["user_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, loser["user_id"])
            await _log_tx(conn, winner["user_id"], bet, f"Menang Duel Dadu vs {loser['full_name']}")
            await _log_tx(conn, loser["user_id"], -bet, f"Kalah Duel Dadu vs {winner['full_name']}")

    await dice2.reply(
        f"🎲 <b>HASIL DUEL DADU MEJA BAR</b>\n\n"
        f"• {_mention(c_user['user_id'], c_user['full_name'])}: <b>{d1}</b>\n"
        f"• {_mention(t_user['user_id'], t_user['full_name'])}: <b>{d2}</b>\n\n"
        f"🏆 <b>Pemenang:</b> {_mention(winner['user_id'], winner['full_name'])} membawa pulang <b>+{bet} VC</b>!",
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
        await _sync_tg_user(conn, user)
        row = await conn.fetchrow("SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1", user.id)

    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    status = f"👑 VIP Reserve (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "🥂 Reguler Guest"
    booth = f"\n• <b>VIP Booth:</b> {html.escape(row['vip_booth_name'])}" if row["vip_booth_name"] else ""
    await message.reply(
        f"🧾 <b>CATATAN TAB — {html.escape(user.first_name)}</b>\n\n"
        f"• <b>Saldo Dompet:</b> <b>{row['coins'] or 0} VC</b>\n"
        f"• <b>Charm Points:</b> <b>{row['charm_points'] or 0} ✨</b>\n"
        f"• <b>Status:</b> {status}{booth}",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("topcharm"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top_charm(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT full_name, charm_points FROM users ORDER BY COALESCE(charm_points, 0) DESC LIMIT 10")
    lines = [
        f"{idx}. <b>{html.escape(r['full_name'])}</b> — <b>{r['charm_points'] or 0} ✨</b>"
        for idx, r in enumerate(rows, start=1)
    ] or ["<i>Belum ada data.</i>"]
    await message.reply(
        "✨ <b>TOP 10 MOST CHARMING GUESTS — THE VELVET HOUR</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# --- SISTEM SHIFT KERJA ---
@dp.message(Command("apply"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_apply_shift(message: types.Message):
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in SHIFT_ROLES:
        return await message.reply(
            "💼 <b>LOWONGAN SHIFT BAR (20 Menit — Upah 50 VC)</b>\n"
            "Pilih posisi: <code>/apply waiter</code>, <code>/apply bartender</code>, atau <code>/apply host</code>",
            parse_mode=ParseMode.HTML,
        )

    role_key = parts[1].lower()
    meta = SHIFT_ROLES[role_key]
    user = message.from_user
    today = datetime.utcnow().date()
    now = datetime.utcnow()

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _sync_tg_user(conn, user)
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
        f"💼 <b>SHIFT DIMULAI — {meta['title'].upper()}</b>\n\n"
        f"{_mention(user.id, user.first_name)} resmi bertugas selama <b>20 menit</b>!\n"
        f"• <b>Tugas Layanan:</b> {meta['cmds']}\n"
        f"• <b>Syarat Upah (50 VC):</b> Selesaikan minimal <b>5x layanan</b> lalu ketik <code>/endshift</code>.",
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
    await message.reply(f"{action_text}\n<i>(Progres Layanan Shift: <b>{new_cnt}/5</b>)</i>", parse_mode=ParseMode.HTML)


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
        f"📋 <b>STATUS SHIFT — {html.escape(user.first_name)}</b>\n"
        f"• <b>Posisi:</b> {shift['role_name'].upper()}\n"
        f"• <b>Layanan Selesai:</b> <b>{shift['service_count']}/5</b>\n"
        f"• <b>Sisa Waktu:</b> ~{rem} menit",
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
                    f"⚠️ Shift diakhiri lebih awal dengan layanan <b>{shift['service_count']}/5</b> (belum memenuhi syarat upah 50 VC).",
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
        f"💰 <b>SHIFT SELESAI — UPAH CAIR!</b>\n\n"
        f"Terima kasih atas kerja kerasmu, {_mention(user.id, user.first_name)}!\n"
        f"• <b>Upah Diterima:</b> <b>+50 Velvet Coins</b>",
        parse_mode=ParseMode.HTML,
    )


# --- EARNING +1 VC/MENIT & AUTO-SYNC USERNAME UNTUK CHAT RP AKTIF DI GRUP ---
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
            INSERT INTO users (user_id, username, full_name, coins, charm_points, joined_at)
            VALUES ($1, $2, $3, $4, 0, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                username = COALESCE(EXCLUDED.username, users.username),
                full_name = EXCLUDED.full_name,
                coins = users.coins + $5;
        """, uid, message.from_user.username, message.from_user.full_name, 50 + earn_delta, earn_delta)


async def register_julian_commands():
    group_cmds = [
        BotCommand(command="menu", description="Buka Buku Menu & Jukebox Interaktif (Mini App)"),
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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
