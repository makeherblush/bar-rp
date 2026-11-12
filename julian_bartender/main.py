import asyncio
import random
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand, BotCommandScopeAllGroupChats
)
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import (
    TOKEN_JULIAN, TOKEN_HANS, OWNER_ID, GROUP_ID,
    REQUIRED_CN_SYMBOL, VIP_COST_24H
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN_JULIAN)
hans_bot = Bot(token=TOKEN_HANS)  # Untuk aksi Bouncer (kick/warn)
dp = Dispatcher()

# --- KATALOG MENU BAR & DAPUR (NARASI ROLEPLAY) ---
DRINKS_MENU = {
    "espresso": (
        "☕ <b>Velvet Double Espresso</b>",
        "<i>Julian menekan tuas mesin espresso kuningan hingga cairan pekat berwarna karamel menetes perlahan ke cangkir porselen hangat.</i>\n"
        "<b>\"Espresso ganda tanpa gula—pas untuk menjaga pikiran tetap tajam malam ini.\"</b>"
    ),
    "negroni": (
        "🍸 <b>Midnight Smoked Negroni</b>",
        "<i>Julian mengaduk gin, campari, dan vermouth merah di dalam mixing glass kristal berisi es batu besar, lalu mengasapinya dengan kayu ceri.</i>\n"
        "<b>\"Sedikit pahit di awal, hangat di akhir. Nikmati perlahan.\"</b>"
    ),
    "whisky": (
        "🥃 <b>Highland Single Malt (On The Rocks)</b>",
        "<i>Suara denting bola es kristal beradu dengan gelas lowball berat saat Julian menuangkan cairan keemasan beraroma kayu ek.</i>\n"
        "<b>\"Pilihan klasik bagi mereka yang datang membawa banyak cerita.\"</b>"
    ),
    "mocktail": (
        "🍹 <b>Crimson Velvet Fizz (Non-Alkohol)</b>",
        "<i>Julian mengocok sari delima, perasan jeruk darah, dan sirup vanila dengan soda dingin, lalu menghiasinya dengan tangkai rosemary segar.</i>\n"
        "<b>\"Segar, ringan, dan tetap berkelas tanpa perlu pusing.\"</b>"
    ),
    "water": (
        "💧 <b>Chilled Sparkling Mineral Water</b>",
        "<i>Julian menuangkan air mineral berkarbonasi dingin ke gelas tinggi dengan irisan lemon tipis di bibir gelas.</i>\n"
        "<b>\"Jeda yang tepat untuk menetralkan suasana malam.\"</b>"
    ),
}

FOODS_MENU = {
    "fries": (
        "🍟 <b>Black Truffle Parmesan Fries</b>",
        "<i>Waitress Clara meletakkan keranjang tembaga berisi kentang goreng renyah beraroma minyak truffle dan taburan keju parmesan tua di mejamu.</i>\n"
        "<b>\"Hati-hati masih panas—ini menu favorit tamu di sudut lounge.\"</b>"
    ),
    "steak": (
        "🥩 <b>Pan-Seared Wagyu Cube Bites</b>",
        "<i>Clara menyajikan piring batu hangat berisi potongan daging wagyu empuk dengan saus lada hitam dan bawang putih panggang.</i>\n"
        "<b>\"Silakan dinikmati selagi hangat agar teksturnya tetap lumer.\"</b>"
    ),
    "pasta": (
        "🍝 <b>Creamy Smoked Carbonara</b>",
        "<i>Aroma lada hitam tumbuk dan kuning telur keemasan langsung tercium saat Clara meletakkan piring pasta di hadapanmu.</i>\n"
        "<b>\"Selamat menikmati makan malammu di The Velvet Hour.\"</b>"
    ),
    "cake": (
        "🍰 <b>Dark Chocolate Velvet Tart</b>",
        "<i>Clara menggeser piring kecil berisi tart cokelat hitam pekat dengan taburan bubuk emas tipis dan buah beri segar.</i>\n"
        "<b>\"Sedikit rasa manis untuk menemani alunan musik malam ini.\"</b>"
    ),
}

# --- HELPER AUTO-DELETE PESAN LAYANAN (2 MENIT) ---
async def schedule_delete(msg: types.Message, delay: int = 120):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

async def reply_and_autodelete(message: types.Message, text: str, delay: int = 120):
    sent = await message.reply(text, parse_mode=ParseMode.HTML)
    asyncio.create_task(schedule_delete(sent, delay))
    return sent

# --- HELPER DATABASE & STATUS ---
async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def get_active_shift(user_id: int):
    async with db.pool.acquire() as conn:
        return await conn.fetchrow("SELECT role, started_at, actions_count FROM active_shifts WHERE user_id = $1", user_id)

async def add_shift_action(user_id: int):
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE active_shifts SET actions_count = actions_count + 1 WHERE user_id = $1", user_id)

# --- SAMBUTAN OTOMATIS SAAT TAMU BARU MASUK GRUP ---
@dp.message(F.chat.id == GROUP_ID, F.new_chat_members)
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
            "Selamat datang di <i>The Velvet Hour</i>. Silakan pilih meja yang nyaman—ketik <code>/order</code> untuk memesan minuman, "
            "<code>/eat</code> untuk hidangan dapur, atau <code>/reqsong</code> untuk memutar lagu di ruangan.\"</b>",
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(schedule_delete(welcome_msg, 120))

# --- COMMAND TAMU DI RUANG UTAMA ---
@dp.message(Command("bill"), F.chat.id == GROUP_ID)
async def cmd_bill(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, total_active_mins FROM users WHERE user_id = $1",
            user_id
        )
    if not row:
        return await reply_and_autodelete(message, "<i>Julian memeriksa buku catatan: Namamu belum terdaftar. Ketuk pintu utama di PC Hans terlebih dahulu.</i>", 60)

    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    status_txt = f"🍾 VIP Reserve (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "🥂 Regular Guest"

    text = (
        f"🧾 <b>BAR TAB & STATUS — {message.from_user.first_name}</b>\n\n"
        f"• <b>Status Meja:</b> {status_txt}\n"
        f"• <b>Saldo Dompet:</b> {row['coins']} Velvet Coins (VC)\n"
        f"• <b>Charm Points:</b> {row['charm_points']} Poin\n"
        f"• <b>Total Waktu Nongkrong:</b> {row['total_active_mins'] or 0} Menit"
    )
    await reply_and_autodelete(message, text, 90)

@dp.message(Command("order"), F.chat.id == GROUP_ID)
async def cmd_order(message: types.Message):
    item_raw = message.text.replace("/order", "").strip().lower()
    if not item_raw:
        menu_list = "\n".join([f"• <code>/order {k}</code> — {v[0]}" for k, v in DRINKS_MENU.items()])
        return await reply_and_autodelete(
            message,
            f"🍸 <b>DAFTAR MINUMAN BARTENDER JULIAN</b>\n\n{menu_list}\n\n<i>Atau ketik nama minuman apa saja, misal: <code>/order Iced Caramel Latte</code></i>",
            90
        )

    matched = None
    for key, val in DRINKS_MENU.items():
        if key in item_raw:
            matched = val
            break

    if matched:
        title, narrative = matched
        text = f"{title}\n{narrative}\n\n<i>— Disajikan untuk <b>{message.from_user.first_name}</b>.</i>"
    else:
        custom_name = message.text.replace("/order", "").strip()
        text = (
            f"🍸 <b>Pesanan Khusus: {custom_name}</b>\n"
            f"<i>Julian mengangguk paham, meracik bahan-bahan pilihan di balik meja bar kayu ek, lalu menggeser gelas <b>{custom_name}</b> dengan mulus ke hadapanmu.</i>\n"
            f"<b>\"Racikan khusus sesuai permintaanmu. Selamat menikmati malam di The Velvet Hour, {message.from_user.first_name}.\"</b>"
        )
    await reply_and_autodelete(message, text, 120)

@dp.message(Command("eat"), F.chat.id == GROUP_ID)
async def cmd_eat(message: types.Message):
    item_raw = message.text.replace("/eat", "").strip().lower()
    if not item_raw:
        menu_list = "\n".join([f"• <code>/eat {k}</code> — {v[0]}" for k, v in FOODS_MENU.items()])
        return await reply_and_autodelete(
            message,
            f"🍽️ <b>DAFTAR HIDANGAN DAPUR (WAITRESS CLARA)</b>\n\n{menu_list}\n\n<i>Atau ketik makanan apa saja, misal: <code>/eat Croissant Hangat</code></i>",
            90
        )

    matched = None
    for key, val in FOODS_MENU.items():
        if key in item_raw:
            matched = val
            break

    if matched:
        title, narrative = matched
        text = f"{title}\n{narrative}\n\n<i>— Diantarkan ke meja <b>{message.from_user.first_name}</b>.</i>"
    else:
        custom_food = message.text.replace("/eat", "").strip()
        text = (
            f"🍽️ <b>Hidangan Khusus: {custom_food}</b>\n"
            f"<i>Waitress Clara keluar dari balik pintu dapur membawa nampan perak hangat, lalu meletakkan <b>{custom_food}</b> di mejamu dengan senyum ramah.</i>\n"
            f"<b>\"Pesanan dari dapur sudah siap. Silakan dinikmati, {message.from_user.first_name}.\"</b>"
        )
    await reply_and_autodelete(message, text, 120)

@dp.message(Command("mystery"), F.chat.id == GROUP_ID)
async def cmd_mystery(message: types.Message):
    user_id = message.from_user.id
    cost = 40
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if not coins or coins < cost:
                return await reply_and_autodelete(message, f"<i>Julian menggeleng sopan: Saldo tidak cukup (butuh <b>{cost} VC</b> untuk memutar Roulette Meja Bar).</i>", 60)
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user_id)

            outcomes = [
                ("golden", "✨ <b>GOLDEN ELIXIR (+85 VC)!</b>\n<i>Cairan berkilau keemasan dituangkan ke gelasmu. Kamu memenangkan hadiah utama meja bar!</i>"),
                ("truth", "🕯️ <b>VELVET TRUTH CARD!</b>\n<i>Julian menyodorkan kartu hitam: \"Jawab dengan jujur di chat—apa hal paling nekat yang pernah kamu lakukan diam-diam?\"</i>"),
                ("dare", "🎲 <b>VELVET DARE CARD!</b>\n<i>Julian tersenyum tipis: \"Tantangan malam ini—kirim pesan pujian RP ke salah satu tamu yang sedang aktif di ruangan!\"</i>"),
                ("water", "💧 <b>CHILLED MINERAL WATER!</b>\n<i>Zonk! Gelas yang muncul hanya berisi air putih dingin. Coba lagi keberuntunganmu nanti.</i>"),
            ]
            choice_key, result_text = random.choice(outcomes)
            if choice_key == "golden":
                await conn.execute("UPDATE users SET coins = coins + 85 WHERE user_id = $1", user_id)

    await reply_and_autodelete(
        message,
        f"🎰 <b>VELVET BAR ROULETTE ({message.from_user.first_name})</b>\n\n{result_text}",
        120
    )

@dp.message(Command("toast"), F.chat.id == GROUP_ID)
async def cmd_toast(message: types.Message):
    target = message.text.replace("/toast", "").strip()
    if not target and message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
    if not target:
        return await reply_and_autodelete(message, "Sebutkan nama/username tamu atau balas pesannya. Contoh: <code>/toast @username</code>", 60)

    await reply_and_autodelete(
        message,
        f"🥂 <b>BERSULANG DI RUANG UTAMA!</b>\n"
        f"<i><b>{message.from_user.first_name}</b> mengangkat gelas kristalnya tinggi-tinggi ke arah <b>{target}</b>. "
        f"Denting dua gelas beradu halus di tengah hangatnya lampu lounge.</i>",
        120
    )

@dp.message(Command("guests"), F.chat.id == GROUP_ID)
async def cmd_guests(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT full_name, is_vip, vip_until FROM users WHERE is_in_bar = TRUE ORDER BY last_active DESC LIMIT 25"
        )
    if not rows:
        return await reply_and_autodelete(message, "<i>Ruang utama tampak lengang malam ini.</i>", 60)

    lines = []
    for r in rows:
        badge = "🍾" if (r["is_vip"] and r["vip_until"] and r["vip_until"] > datetime.utcnow()) else "🥂"
        lines.append(f"{badge} {r['full_name']}")

    await reply_and_autodelete(
        message,
        f"📋 <b>DAFTAR TAMU DI DALAM LOUNGE ({len(rows)})</b>\n\n" + "\n".join(lines),
        90
    )

@dp.message(Command("topcharm"), F.chat.id == GROUP_ID)
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

@dp.message(Command("checkin"), F.chat.id == GROUP_ID)
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

@dp.message(Command("checkout"), F.chat.id == GROUP_ID)
async def cmd_checkout(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_in_bar = FALSE WHERE user_id = $1", user_id)

    await message.answer(
        f"<i><b>{message.from_user.first_name}</b> meletakkan serbet di atas meja dan beranjak menuju pintu keluar. "
        f"Bouncer Hans membukakan pintu mahoni dengan anggukan hormat.</i>\n"
        f"<b>\"Terima kasih telah berkunjung ke The Velvet Hour. Hati-hati di jalan.\"</b>",
        parse_mode=ParseMode.HTML
    )
    if not await is_staff_or_owner(user_id):
        try:
            await hans_bot.ban_chat_member(GROUP_ID, user_id)
            await hans_bot.unban_chat_member(GROUP_ID, user_id)
        except Exception:
            pass

# --- SISTEM SHIFT KERJA PARUH WAKTU ---
@dp.message(Command("apply"), F.chat.id == GROUP_ID)
async def cmd_apply(message: types.Message):
    role = message.text.replace("/apply", "").strip().lower()
    valid_roles = {"bartender", "waiter", "host", "dj"}
    if role not in valid_roles:
        return await reply_and_autodelete(
            message,
            "💼 <b>PILIH POSISI SHIFT (2 JAM — UPAH 120 VC)</b>\n"
            "• <code>/apply bartender</code>\n"
            "• <code>/apply waiter</code>\n"
            "• <code>/apply host</code>\n"
            "• <code>/apply dj</code>",
            90
        )

    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT user_id FROM active_shifts WHERE role = $1", role)
        if existing:
            return await reply_and_autodelete(message, f"Posisi <b>{role.upper()}</b> sedang diisi oleh staf lain saat ini.", 60)

        already_working = await conn.fetchrow("SELECT role FROM active_shifts WHERE user_id = $1", user_id)
        if already_working:
            return await reply_and_autodelete(message, f"Kamu sudah bertugas sebagai <b>{already_working['role'].upper()}</b>. Ketik <code>/endshift</code> untuk selesai.", 60)

        await conn.execute(
            "INSERT INTO active_shifts (role, user_id, started_at, actions_count) VALUES ($1, $2, NOW(), 0)",
            role, user_id
        )

    await message.answer(
        f"💼 <b>SHIFT DIMULAI!</b>\n"
        f"<b>{message.from_user.first_name}</b> kini mengenakan pin staf dan resmi bertugas sebagai <b>{role.upper()}</b> selama 2 jam ke depan!\n"
        f"<i>(Lakukan minimal 5x interaksi melayani tamu lalu ketik <code>/endshift</code> untuk mencairkan upah 120 VC).</i>",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("endshift"), F.chat.id == GROUP_ID)
async def cmd_endshift(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        shift = await conn.fetchrow("SELECT role, actions_count FROM active_shifts WHERE user_id = $1", user_id)
        if not shift:
            return await reply_and_autodelete(message, "Kamu sedang tidak dalam jadwal shift kerja.", 60)

        await conn.execute("DELETE FROM active_shifts WHERE user_id = $1", user_id)
        if shift["actions_count"] >= 5:
            await conn.execute("UPDATE users SET coins = coins + 120 WHERE user_id = $1", user_id)
            msg_txt = (
                f"💵 <b>SHIFT SELESAI — UPAH CAIR!</b>\n"
                f"Bartender Julian menyerahkan amplop berisi <b>+120 Velvet Coins</b> kepada <b>{message.from_user.first_name}</b> "
                f"atas kerja kerasnya sebagai <b>{shift['role'].upper()}</b> ({shift['actions_count']} layanan)."
            )
        else:
            msg_txt = (
                f"📋 <b>SHIFT DIAKHIRI</b>\n"
                f"<b>{message.from_user.first_name}</b> melepas pin <b>{shift['role'].upper()}</b>. "
                f"<i>(Upah tidak cair karena layanan baru mencapai {shift['actions_count']}/5 kali).</i>"
            )
    await message.answer(msg_txt, parse_mode=ParseMode.HTML)

# --- AKSI STAF PARUH WAKTU (RP NARASI) ---
@dp.message(Command("mix"), F.chat.id == GROUP_ID)
async def cmd_mix(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "bartender") and not await is_staff_or_owner(message.from_user.id):
        return
    drink = message.text.replace("/mix", "").strip() or "Signature Velvet Cocktail"
    await add_shift_action(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"🍸 <b>Bartender {message.from_user.first_name}</b> mengocok shaker perak dengan lihai dan menuangkan <b>{drink}</b> ke gelas kristal dingin!",
        120
    )

@dp.message(Command("sober"), F.chat.id == GROUP_ID)
async def cmd_sober(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "bartender") and not await is_staff_or_owner(message.from_user.id):
        return
    target = message.text.replace("/sober", "").strip() or "tamu di sudut bar"
    await add_shift_action(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"☕ <b>Bartender {message.from_user.first_name}</b> menyodorkan secangkir kopi hitam pekat dan air dingin kepada <b>{target}</b> agar kembali segar.",
        120
    )

@dp.message(Command("welcome"), F.chat.id == GROUP_ID)
async def cmd_welcome_staff(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "waiter") and not await is_staff_or_owner(message.from_user.id):
        return
    target = message.text.replace("/welcome", "").strip() or "tamu baru"
    await add_shift_action(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"🍽️ <b>Waiter {message.from_user.first_name}</b> menyambut <b>{target}</b> dengan senyum hangat, mengantar ke meja beludru, dan menyalakan lilin meja.",
        120
    )

@dp.message(Command("dish"), F.chat.id == GROUP_ID)
async def cmd_dish(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "waiter") and not await is_staff_or_owner(message.from_user.id):
        return
    dish_name = message.text.replace("/dish", "").strip() or "Hidangan Spesial Chef"
    await add_shift_action(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"🍽️ <b>Waiter {message.from_user.first_name}</b> menyajikan <b>{dish_name}</b> hangat dari dapur langsung ke meja tamu.",
        120
    )

@dp.message(Command("ambience"), F.chat.id == GROUP_ID)
async def cmd_ambience(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "host") and not await is_staff_or_owner(message.from_user.id):
        return
    await add_shift_action(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"🕯️ <b>Host {message.from_user.first_name}</b> meredupkan lampu gantung kristal, menyisakan pendar cahaya lilin hangat yang intim di seluruh penjuru lounge...",
        120
    )

@dp.message(Command("toastall"), F.chat.id == GROUP_ID)
async def cmd_toastall(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "host") and not await is_staff_or_owner(message.from_user.id):
        return
    await add_shift_action(message.from_user.id)
    await reply_and_autodelete(
        message,
        f"🥂 <b>Host {message.from_user.first_name}</b> berdiri di tengah ruangan sambil mengangkat gelas: <b>\"Mari bersulang untuk malam yang tak terlupakan di The Velvet Hour!\"</b>",
        120
    )

# --- MODERASI ADMIN & OWNER ---
@dp.message(Command("mute"), F.chat.id == GROUP_ID)
async def cmd_mute(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id) or not message.reply_to_message:
        return
    target = message.reply_to_message.from_user
    until = datetime.utcnow() + timedelta(minutes=15)
    try:
        await bot.restrict_chat_member(GROUP_ID, target.id, types.ChatPermissions(can_send_messages=False), until_date=until)
        await message.answer(
            f"🔇 <i>Bouncer Hans melangkah mendekat ke meja <b>{target.first_name}</b> dan memberi isyarat tenang.</i>\n"
            f"<b>\"Harap tenangkan diri selama 15 menit sebelum kembali berbincang.\"</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await reply_and_autodelete(message, f"Gagal mute: {e}", 30)

@dp.message(Command("kick"), F.chat.id == GROUP_ID)
async def cmd_kick(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id) or not message.reply_to_message:
        return
    target = message.reply_to_message.from_user
    try:
        await hans_bot.ban_chat_member(GROUP_ID, target.id)
        await hans_bot.unban_chat_member(GROUP_ID, target.id)
        async with db.pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_in_bar = FALSE WHERE user_id = $1", target.id)
        await message.answer(
            f"🚪 <i>Bouncer Hans mencengkeram bahu <b>{target.first_name}</b> dengan tegas dan mengantarnya keluar pintu mahoni.</i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await reply_and_autodelete(message, f"Gagal kick: {e}", 30)

@dp.message(Command("round"), F.chat.id == GROUP_ID)
async def cmd_round(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET coins = coins + 25 WHERE is_in_bar = TRUE")
    await message.answer(
        "🍾 <b>ON THE HOUSE — TRATIRAN OWNER!</b>\n"
        "<i>Bartender Julian membunyikan lonceng kuningan di atas meja bar! Seluruh tamu yang sedang berada di dalam lounge mendapatkan <b>+25 Velvet Coins</b>!</i>",
        parse_mode=ParseMode.HTML
    )

# --- LISTENER AKTIVITAS CHAT, KOIN RP & ANTI-LEPAS SIMBOL CN ---
@dp.message(F.chat.id == GROUP_ID, F.text)
async def on_group_activity(message: types.Message):
    if message.from_user.is_bot:
        return

    user = message.from_user
    user_id = user.id

    # 1. Cek Anti-Lepas Simbol CN (🥂) untuk non-staff
    if not await is_staff_or_owner(user_id):
        if REQUIRED_CN_SYMBOL not in (user.full_name or ""):
            await message.answer(
                f"🚨 <i>Bouncer Hans menghentikan langkah <b>{user.first_name}</b> di tengah ruangan.</i>\n"
                f"<b>\"Atribut resmi ({REQUIRED_CN_SYMBOL}) tidak terlihat pada namamu. Sesuai aturan, saya harus mengantarmu keluar.\"</b>",
                parse_mode=ParseMode.HTML
            )
            try:
                await hans_bot.ban_chat_member(GROUP_ID, user_id)
                await hans_bot.unban_chat_member(GROUP_ID, user_id)
            except Exception:
                pass
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE users SET is_in_bar = FALSE WHERE user_id = $1", user_id)
            return

    # 2. Reset timer pasif & beri koin tipis jika chat RP >= 3 kata
    words = len(message.text.strip().split())
    if words >= 3:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, is_in_bar, last_active, warned_idle, total_active_mins)
                VALUES ($1, $2, $3, TRUE, NOW(), FALSE, 1)
                ON CONFLICT (user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name,
                    is_in_bar = TRUE,
                    last_active = NOW(),
                    warned_idle = FALSE,
                    total_active_mins = users.total_active_mins + 1,
                    coins = users.coins + 1;
            """, user_id, user.username or "NoUsername", user.full_name)

# --- BACKGROUND WORKER: PENGAWAS TAMU PASIF (IDLE 60M / VIP 120M) ---
async def idle_watcher_loop():
    while True:
        await asyncio.sleep(60)
        try:
            async with db.pool.acquire() as conn:
                guests = await conn.fetch(
                    "SELECT user_id, full_name, is_vip, vip_until, last_active, warned_idle FROM users WHERE is_in_bar = TRUE"
                )
                now = datetime.utcnow()
                for g in guests:
                    uid = g["user_id"]
                    if await is_staff_or_owner(uid):
                        continue

                    is_vip = bool(g["is_vip"] and g["vip_until"] and g["vip_until"] > now)
                    limit_mins = 120 if is_vip else 60
                    warn_mins = limit_mins - 10
                    idle_mins = (now - g["last_active"]).total_seconds() / 60

                    if idle_mins >= limit_mins:
                        await conn.execute("UPDATE users SET is_in_bar = FALSE, warned_idle = FALSE WHERE user_id = $1", uid)
                        try:
                            await hans_bot.ban_chat_member(GROUP_ID, uid)
                            await hans_bot.unban_chat_member(GROUP_ID, uid)
                            await bot.send_message(
                                GROUP_ID,
                                f"🚪 <i>Bouncer Hans mengantar <b>{g['full_name']}</b> yang tertidur di sudut meja keluar pintu mahoni. "
                                f"Saldo koin dan hadiah tetap tersimpan aman.</i>",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
                    elif idle_mins >= warn_mins and not g["warned_idle"]:
                        await conn.execute("UPDATE users SET warned_idle = TRUE WHERE user_id = $1", uid)
                        warn_msg = await bot.send_message(
                            GROUP_ID,
                            f"🕯️ <i>Waitress Clara menyentuh bahu <a href='tg://user?id={uid}'>{g['full_name']}</a> dengan lembut:</i>\n"
                            f"<b>\"Permisi, meja ini akan segera dirapikan dalam 10 menit jika tidak ada aktivitas. Ketik obrolan atau <code>/checkin</code> jika masih bersantai.\"</b>",
                            parse_mode=ParseMode.HTML
                        )
                        asyncio.create_task(schedule_delete(warn_msg, 120))
        except Exception as e:
            logging.error(f"Idle watcher error: {e}")

# --- REGISTER MENU COMMAND (/) DI GRUP ---
async def register_julian_commands():
    commands = [
        BotCommand(command="order", description="Pesan minuman ke Bartender Julian"),
        BotCommand(command="eat", description="Pesan makanan ke Waitress Clara"),
        BotCommand(command="bill", description="Cek saldo Velvet Coins, VIP & Charm"),
        BotCommand(command="mystery", description="Putar Bar Roulette (40 VC)"),
        BotCommand(command="toast", description="Ajak bersulang tamu lain"),
        BotCommand(command="guests", description="Lihat daftar tamu di dalam lounge"),
        BotCommand(command="topcharm", description="Papan peringkat Charm Points"),
        BotCommand(command="checkin", description="Perbarui waktu santai (anti-idle)"),
        BotCommand(command="checkout", description="Pamit keluar dari ruang bar"),
        BotCommand(command="apply", description="Ambil shift kerja paruh waktu (120 VC)"),
        BotCommand(command="endshift", description="Selesaikan shift & cairkan upah"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())

async def main():
    await db.init_db()
    await register_julian_commands()
    asyncio.create_task(idle_watcher_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
