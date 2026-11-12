import asyncio
import random
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import (
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeChatMember,
    InlineKeyboardMarkup, InlineKeyboardButton
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

# --- KONFIGURASI SHIFT KERJA PARUH WAKTU ---
SHIFT_MAX_MINUTES = 20
SHIFT_REQUIRED_ACTIONS = 5
SHIFT_REWARD_VC = 50
MAX_SHIFTS_PER_DAY = 3    # Maksimal 3x shift per hari per tamu

# Kuota staf aktif bersamaan disesuaikan dengan kebutuhan posisi
MAX_ACTIVE_PER_ROLE = {
    "waiter": 4,      # Pelayan butuh paling banyak untuk melayani meja tamu
    "bartender": 2,   # 2 Bartender di balik meja bar
    "host": 2,        # 2 Lounge Host pemandu suasana
    "dj": 1,          # 1 Resident DJ agar kendali lagu tidak bentrok
}

# --- KATALOG MENU BAR & DAPUR (NARASI ROLEPLAY LENGKAP) ---
DRINKS_MENU = {
    "espresso": (
        "☕ <b>Velvet Double Espresso</b>",
        "<i>Julian menekan tuas mesin espresso kuningan hingga cairan pekat berwarna karamel menetes perlahan ke cangkir porselen hangat.</i>\n\n"
        "<b>\"Espresso ganda tanpa gula—pas untuk menjaga pikiran tetap tajam malam ini.\"</b>"
    ),
    "latte": (
        "🥛 <b>Smoked Vanilla Bean Latte</b>",
        "<i>Julian menuangkan susu hangat berbusa lembut di atas espresso pekat, lalu menaburkan bubuk vanila panggang di permukaannya.</i>\n\n"
        "<b>\"Lembut, manis tipis, dan menenangkan untuk obrolan panjang.\"</b>"
    ),
    "negroni": (
        "🍸 <b>Midnight Smoked Negroni</b>",
        "<i>Julian mengaduk gin, campari, dan vermouth merah di dalam mixing glass kristal berisi es batu besar, lalu mengasapinya dengan kayu ceri.</i>\n\n"
        "<b>\"Sedikit pahit di awal, hangat di akhir. Nikmati perlahan.\"</b>"
    ),
    "whisky": (
        "🥃 <b>Highland Single Malt (On The Rocks)</b>",
        "<i>Suara denting bola es kristal beradu dengan gelas lowball berat saat Julian menuangkan cairan keemasan beraroma kayu ek.</i>\n\n"
        "<b>\"Pilihan klasik bagi mereka yang datang membawa banyak cerita.\"</b>"
    ),
    "mojito": (
        "🌿 <b>Midnight Blackberry Mojito</b>",
        "<i>Julian menumbuk daun mint segar dan buah blackberry gelap bersama perasan jeruk nipis, lalu menuangkan soda dingin di atas es serut.</i>\n\n"
        "<b>\"Segar dengan sentuhan asam manis yang membangkitkan suasana.\"</b>"
    ),
    "mocktail": (
        "🍹 <b>Crimson Velvet Fizz (Non-Alkohol)</b>",
        "<i>Julian mengocok sari delima, perasan jeruk darah, dan sirup vanila dengan soda dingin, lalu menghiasinya dengan tangkai rosemary segar.</i>\n\n"
        "<b>\"Segar, ringan, dan tetap berkelas tanpa perlu pusing.\"</b>"
    ),
    "tea": (
        "🫖 <b>Earl Grey Lavender Infusion</b>",
        "<i>Julian menyeduh daun teh bergamot dan kelopak lavender kering dalam teko kaca bening beraroma floral yang menenangkan.</i>\n\n"
        "<b>\"Hangat dan menenangkan—cocok untuk melepas penat malam ini.\"</b>"
    ),
    "water": (
        "💧 <b>Chilled Sparkling Mineral Water</b>",
        "<i>Julian menuangkan air mineral berkarbonasi dingin ke gelas tinggi dengan irisan lemon tipis di bibir gelas.</i>\n\n"
        "<b>\"Jeda yang tepat untuk menetralkan suasana malam.\"</b>"
    ),
}

FOODS_MENU = {
    "fries": (
        "🍟 <b>Black Truffle Parmesan Fries</b>",
        "<i>Waitress Clara meletakkan keranjang tembaga berisi kentang goreng renyah beraroma minyak truffle dan taburan keju parmesan tua di mejamu.</i>\n\n"
        "<b>\"Hati-hati masih panas—ini menu favorit tamu di sudut lounge.\"</b>"
    ),
    "steak": (
        "🥩 <b>Pan-Seared Wagyu Cube Bites</b>",
        "<i>Clara menyajikan piring batu hangat berisi potongan daging wagyu empuk dengan saus lada hitam dan bawang putih panggang.</i>\n\n"
        "<b>\"Silakan dinikmati selagi hangat agar teksturnya tetap lumer.\"</b>"
    ),
    "pasta": (
        "🍝 <b>Creamy Smoked Carbonara</b>",
        "<i>Aroma lada hitam tumbuk dan kuning telur keemasan langsung tercium saat Clara meletakkan piring pasta di hadapanmu.</i>\n\n"
        "<b>\"Selamat menikmati makan malammu di The Velvet Hour.\"</b>"
    ),
    "croissant": (
        "🥐 <b>Warm Almond Butter Croissant</b>",
        "<i>Clara menyajikan piring porselen berisi croissant berlapis renyah yang baru keluar dari panggangan dengan olesan mentega almon.</i>\n\n"
        "<b>\"Pas sekali dipadukan dengan kopi atau teh hangat malam ini.\"</b>"
    ),
    "platter": (
        "🧀 <b>Velvet Artisanal Cheese & Berry Platter</b>",
        "<i>Clara meletakkan papan kayu ek berisi potongan keju brie, cheddar tua, kacang panggang, madu hutan, dan anggur merah segar.</i>\n\n"
        "<b>\"Sajian ringan untuk menemani obrolan santai di meja utama.\"</b>"
    ),
    "cake": (
        "🍰 <b>Dark Chocolate Velvet Tart</b>",
        "<i>Clara menggeser piring kecil berisi tart cokelat hitam pekat dengan taburan bubuk emas tipis dan buah beri segar.</i>\n\n"
        "<b>\"Sedikit rasa manis untuk menemani alunan musik malam ini.\"</b>"
    ),
    "tiramisu": (
        "🍮 <b>Classic Espresso Tiramisu</b>",
        "<i>Clara menyajikan gelas saji berisi lapisan mascarpone lembut yang direndam espresso pekat dengan taburan bubuk kakao pahit.</i>\n\n"
        "<b>\"Manis yang dewasa dan lembut di setiap sendokan.\"</b>"
    ),
}

# --- DAFTAR COMMAND DINAMIS PER PEKERJAAN (DENGAN CONTOH) ---
BASE_GROUP_COMMANDS = [
    BotCommand(command="order", description="Pesan minum — Contoh: /order negroni atau /order Matcha Latte"),
    BotCommand(command="eat", description="Pesan makan — Contoh: /eat steak atau /eat Beef Lasagna"),
    BotCommand(command="lapak", description="Lihat katalog toko partner — Contoh: /lapak"),
    BotCommand(command="bill", description="Cek saldo VC, VIP & Charm — Contoh: /bill"),
    BotCommand(command="mystery", description="Putar Bar Roulette (40 VC) — Contoh: /mystery"),
    BotCommand(command="toast", description="Ajak bersulang — Contoh: /toast @username"),
    BotCommand(command="guests", description="Lihat daftar tamu di dalam lounge — Contoh: /guests"),
    BotCommand(command="topcharm", description="Papan peringkat Charm Points — Contoh: /topcharm"),
    BotCommand(command="checkin", description="Perbarui waktu santai (anti-idle) — Contoh: /checkin"),
    BotCommand(command="checkout", description="Pamit keluar dari ruang bar — Contoh: /checkout"),
    BotCommand(command="apply", description="Ambil shift (20m, 50 VC) — Contoh: /apply waiter"),
]

SHIFT_COMMANDS_MAP = {
    "bartender": [
        BotCommand(command="mix", description="[Tugas Bartender] Racik minum — Contoh: /mix Velvet Sunset"),
        BotCommand(command="sober", description="[Tugas Bartender] Kopi penetral — Contoh: /sober @username"),
        BotCommand(command="myshift", description="Cek sisa waktu & progres layanan — Contoh: /myshift"),
        BotCommand(command="endshift", description="Selesaikan shift & cairkan gaji 50 VC — Contoh: /endshift"),
    ],
    "waiter": [
        BotCommand(command="welcome", description="[Tugas Waiter] Sambut tamu — Contoh: /welcome @username"),
        BotCommand(command="dish", description="[Tugas Waiter] Antar hidangan — Contoh: /dish Wagyu Steak"),
        BotCommand(command="myshift", description="Cek sisa waktu & progres layanan — Contoh: /myshift"),
        BotCommand(command="endshift", description="Selesaikan shift & cairkan gaji 50 VC — Contoh: /endshift"),
    ],
    "host": [
        BotCommand(command="ambience", description="[Tugas Host] Atur cahaya lilin lounge — Contoh: /ambience"),
        BotCommand(command="toastall", description="[Tugas Host] Pimpin bersulang ruangan — Contoh: /toastall"),
        BotCommand(command="myshift", description="Cek sisa waktu & progres layanan — Contoh: /myshift"),
        BotCommand(command="endshift", description="Selesaikan shift & cairkan gaji 50 VC — Contoh: /endshift"),
    ],
    "dj": [
        BotCommand(command="myshift", description="Cek sisa waktu & progres layanan DJ — Contoh: /myshift"),
        BotCommand(command="endshift", description="Selesaikan shift & cairkan gaji 50 VC — Contoh: /endshift"),
    ],
}

ROLE_GUIDES = {
    "waiter": (
        "🍽️ <b>WAITER / WAITRESS SHIFT</b>",
        "• <code>/welcome [@username / nama tamu]</code>\n"
        "  Menyambut tamu baru & menyiapkan meja lilin.\n"
        "  Contoh: <code>/welcome @clara</code>\n\n"
        "• <code>/dish [Nama Makanan Bebas]</code>\n"
        "  Mengantarkan hidangan apa saja dari dapur.\n"
        "  Contoh: <code>/dish Wagyu Steak</code> atau <code>/dish Dimsum Mentai</code>"
    ),
    "bartender": (
        "🍸 <b>BARTENDER SHIFT</b>",
        "• <code>/mix [Nama Minuman Bebas]</code>\n"
        "  Meracik minuman apa saja untuk tamu.\n"
        "  Contoh: <code>/mix Velvet Sunset</code> atau <code>/mix Es Kopi Susu Gula Aren</code>\n\n"
        "• <code>/sober [@username / nama tamu]</code>\n"
        "  Menyajikan kopi hitam penetral untuk tamu.\n"
        "  Contoh: <code>/sober @alvaro</code>"
    ),
    "host": (
        "🕯️ <b>LOUNGE HOST SHIFT</b>",
        "• <code>/ambience</code>\n"
        "  Mengatur pencahayaan lilin & suasana intim lounge.\n"
        "  Contoh: <code>/ambience</code> (langsung kirim tanpa teks tambahan)\n\n"
        "• <code>/toastall</code>\n"
        "  Memimpin bersulang untuk seluruh tamu di ruangan.\n"
        "  Contoh: <code>/toastall</code> (langsung kirim tanpa teks tambahan)"
    ),
    "dj": (
        "🎧 <b>RESIDENT DJ SHIFT</b>",
        "• <code>/spinmusic [Judul Lagu - Penyanyi]</code>\n"
        "  Memutar lagu prioritas antrean teratas.\n"
        "  Contoh: <code>/spinmusic Sunsetz - Cigarettes After Sex</code>\n\n"
        "• <code>/dedicate [@username] [Judul - Penyanyi] | [Pesan]</code>\n"
        "  Memutar lagu dedikasi spesial dengan pesan.\n"
        "  Contoh: <code>/dedicate @clara Perfect - Ed Sheeran | Buat kamu</code>"
    )
}

async def ensure_shift_schema():
    """Memastikan tabel active_shifts mendukung multi-staf per role dan kuota 3x/hari."""
    async with db.pool.acquire() as conn:
        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS daily_shift_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_shift_date DATE;
        """)
        await conn.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE table_name = 'active_shifts' AND constraint_type = 'PRIMARY KEY'
                ) THEN
                    ALTER TABLE active_shifts DROP CONSTRAINT active_shifts_pkey;
                END IF;
            END $$;
        """)
        await conn.execute("""
            DELETE FROM active_shifts a USING active_shifts b
            WHERE a.ctid < b.ctid AND a.user_id = b.user_id;
        """)
        await conn.execute("""
            ALTER TABLE active_shifts ADD PRIMARY KEY (user_id);
        """)

async def update_member_shift_commands(user_id: int, role: str | None):
    scope = BotCommandScopeChatMember(chat_id=GROUP_ID, user_id=user_id)
    try:
        if role and role in SHIFT_COMMANDS_MAP:
            cmds = SHIFT_COMMANDS_MAP[role] + BASE_GROUP_COMMANDS
            await bot.set_my_commands(cmds, scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception as e:
        logging.warning(f"Gagal update member commands untuk {user_id}: {e}")

# --- HELPER AUTO-DELETE PESAN LAYANAN (2 MENIT) ---
async def schedule_delete(msg: types.Message, delay: int = 120):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

async def reply_and_autodelete(message: types.Message, text: str, delay: int = 120, reply_markup=None):
    sent = await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
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

async def add_shift_action(user_id: int) -> int:
    async with db.pool.acquire() as conn:
        new_val = await conn.fetchval(
            "UPDATE active_shifts SET actions_count = actions_count + 1 WHERE user_id = $1 RETURNING actions_count",
            user_id
        )
        return new_val or 0

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
            "Selamat datang di <i>The Velvet Hour</i>.\"</b>\n\n"
            "• <code>/order</code> — Buku menu minuman (Contoh: <code>/order negroni</code>)\n"
            "• <code>/eat</code> — Buku menu makanan (Contoh: <code>/eat steak</code>)\n"
            "• <code>/reqsong Judul - Penyanyi</code> — Putar lagu di ruangan\n"
            "• <code>/lapak</code> — Intip katalog toko partner",
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(schedule_delete(welcome_msg, 120))

# --- COMMAND TAMU DI RUANG UTAMA ---
@dp.message(Command("bill"), F.chat.id == GROUP_ID)
async def cmd_bill(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT coins, charm_points, gifts_sent_vc, is_vip, vip_until, total_active_mins, daily_shift_count, last_shift_date FROM users WHERE user_id = $1",
            user_id
        )
    if not row:
        return await reply_and_autodelete(message, "<i>Julian memeriksa buku catatan: Namamu belum terdaftar. Ketuk pintu utama di PC Hans terlebih dahulu.</i>", 60)

    today = datetime.utcnow().date()
    used_shifts = row["daily_shift_count"] if row["last_shift_date"] == today else 0
    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    status_txt = f"🍾 VIP Reserve (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "🥂 Regular Guest"

    text = (
        f"🧾 <b>BAR TAB & STATUS — {message.from_user.first_name}</b>\n\n"
        f"• <b>Status Meja:</b> {status_txt}\n"
        f"• <b>Saldo Dompet:</b> {row['coins']} Velvet Coins (VC)\n"
        f"• <b>Charm Points:</b> {row['charm_points']} Poin\n"
        f"• <b>Total Gift Diberikan:</b> {row['gifts_sent_vc'] or 0} VC\n"
        f"• <b>Kuota Shift Hari Ini:</b> {used_shifts}/{MAX_SHIFTS_PER_DAY} shift\n"
        f"• <b>Total Waktu Nongkrong:</b> {row['total_active_mins'] or 0} Menit"
    )
    await reply_and_autodelete(message, text, 90)

@dp.message(Command("lapak"), F.chat.id == GROUP_ID)
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
        return await reply_and_autodelete(
            message,
            "🏪 <i>Belum ada lapak partner yang buka di sudut lounge saat ini.</i>",
            60
        )

    lines = []
    for s in shops:
        owner_tag = f" (@{s['owner_username']})" if s["owner_username"] else ""
        lines.append(f"• <b>{s['shop_name']}</b>{owner_tag} — <i>{s['active_items']} item tersedia</i>")

    hans_me = await hans_bot.get_me()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍️ Lihat Katalog & Beli di PC Hans", url=f"https://t.me/{hans_me.username}?start=lapak")]
    ])

    await reply_and_autodelete(
        message,
        "🏪 <b>POJOK LAPAK PARTNER — THE VELVET HOUR</b>\n\n"
        + "\n".join(lines) +
        "\n\n<i>Klik tombol di bawah untuk melihat stiker/foto koleksi dan bertransaksi menggunakan <b>Velvet Coins (VC)</b>:</i>",
        90,
        reply_markup=kb
    )

@dp.message(Command("order"), F.chat.id == GROUP_ID)
async def cmd_order(message: types.Message):
    item_raw = message.text.replace("/order", "").strip().lower()
    if not item_raw:
        menu_list = "\n".join([f"• <code>/order {k}</code> — {v[0]}" for k, v in DRINKS_MENU.items()])
        return await reply_and_autodelete(
            message,
            f"🍸 <b>DAFTAR MINUMAN BARTENDER JULIAN</b>\n\n{menu_list}\n\n"
            "💡 <i>Bisa juga pesan minuman bebas di belakang command:\n"
            "Contoh: <code>/order Iced Caramel Macchiato</code></i>",
            90
        )

    matched = None
    for key, val in DRINKS_MENU.items():
        if key in item_raw:
            matched = val
            break

    if matched:
        title, narrative = matched
        text = f"{title}\n\n{narrative}\n\n<i>— Disajikan untuk <b>{message.from_user.first_name}</b>.</i>"
    else:
        custom_name = message.text.replace("/order", "").strip()
        text = (
            f"🍸 <b>Pesanan Khusus: {custom_name}</b>\n\n"
            f"<i>Julian mengangguk paham, meracik bahan-bahan pilihan di balik meja bar kayu ek, lalu menggeser gelas <b>{custom_name}</b> dengan mulus ke hadapanmu.</i>\n\n"
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
            f"🍽️ <b>DAFTAR HIDANGAN DAPUR (WAITRESS CLARA)</b>\n\n{menu_list}\n\n"
            "💡 <i>Bisa juga pesan makanan bebas di belakang command:\n"
            "Contoh: <code>/eat Ramen Pedas Hangat</code></i>",
            90
        )

    matched = None
    for key, val in FOODS_MENU.items():
        if key in item_raw:
            matched = val
            break

    if matched:
        title, narrative = matched
        text = f"{title}\n\n{narrative}\n\n<i>— Diantarkan ke meja <b>{message.from_user.first_name}</b>.</i>"
    else:
        custom_food = message.text.replace("/eat", "").strip()
        text = (
            f"🍽️ <b>Hidangan Khusus: {custom_food}</b>\n\n"
            f"<i>Waitress Clara keluar dari balik pintu dapur membawa nampan perak hangat, lalu meletakkan <b>{custom_food}</b> di mejamu dengan senyum ramah.</i>\n\n"
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
                ("golden", "✨ <b>GOLDEN ELIXIR (+85 VC)!</b>\n\n<i>Cairan berkilau keemasan dituangkan ke gelasmu. Kamu memenangkan hadiah utama meja bar!</i>"),
                ("truth", "🕯️ <b>VELVET TRUTH CARD!</b>\n\n<i>Julian menyodorkan kartu hitam: \"Jawab dengan jujur di chat—apa hal paling nekat yang pernah kamu lakukan diam-diam?\"</i>"),
                ("dare", "🎲 <b>VELVET DARE CARD!</b>\n\n<i>Julian tersenyum tipis: \"Tantangan malam ini—kirim pesan pujian RP ke salah satu tamu yang sedang aktif di ruangan!\"</i>"),
                ("water", "💧 <b>CHILLED MINERAL WATER!</b>\n\n<i>Zonk! Gelas yang muncul hanya berisi air putih dingin. Coba lagi keberuntunganmu nanti.</i>"),
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
        return await reply_and_autodelete(
            message,
            "Sebutkan nama/username tamu atau balas pesannya.\nContoh: <code>/toast @username</code> atau <code>/toast Clara</code>",
            60
        )

    await reply_and_autodelete(
        message,
        f"🥂 <b>BERSULANG DI RUANG UTAMA!</b>\n\n"
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

# =====================================================================
# --- SISTEM SHIFT KERJA (KUOTA SESUAI JOB, MAKS 3x/HARI, 20M, 50 VC) ---
# =====================================================================
@dp.message(Command("apply"), F.chat.id == GROUP_ID)
async def cmd_apply(message: types.Message):
    role = message.text.replace("/apply", "").strip().lower()
    async with db.pool.acquire() as conn:
        counts_rows = await conn.fetch("SELECT role, COUNT(*) as cnt FROM active_shifts GROUP BY role")
        counts = {r["role"]: r["cnt"] for r in counts_rows}

    if role not in MAX_ACTIVE_PER_ROLE:
        return await reply_and_autodelete(
            message,
            f"💼 <b>PILIH POSISI SHIFT ({SHIFT_MAX_MINUTES} MENIT — UPAH {SHIFT_REWARD_VC} VC)</b>\n"
            f"<i>Batas kerja harian: Maksimal <b>{MAX_SHIFTS_PER_DAY}x shift/hari</b></i>\n\n"
            f"• <code>/apply waiter</code> (Slot: <b>{counts.get('waiter', 0)}/{MAX_ACTIVE_PER_ROLE['waiter']}</b>) — Pelayan meja & dapur\n"
            f"• <code>/apply bartender</code> (Slot: <b>{counts.get('bartender', 0)}/{MAX_ACTIVE_PER_ROLE['bartender']}</b>) — Peracik minuman bar\n"
            f"• <code>/apply host</code> (Slot: <b>{counts.get('host', 0)}/{MAX_ACTIVE_PER_ROLE['host']}</b>) — Pemandu suasana lounge\n"
            f"• <code>/apply dj</code> (Slot: <b>{counts.get('dj', 0)}/{MAX_ACTIVE_PER_ROLE['dj']}</b>) — Pengendali musik ruangan\n\n"
            f"💡 <b>Contoh:</b> Ketik <code>/apply waiter</code> untuk melamar sebagai Waiter.",
            90
        )

    user_id = message.from_user.id
    today = datetime.utcnow().date()
    max_slot_role = MAX_ACTIVE_PER_ROLE[role]

    async with db.pool.acquire() as conn:
        # 1. Cek apakah user sudah sedang aktif shift
        already_working = await conn.fetchrow("SELECT role FROM active_shifts WHERE user_id = $1", user_id)
        if already_working:
            return await reply_and_autodelete(
                message,
                f"Kamu sudah bertugas sebagai <b>{already_working['role'].upper()}</b>.\n"
                "Ketik <code>/myshift</code> untuk cek progres atau <code>/endshift</code> untuk selesai.",
                60
            )

        # 2. Cek batas harian per user (maks 3x shift per hari)
        u_row = await conn.fetchrow("SELECT daily_shift_count, last_shift_date FROM users WHERE user_id = $1", user_id)
        used_today = (u_row["daily_shift_count"] or 0) if (u_row and u_row["last_shift_date"] == today) else 0
        if used_today >= MAX_SHIFTS_PER_DAY:
            return await reply_and_autodelete(
                message,
                f"⏳ <b>Kuota Shift Harian Habis ({used_today}/{MAX_SHIFTS_PER_DAY})</b>\n\n"
                f"Kamu sudah mencapai batas maksimal <b>{MAX_SHIFTS_PER_DAY}x kerja</b> hari ini. Silakan kembali bekerja besok!",
                60
            )

        # 3. Cek batas maksimal staf aktif pada posisi tersebut sesuai job
        active_in_role = await conn.fetchval("SELECT COUNT(*) FROM active_shifts WHERE role = $1", role)
        if (active_in_role or 0) >= max_slot_role:
            return await reply_and_autodelete(
                message,
                f"🚫 <b>Slot Posisi {role.upper()} Penuh ({active_in_role}/{max_slot_role})</b>\n\n"
                "Kuota staf aktif untuk posisi ini sudah penuh. Silakan pilih posisi lain yang masih tersedia (contoh: <code>/apply waiter</code>).",
                60
            )

        # 4. Catat shift baru & increment kuota harian user
        new_used_today = used_today + 1
        await conn.execute("""
            UPDATE users
            SET daily_shift_count = $1, last_shift_date = $2
            WHERE user_id = $3
        """, new_used_today, today, user_id)

        await conn.execute(
            "INSERT INTO active_shifts (role, user_id, started_at, actions_count) VALUES ($1, $2, NOW(), 0)",
            role, user_id
        )

    await update_member_shift_commands(user_id, role)

    title_role, cmd_guide = ROLE_GUIDES[role]
    await message.answer(
        f"💼 <b>SHIFT DIMULAI — {title_role}</b>\n\n"
        f"<b>{message.from_user.first_name}</b> resmi bertugas selama <b>{SHIFT_MAX_MINUTES} menit</b>! "
        f"(Kuota harian: <b>{new_used_today}/{MAX_SHIFTS_PER_DAY}</b>)\n"
        "<i>(Command tugasmu sudah otomatis ditambahkan ke menu <code>/</code> di keyboard kamu).</i>\n\n"
        f"<b>Daftar Tugas ({SHIFT_REQUIRED_ACTIONS}x Layanan):</b>\n"
        f"{cmd_guide}\n\n"
        "• Cek progres: <code>/myshift</code>\n"
        f"• Cairkan gaji <b>{SHIFT_REWARD_VC} VC</b>: <code>/endshift</code>",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("myshift"), F.chat.id == GROUP_ID)
async def cmd_myshift(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if not shift:
        return await reply_and_autodelete(
            message,
            "Kamu sedang tidak dalam jadwal shift kerja.\nContoh melamar: <code>/apply waiter</code>",
            60
        )

    elapsed_mins = int((datetime.utcnow() - shift["started_at"]).total_seconds() / 60)
    rem_mins = max(0, SHIFT_MAX_MINUTES - elapsed_mins)
    status_gaji = (
        f"✅ <b>Siap Cair!</b> Ketik <code>/endshift</code> untuk klaim <b>+{SHIFT_REWARD_VC} VC</b>."
        if shift["actions_count"] >= SHIFT_REQUIRED_ACTIONS
        else f"⏳ Kurang <b>{SHIFT_REQUIRED_ACTIONS - shift['actions_count']}x layanan lagi</b>."
    )

    _, cmd_guide = ROLE_GUIDES.get(shift["role"], ("", ""))
    await reply_and_autodelete(
        message,
        f"📋 <b>STATUS SHIFT — {message.from_user.first_name}</b>\n\n"
        f"• <b>Posisi:</b> {shift['role'].upper()}\n"
        f"• <b>Progres Layanan:</b> {shift['actions_count']} / {SHIFT_REQUIRED_ACTIONS} kali\n"
        f"• <b>Sisa Waktu:</b> {rem_mins} menit (dari {SHIFT_MAX_MINUTES} menit)\n"
        f"• <b>Status Upah:</b> {status_gaji}\n\n"
        f"<b>Command Tugasmu:</b>\n{cmd_guide}",
        60
    )

@dp.message(Command("endshift"), F.chat.id == GROUP_ID)
async def cmd_endshift(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        shift = await conn.fetchrow("SELECT role, actions_count FROM active_shifts WHERE user_id = $1", user_id)
        if not shift:
            return await reply_and_autodelete(message, "Kamu sedang tidak dalam jadwal shift kerja.", 60)

        await conn.execute("DELETE FROM active_shifts WHERE user_id = $1", user_id)
        if shift["actions_count"] >= SHIFT_REQUIRED_ACTIONS:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", SHIFT_REWARD_VC, user_id)
            msg_txt = (
                f"💵 <b>SHIFT SELESAI — UPAH {SHIFT_REWARD_VC} VC CAIR!</b>\n\n"
                f"Bartender Julian menyerahkan amplop berisi <b>+{SHIFT_REWARD_VC} Velvet Coins</b> kepada <b>{message.from_user.first_name}</b> "
                f"atas dedikasinya sebagai <b>{shift['role'].upper()}</b> ({shift['actions_count']} layanan)."
            )
        else:
            msg_txt = (
                f"📋 <b>SHIFT DIAKHIRI</b>\n\n"
                f"<b>{message.from_user.first_name}</b> melepas pin <b>{shift['role'].upper()}</b>.\n\n"
                f"<i>(Upah tidak cair karena layanan baru mencapai {shift['actions_count']}/{SHIFT_REQUIRED_ACTIONS} kali).</i>"
            )

    await update_member_shift_commands(user_id, None)
    await message.answer(msg_txt, parse_mode=ParseMode.HTML)

# --- AKSI STAF PARUH WAKTU (RP NARASI + HITUNG PROGRES) ---
@dp.message(Command("mix"), F.chat.id == GROUP_ID)
async def cmd_mix(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "bartender") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Bartender</b>. Contoh melamar: <code>/apply bartender</code>", 45)
    drink = message.text.replace("/mix", "").strip()
    if not drink:
        return await reply_and_autodelete(message, "Tuliskan nama minuman yang ingin diracik.\nContoh: <code>/mix Midnight Negroni</code>", 45)
    cnt = await add_shift_action(message.from_user.id)
    prog = f"\n\n📊 <i>Progres Shift: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>" if shift else ""
    await reply_and_autodelete(
        message,
        f"🍸 <b>Bartender {message.from_user.first_name}</b> mengocok shaker perak dengan lihai dan menuangkan <b>{drink}</b> ke gelas kristal dingin!{prog}",
        120
    )

@dp.message(Command("sober"), F.chat.id == GROUP_ID)
async def cmd_sober(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "bartender") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Bartender</b>. Contoh melamar: <code>/apply bartender</code>", 45)
    target = message.text.replace("/sober", "").strip()
    if not target and message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
    if not target:
        return await reply_and_autodelete(message, "Tuliskan username/nama tamu atau balas pesannya.\nContoh: <code>/sober @alvaro</code>", 45)
    cnt = await add_shift_action(message.from_user.id)
    prog = f"\n\n📊 <i>Progres Shift: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>" if shift else ""
    await reply_and_autodelete(
        message,
        f"☕ <b>Bartender {message.from_user.first_name}</b> menyodorkan secangkir kopi hitam pekat dan air dingin kepada <b>{target}</b> agar kembali segar.{prog}",
        120
    )

@dp.message(Command("welcome"), F.chat.id == GROUP_ID)
async def cmd_welcome_staff(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "waiter") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Waiter</b>. Contoh melamar: <code>/apply waiter</code>", 45)
    target = message.text.replace("/welcome", "").strip()
    if not target and message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
    if not target:
        return await reply_and_autodelete(message, "Tuliskan username/nama tamu yang disambut.\nContoh: <code>/welcome @clara</code>", 45)
    cnt = await add_shift_action(message.from_user.id)
    prog = f"\n\n📊 <i>Progres Shift: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>" if shift else ""
    await reply_and_autodelete(
        message,
        f"🍽️ <b>Waiter {message.from_user.first_name}</b> menyambut <b>{target}</b> dengan senyum hangat, mengantar ke meja beludru, dan menyalakan lilin meja.{prog}",
        120
    )

@dp.message(Command("dish"), F.chat.id == GROUP_ID)
async def cmd_dish(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "waiter") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Waiter</b>. Contoh melamar: <code>/apply waiter</code>", 45)
    dish_name = message.text.replace("/dish", "").strip()
    if not dish_name:
        return await reply_and_autodelete(message, "Tuliskan nama hidangan yang diantar.\nContoh: <code>/dish Wagyu Cube Bites</code>", 45)
    cnt = await add_shift_action(message.from_user.id)
    prog = f"\n\n📊 <i>Progres Shift: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>" if shift else ""
    await reply_and_autodelete(
        message,
        f"🍽️ <b>Waiter {message.from_user.first_name}</b> menyajikan <b>{dish_name}</b> hangat dari dapur langsung ke meja tamu.{prog}",
        120
    )

@dp.message(Command("ambience"), F.chat.id == GROUP_ID)
async def cmd_ambience(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "host") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Host</b>. Contoh melamar: <code>/apply host</code>", 45)
    cnt = await add_shift_action(message.from_user.id)
    prog = f"\n\n📊 <i>Progres Shift: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>" if shift else ""
    await reply_and_autodelete(
        message,
        f"🕯️ <b>Host {message.from_user.first_name}</b> meredupkan lampu gantung kristal, menyisakan pendar cahaya lilin hangat yang intim di seluruh penjuru lounge...{prog}",
        120
    )

@dp.message(Command("toastall"), F.chat.id == GROUP_ID)
async def cmd_toastall(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role"] != "host") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Host</b>. Contoh melamar: <code>/apply host</code>", 45)
    cnt = await add_shift_action(message.from_user.id)
    prog = f"\n\n📊 <i>Progres Shift: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>" if shift else ""
    await reply_and_autodelete(
        message,
        f"🥂 <b>Host {message.from_user.first_name}</b> berdiri di tengah ruangan sambil mengangkat gelas:\n\n<b>\"Mari bersulang untuk malam yang tak terlupakan di The Velvet Hour!\"</b>{prog}",
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
            f"🔇 <i>Bouncer Hans melangkah mendekat ke meja <b>{target.first_name}</b> dan memberi isyarat tenang.</i>\n\n"
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
        "🍾 <b>ON THE HOUSE — TRATIRAN OWNER!</b>\n\n"
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

    if not await is_staff_or_owner(user_id):
        if REQUIRED_CN_SYMBOL not in (user.full_name or ""):
            await message.answer(
                f"🚨 <i>Bouncer Hans menghentikan langkah <b>{user.first_name}</b> di tengah ruangan.</i>\n\n"
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

# --- BACKGROUND WORKER: PENGAWAS TAMU PASIF & SHIFT EXPIRE 20 MENIT ---
async def idle_watcher_loop():
    while True:
        await asyncio.sleep(60)
        try:
            async with db.pool.acquire() as conn:
                now = datetime.utcnow()

                # A. Cek Shift Kerja Melebihi 20 Menit
                expired_shifts = await conn.fetch(
                    "SELECT role, user_id, actions_count FROM active_shifts WHERE started_at <= $1",
                    now - timedelta(minutes=SHIFT_MAX_MINUTES)
                )
                for sh in expired_shifts:
                    await conn.execute("DELETE FROM active_shifts WHERE user_id = $1", sh["user_id"])
                    await update_member_shift_commands(sh["user_id"], None)
                    if sh["actions_count"] >= SHIFT_REQUIRED_ACTIONS:
                        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", SHIFT_REWARD_VC, sh["user_id"])
                        try:
                            await bot.send_message(
                                GROUP_ID,
                                f"💼 <b>SHIFT {SHIFT_MAX_MINUTES} MENIT SELESAI — UPAH {SHIFT_REWARD_VC} VC CAIR!</b>\n\n"
                                f"Waktu shift untuk posisi <b>{sh['role'].upper()}</b> telah berakhir. "
                                f"Upah <b>+{SHIFT_REWARD_VC} VC</b> otomatis ditransfer ke dompet staf!",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            await bot.send_message(
                                GROUP_ID,
                                f"⏰ <b>SHIFT {SHIFT_MAX_MINUTES} MENIT BERAKHIR</b>\n\n"
                                f"Waktu shift <b>{sh['role'].upper()}</b> telah habis (layanan tercapai {sh['actions_count']}/{SHIFT_REQUIRED_ACTIONS}).",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass

                # B. Cek Tamu Pasif (Idle 60m / VIP 120m)
                guests = await conn.fetch(
                    "SELECT user_id, full_name, is_vip, vip_until, last_active, warned_idle FROM users WHERE is_in_bar = TRUE"
                )
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
                            f"🕯️ <i>Waitress Clara menyentuh bahu <a href='tg://user?id={uid}'>{g['full_name']}</a> dengan lembut:</i>\n\n"
                            f"<b>\"Permisi, meja ini akan segera dirapikan dalam 10 menit jika tidak ada aktivitas. Ketik obrolan atau <code>/checkin</code> jika masih bersantai.\"</b>",
                            parse_mode=ParseMode.HTML
                        )
                        asyncio.create_task(schedule_delete(warn_msg, 120))
        except Exception as e:
            logging.error(f"Idle watcher error: {e}")

# --- REGISTER MENU COMMAND (/) DI GRUP ---
async def register_julian_commands():
    await bot.set_my_commands(BASE_GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())

async def main():
    await db.init_db()
    await ensure_shift_schema()
    await register_julian_commands()
    asyncio.create_task(idle_watcher_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
