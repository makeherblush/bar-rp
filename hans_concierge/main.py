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
    waiting_new_shop = State()

class ShopSellerState(StatesGroup):
    waiting_media = State()
    waiting_name = State()
    waiting_price = State()
    waiting_desc = State()

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

async def get_owned_shops(user_id: int):
    async with db.pool.acquire() as conn:
        if user_id == OWNER_ID:
            return await conn.fetch("SELECT id, shop_name, owner_id, owner_username FROM partner_shops ORDER BY id ASC")
        return await conn.fetch("SELECT id, shop_name, owner_id, owner_username FROM partner_shops WHERE owner_id = $1 ORDER BY id ASC", user_id)

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
            InlineKeyboardButton(text="🏪 Pojok Lapak Partner", callback_data="shops_hub"),
            InlineKeyboardButton(text="🏆 Hall of Fame", callback_data="hall_of_fame")
        ],
        [
            InlineKeyboardButton(text="📖 Pusat Panduan", callback_data="info_hub"),
            InlineKeyboardButton(text="☕ Support & Donate", callback_data="info_donate")
        ]
    ]

    owned_shops = await get_owned_shops(user_id)
    if owned_shops and user_id != OWNER_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Kelola Lapak Saya", callback_data="my_shops_manage")])

    if await is_staff_or_owner(user_id):
        buttons.append([InlineKeyboardButton(text="🛡️ Panel Kendali Staf", callback_data="staff_panel")])

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
    "<i>Silakan periksa Pusat Panduan jika baru pertama kali berkunjung, atau buktikan bahwa kamu memang tamu undangan kami.</i>"
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

# =====================================================================
# --- PUSAT PANDUAN INTERAKTIF (MULTI-BUTTON & RAMAH PEMULA) ---
# =====================================================================
def info_hub_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🥂 Cara Bermain", callback_data="info_guide"),
            InlineKeyboardButton(text="📜 Rules & Atribut", callback_data="info_rules")
        ],
        [
            InlineKeyboardButton(text="💎 Koin VC & Charm", callback_data="info_eco"),
            InlineKeyboardButton(text="💼 Kerja Paruh Waktu", callback_data="info_jobs")
        ],
        [
            InlineKeyboardButton(text="🍾 Keuntungan VIP", callback_data="info_vip"),
            InlineKeyboardButton(text="🏪 Cara Beli di Lapak", callback_data="info_shops")
        ],
        [
            InlineKeyboardButton(text="🍸 Command Bar", callback_data="info_cmd_bar"),
            InlineKeyboardButton(text="🎧 Command Musik", callback_data="info_cmd_music")
        ],
        [InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")]
    ])

def back_info_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali ke Pusat Panduan", callback_data="info_hub")],
        [InlineKeyboardButton(text="🔙 Pintu Depan", callback_data="back_home")]
    ])

@dp.callback_query(F.data == "info_hub")
async def cb_info_hub(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "📖 <b>PUSAT PANDUAN — THE VELVET HOUR</b>\n\n"
        "<i>Hans menunjuk papan kayu berukir di sisi lorong yang memuat berbagai catatan penting bagi tamu.</i>\n\n"
        "Pilih topik di bawah ini untuk membaca penjelasan singkat dan daftar perintahnya:",
        parse_mode=ParseMode.HTML,
        reply_markup=info_hub_kb()
    )

@dp.callback_query(F.data == "info_guide")
async def cb_info_guide(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🥂 <b>PANDUAN BERKUNJUNG — THE VELVET HOUR</b>\n\n"
        "<b>1. Sistem Berkunjung & Pulang:</b>\n"
        "• Jika kamu diam tanpa chat selama <b>60 menit</b> (atau <b>120 menit</b> untuk VIP), Waitress Clara akan memberi peringatan, lalu Bouncer Hans akan mengantarmu pulang (<i>auto-kick</i>).\n"
        "• Saldo koin dan koleksi hadiahmu tetap aman. Ketuk pintu ini lagi kapan pun kamu ingin mampir kembali.\n\n"
        "<b>2. Interaksi di Ruang Utama:</b>\n"
        "• Pesan minuman (<code>/order</code>), makanan (<code>/eat</code>), lagu (<code>/reqsong</code>), atau mainkan roulette (<code>/mystery</code>).\n"
        "• Gunakan <code>/checkin</code> jika hanya menyimak obrolan, atau <code>/checkout</code> jika pamit pulang."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@dp.callback_query(F.data == "info_rules")
async def cb_info_rules(call: types.CallbackQuery):
    await call.answer()
    text = (
        "📜 <b>ATURAN TAK TERTULIS THE VELVET HOUR</b>\n\n"
        "<b>1. Wajib Atribut Resmi (Dresscode):</b>\n"
        f"• Selama di dalam bar, kamu <b>wajib</b> menyematkan simbol <b>{REQUIRED_CN_SYMBOL}</b> pada nama profil Telegram-mu (Contoh: <code>Alvaro {REQUIRED_CN_SYMBOL}</code>). Melepas atribut di dalam ruangan berakibat diantar keluar.\n\n"
        "<b>2. Jaga Suasana Roleplay:</b>\n"
        "• Dilarang membawa drama OOC, ujaran kebencian, atau keributan.\n"
        "• Obrolan suara (Voice Chat) khusus untuk mendengarkan musik lounge (mikrofon tamu dikunci).\n\n"
        "<b>3. Anti-Spam:</b>\n"
        "• Timer pasif hanya ter-reset oleh obrolan minimal 3 kata atau perintah RP."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@dp.callback_query(F.data == "info_eco")
async def cb_info_eco(call: types.CallbackQuery):
    await call.answer()
    text = (
        "💎 <b>VELVET COINS (VC) & CHARM POINTS</b>\n\n"
        "<b>• Apa itu Velvet Coins (VC)?</b>\n"
        "Mata uang resmi bar untuk memutar lagu di speaker grup, membeli VIP Pass, mengirim gift, dan jajan di <b>Pojok Lapak Partner</b>.\n\n"
        "<b>• Sumber Koin:</b>\n"
        "Modal awal 200 VC, Absen harian <code>/daily</code> (+30 VC), keaktifan chat RP (+1 VC/pesan), dan upah kerja paruh waktu (+120 VC).\n\n"
        "<b>• Apa itu Charm Points?</b>\n"
        "Poin pesona yang kamu dapatkan setiap kali <b>menerima Gift</b> dari tamu lain. Semakin tinggi Charm, semakin tinggi posisimu di <b>Hall of Fame</b>!\n\n"
        "<b>• Penukaran Gift:</b>\n"
        "Hadiah yang masuk ke tasmu bisa dicairkan menjadi koin (nilai tukar <b>50%</b>) di menu <i>Tas & VIP Pass</i>."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Top Up Koin (Hubungi Owner)", url=f"https://t.me/{OWNER_USERNAME}")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Pusat Panduan", callback_data="info_hub")]
    ])
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data == "info_jobs")
async def cb_info_jobs(call: types.CallbackQuery):
    await call.answer()
    text = (
        "💼 <b>CARA KERJA PARUH WAKTU (GAJI 120 VC)</b>\n\n"
        "Kamu <b>tidak perlu</b> menunggu 2 jam penuh untuk gajian! Angka 2 jam hanyalah batas waktu maksimal shift sebelum ditutup otomatis.\n\n"
        "<b>Alur Singkat Mendapatkan Gaji:</b>\n"
        "1. Ketik <code>/apply</code> di ruang utama untuk memilih posisi (<i>bartender, waiter, host,</i> atau <i>dj</i>).\n"
        "2. Lakukan <b>minimal 5x aksi layanan</b> sesuai posisimu:\n"
        "   • <b>🍸 Bartender:</b> <code>/mix</code>, <code>/sober</code>\n"
        "   • <b>🍽️ Waiter:</b> <code>/welcome</code>, <code>/dish</code>\n"
        "   • <b>🎩 Host:</b> <code>/ambience</code>, <code>/toastall</code>\n"
        "   • <b>🎶 Resident DJ:</b> <code>/spinmusic</code>, <code>/dedicate</code>\n"
        "3. Cek progres kapan saja lewat <code>/myshift</code>.\n"
        "4. Begitu mencapai <b>5/5 layanan</b>, ketik <code>/endshift</code> — gaji <b>120 VC</b> langsung cair detik itu juga!"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@dp.callback_query(F.data == "info_vip")
async def cb_info_vip(call: types.CallbackQuery):
    await call.answer()
    text = (
        f"🍾 <b>KEUNTUNGAN VIP PASS ({VIP_COST_24H} VC / 24 JAM)</b>\n\n"
        "• <b>Gratis Request Lagu Sepuasnya:</b> Pakai <code>/reqsong</code> di ruang utama tanpa dipotong koin.\n"
        "• <b>Spotlight Pin Promote:</b> Kartu promotemu otomatis di-pin di CH Promote + boleh melampirkan foto & teks hingga 800 karakter.\n"
        "• <b>Promote Lebih Cepat:</b> Cooldown promote dipangkas dari 45 menit menjadi <b>30 menit</b>.\n"
        "• <b>Waktu Santai 2x Lebih Lama:</b> Batas anti-idle diperpanjang dari 60 menit menjadi <b>120 menit</b>.\n"
        "• <b>Lencana Eksklusif:</b> Tanda 🍾 muncul di daftar tamu lounge."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎒 Buka Menu VIP Pass", callback_data="menu_inv")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Pusat Panduan", callback_data="info_hub")]
    ])
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data == "info_shops")
async def cb_info_shops(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🏪 <b>POJOK LAPAK PARTNER (TRANSAKSI PAKAI VC)</b>\n\n"
        "Area khusus bagi rekan/partner resmi <i>The Velvet Hour</i> untuk memajang katalog koleksi mereka (seperti ikan cupang, jasa, atau item koleksi lainnya).\n\n"
        "• Buka tombol <b>🏪 Pojok Lapak Partner</b> untuk melihat daftar toko yang buka.\n"
        "• Pilih produk untuk melihat stiker/foto dan deskripsinya.\n"
        "• Klik <b>Beli Sekarang</b> untuk membayar langsung memakai <b>Velvet Coins (VC)</b> dan terhubung ke chat pemilik toko."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@dp.callback_query(F.data == "info_cmd_bar")
async def cb_info_cmd_bar(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🍸 <b>COMMAND TAMU DI RUANG UTAMA (GRUP)</b>\n\n"
        "• <code>/order</code> — Buka buku menu minuman & pesan ke Julian\n"
        "• <code>/eat</code> — Buka buku menu makanan & pesan ke Clara\n"
        "• <code>/bill</code> — Cek saldo VC, status VIP, dan Charm Points\n"
        "• <code>/mystery</code> — Putar Bar Roulette (40 VC)\n"
        "• <code>/toast @username</code> — Ajak bersulang tamu lain\n"
        "• <code>/guests</code> — Lihat daftar tamu di dalam lounge\n"
        "• <code>/topcharm</code> — Lihat papan peringkat Charm di grup\n"
        "• <code>/checkin</code> — Perbarui timer santai (anti-idle)\n"
        "• <code>/checkout</code> — Pamit keluar dari ruang bar"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@dp.callback_query(F.data == "info_cmd_music")
async def cb_info_cmd_music(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🎧 <b>COMMAND MUSIK & KURATOR KAELEN</b>\n\n"
        "<b>Untuk Semua Tamu:</b>\n"
        "• <code>/reqsong Judul Lagu - Penyanyi</code>\n"
        "  Putar lagu di Obrolan Suara grup (15 VC, gratis untuk VIP & DJ).\n"
        "• <code>/myearphone Judul Lagu - Penyanyi</code>\n"
        "  Kirim file lagu MP3 langsung ke chat pribadimu.\n\n"
        "<b>Khusus Staf Shift Resident DJ & Staff:</b>\n"
        "• <code>/spinmusic Judul - Penyanyi</code> — Putar lagu prioritas #1\n"
        "• <code>/dedicate @user Judul - Penyanyi | Pesan</code> — Lagu dedikasi\n"
        "• <code>/skip</code> — Lewati lagu yang sedang diputar\n"
        "• <code>/stopmusic</code> — Hentikan musik & bersihkan antrean"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

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

# =====================================================================
# --- HALL OF FAME: LEADERBOARD TOP SULTAN & TOP CHARM ---
# =====================================================================
@dp.callback_query(F.data == "hall_of_fame")
async def cb_hall_of_fame(call: types.CallbackQuery):
    await call.answer()
    async with db.pool.acquire() as conn:
        sultans = await conn.fetch(
            "SELECT full_name, gifts_sent_vc FROM users WHERE gifts_sent_vc > 0 ORDER BY gifts_sent_vc DESC LIMIT 7"
        )
        charms = await conn.fetch(
            "SELECT full_name, charm_points FROM users WHERE charm_points > 0 ORDER BY charm_points DESC LIMIT 7"
        )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

    if sultans:
        sultan_lines = "\n".join([f"{medals[i]} <b>{r['full_name']}</b> — {r['gifts_sent_vc']} VC" for i, r in enumerate(sultans)])
    else:
        sultan_lines = "<i>Belum ada transaksi gift tercatat.</i>"

    if charms:
        charm_lines = "\n".join([f"{medals[i]} <b>{r['full_name']}</b> — {r['charm_points']} Charm" for i, r in enumerate(charms)])
    else:
        charm_lines = "<i>Belum ada tamu yang mengumpulkan Charm.</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Kirim Gift Sekarang", callback_data="menu_shop")],
        [InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")]
    ])
    await call.message.edit_text(
        "🏆 <b>HALL OF FAME — THE VELVET HOUR</b>\n\n"
        "💎 <b>TOP SULTAN (Pemberi Gift Terbanyak):</b>\n"
        f"{sultan_lines}\n\n"
        "✨ <b>TOP CHARM (Penerima Gift Terbanyak):</b>\n"
        f"{charm_lines}\n\n"
        "<i>Kirimkan hadiah melalui Bar Boutique untuk menaikkan peringkat Sultanmu dan memberi poin Charm kepada penerima!</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

# =====================================================================
# --- POJOK LAPAK PARTNER (MULTI-TOKO DINAMIS VIA DB) ---
# =====================================================================
@dp.callback_query(F.data == "shops_hub")
async def cb_shops_hub(call: types.CallbackQuery):
    await call.answer()
    async with db.pool.acquire() as conn:
        shops = await conn.fetch("SELECT id, shop_name, owner_username FROM partner_shops ORDER BY id ASC")

    if not shops:
        return await call.message.edit_text(
            "🏪 <b>POJOK LAPAK PARTNER — THE VELVET HOUR</b>\n\n"
            "<i>Belum ada lapak partner yang dibuka di sudut lounge saat ini.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_kb()
        )

    btns = [
        [InlineKeyboardButton(text=f"{s['shop_name']}", callback_data=f"openshop_{s['id']}")]
        for s in shops
    ]
    btns.append([InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")])

    await call.message.edit_text(
        "🏪 <b>POJOK LAPAK PARTNER — THE VELVET HOUR</b>\n\n"
        "<i>Di sudut ruangan yang diterangi lampu temaram, tersedia beberapa etalase eksklusif milik rekan resmi bar.</i>\n\n"
        "Pilih lapak yang ingin kamu kunjungi:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )

@dp.callback_query(F.data.startswith("openshop_"))
async def cb_open_shop(call: types.CallbackQuery):
    await call.answer()
    shop_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        shop = await conn.fetchrow("SELECT shop_name, owner_username FROM partner_shops WHERE id = $1", shop_id)
        items = await conn.fetch(
            "SELECT id, name, price_vc FROM shop_items WHERE shop_id = $1 AND is_sold = FALSE ORDER BY id DESC LIMIT 25",
            shop_id
        )

    if not shop:
        return await call.message.edit_text("Lapak tidak ditemukan.", reply_markup=back_home_kb())

    owner_txt = f" (@{shop['owner_username']})" if shop["owner_username"] else ""
    if not items:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Daftar Lapak Lain", callback_data="shops_hub")],
            [InlineKeyboardButton(text="🔙 Pintu Depan", callback_data="back_home")]
        ])
        return await call.message.edit_text(
            f"🏪 <b>{shop['shop_name']}</b>{owner_txt}\n\n"
            "<i>Etalase lapak ini sedang kosong atau semua koleksi sudah terjual.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )

    btns = [
        [InlineKeyboardButton(text=f"• {it['name']} — {it['price_vc']} VC", callback_data=f"viewitem_{it['id']}")]
        for it in items
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Daftar Lapak Lain", callback_data="shops_hub")])
    btns.append([InlineKeyboardButton(text="🔙 Pintu Depan", callback_data="back_home")])

    await call.message.edit_text(
        f"🏪 <b>{shop['shop_name']}</b>{owner_txt}\n\n"
        "Pilih produk di bawah ini untuk melihat stiker/foto, deskripsi, dan membeli dengan <b>Velvet Coins (VC)</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )

@dp.callback_query(F.data.startswith("viewitem_"))
async def cb_view_shop_item(call: types.CallbackQuery):
    item_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        item = await conn.fetchrow("""
            SELECT i.*, s.shop_name, s.owner_username
            FROM shop_items i
            JOIN partner_shops s ON i.shop_id = s.id
            WHERE i.id = $1 AND i.is_sold = FALSE
        """, item_id)

    if not item:
        return await call.answer("Maaf, item ini sudah terjual atau ditarik seller!", show_alert=True)

    await call.answer()
    if item["media_type"] == "sticker" and item["media_file_id"]:
        try:
            await call.message.answer_sticker(item["media_file_id"])
        except Exception:
            pass
    elif item["media_type"] == "photo" and item["media_file_id"]:
        try:
            await call.message.answer_photo(item["media_file_id"])
        except Exception:
            pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Beli Sekarang ({item['price_vc']} VC)", callback_data=f"buyitem_{item['id']}")],
        [InlineKeyboardButton(text=f"⬅️ Kembali ke {item['shop_name']}", callback_data=f"openshop_{item['shop_id']}")]
    ])
    await call.message.answer(
        f"🏷️ <b>{item['name']}</b>\n"
        f"<i>Lapak: {item['shop_name']}</i>\n\n"
        f"• <b>Harga:</b> {item['price_vc']} Velvet Coins (VC)\n"
        f"• <b>Keterangan:</b> {item['description']}\n\n"
        "<i>Klik tombol di bawah untuk membayar otomatis menggunakan saldo VC kamu.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("buyitem_"))
async def cb_buy_shop_item(call: types.CallbackQuery):
    item_id = int(call.data.split("_")[1])
    buyer = call.from_user

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            item = await conn.fetchrow("""
                SELECT i.*, s.shop_name, s.owner_id, s.owner_username
                FROM shop_items i
                JOIN partner_shops s ON i.shop_id = s.id
                WHERE i.id = $1 FOR UPDATE
            """, item_id)

            if not item or item["is_sold"]:
                return await call.answer("Terlambat! Item ini baru saja dibeli tamu lain.", show_alert=True)

            if buyer.id == item["owner_id"]:
                return await call.answer("Kamu tidak bisa membeli produk dari lapakmu sendiri.", show_alert=True)

            buyer_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", buyer.id)
            if not buyer_coins or buyer_coins < item["price_vc"]:
                return await call.answer(f"Saldo VC tidak cukup (butuh {item['price_vc']} VC).", show_alert=True)

            # Potong saldo pembeli & kirim ke pemilik toko
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", item["price_vc"], buyer.id)
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, coins)
                VALUES ($1, $2, 'Partner Seller', $3)
                ON CONFLICT (user_id) DO UPDATE SET coins = users.coins + $3;
            """, item["owner_id"], item["owner_username"] or "Seller", item["price_vc"])

            await conn.execute("UPDATE shop_items SET is_sold = TRUE, buyer_id = $1 WHERE id = $2", buyer.id, item_id)

    await call.answer("Pembelian berhasil!")

    # Kirim notifikasi DM ke pemilik toko
    try:
        buyer_tag = f"@{buyer.username}" if buyer.username else f"<a href='tg://user?id={buyer.id}'>{buyer.first_name}</a>"
        await bot.send_message(
            item["owner_id"],
            f"🔔 <b>PESANAN BARU — {item['shop_name']}!</b>\n\n"
            f"• <b>Produk:</b> {item['name']}\n"
            f"• <b>Pembayaran:</b> +{item['price_vc']} VC (Sudah masuk ke dompetmu)\n"
            f"• <b>Pembeli:</b> {buyer.full_name} ({buyer_tag})\n\n"
            "<i>Silakan hubungi pembeli untuk koordinasi pengiriman/serah terima barang.</i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.warning(f"Gagal kirim notif ke seller {item['owner_id']}: {e}")

    btns = []
    if item["owner_username"]:
        btns.append([InlineKeyboardButton(text=f"💬 Hubungi Seller (@{item['owner_username']})", url=f"https://t.me/{item['owner_username']}")])
    btns.append([InlineKeyboardButton(text="🔙 Kembali ke Pintu Depan", callback_data="back_home")])

    await call.message.edit_text(
        f"✅ <b>TRANSAKSI BERHASIL!</b>\n\n"
        f"Kamu telah membeli <b>{item['name']}</b> dari <b>{item['shop_name']}</b> seharga <b>{item['price_vc']} VC</b>.\n\n"
        "Pemilik lapak sudah menerima notifikasi pembayaranmu—silakan hubungi seller melalui tombol di bawah:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )

# --- PANEL KELOLA LAPAK MILIK SELLER / OWNER ---
@dp.callback_query(F.data == "my_shops_manage")
async def cb_my_shops_manage(call: types.CallbackQuery):
    shops = await get_owned_shops(call.from_user.id)
    if not shops:
        return await call.answer("Kamu tidak terdaftar sebagai pemilik lapak.", show_alert=True)

    await call.answer()
    btns = [
        [InlineKeyboardButton(text=f"⚙️ Kelola: {s['shop_name']}", callback_data=f"mngshop_{s['id']}")]
        for s in shops
    ]
    btns.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="back_home")])
    await call.message.edit_text(
        "⚙️ <b>KELOLA LAPAK PARTNER</b>\n\nPilih lapak yang ingin kamu atur katalognya:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )

@dp.callback_query(F.data.startswith("mngshop_"))
async def cb_manage_single_shop(call: types.CallbackQuery):
    shop_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        shop = await conn.fetchrow("SELECT id, shop_name, owner_id FROM partner_shops WHERE id = $1", shop_id)

    if not shop or (call.from_user.id != OWNER_ID and call.from_user.id != shop["owner_id"]):
        return await call.answer("Akses ditolak.", show_alert=True)

    await call.answer()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Tambah Produk Baru", callback_data=f"shopadd_{shop_id}")],
        [InlineKeyboardButton(text="🗑️ Hapus Produk dari Etalase", callback_data=f"shopdel_{shop_id}")],
        [InlineKeyboardButton(text="📢 Siarkan Restock ke Grup", callback_data=f"shopann_{shop_id}")],
        [InlineKeyboardButton(text="🔙 Kembali ke Menu Utama", callback_data="back_home")]
    ])
    await call.message.edit_text(
        f"⚙️ <b>PANEL SELLER — {shop['shop_name']}</b>\n\n"
        "Kelola koleksi produk yang dipajang di sudut bar:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("shopadd_"))
async def cb_shop_add_start(call: types.CallbackQuery, state: FSMContext):
    shop_id = int(call.data.split("_")[1])
    await call.answer()
    await state.update_data(target_shop_id=shop_id)
    await state.set_state(ShopSellerState.waiting_media)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Lewati (Tanpa Sticker/Foto)", callback_data="shop_skip_media")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="back_home")]
    ])
    await call.message.edit_text(
        "📦 <b>TAMBAH PRODUK BARU (Langkah 1 dari 4)</b>\n\n"
        "Kirimkan <b>Sticker</b> atau <b>Foto</b> produk sekarang:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@dp.callback_query(F.data == "shop_skip_media", ShopSellerState.waiting_media)
async def cb_shop_skip_media(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(media_type="none", media_file_id=None)
    await state.set_state(ShopSellerState.waiting_name)
    await call.message.edit_text(
        "📦 <b>TAMBAH PRODUK BARU (Langkah 2 dari 4)</b>\n\n"
        "Ketik <b>Nama Produk</b> (contoh: <code>Halfmoon Koi Galaxy</code>):",
        parse_mode=ParseMode.HTML
    )

@dp.message(ShopSellerState.waiting_media, F.chat.type == "private")
async def process_shop_media(message: types.Message, state: FSMContext):
    if message.sticker:
        await state.update_data(media_type="sticker", media_file_id=message.sticker.file_id)
    elif message.photo:
        await state.update_data(media_type="photo", media_file_id=message.photo[-1].file_id)
    else:
        return await message.answer("Kirimkan berupa <b>Sticker</b> atau <b>Foto</b> (atau klik tombol Lewati).", parse_mode=ParseMode.HTML)

    await state.set_state(ShopSellerState.waiting_name)
    await message.answer(
        "📦 <b>TAMBAH PRODUK BARU (Langkah 2 dari 4)</b>\n\n"
        "Ketik <b>Nama Produk</b> (contoh: <code>Avatar Gordon</code>):",
        parse_mode=ParseMode.HTML
    )

@dp.message(ShopSellerState.waiting_name, F.chat.type == "private")
async def process_shop_name(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Ketik nama produk dalam bentuk teks.")
    await state.update_data(item_name=message.text.strip())
    await state.set_state(ShopSellerState.waiting_price)
    await message.answer(
        "📦 <b>TAMBAH PRODUK BARU (Langkah 3 dari 4)</b>\n\n"
        "Masukkan <b>Harga dalam angka Velvet Coins (VC)</b> saja (contoh: <code>500</code>):",
        parse_mode=ParseMode.HTML
    )

@dp.message(ShopSellerState.waiting_price, F.chat.type == "private")
async def process_shop_price(message: types.Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        return await message.answer("Masukkan angka bulat lebih dari 0 (contoh: <code>450</code>):", parse_mode=ParseMode.HTML)
    await state.update_data(item_price=int(message.text.strip()))
    await state.set_state(ShopSellerState.waiting_desc)
    await message.answer(
        "📦 <b>TAMBAH PRODUK BARU (Langkah 4 dari 4)</b>\n\n"
        "Tulis <b>Deskripsi / Spesifikasi Singkat</b> produk:",
        parse_mode=ParseMode.HTML
    )

@dp.message(ShopSellerState.waiting_desc, F.chat.type == "private")
async def process_shop_desc(message: types.Message, state: FSMContext):
    if not message.text:
        return await message.answer("Tulis deskripsi dalam bentuk teks.")
    data = await state.get_data()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO shop_items (shop_id, name, price_vc, description, media_type, media_file_id)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, data["target_shop_id"], data["item_name"], data["item_price"], message.text.strip(), data["media_type"], data["media_file_id"])

    await state.clear()
    await message.answer(
        f"✅ <b>{data['item_name']} ({data['item_price']} VC)</b> berhasil ditambahkan ke etalase lapak!",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Kembali ke Panel Lapak", callback_data=f"mngshop_{data['target_shop_id']}")],
            [InlineKeyboardButton(text="🔙 Pintu Depan", callback_data="back_home")]
        ])
    )

@dp.callback_query(F.data.startswith("shopdel_"))
async def cb_shop_del_list(call: types.CallbackQuery):
    shop_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        items = await conn.fetch("SELECT id, name, price_vc FROM shop_items WHERE shop_id = $1 AND is_sold = FALSE ORDER BY id DESC", shop_id)

    if not items:
        return await call.answer("Tidak ada produk aktif di etalase.", show_alert=True)

    await call.answer()
    btns = [
        [InlineKeyboardButton(text=f"❌ Hapus: {it['name']} ({it['price_vc']} VC)", callback_data=f"delitem_{it['id']}_{shop_id}")]
        for it in items
    ]
    btns.append([InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"mngshop_{shop_id}")])
    await call.message.edit_text("Pilih produk yang ingin dihapus:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("delitem_"))
async def cb_shop_del_exec(call: types.CallbackQuery):
    parts = call.data.split("_")
    item_id, shop_id = int(parts[1]), int(parts[2])
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM shop_items WHERE id = $1", item_id)
    await call.answer("Produk berhasil dihapus!", show_alert=True)
    call.data = f"mngshop_{shop_id}"
    await cb_manage_single_shop(call)

@dp.callback_query(F.data.startswith("shopann_"))
async def cb_shop_announce(call: types.CallbackQuery):
    shop_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        shop = await conn.fetchrow("SELECT shop_name FROM partner_shops WHERE id = $1", shop_id)
    if not shop:
        return

    try:
        await julian_bot.send_message(
            GROUP_ID,
            f"🏪 <b>RESTOCK ALERT — {shop['shop_name']}!</b>\n\n"
            f"<i>Bartender Julian menyalakan lampu sorot ke arah etalase <b>{shop['shop_name']}</b> di sudut lounge. "
            "Koleksi terbaru baru saja dipajang!</i>\n\n"
            "Buka <b>Private Chat Hans</b> $\\rightarrow$ pilih <b>Pojok Lapak Partner</b> untuk melihat katalog dan membelinya dengan <b>Velvet Coins (VC)</b>.",
            parse_mode=ParseMode.HTML
        )
        await call.answer("Pengumuman restock berhasil dikirim ke ruang utama!", show_alert=True)
    except Exception as e:
        await call.answer(f"Gagal mengirim pengumuman: {e}", show_alert=True)

# =====================================================================
# --- ALUR GATEKEEPING 3 LAPIS ---
# =====================================================================
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
            bonus_msg = f"\n\n🎁 <i>Sebagai tamu baru, <b>{WELCOME_BONUS} Velvet Coins</b> telah disimpan ke dompetmu.</i>"
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

# =====================================================================
# --- DAILY CLAIM ---
# =====================================================================
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
        f"🍸 <b>Absen Harian Berhasil!</b> (Hari ke-{streak})\n\n"
        f"Bartender Julian menyerahkan <b>+{reward} Velvet Coins</b> ke dompetmu.",
        parse_mode=ParseMode.HTML
    )

# =====================================================================
# --- PROMOTE & CURHAT ---
# =====================================================================
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
        f"📢 <b>BUAT KARTU PROMOSI</b>\n\n"
        f"Status Meja: {mode_txt}\n\n"
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
            f"❌ <b>Gagal mengirim ke CH Promote:</b>\n<code>{e}</code>",
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
            f"❌ <b>Gagal mengirim catatan ke Grup Utama:</b>\n<code>{e}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_home_kb()
        )

# =====================================================================
# --- BAR BOUTIQUE (TOKO GIFT & SULTAN TRACKER) ---
# =====================================================================
@dp.callback_query(F.data == "menu_shop")
async def cb_menu_shop(call: types.CallbackQuery):
    await call.answer()
    async with db.pool.acquire() as conn:
        coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", call.from_user.id)

    rows = []
    for code, (name, price, _, charm) in GIFTS_CATALOG.items():
        rows.append([InlineKeyboardButton(text=f"{name} — {price} VC (+{charm} Charm)", callback_data=f"buygift_{code}")])
    rows.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="back_home")])

    await call.message.edit_text(
        f"🎁 <b>BAR BOUTIQUE — KATALOG HADIAH</b>\n\n"
        f"Saldo Dompetmu: <b>{coins} VC</b>\n"
        "<i>Hadiah yang dikirim menambah <b>Charm Points</b> penerima & meningkatkan peringkat <b>Top Sultan</b> kamu.</i>\n\n"
        "Pilih hadiah yang ingin kamu kirimkan:",
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
            await conn.execute(
                "UPDATE users SET coins = coins - $1, gifts_sent_vc = COALESCE(gifts_sent_vc, 0) + $1 WHERE user_id = $2",
                price, sender_id
            )
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
        f"🎁 <b>SPECIAL DELIVERY — THE VELVET HOUR</b>\n\n"
        f"Waitress Clara mengantarkan <b>{name}</b> ke meja <a href='tg://user?id={target_id}'>{data['target_name']}</a>!\n\n"
        f"💌 <i>\"{data['note']}\"</i>\n\n"
        f"— Dari: {sender_label} <i>(+{charm} Charm & +15m Waktu Lounge)</i>"
    )
    try:
        await julian_bot.send_message(GROUP_ID, announce, parse_mode=ParseMode.HTML)
        await call.message.edit_text("✅ Hadiah berhasil diantarkan ke meja utama!", reply_markup=back_home_kb())
    except Exception as e:
        await call.message.edit_text(f"⚠️ Hadiah masuk ke tas penerima, tapi gagal diumumkan di grup: <code>{e}</code>", parse_mode=ParseMode.HTML, reply_markup=back_home_kb())

# =====================================================================
# --- TAS KOLEKSI, PENUKARAN GIFT & VIP PASS ---
# =====================================================================
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
        f"<b>Keuntungan VIP Pass (24 Jam):</b>\n"
        f"• Gratis request lagu di grup tanpa potong koin\n"
        f"• Spotlight Pin + lampiran foto di CH Promote\n"
        f"• Cooldown promote 30 menit & anti-idle 2 jam\n\n"
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

# =====================================================================
# --- PANEL KENDALI STAF & KELOLA LAPAK PARTNER (OWNER) ---
# =====================================================================
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
            [InlineKeyboardButton(text="🏪 Kelola Lapak Partner (Tambah/Hapus Toko)", callback_data="own_shops_panel")],
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
        f"<b>{role_title}</b>\n\nPilih tindakan pengelolaan bar di bawah ini:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

# --- SUB-PANEL OWNER: TAMBAH / HAPUS LAPAK PARTNER DINAMIS ---
@dp.callback_query(F.data == "own_shops_panel")
async def cb_own_shops_panel(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return
    await call.answer()
    async with db.pool.acquire() as conn:
        shops = await conn.fetch("SELECT id, shop_name, owner_id, owner_username FROM partner_shops ORDER BY id ASC")

    btns = [[InlineKeyboardButton(text="➕ Buka Lapak Partner Baru", callback_data="own_add_shop")]]
    for s in shops:
        btns.append([
            InlineKeyboardButton(text=f"⚙️ {s['shop_name']}", callback_data=f"mngshop_{s['id']}"),
            InlineKeyboardButton(text="🗑️ Tutup Lapak", callback_data=f"own_del_shop_{s['id']}")
        ])
    btns.append([InlineKeyboardButton(text="⬅️ Kembali ke Panel Owner", callback_data="staff_panel")])

    shop_list_txt = "\n".join([
        f"• <b>{s['shop_name']}</b> — Owner: <code>{s['owner_id']}</code> (@{s['owner_username'] or '-'})"
        for s in shops
    ]) or "<i>Belum ada lapak partner terdaftar.</i>"

    await call.message.edit_text(
        "🏪 <b>MANAJEMEN LAPAK PARTNER (OWNER)</b>\n\n"
        f"{shop_list_txt}\n\n"
        "<i>Klik <b>Buka Lapak Partner Baru</b> untuk mendaftarkan toko baru beserta pemiliknya tanpa perlu edit kode/variabel.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )

@dp.callback_query(F.data == "own_add_shop")
async def cb_own_add_shop(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await call.answer()
    await state.set_state(AdminState.waiting_new_shop)
    await call.message.edit_text(
        "🏪 <b>BUKA LAPAK PARTNER BARU</b>\n\n"
        "Kirim data dengan format (pisahkan dengan tanda <code>|</code>):\n"
        "<code>Nama Lapak | User_ID_Pemilik | @username_pemilik</code>\n\n"
        "<b>Contoh:</b>\n"
        "<code>🐠 The Velvet Aquarium | 123456789 | @rizkybetta</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_kb()
    )

@dp.message(AdminState.waiting_new_shop, F.chat.type == "private")
async def process_own_add_shop(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID or not message.text:
        return
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer(
            "Format salah! Gunakan pemisah <code>|</code> dan pastikan User ID berupa angka.\n\n"
            "Contoh: <code>🐠 The Velvet Aquarium | 123456789 | @rizkybetta</code>",
            parse_mode=ParseMode.HTML
        )

    shop_name = parts[0]
    owner_id = int(parts[1])
    owner_uname = parts[2].lstrip("@") if len(parts) >= 3 else ""

    async with db.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO partner_shops (shop_name, owner_id, owner_username) VALUES ($1, $2, $3)",
            shop_name, owner_id, owner_uname
        )

    await state.clear()
    await message.answer(
        f"✅ Lapak <b>{shop_name}</b> berhasil dibuka untuk pemilik <code>{owner_id}</code> (@{owner_uname or '-'})!\n\n"
        "Pemilik tersebut sekarang otomatis melihat tombol <b>⚙️ Kelola Lapak Saya</b> saat membuka bot Hans.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_home_kb()
    )

@dp.callback_query(F.data.startswith("own_del_shop_"))
async def cb_own_del_shop(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return
    shop_id = int(call.data.split("_")[3])
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM partner_shops WHERE id = $1", shop_id)
    await call.answer("Lapak berhasil ditutup & dihapus.", show_alert=True)
    await cb_own_shops_panel(call)

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
