import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeAllPrivateChats
)
from aiogram.enums import ParseMode, ChatMemberStatus

import shared.database as db
from shared.config import (
    TOKEN_HANS, TOKEN_JULIAN, OWNER_ID, OWNER_USERNAME, GROUP_ID,
    CH_INFO_ID, CH_PROMOTE_ID, CH_INFO_LINK, CH_PROMOTE_LINK,
    REQUIRED_CN_SYMBOL, WELCOME_BONUS, DAILY_COIN, VIP_COST_24H,
    PROMOTE_CD_REG, PROMOTE_CD_VIP, GIFTS_CATALOG
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN_HANS)
julian_bot = Bot(token=TOKEN_JULIAN)
dp = Dispatcher()

# --- FSM STATES ---
class GateState(StatesGroup):
    waiting_password = State()

class PromoteState(StatesGroup):
    waiting_content = State()

class CurhatState(StatesGroup):
    waiting_text = State()

class GiftState(StatesGroup):
    waiting_target = State()
    waiting_note = State()

class AdminState(StatesGroup):
    waiting_add_admin = State()
    waiting_rem_admin = State()
    waiting_new_pass = State()
    waiting_topup = State()
    waiting_broadcast = State()

# --- HELPER FUNCTIONS ---
async def ensure_user(user: types.User):
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = EXCLUDED.username, full_name = EXCLUDED.full_name;
        """, user.id, user.username or "NoUsername", user.full_name)

async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def check_vip_status(user_id: int) -> bool:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        if row and row["is_vip"]:
            if row["vip_until"] and row["vip_until"] > datetime.utcnow():
                return True
            else:
                await conn.execute("UPDATE users SET is_vip = FALSE WHERE user_id = $1", user_id)
        return False

async def check_channels_sub(user_id: int) -> tuple[bool, str]:
    valid_statuses = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    try:
        m1 = await bot.get_chat_member(CH_INFO_ID, user_id)
    except Exception as e:
        return False, f"Gagal cek CH Info ({CH_INFO_ID}): {e}"
    try:
        m2 = await bot.get_chat_member(CH_PROMOTE_ID, user_id)
    except Exception as e:
        return False, f"Gagal cek CH Promote ({CH_PROMOTE_ID}): {e}"

    if (m1.status in valid_statuses) and (m2.status in valid_statuses):
        return True, "OK"
    return False, "NOT_SUBBED"

# --- KEYBOARDS ---
async def main_menu_kb(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="🚪 Masuk ke Bar (Verifikasi)", callback_data="gate_start")],
        [
            InlineKeyboardButton(text="📢 Buat Promote", callback_data="menu_promote"),
            InlineKeyboardButton(text="💌 Meja Curhat", callback_data="menu_curhat")
        ],
        [
            InlineKeyboardButton(text="🎁 Bar Boutique (Gift)", callback_data="menu_shop"),
            InlineKeyboardButton(text="🎒 Tas & VIP Pass", callback_data="menu_inv")
        ],
        [
            InlineKeyboardButton(text="📖 Cara Bermain", callback_data="info_guide"),
            InlineKeyboardButton(text="📜 Rules & Etika", callback_data="info_rules")
        ],
        [
            InlineKeyboardButton(text="💼 Lowongan Shift", callback_data="info_jobs"),
            InlineKeyboardButton(text="💎 Sistem Koin & Gift", callback_data="info_eco")
        ],
        [InlineKeyboardButton(text="☕ Support & Donate", callback_data="info_donate")]
    ]
    if await is_staff_or_owner(user_id):
        buttons.append([InlineKeyboardButton(text="⚙️ Panel Kendali Staf", callback_data="staff_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_home_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")]
    ])

# --- OPENING & MENU UTAMA ---
OPENING_TEXT = (
    "<i>Langkah kakimu berhenti tepat di depan sebuah pintu kayu mahoni berat di ujung lorong yang remang. "
    "Lubang intip kecil di pintu itu bergeser terbuka, menampakkan tatapan tajam dari balik kegelapan.</i>\n\n"
    "<b>\"Selamat malam. Angin di luar cukup dingin, bukan? Saya Hans, penjaga pintu <i>The Velvet Hour</i>. "
    "Tempat ini tertutup untuk umum—hanya mereka yang tahu aturan main dan membawa kunci yang boleh melangkah masuk.\"</b>\n\n"
    "<i>Silakan periksa papan informasi di sebelah kananmu, atau buktikan bahwa kamu memang tamu undangan kami.</i>"
)

@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await ensure_user(message.from_user)
    await message.answer(
        OPENING_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=await main_menu_kb(message.from_user.id)
    )

@dp.callback_query(F.data == "back_home")
async def cb_back_home(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.edit_text(
        OPENING_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=await main_menu_kb(call.from_user.id)
    )

# --- KATEGORI INFORMASI ---
@dp.callback_query(F.data == "info_guide")
async def cb_info_guide(call: types.CallbackQuery):
    await call.answer()
    text = (
        "<i>Hans menyandarkan bahunya ke dinding batu, melipat kedua tangannya di dada.</i>\n\n"
        "<b>🥂 PANDUAN BERKUNJUNG — THE VELVET HOUR</b>\n\n"
        "<b>1. Sistem Berkunjung & Pulang:</b>\n"
        "• Jika kamu diam selama <b>60 menit</b> (atau <b>120 menit</b> untuk VIP), Waitress Clara akan memberi peringatan, lalu saya akan mengantarmu pulang (<i>auto-kick</i>).\n"
        "• Saldo koin dan hadiahmu tetap aman. Ketuk pintu ini lagi kapan pun kamu ingin mampir kembali.\n\n"
        "<b>2. Interaksi di Ruang Utama:</b>\n"
        "• Pesan minum (<code>/order</code>), makanan (<code>/eat</code>), lagu (<code>/reqsong</code>), atau mainkan roulette (<code>/mystery</code>).\n"
        "• Gunakan <code>/checkin</code> jika hanya menyimak obrolan, atau <code>/checkout</code> jika pamit pulang."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.callback_query(F.data == "info_rules")
async def cb_info_rules(call: types.CallbackQuery):
    await call.answer()
    text = (
        "<i>Hans mengetuk papan kuningan di samping pintu dengan buku jarinya.</i>\n\n"
        "<b>📜 ATURAN TAK TERTULIS THE VELVET HOUR</b>\n\n"
        "<b>1. Wajib Atribut Resmi (Dresscode):</b>\n"
        f"• Selama di dalam bar, kamu <b>wajib</b> menyematkan simbol <b>{REQUIRED_CN_SYMBOL}</b> pada nama profil Telegram-mu (Contoh: <code>Alvaro {REQUIRED_CN_SYMBOL}</code>). Melepas atribut di dalam ruangan berakibat diantar keluar.\n\n"
        "<b>2. Jaga Suasana Roleplay:</b>\n"
        "• Dilarang membawa drama OOC, ujaran kebencian, atau keributan.\n"
        "• Obrolan suara (Voice Chat) khusus untuk mendengarkan musik lounge (mikrofon tamu dikunci).\n\n"
        "<b>3. Anti-Spam:</b>\n"
        "• Timer pasif hanya ter-reset oleh obrolan minimal 3 kata atau perintah RP."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.callback_query(F.data == "info_eco")
async def cb_info_eco(call: types.CallbackQuery):
    await call.answer()
    text = (
        "<i>Bartender Julian melangkah mendekat dari balik tirai beludru sambil mengelap gelas kristal.</i>\n\n"
        "<b>💎 VELVET COINS (VC) & SISTEM GIFT</b>\n\n"
        "<b>• Sumber Koin:</b> Modal awal 200 VC, Absen harian <code>/daily</code> (+30 VC), keaktifan chat RP, dan upah kerja paruh waktu.\n"
        "<b>• VIP Pass (300 VC / 24 Jam):</b> Cooldown promote 30 menit, boleh lampirkan foto/GIF, masuk <i>Spotlight Pin</i>, dan batas waktu pasif 2 jam.\n"
        "<b>• Pengaruh Gift:</b> Hadiah yang kamu terima menambah <b>Charm Points</b> (Leaderboard) dan memperpanjang waktu nongkrong <b>+15 menit</b>.\n"
        "<b>• Penukaran Gift:</b> Hadiah di tas dapat dicairkan menjadi koin (nilai tukar <b>50%</b>) atau ditukar menjadi VIP Pass."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Top Up Koin (Hubungi Owner)", url=f"https://t.me/{OWNER_USERNAME}")],
        [InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")]
    ])
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data == "info_jobs")
async def cb_info_jobs(call: types.CallbackQuery):
    await call.answer()
    text = (
        "<i>Julian meletakkan lembar formulir di atas meja kayu.</i>\n\n"
        "<b>💼 LOWONGAN STAF PARUH WAKTU (SHIFT 2 JAM)</b>\n"
        "<i>Upah: 120 VC per shift (cair setelah minimal 5x melayani tamu).</i>\n\n"
        "• <b>🍸 Bartender:</b> <code>/mix</code>, <code>/sober</code>\n"
        "• <b>🍽️ Waiter/Waitress:</b> <code>/welcome</code>, <code>/dish</code>\n"
        "• <b>🎩 Host:</b> <code>/ambience</code>, <code>/toastall</code>\n"
        "• <b>🎶 Resident DJ:</b> <code>/spinmusic</code>, <code>/dedicate</code>\n\n"
        "<i>Ketik <code>/apply</code> di dalam ruang utama untuk mengambil shift yang kosong.</i>"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.callback_query(F.data == "info_donate")
async def cb_info_donate(call: types.CallbackQuery):
    await call.answer()
    text = (
        "<i>Hans menundukkan kepala sedikit, lalu menggeser kartu nama berlapis tinta emas di atas meja resepsionis.</i>\n\n"
        "<b>☕ SUPPORT & DONATE (VELVET PATRON)</b>\n\n"
        "\"Terima kasih atas niat baikmu untuk menjaga lampu <i>The Velvet Hour</i> tetap menyala. "
        "Seluruh dukungan dana digunakan untuk pemeliharaan server dan event mingguan.\"\n\n"
        "<i>Silakan hubungi <b>Owner</b> kami melalui tombol di bawah ini untuk menyalurkan dukungan secara langsung.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Hubungi Owner", url=f"https://t.me/{OWNER_USERNAME}")],
        [InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")]
    ])
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

# --- ALUR GATEKEEPING 3 LAPIS ---
@dp.callback_query(F.data == "gate_start")
async def cb_gate_start(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    await ensure_user(call.from_user)

    async with db.pool.acquire() as conn:
        bar_open = await conn.fetchval("SELECT value FROM bar_settings WHERE key = 'bar_open'")
    if bar_open != "true" and not await is_staff_or_owner(user_id):
        return await call.answer("Pintu bar sedang dikunci oleh Owner untuk jam tutup.", show_alert=True)

    is_sub, sub_info = await check_channels_sub(user_id)
    if not is_sub:
        await call.answer()
        if sub_info != "NOT_SUBBED":
            return await call.message.edit_text(
                f"⚠️ <b>Konfigurasi Channel Bermasalah:</b>\n<code>{sub_info}</code>\n\n"
                "<i>Pastikan Bot Hans sudah dijadikan Admin di CH Info dan CH Promote, dan ID channel diawali -100.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_home_kb()
            )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📌 Gabung CH Info & Kode", url=CH_INFO_LINK)],
            [InlineKeyboardButton(text="📢 Gabung CH Lapak Promote", url=CH_PROMOTE_LINK)],
            [InlineKeyboardButton(text="🔄 Periksa Ulang Status", callback_data="gate_start")],
            [InlineKeyboardButton(text="🔙 Kembali", callback_data="back_home")]
        ])
        return await call.message.edit_text(
            "<i>Hans melirik buku tamu di tangannya.</i>\n\n"
            "<b>\"Namamu belum tercatat di kedua saluran resmi kami. Pastikan kamu sudah bergabung di papan informasi dan papan promosi sebelum mengetuk pintu.\"</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    await call.answer()
    await state.set_state(GateState.waiting_password)
    await call.message.edit_text(
        "<i>Hans mengangguk singkat setelah memastikan namamu terdaftar di kedua saluran.</i>\n\n"
        "<b>\"Sekarang, bisikkan kata sandi malam ini yang tertera di papan informasi kami.\"</b>\n"
        "<i>(Ketik dan kirim kata sandinya sekarang...)</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_kb()
    )

@dp.message(GateState.waiting_password, F.chat.type == "private")
async def process_gate_password(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Kirimkan kata sandi dalam bentuk teks.")

    async with db.pool.acquire() as conn:
        real_pass = await conn.fetchval("SELECT value FROM bar_settings WHERE key = 'door_password'")

    if message.text.strip().upper() != (real_pass or "VELVET").upper():
        return await message.answer(
            "<i>Hans menggeleng dingin dari balik lubang intip.</i>\n"
            "<b>\"Kata sandi salah. Periksa kembali papan informasi kami dan coba lagi.\"</b>",
            parse_mode=ParseMode.HTML
        )

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔍 Periksa Simbol CN ({REQUIRED_CN_SYMBOL})", callback_data="gate_check_cn")],
        [InlineKeyboardButton(text="🔙 Batal", callback_data="back_home")]
    ])
    await message.answer(
        "<i>Password diterima. Hans memindai penampilanmu dari atas ke bawah.</i>\n\n"
        f"<b>\"Satu syarat terakhir: sematkan simbol {REQUIRED_CN_SYMBOL} di belakang nama profil Telegram-mu sekarang. "
        "Jika sudah terpasang, tekan tombol di bawah.\"</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@dp.callback_query(F.data == "gate_check_cn")
async def cb_gate_check_cn(call: types.CallbackQuery):
    user = call.from_user
    # Ambil nama profil terbaru langsung dari server Telegram agar tidak nyangkut cache lama
    try:
        fresh_chat = await bot.get_chat(user.id)
        current_full_name = f"{fresh_chat.first_name or ''} {fresh_chat.last_name or ''}".strip()
    except Exception:
        current_full_name = user.full_name or ""

    if REQUIRED_CN_SYMBOL not in current_full_name:
        return await call.answer(
            f"Simbol {REQUIRED_CN_SYMBOL} belum terlihat di namamu ({current_full_name}). Pasang di Pengaturan Telegram lalu klik lagi!",
            show_alert=True
        )

    await call.answer("Atribut terverifikasi! Menyiapkan pintu masuk...")

    try:
        expire_time = datetime.utcnow() + timedelta(minutes=3)
        invite = await bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            expire_date=expire_time,
            member_limit=1
        )
    except Exception as e:
        return await call.message.edit_text(
            f"❌ <b>Gagal Membuat Tautan Masuk Grup:</b>\n<code>{e}</code>\n\n"
            "<i>Pastikan Bot Hans sudah masuk Grup Utama, dijadikan Admin dengan izin 'Invite Users via Link', dan GROUP_ID benar.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_kb()
        )

    bonus_msg = ""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT got_welcome FROM users WHERE user_id = $1", user.id)
        if row and not row["got_welcome"]:
            await conn.execute(
                "UPDATE users SET coins = coins + $1, got_welcome = TRUE WHERE user_id = $2",
                WELCOME_BONUS, user.id
            )
            bonus_msg = f"\n🎁 <i>Sebagai tamu baru, <b>{WELCOME_BONUS} Velvet Coins</b> telah disimpan ke dompetmu.</i>"
        await conn.execute(
            "UPDATE users SET is_in_bar = TRUE, full_name = $1, last_active = NOW(), warned_idle = FALSE WHERE user_id = $2",
            current_full_name, user.id
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥂 Melangkah Masuk ke Lounge", url=invite.invite_link)],
        [InlineKeyboardButton(text="🔙 Kembali ke Menu Utama", callback_data="back_home")]
    ])
    await call.message.edit_text(
        "<i>Klik... Kunci pintu besi diputar terbuka. Alunan jazz hangat dan denting gelas langsung menyambutmu.</i>\n\n"
        "<b>\"Selamat datang di <i>The Velvet Hour</i>. Tautan di bawah ini hanya berlaku 3 menit untuk satu kali masuk.\"</b>"
        f"{bonus_msg}",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

# --- DAILY CLAIM ---
@dp.message(Command("daily"), F.chat.type == "private")
async def cmd_daily(message: types.Message):
    await ensure_user(message.from_user)
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_daily, daily_streak, coins FROM users WHERE user_id = $1", message.from_user.id)
        if row["last_daily"] == today:
            return await message.answer("<i>Julian tersenyum: \"Kamu sudah mengambil jatah koin harianmu hari ini. Kembalilah besok.\"</i>", parse_mode=ParseMode.HTML)

        streak = (row["daily_streak"] + 1) if row["last_daily"] == (today - timedelta(days=1)) else 1
        reward = 70 if streak % 7 == 0 else DAILY_COIN
        await conn.execute(
            "UPDATE users SET coins = coins + $1, last_daily = $2, daily_streak = $3 WHERE user_id = $4",
            reward, today, streak, message.from_user.id
        )
    await message.answer(
        f"🍸 <b>Absen Harian Berhasil!</b> (Hari ke-{streak})\n"
        f"Bartender Julian menyerahkan <b>+{reward} Velvet Coins</b> ke dompetmu.",
        parse_mode=ParseMode.HTML
    )

# --- PROMOTE (FREE 45M vs VIP 30M + SPOTLIGHT PIN) ---
@dp.callback_query(F.data == "menu_promote")
async def cb_menu_promote(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    is_sub, sub_info = await check_channels_sub(user_id)
    if not is_sub:
        if sub_info != "NOT_SUBBED":
            await call.answer()
            return await call.message.edit_text(f"⚠️ <b>Error Cek Channel:</b> <code>{sub_info}</code>", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())
        return await call.answer("Kamu wajib subscribe kedua channel resmi bar terlebih dahulu!", show_alert=True)

    is_vip = await check_vip_status(user_id)
    cd_mins = PROMOTE_CD_VIP if is_vip else PROMOTE_CD_REG

    async with db.pool.acquire() as conn:
        last_prom = await conn.fetchval("SELECT last_promote FROM users WHERE user_id = $1", user_id)
        if last_prom:
            diff = (datetime.utcnow() - last_prom).total_seconds() / 60
            if diff < cd_mins:
                sisa = int(cd_mins - diff) + 1
                return await call.answer(f"Meja promosi masih disiapkan. Tunggu {sisa} menit lagi.", show_alert=True)

    await call.answer()
    await state.set_state(PromoteState.waiting_content)
    mode_txt = "🍾 <b>VIP Reserve (Maks 800 karakter + Boleh Foto/GIF + Spotlight Pin)</b>" if is_vip else "🥂 <b>Standard Glass (Teks saja, Maks 400 karakter)</b>"
    await call.message.edit_text(
        f"<b>📢 BUAT KARTU PROMOSI</b>\nStatus Meja: {mode_txt}\n\n"
        "<i>Silakan kirimkan teks promosi RP-mu sekarang (atau klik Kembali untuk batal).</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_kb()
    )

@dp.message(PromoteState.waiting_content, F.chat.type == "private")
async def process_promote(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    is_vip = await check_vip_status(user_id)
    raw_text = message.caption or message.text or ""

    if not raw_text.strip():
        return await message.answer("Kirimkan teks promosi yang valid.")

    max_len = 800 if is_vip else 400
    if len(raw_text) > max_len:
        return await message.answer(f"Teks terlalu panjang ({len(raw_text)}/{max_len} karakter). Ringkas sedikit ya.")

    if message.photo and not is_vip:
        return await message.answer("Lampiran foto/media hanya tersedia untuk pemegang <b>VIP Pass</b>. Kirim teks saja atau aktifkan VIP Pass.", parse_mode=ParseMode.HTML)

    if is_vip:
        header = "🍾 <b>VIP SPOTLIGHT — THE VELVET HOUR</b> ✦\n<i>Bartender Julian menyalakan lampu sorot di meja VIP...</i>\n\n"
    else:
        header = "🥂 <b>GUEST CARD — THE VELVET HOUR</b>\n<i>Sebuah kartu nama diletakkan di papan lounge...</i>\n\n"

    footer = f"\n\n— <i>Dikirim oleh</i> <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
    final_post = header + raw_text + footer

    try:
        if message.photo and is_vip:
            sent = await julian_bot.send_photo(CH_PROMOTE_ID, photo=message.photo[-1].file_id, caption=final_post, parse_mode=ParseMode.HTML)
        else:
            sent = await julian_bot.send_message(CH_PROMOTE_ID, text=final_post, parse_mode=ParseMode.HTML)
    except Exception as e:
        await state.clear()
        return await message.answer(
            f"❌ <b>Gagal mengirim ke CH Promote:</b>\n<code>{e}</code>\n\n"
            "<i>Pastikan Bot Julian sudah jadi Admin (izin Post Messages) di CH Promote dan TOKEN_JULIAN di service Hans sudah benar.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_kb()
        )

    await state.clear()

    if is_vip:
        async with db.pool.acquire() as conn:
            old_pin = await conn.fetchval("SELECT value FROM bar_settings WHERE key = 'current_pin_id'")
            if old_pin and int(old_pin) != 0:
                try:
                    await julian_bot.unpin_chat_message(CH_PROMOTE_ID, int(old_pin))
                except Exception:
                    pass
            try:
                await julian_bot.pin_chat_message(CH_PROMOTE_ID, sent.message_id, disable_notification=True)
                await conn.execute("UPDATE bar_settings SET value = $1 WHERE key = 'current_pin_id'", str(sent.message_id))
            except Exception:
                pass

    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET last_promote = NOW() WHERE user_id = $1", user_id)

    await message.answer(
        "✅ <b>Kartu promosimu telah dipasang di papan utama!</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👀 Lihat di CH Promote", url=CH_PROMOTE_LINK)],
            [InlineKeyboardButton(text="🔙 Menu Utama", callback_data="back_home")]
        ])
    )

# --- MEJA CURHAT ANONIM ---
@dp.callback_query(F.data == "menu_curhat")
async def cb_menu_curhat(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(CurhatState.waiting_text)
    await call.message.edit_text(
        "<i>Bartender Julian menyodorkan selembar tisu bar dan pena.</i>\n\n"
        "<b>\"Tuliskan apa yang mengganjal di pikiranmu sekarang. Saya akan meletakkannya di meja ruang utama tanpa mencantumkan namamu.\"</b>\n\n"
        "<i>(Ketik pesan curhatmu di kolom chat bawah lalu kirim...)</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_kb()
    )

@dp.message(CurhatState.waiting_text, F.chat.type == "private")
async def process_curhat(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Kirimkan curhatmu dalam bentuk teks.")

    post = (
        "🕯️ <b>BARTENDER'S CONFESSION (ANONIM)</b>\n"
        "<i>Sebuah catatan ditinggalkan di sudut meja bar...</i>\n\n"
        f"“{message.text}”\n\n"
        "<i>Balas pesan ini jika ingin menanggapi secara RP.</i>"
    )
    try:
        await julian_bot.send_message(GROUP_ID, post, parse_mode=ParseMode.HTML)
        await state.clear()
        await message.answer(
            "✅ <b>Catatan anonimmu telah diletakkan di meja utama!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_kb()
        )
    except Exception as e:
        await state.clear()
        await message.answer(
            f"❌ <b>Gagal mengirim catatan ke Grup Utama:</b>\n<code>{e}</code>\n\n"
            "<i>Cek apakah Bot Julian sudah ada di grup, GROUP_ID diawali -100, dan TOKEN_JULIAN pada variabel Railway service Hans sudah diisi.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_kb()
        )

# --- BAR BOUTIQUE (TOKO GIFT) ---
@dp.callback_query(F.data == "menu_shop")
async def cb_menu_shop(call: types.CallbackQuery):
    await call.answer()
    async with db.pool.acquire() as conn:
        coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", call.from_user.id)

    rows = []
    for code, (name, price, _, _) in GIFTS_CATALOG.items():
        rows.append([InlineKeyboardButton(text=f"{name} — {price} VC", callback_data=f"buygift_{code}")])
    rows.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="back_home")])

    await call.message.edit_text(
        f"🎁 <b>BAR BOUTIQUE — KATALOG HADIAH</b>\nSaldo Dompetmu: <b>{coins} VC</b>\n\n"
        "<i>Pilih hadiah yang ingin kamu kirimkan ke tamu di dalam ruang utama:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@dp.callback_query(F.data.startswith("buygift_"))
async def cb_buy_gift(call: types.CallbackQuery, state: FSMContext):
    code = call.data.split("_")[1]
    name, price, _, _ = GIFTS_CATALOG[code]

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins, total_active_mins FROM users WHERE user_id = $1", call.from_user.id)
        if not row or row["coins"] < price:
            return await call.answer("Velvet Coins kamu tidak mencukupi!", show_alert=True)
        if (row["total_active_mins"] or 0) < 15 and not await is_staff_or_owner(call.from_user.id):
            return await call.answer("Tamu baru wajib aktif minimal 15 menit di bar sebelum mengirim hadiah.", show_alert=True)

    await call.answer()
    await state.update_data(gift_code=code)
    await state.set_state(GiftState.waiting_target)
    await call.message.edit_text(
        f"Kamu memilih: <b>{name} ({price} VC)</b>\n\n"
        "Ketik <b>@username</b> penerima hadiah tersebut (pastikan dia sudah pernah /start di bot ini):",
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_kb()
    )

@dp.message(GiftState.waiting_target, F.chat.type == "private")
async def process_gift_target(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Ketik @username penerima hadiah.")
    target_uname = message.text.strip().lstrip("@")
    async with db.pool.acquire() as conn:
        target = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE LOWER(username) = LOWER($1)", target_uname)
    if not target:
        return await message.answer("Tamu dengan username tersebut tidak ditemukan di buku tamu bar.")

    await state.update_data(target_id=target["user_id"], target_name=target["full_name"], target_uname=target_uname)
    await state.set_state(GiftState.waiting_note)
    await message.answer("Tuliskan <b>pesan singkat</b> yang akan disematkan pada kartu hadiah:", parse_mode=ParseMode.HTML)

@dp.message(GiftState.waiting_note, F.chat.type == "private")
async def process_gift_note(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Tuliskan pesan singkat dalam bentuk teks.")
    await state.update_data(note=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕵️ Kirim Secara Anonim", callback_data="sendgift_anon")],
        [InlineKeyboardButton(text="🥂 Tampilkan Namaku", callback_data="sendgift_public")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="back_home")]
    ])
    await message.answer("Bagaimana cara pelayan kami menyampaikan hadiah ini?", reply_markup=kb)

@dp.callback_query(F.data.startswith("sendgift_"))
async def cb_send_gift_exec(call: types.CallbackQuery, state: FSMContext):
    mode = call.data.split("_")[1]
    data = await state.get_data()
    if not data:
        return await call.answer("Sesi hadiah kedaluwarsa. Ulangi dari menu utama.", show_alert=True)
    await state.clear()

    code = data["gift_code"]
    name, price, sell_val, charm = GIFTS_CATALOG[code]
    sender_id = call.from_user.id
    target_id = data["target_id"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender_id)
            if not coins or coins < price:
                return await call.answer("Koin tidak cukup!", show_alert=True)
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", price, sender_id)
            await conn.execute("""
                UPDATE users 
                SET charm_points = charm_points + $1, last_active = last_active + INTERVAL '15 minutes'
                WHERE user_id = $2
            """, charm, target_id)
            await conn.execute(
                "INSERT INTO inventory (user_id, item_code, item_name, sell_value) VALUES ($1, $2, $3, $4)",
                target_id, code, name, sell_val
            )

    await call.answer("Hadiah terkirim!")
    sender_label = "<b>Pengagum Rahasia (Anonim)</b>" if mode == "anon" else f"<a href='tg://user?id={sender_id}'>{call.from_user.first_name}</a>"
    announce = (
        f"🎁 <b>SPECIAL DELIVERY — THE VELVET HOUR</b>\n"
        f"Waitress Clara mengantarkan <b>{name}</b> ke meja <a href='tg://user?id={target_id}'>{data['target_name']}</a>!\n\n"
        f"💌 <i>\"{data['note']}\"</i>\n"
        f"— Dari: {sender_label} <i>(+{charm} Charm & +15m Waktu Lounge)</i>"
    )
    try:
        await julian_bot.send_message(GROUP_ID, announce, parse_mode=ParseMode.HTML)
        await call.message.edit_text("✅ Hadiah berhasil diantarkan ke meja utama!", reply_markup=back_home_kb())
    except Exception as e:
        await call.message.edit_text(f"⚠️ Hadiah masuk ke tas penerima, tapi gagal diumumkan di grup: <code>{e}</code>", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

# --- TAS KOLEKSI, PENUKARAN GIFT & VIP PASS ---
@dp.callback_query(F.data == "menu_inv")
async def cb_menu_inv(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    is_vip = await check_vip_status(user_id)
    async with db.pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT coins, charm_points, vip_until FROM users WHERE user_id = $1", user_id)
        items = await conn.fetch("SELECT item_name, COUNT(*) as qty, SUM(sell_value) as total_val FROM inventory WHERE user_id = $1 GROUP BY item_name", user_id)

    inv_lines = "\n".join([f"• {r['item_name']} (x{r['qty']}) — Tukar: {r['total_val']} VC" for r in items]) or "<i>Belum ada hadiah di tasmu.</i>"
    vip_txt = f"Aktif hingga {user_row['vip_until'].strftime('%d %b %H:%M UTC')}" if is_vip else "Tidak Aktif"

    text = (
        f"🎒 <b>TAS & STATUS KEANGGOTAAN</b>\n\n"
        f"💰 <b>Saldo:</b> {user_row['coins']} VC\n"
        f"✨ <b>Charm Points:</b> {user_row['charm_points']} Poin\n"
        f"🍾 <b>Status VIP:</b> {vip_txt}\n\n"
        f"<b>Koleksi Hadiahmu:</b>\n{inv_lines}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🍾 Beli VIP Pass 24 Jam ({VIP_COST_24H} VC)", callback_data="buy_vip_24")],
        [InlineKeyboardButton(text="💰 Cairkan Semua Gift ke Koin (50%)", callback_data="sell_all_gifts")],
        [InlineKeyboardButton(text="🔙 Kembali", callback_data="back_home")]
    ])
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data == "buy_vip_24")
async def cb_buy_vip(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if row["coins"] < VIP_COST_24H:
                return await call.answer("Saldo VC tidak cukup untuk VIP Pass!", show_alert=True)
            base_time = row["vip_until"] if (row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow()) else datetime.utcnow()
            new_until = base_time + timedelta(hours=24)
            await conn.execute(
                "UPDATE users SET coins = coins - $1, is_vip = TRUE, vip_until = $2 WHERE user_id = $3",
                VIP_COST_24H, new_until, user_id
            )
    await call.answer("Selamat! VIP Pass 24 Jam telah aktif.", show_alert=True)
    await cb_menu_inv(call)

@dp.callback_query(F.data == "sell_all_gifts")
async def cb_sell_all_gifts(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            total_val = await conn.fetchval("SELECT COALESCE(SUM(sell_value), 0) FROM inventory WHERE user_id = $1", user_id)
            if total_val == 0:
                return await call.answer("Tidak ada hadiah yang bisa dicairkan.", show_alert=True)
            await conn.execute("DELETE FROM inventory WHERE user_id = $1", user_id)
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", total_val, user_id)
    await call.answer(f"Berhasil menukar hadiah menjadi +{total_val} VC!", show_alert=True)
    await cb_menu_inv(call)

# --- PANEL KENDALI STAF (OWNER vs ADMIN) ---
@dp.callback_query(F.data == "staff_panel")
async def cb_staff_panel(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not await is_staff_or_owner(user_id):
        return await call.answer("Akses ditolak.", show_alert=True)

    await call.answer()
    buttons = [
        [InlineKeyboardButton(text="💰 Top Up Koin Tamu", callback_data="adm_topup")],
        [InlineKeyboardButton(text="📊 Statistik Lounge", callback_data="adm_stats")]
    ]
    if user_id == OWNER_ID:
        buttons.extend([
            [
                InlineKeyboardButton(text="➕ Angkat Admin", callback_data="own_add_admin"),
                InlineKeyboardButton(text="➖ Copot Admin", callback_data="own_rem_admin")
            ],
            [
                InlineKeyboardButton(text="🔑 Ganti Password Pintu", callback_data="own_set_pass"),
                InlineKeyboardButton(text="🔒 Buka/Tutup Bar", callback_data="own_toggle_bar")
            ],
            [InlineKeyboardButton(text="📢 Broadcast Semua Tamu", callback_data="own_broadcast")]
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="back_home")])

    role_title = "👑 OWNER CONTROL PANEL" if user_id == OWNER_ID else "🛡️ ADMIN BAR PANEL"
    await call.message.edit_text(
        f"<b>{role_title}</b>\nPilih tindakan pengelolaan bar di bawah ini:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data == "adm_stats")
async def cb_adm_stats(call: types.CallbackQuery):
    async with db.pool.acquire() as conn:
        total_u = await conn.fetchval("SELECT COUNT(*) FROM users")
        in_bar = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_in_bar = TRUE")
        total_c = await conn.fetchval("SELECT COALESCE(SUM(coins), 0) FROM users")
        cur_pass = await conn.fetchval("SELECT value FROM bar_settings WHERE key = 'door_password'")
    await call.answer(
        f"Total Tamu: {total_u} | Aktif di Bar: {in_bar}\nKoin Beredar: {total_c} VC | Sandi: {cur_pass}",
        show_alert=True
    )

@dp.callback_query(F.data == "adm_topup")
async def cb_adm_topup(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AdminState.waiting_topup)
    await call.message.edit_text("Kirim format: <code>@username jumlah_koin</code>\nContoh: <code>@alvaro 500</code>", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.message(AdminState.waiting_topup, F.chat.type == "private")
async def process_adm_topup(message: types.Message, state: FSMContext):
    if not await is_staff_or_owner(message.from_user.id):
        return
    try:
        parts = message.text.strip().split()
        uname = parts[0].lstrip("@")
        amt = int(parts[1])
        async with db.pool.acquire() as conn:
            res = await conn.execute("UPDATE users SET coins = coins + $1 WHERE LOWER(username) = LOWER($2)", amt, uname)
        await state.clear()
        await message.answer(f"✅ Berhasil menambahkan <b>{amt} VC</b> ke @{uname}. ({res})", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())
    except Exception:
        await message.answer("Format salah. Gunakan: <code>@username jumlah</code>", parse_mode=ParseMode.HTML)

# --- AKSI EKSKLUSIF OWNER ---
@dp.callback_query(F.data == "own_add_admin")
async def cb_own_add_admin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.answer()
    await state.set_state(AdminState.waiting_add_admin)
    await call.message.edit_text("Kirim <b>@username</b> atau <b>User ID</b> yang ingin diangkat menjadi Admin Bar:", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.message(AdminState.waiting_add_admin, F.chat.type == "private")
async def process_own_add_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    target = message.text.strip().lstrip("@")
    async with db.pool.acquire() as conn:
        if target.isdigit():
            await conn.execute("UPDATE users SET is_admin = TRUE WHERE user_id = $1", int(target))
        else:
            await conn.execute("UPDATE users SET is_admin = TRUE WHERE LOWER(username) = LOWER($1)", target)
    await state.clear()
    await message.answer(f"✅ <b>{target}</b> kini memiliki akses Admin Bar.", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.callback_query(F.data == "own_rem_admin")
async def cb_own_rem_admin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.answer()
    await state.set_state(AdminState.waiting_rem_admin)
    await call.message.edit_text("Kirim <b>@username</b> atau <b>User ID</b> yang ingin dicopot akses Admin-nya:", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.message(AdminState.waiting_rem_admin, F.chat.type == "private")
async def process_own_rem_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    target = message.text.strip().lstrip("@")
    async with db.pool.acquire() as conn:
        if target.isdigit():
            await conn.execute("UPDATE users SET is_admin = FALSE WHERE user_id = $1", int(target))
        else:
            await conn.execute("UPDATE users SET is_admin = FALSE WHERE LOWER(username) = LOWER($1)", target)
    await state.clear()
    await message.answer(f"✅ Akses Admin untuk <b>{target}</b> telah dicabut.", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.callback_query(F.data == "own_set_pass")
async def cb_own_set_pass(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.answer()
    await state.set_state(AdminState.waiting_new_pass)
    await call.message.edit_text("Ketik <b>kata sandi pintu masuk</b> yang baru (tanpa spasi):", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.message(AdminState.waiting_new_pass, F.chat.type == "private")
async def process_own_set_pass(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    new_pass = message.text.strip().upper()
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE bar_settings SET value = $1 WHERE key = 'door_password'", new_pass)
    await state.clear()
    await message.answer(f"🔑 Kata sandi pintu berhasil diperbarui menjadi: <code>{new_pass}</code>", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.callback_query(F.data == "own_toggle_bar")
async def cb_own_toggle_bar(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return
    async with db.pool.acquire() as conn:
        cur = await conn.fetchval("SELECT value FROM bar_settings WHERE key = 'bar_open'")
        new_val = "false" if cur == "true" else "true"
        await conn.execute("UPDATE bar_settings SET value = $1 WHERE key = 'bar_open'", new_val)

    try:
        if new_val == "true":
            await julian_bot.set_chat_permissions(GROUP_ID, types.ChatPermissions(can_send_messages=True, can_send_other_messages=True))
            await julian_bot.send_message(GROUP_ID, "🔓 <b>Pintu The Velvet Hour telah dibuka!</b> Selamat datang dan selamat menikmati malam ini.", parse_mode=ParseMode.HTML)
            await call.answer("Bar dibuka!", show_alert=True)
        else:
            await julian_bot.set_chat_permissions(GROUP_ID, types.ChatPermissions(can_send_messages=False))
            await julian_bot.send_message(GROUP_ID, "🔒 <b>Jam Operasional Berakhir.</b> Pintu bar ditutup sementara oleh Owner.", parse_mode=ParseMode.HTML)
            await call.answer("Bar dikunci!", show_alert=True)
    except Exception as e:
        await call.answer(f"Status DB berubah, tapi gagal atur grup: {e}", show_alert=True)

@dp.callback_query(F.data == "own_broadcast")
async def cb_own_broadcast(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.answer()
    await state.set_state(AdminState.waiting_broadcast)
    await call.message.edit_text("Kirim pesan pengumuman yang akan disebarkan ke seluruh tamu terdaftar:", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

@dp.message(AdminState.waiting_broadcast, F.chat.type == "private")
async def process_own_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    await state.clear()
    async with db.pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    sent_count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], f"📢 <b>PENGUMUMAN THE VELVET HOUR</b>\n\n{message.text}", parse_mode=ParseMode.HTML)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Pengumuman terkirim ke <b>{sent_count}</b> tamu.", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

async def register_private_commands():
    commands = [
        BotCommand(command="start", description="Ketuk pintu utama The Velvet Hour"),
        BotCommand(command="daily", description="Klaim jatah Velvet Coins harian (+30 VC)"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())

async def main():
    await db.init_db()
    await register_private_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
