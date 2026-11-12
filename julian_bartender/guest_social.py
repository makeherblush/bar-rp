import asyncio
import random
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import GROUP_ID
from julian_bartender.helpers import (
    hans_bot, DRINKS_MENU, FOODS_MENU,
    TREAT_COST_VC, TREAT_CHARM_BONUS, DICE_MIN_BET, DICE_MAX_BET,
    schedule_delete, reply_and_autodelete, is_staff_or_owner,
    get_user_booth_tag, log_wallet_tx, add_bar_quest_progress
)

router = Router()

# Penyimpanan tantangan dadu 1v1 sementara
active_dice_challenges = {}

# --- SAMBUTAN OTOMATIS SAAT TAMU BARU MASUK GRUP ---
@router.message(F.chat.id == GROUP_ID, F.new_chat_members)
async def on_guest_enter(message: types.Message):
    for member in message.new_chat_members:
        if member.is_bot:
            continue

        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, is_in_bar, last_active, warned_idle)
                VALUES ($1, $2, $3, TRUE, NOW(), FALSE)
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name,
                    is_in_bar = TRUE,
                    last_active = NOW(),
                    warned_idle = FALSE;
            """, member.id, member.username or "NoUsername", member.full_name)

        welcome_msg = await message.answer(
            "<i>Tirai beludru merah di pintu masuk tersibak perlahan. Bartender Julian mengangkat pandangan dari gelas kristal yang sedang ia lap, lalu tersenyum ramah.</i>\n\n"
            f"🥂 <b>\"Selamat malam, <a href='tg://user?id={member.id}'>{member.first_name}</a>. "
            "Selamat datang di <i>The Velvet Hour</i>.\"</b>\n\n"
            "• <code>/order</code> — Buku menu minuman (Contoh: <code>/order negroni</code>)\n"
            "• <code>/eat</code> — Buku menu makanan (Contoh: <code>/eat steak</code>)\n"
            "• <code>/treat @user menu</code> — Traktir tamu lain (+5 Charm)\n"
            "• <code>/reqsong Judul - Penyanyi</code> — Putar lagu di ruangan",
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(schedule_delete(welcome_msg, 120))

# --- CEK BILL & LAPAK ---
@router.message(Command("bill"), F.chat.id == GROUP_ID)
async def cmd_bill(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT coins, charm_points, gifts_sent_vc, is_vip, vip_until, vip_booth_name, total_active_mins, daily_shift_count, last_shift_date FROM users WHERE user_id = $1",
            user_id
        )
    if not row:
        return await reply_and_autodelete(message, "<i>Julian memeriksa buku catatan: Namamu belum terdaftar. Ketuk pintu utama di PC Hans terlebih dahulu.</i>", 60)

    today = datetime.utcnow().date()
    used_shifts = row["daily_shift_count"] if row["last_shift_date"] == today else 0
    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    status_txt = f"🍾 VIP Reserve (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "🥂 Regular Guest"
    booth_txt = f"\n• <b>Private Booth:</b> {row['vip_booth_name']}" if (is_vip and row["vip_booth_name"]) else ""

    text = (
        f"🧾 <b>BAR TAB & STATUS — {message.from_user.first_name}</b>\n\n"
        f"• <b>Status Meja:</b> {status_txt}{booth_txt}\n"
        f"• <b>Saldo Dompet:</b> {row['coins']} Velvet Coins (VC)\n"
        f"• <b>Charm Points:</b> {row['charm_points']} Poin\n"
        f"• <b>Total Gift Diberikan:</b> {row['gifts_sent_vc'] or 0} VC\n"
        f"• <b>Kuota Shift Hari Ini:</b> {used_shifts}/3 shift\n"
        f"• <b>Total Waktu Nongkrong:</b> {row['total_active_mins'] or 0} Menit"
    )
    await reply_and_autodelete(message, text, 90)

@router.message(Command("lapak"), F.chat.id == GROUP_ID)
async def cmd_lapak_group(message: types.Message):
    async with db.pool.acquire() as conn:
        shops = await conn.fetch("""
            SELECT s.id, s.shop_name, s.owner_username, COUNT(i.id) as active_items
            FROM partner_shops s
            LEFT JOIN shop_items i ON s.id = i.shop_id AND i.is_sold = FALSE
            GROUP BY s.id, s.shop_name, s.owner_username
            ORDER BY s.id ASC
        """)

    if not shops:
        return await reply_and_autodelete(message, "🏪 <i>Belum ada lapak partner yang buka di sudut lounge saat ini.</i>", 60)

    lines = [
        f"• <b>{s['shop_name']}</b>{f' (@{s[\"owner_username\"]})' if s['owner_username'] else ''} — <i>{s['active_items']} item tersedia</i>"
        for s in shops
    ]

    hans_me = await hans_bot.get_me()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Lihat Katalog & Beli di PC Hans", url=f"https://t.me/{hans_me.username}?start=lapak")]
    ])

    await reply_and_autodelete(
        message,
        "🏪 <b>POJOK LAPAK PARTNER — THE VELVET HOUR</b>\n\n"
        + "\n".join(lines) +
        "\n\n<i>Klik tombol di bawah untuk melihat koleksi dan bertransaksi menggunakan <b>Velvet Coins (VC)</b>:</i>",
        90,
        reply_markup=kb
    )

# --- PESAN MINUM & MAKAN (+ PROGRES MISI HARIAN) ---
@router.message(Command("order"), F.chat.id == GROUP_ID)
async def cmd_order(message: types.Message):
    item_raw = message.text.replace("/order", "").strip().lower()
    if not item_raw:
        menu_list = "\n".join([f"• <code>/order {k}</code> — {v[0]}" for k, v in DRINKS_MENU.items()])
        return await reply_and_autodelete(
            message,
            f"🍸 <b>DAFTAR MINUMAN BARTENDER JULIAN</b>\n\n{menu_list}\n\n"
            "💡 <i>Bisa juga pesan minuman bebas:\nContoh: <code>/order Iced Caramel Macchiato</code></i>",
            90
        )

    booth_tag = await get_user_booth_tag(message.from_user.id)
    matched = next((val for key, val in DRINKS_MENU.items() if key in item_raw), None)

    if matched:
        title, narrative = matched
        text = f"{title}\n\n{narrative}\n\n<i>— Disajikan untuk <b>{message.from_user.first_name}</b>{booth_tag}.</i>"
    else:
        custom_name = message.text.replace("/order", "").strip()
        text = (
            f"🍸 <b>Pesanan Khusus: {custom_name}</b>\n\n"
            f"<i>Julian mengangguk paham, meracik bahan pilihan di balik meja bar kayu ek, lalu menggeser gelas <b>{custom_name}</b> ke hadapanmu.</i>\n\n"
            f"<b>\"Racikan khusus sesuai permintaanmu. Selamat menikmati malam, {message.from_user.first_name}.\"</b>{booth_tag}"
        )

    await add_bar_quest_progress(message.from_user.id)
    await reply_and_autodelete(message, text, 120)

@router.message(Command("eat"), F.chat.id == GROUP_ID)
async def cmd_eat(message: types.Message):
    item_raw = message.text.replace("/eat", "").strip().lower()
    if not item_raw:
        menu_list = "\n".join([f"• <code>/eat {k}</code> — {v[0]}" for k, v in FOODS_MENU.items()])
        return await reply_and_autodelete(
            message,
            f"🍽️ <b>DAFTAR HIDANGAN DAPUR (WAITRESS CLARA)</b>\n\n{menu_list}\n\n"
            "💡 <i>Bisa juga pesan makanan bebas:\nContoh: <code>/eat Ramen Pedas Hangat</code></i>",
            90
        )

    booth_tag = await get_user_booth_tag(message.from_user.id)
    matched = next((val for key, val in FOODS_MENU.items() if key in item_raw), None)

    if matched:
        title, narrative = matched
        text = f"{title}\n\n{narrative}\n\n<i>— Diantarkan ke meja <b>{message.from_user.first_name}</b>{booth_tag}.</i>"
    else:
        custom_food = message.text.replace("/eat", "").strip()
        text = (
            f"🍽️ <b>Hidangan Khusus: {custom_food}</b>\n\n"
            f"<i>Waitress Clara keluar dari pintu dapur membawa nampan perak hangat, lalu meletakkan <b>{custom_food}</b> di mejamu dengan senyum ramah.</i>\n\n"
            f"<b>\"Pesanan dari dapur sudah siap. Silakan dinikmati, {message.from_user.first_name}.\"</b>{booth_tag}"
        )

    await add_bar_quest_progress(message.from_user.id)
    await reply_and_autodelete(message, text, 120)

# --- TRAKTIR TAMU LAIN (/treat) + MUTASI DOMPET & MISI HARIAN ---
@router.message(Command("treat"), F.chat.id == GROUP_ID)
async def cmd_treat(message: types.Message):
    sender = message.from_user
    raw = message.text.replace("/treat", "").strip()

    target_user_id = None
    target_display_name = None
    item_raw = ""

    if message.reply_to_message and not message.reply_to_message.from_user.is_bot:
        target_user_id = message.reply_to_message.from_user.id
        target_display_name = message.reply_to_message.from_user.first_name
        item_raw = raw
    elif raw.startswith("@"):
        parts = raw.split(" ", 1)
        uname = parts[0].lstrip("@").lower()
        item_raw = parts[1].strip() if len(parts) > 1 else ""
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE LOWER(username) = $1", uname)
            if row:
                target_user_id = row["user_id"]
                target_display_name = row["full_name"]

    if not target_user_id or not item_raw:
        return await reply_and_autodelete(
            message,
            f"🥂 <b>TRAKTIR TAMU LAIN ({TREAT_COST_VC} VC — +{TREAT_CHARM_BONUS} CHARM PENERIMA)</b>\n\n"
            "• <b>Cara 1:</b> <code>/treat @username [nama menu/bebas]</code>\n"
            "  Contoh: <code>/treat @clara negroni</code>\n"
            "• <b>Cara 2:</b> Balas (reply) pesan tamu lalu ketik <code>/treat [nama menu]</code>",
            90
        )

    if target_user_id == sender.id:
        return await reply_and_autodelete(message, "<i>Julian tersenyum tipis: Kamu tidak bisa mentraktir dirimu sendiri—gunakan <code>/order</code> atau <code>/eat</code>.</i>", 45)

    lower_item = item_raw.lower()
    if lower_item in DRINKS_MENU:
        item_display = DRINKS_MENU[lower_item][0]
    elif lower_item in FOODS_MENU:
        item_display = FOODS_MENU[lower_item][0]
    else:
        item_display = f"<b>{item_raw}</b>"

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if not coins or coins < TREAT_COST_VC:
                return await reply_and_autodelete(
                    message,
                    f"<i>Julian berbisik pelan: Saldo tidak cukup untuk mentraktir (butuh <b>{TREAT_COST_VC} VC</b>).</i>",
                    60
                )
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", TREAT_COST_VC, sender.id)
            await conn.execute("UPDATE users SET charm_points = charm_points + $1 WHERE user_id = $2", TREAT_CHARM_BONUS, target_user_id)
            await log_wallet_tx(conn, sender.id, -TREAT_COST_VC, f"Traktir {target_display_name} ({item_raw[:25]})")

    await add_bar_quest_progress(sender.id)
    booth_tag = await get_user_booth_tag(target_user_id)
    await reply_and_autodelete(
        message,
        f"🥂 <b>TRAKTIRAN MEJA BAR — THE VELVET HOUR</b>\n\n"
        f"<i>Waitress Clara membawa nampan perak berisi {item_display} ke meja <a href='tg://user?id={target_user_id}'>{target_display_name}</a>{booth_tag} dengan anggukan sopan.</i>\n\n"
        f"<b>\"Hidangan spesial ini ditraktir oleh {sender.first_name} untuk menemani malammu.\"</b>\n\n"
        f"✨ <i><b>{target_display_name}</b> menerima <b>+{TREAT_CHARM_BONUS} Charm Points</b>!</i>",
        120
    )

# --- RESERVASI PRIVATE VIP BOOTH (/booth) ---
@router.message(Command("booth"), F.chat.id == GROUP_ID)
async def cmd_booth(message: types.Message):
    user_id = message.from_user.id
    booth_name = message.text.replace("/booth", "").strip()

    async with db.pool.acquire() as conn:
        now = datetime.utcnow()
        if not booth_name:
            rows = await conn.fetch("""
                SELECT full_name, vip_booth_name FROM users
                WHERE is_vip = TRUE AND vip_until > $1 AND vip_booth_name IS NOT NULL AND vip_booth_name != ''
                ORDER BY last_active DESC LIMIT 15
            """, now)
            if not rows:
                return await reply_and_autodelete(
                    message,
                    "🍾 <b>PRIVATE VELVET BOOTH (KHUSUS VIP)</b>\n\n"
                    "<i>Belum ada tamu VIP yang memesan booth malam ini.</i>\n\n"
                    "💡 <b>Cara Reservasi (VIP):</b>\n"
                    "• Format: <code>/booth [Nama Booth / Suasana]</code>\n"
                    "• Contoh: <code>/booth Velvet Corner #1</code>",
                    75
                )
            lines = [f"• 🍾 <b>{r['vip_booth_name']}</b> — ditempati oleh <b>{r['full_name']}</b>" for r in rows]
            return await reply_and_autodelete(
                message,
                "🍾 <b>DAFTAR PRIVATE BOOTH TERISI MALAM INI</b>\n\n"
                + "\n".join(lines) +
                "\n\n💡 <i>Ganti nama booth milikmu: <code>/booth [Nama Booth Baru]</code></i>",
                90
            )

        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > now)
        if not is_vip and not await is_staff_or_owner(user_id):
            return await reply_and_autodelete(
                message,
                "🍾 <i>Maaf, reservasi <b>Private Velvet Booth</b> hanya tersedia untuk pemegang <b>VIP Pass</b> (aktifkan di PC Hans).</i>",
                60
            )

        if len(booth_name) > 40:
            return await reply_and_autodelete(message, "Nama booth maksimal 40 karakter. Contoh: <code>/booth Crimson Balcony</code>", 45)

        await conn.execute("UPDATE users SET vip_booth_name = $1 WHERE user_id = $2", booth_name, user_id)

    await reply_and_autodelete(
        message,
        f"🍾 <b>PRIVATE BOOTH DIRESERVASI!</b>\n\n"
        f"<i>Host menyibakkan tirai beludru emas dan menyalakan lilin aromaterapi di meja eksklusif <b>{booth_name}</b> untuk <b>{message.from_user.first_name}</b>.</i>",
        120
    )

# --- MINI-GAME DADU MEJA BAR 1V1 (/dice) + MUTASI DOMPET ---
@router.message(Command("dice"), F.chat.id == GROUP_ID)
async def cmd_dice(message: types.Message):
    challenger = message.from_user
    raw = message.text.replace("/dice", "").strip()
    parts = raw.split()

    if len(parts) < 2 or not parts[0].startswith("@") or not parts[1].isdigit():
        return await reply_and_autodelete(
            message,
            f"🎲 <b>VELVET DICE DUEL 1V1 ({DICE_MIN_BET}–{DICE_MAX_BET} VC)</b>\n\n"
            "• Format: <code>/dice @username [jumlah taruhan VC]</code>\n"
            "• Contoh: <code>/dice @alvaro 25</code>",
            75
        )

    target_uname = parts[0].lstrip("@").lower()
    bet = int(parts[1])

    if bet < DICE_MIN_BET or bet > DICE_MAX_BET:
        return await reply_and_autodelete(
            message,
            f"Taruhan dadu harus antara <b>{DICE_MIN_BET} VC</b> hingga <b>{DICE_MAX_BET} VC</b>.\nContoh: <code>/dice @{target_uname} 30</code>",
            45
        )

    async with db.pool.acquire() as conn:
        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id)
        if not c_coins or c_coins < bet:
            return await reply_and_autodelete(message, f"Saldo VC kamu tidak cukup untuk bertaruh <b>{bet} VC</b>.", 45)

        target_row = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE LOWER(username) = $1", target_uname)
        if not target_row:
            return await reply_and_autodelete(message, f"Tamu <b>@{target_uname}</b> belum terdaftar di buku bar.", 45)

        target_id = target_row["user_id"]
        target_name = target_row["full_name"]

        if target_id == challenger.id:
            return await reply_and_autodelete(message, "Kamu tidak bisa menantang dirimu sendiri.", 45)

        if (target_row["coins"] or 0) < bet:
            return await reply_and_autodelete(message, f"Saldo VC <b>{target_name}</b> tidak cukup untuk menerima taruhan <b>{bet} VC</b>.", 45)

    duel_id = f"{challenger.id}_{target_id}_{random.randint(1000, 9999)}"
    active_dice_challenges[duel_id] = {
        "challenger_id": challenger.id,
        "challenger_name": challenger.first_name,
        "target_id": target_id,
        "target_name": target_name,
        "bet": bet,
        "created_at": datetime.utcnow()
    }

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"🎲 Terima Tantangan ({bet} VC)", callback_data=f"dice_acc_{duel_id}"),
            InlineKeyboardButton(text="❌ Tolak", callback_data=f"dice_dec_{duel_id}")
        ]
    ])

    await reply_and_autodelete(
        message,
        f"🎲 <b>TANTANGAN DADU MEJA BAR!</b>\n\n"
        f"<b>{challenger.first_name}</b> menantang <a href='tg://user?id={target_id}'>{target_name}</a> "
        f"dengan taruhan <b>{bet} Velvet Coins</b>!\n\n"
        f"<i>Hanya <b>{target_name}</b> yang dapat menekan tombol di bawah (berlaku 2 menit):</i>",
        120,
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("dice_acc_"))
async def cb_dice_accept(call: types.CallbackQuery):
    duel_id = call.data.replace("dice_acc_", "")
    duel = active_dice_challenges.get(duel_id)
    if not duel:
        return await call.answer("Tantangan dadu sudah kedaluwarsa atau selesai.", show_alert=True)

    if call.from_user.id != duel["target_id"]:
        return await call.answer("Bukan tantangan untukmu!", show_alert=True)

    active_dice_challenges.pop(duel_id, None)
    await call.answer("Melempar dadu kristal...")

    bet = duel["bet"]
    c_id, c_name = duel["challenger_id"], duel["challenger_name"]
    t_id, t_name = duel["target_id"], duel["target_name"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", c_id)
            t_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", t_id)

            if (c_coins or 0) < bet or (t_coins or 0) < bet:
                return await call.message.edit_text(
                    "⚠️ <i>Duel dadu dibatalkan karena saldo salah satu pemain tidak lagi mencukupi.</i>",
                    parse_mode=ParseMode.HTML
                )

            c_d1, c_d2 = random.randint(1, 6), random.randint(1, 6)
            t_d1, t_d2 = random.randint(1, 6), random.randint(1, 6)
            c_tot = c_d1 + c_d2
            t_tot = t_d1 + t_d2

            if c_tot > t_tot:
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, c_id)
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, t_id)
                await log_wallet_tx(conn, c_id, bet, f"Menang Dice Duel vs {t_name}")
                await log_wallet_tx(conn, t_id, -bet, f"Kalah Dice Duel vs {c_name}")
                outcome = f"🏆 <b>{c_name} MENANG!</b> Memboyong <b>+{bet} VC</b> dari meja taruhan!"
            elif t_tot > c_tot:
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, t_id)
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, c_id)
                await log_wallet_tx(conn, t_id, bet, f"Menang Dice Duel vs {c_name}")
                await log_wallet_tx(conn, c_id, -bet, f"Kalah Dice Duel vs {t_name}")
                outcome = f"🏆 <b>{t_name} MENANG!</b> Memboyong <b>+{bet} VC</b> dari meja taruhan!"
            else:
                outcome = "🤝 <b>SERI (DRAW)!</b> Taruhan dikembalikan utuh ke masing-masing dompet."

    await call.message.edit_text(
        f"🎲 <b>HASIL VELVET DICE DUEL (TARUHAN {bet} VC)</b>\n\n"
        f"• <b>{c_name}:</b> [{c_d1}] + [{c_d2}] = <b>{c_tot}</b>\n"
        f"• <b>{t_name}:</b> [{t_d1}] + [{t_d2}] = <b>{t_tot}</b>\n\n"
        f"{outcome}",
        parse_mode=ParseMode.HTML
    )

@router.callback_query(F.data.startswith("dice_dec_"))
async def cb_dice_decline(call: types.CallbackQuery):
    duel_id = call.data.replace("dice_dec_", "")
    duel = active_dice_challenges.get(duel_id)
    if not duel:
        return await call.answer("Tantangan sudah tidak aktif.", show_alert=True)

    if call.from_user.id not in (duel["target_id"], duel["challenger_id"]):
        return await call.answer("Bukan tantangan untukmu!", show_alert=True)

    active_dice_challenges.pop(duel_id, None)
    await call.answer("Tantangan dibatalkan.")
    await call.message.edit_text(
        f"🎲 <i>Tantangan dadu antara <b>{duel['challenger_name']}</b> dan <b>{duel['target_name']}</b> dibatalkan.</i>",
        parse_mode=ParseMode.HTML
    )

# --- ROULETTE SOLO (/mystery) + MUTASI DOMPET ---
@router.message(Command("mystery"), F.chat.id == GROUP_ID)
async def cmd_mystery(message: types.Message):
    user_id = message.from_user.id
    cost = 40
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if not coins or coins < cost:
                return await reply_and_autodelete(message, f"<i>Julian menggeleng sopan: Saldo tidak cukup (butuh <b>{cost} VC</b> untuk memutar Roulette Meja Bar).</i>", 60)
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user_id)
            await log_wallet_tx(conn, user_id, -cost, "Putar Velvet Bar Roulette (/mystery)")

            outcomes = [
                ("golden", "✨ <b>GOLDEN ELIXIR (+85 VC)!</b>\n\n<i>Cairan berkilau keemasan dituangkan ke gelasmu. Kamu memenangkan hadiah utama meja bar!</i>"),
                ("truth", "🕯️ <b>VELVET TRUTH CARD!</b>\n\n<i>Julian menyodorkan kartu hitam: \"Jawab dengan jujur di chat—apa hal paling nekat yang pernah kamu lakukan diam-diam?\"</i>"),
                ("dare", "🎲 <b>VELVET DARE CARD!</b>\n\n<i>Julian tersenyum tipis: \"Tantangan malam ini—kirim pesan pujian RP ke salah satu tamu yang sedang aktif di ruangan!\"</i>"),
                ("water", "💧 <b>CHILLED MINERAL WATER!</b>\n\n<i>Zonk! Gelas yang muncul hanya berisi air putih dingin. Coba lagi keberuntunganmu nanti.</i>"),
            ]
            choice_key, result_text = random.choice(outcomes)
            if choice_key == "golden":
                await conn.execute("UPDATE users SET coins = coins + 85 WHERE user_id = $1", user_id)
                await log_wallet_tx(conn, user_id, 85, "Jackpot Golden Elixir Bar Roulette")

    await reply_and_autodelete(
        message,
        f"🎰 <b>VELVET BAR ROULETTE ({message.from_user.first_name})</b>\n\n{result_text}",
        120
    )

# --- SOSIAL & PRESENSI ---
@router.message(Command("toast"), F.chat.id == GROUP_ID)
async def cmd_toast(message: types.Message):
    target = message.text.replace("/toast", "").strip()
    if not target and message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
    if not target:
        return await reply_and_autodelete(
            message,
            "Sebutkan nama/username tamu atau balas pesannya.\nContoh: <code>/toast @username</code> atau <code>/toast Clara</code>",
            60
        )

    booth_tag = await get_user_booth_tag(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"🥂 <b>BERSULANG DI RUANG UTAMA!</b>\n\n"
        f"<i><b>{message.from_user.first_name}</b>{booth_tag} mengangkat gelas kristalnya tinggi-tinggi ke arah <b>{target}</b>. "
        f"Denting dua gelas beradu halus di tengah hangatnya lampu lounge.</i>",
        120
    )

@router.message(Command("guests"), F.chat.id == GROUP_ID)
async def cmd_guests(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT full_name, is_vip, vip_until, vip_booth_name FROM users WHERE is_in_bar = TRUE ORDER BY last_active DESC LIMIT 25"
        )
    if not rows:
        return await reply_and_autodelete(message, "<i>Ruang utama tampak lengang malam ini.</i>", 60)

    lines = []
    for r in rows:
        is_vip = bool(r["is_vip"] and r["vip_until"] and r["vip_until"] > datetime.utcnow())
        badge = "🍾" if is_vip else "🥂"
        b_info = f" <i>[{r['vip_booth_name']}]</i>" if (is_vip and r["vip_booth_name"]) else ""
        lines.append(f"{badge} {r['full_name']}{b_info}")

    await reply_and_autodelete(
        message,
        f"📋 <b>DAFTAR TAMU DI DALAM LOUNGE ({len(rows)})</b>\n\n" + "\n".join(lines),
        90
    )

@router.message(Command("topcharm"), F.chat.id == GROUP_ID)
async def cmd_topcharm(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT full_name, charm_points FROM users WHERE charm_points > 0 ORDER BY charm_points DESC LIMIT 10")
    if not rows:
        return await reply_and_autodelete(message, "<i>Belum ada tamu yang mengumpulkan Charm Points malam ini.</i>", 60)

    medals = ["🥇", "🥈", "🥉"] + ["✨"] * 7
    lines = [f"{medals[i]} <b>{r['full_name']}</b> — {r['charm_points']} Charm" for i, r in enumerate(rows)]
    await reply_and_autodelete(
        message,
        "🏆 <b>TOP CHARM LEADERBOARD — THE VELVET HOUR</b>\n\n" + "\n".join(lines),
        90
    )

@router.message(Command("checkin"), F.chat.id == GROUP_ID)
async def cmd_checkin(message: types.Message):
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_in_bar = TRUE, last_active = NOW(), warned_idle = FALSE WHERE user_id = $1",
            message.from_user.id
        )
    await reply_and_autodelete(
        message,
        f"<i>Waitress Clara mengangguk sopan ke arah meja <b>{message.from_user.first_name}</b>—waktu kunjunganmu telah diperbarui.</i>",
        60
    )

@router.message(Command("checkout"), F.chat.id == GROUP_ID)
async def cmd_checkout(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_in_bar = FALSE, vip_booth_name = NULL WHERE user_id = $1", user_id)

    await message.answer(
        f"<i><b>{message.from_user.first_name}</b> meletakkan serbet di atas meja dan beranjak menuju pintu keluar. "
        f"Bouncer Hans membukakan pintu mahoni dengan anggukan hormat.</i>\n\n"
        f"<b>\"Terima kasih telah berkunjung ke The Velvet Hour. Hati-hati di jalan.\"</b>",
        parse_mode=ParseMode.HTML
    )
    if not await is_staff_or_owner(user_id):
        try:
            await hans_bot.ban_chat_member(GROUP_ID, user_id)
            await hans_bot.unban_chat_member(GROUP_ID, user_id)
        except Exception:
            pass
