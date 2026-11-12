import asyncio
import logging
from datetime import datetime

from aiogram import Bot, types
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChatMember

import shared.database as db
from shared.config import TOKEN_JULIAN, TOKEN_HANS, OWNER_ID, GROUP_ID

bot = Bot(token=TOKEN_JULIAN)
hans_bot = Bot(token=TOKEN_HANS)

# --- KONFIGURASI SHIFT KERJA & FITUR BAR ---
SHIFT_MAX_MINUTES = 20
SHIFT_REQUIRED_ACTIONS = 5
SHIFT_REWARD_VC = 50
MAX_SHIFTS_PER_DAY = 3

MAX_ACTIVE_PER_ROLE = {
    "waiter": 4,
    "bartender": 2,
    "host": 2,
    "dj": 1,
}

VIP_MENU_NONVIP_COST = 15  # Biaya jika tamu non-VIP memesan menu khusus VIP (VIP Gratis)
TREAT_COST_VC = 20
TREAT_CHARM_BONUS = 5
DICE_MIN_BET = 10
DICE_MAX_BET = 100

# --- KATALOG MINUMAN REGULER (GRATIS) ---
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

# --- KATALOG MINUMAN EKSKLUSIF VIP (GRATIS VIP / 15 VC REGULER) ---
VIP_DRINKS_MENU = {
    "vip_dom": (
        "🍾 <b>Dom Pérignon Vintage 2012 (Chilled Flute)</b>",
        "<i>Julian membuka segel foil emas botol champagne vintage dengan dentuman halus, lalu menuangkan gelembung keemasan ke gelas flute kristal Baccarat.</i>\n\n"
        "<b>\"Persembahan eksklusif dari gudang bawah tanah The Velvet Hour.\"</b>"
    ),
    "vip_blue": (
        "🥃 <b>Johnnie Walker Blue Label (Crystal Decanter)</b>",
        "<i>Dari decanter kristal berukir, Julian menuangkan blend langka beraroma madu hutan, hazelnut panggang, dan asap lembut ke gelas berukir emas.</i>\n\n"
        "<b>\"Hanya satu dari sepuluh ribu tong kayu yang memiliki karakter sehalus ini.\"</b>"
    ),
    "vip_absinthe": (
        "🧪 <b>Emerald La Fée Absinthe Ritual</b>",
        "<i>Julian meletakkan sendok perak berlubang dengan kubus gula di atas gelas, lalu meneteskan air es perlahan hingga cairan hijau zamrud berubah keruh berkilau.</i>\n\n"
        "<b>\"Ritual klasik malam Paris—aroma adas bintangnya akan memikat indramu.\"</b>"
    ),
    "vip_royal": (
        "🍷 <b>Château Margaux Grand Cru (1996)</b>",
        "<i>Julian menuangkan anggur merah tua yang telah didekantasi selama dua jam, menebarkan aroma blackcurrant, cedar, dan bunga violet di sekitar mejamu.</i>\n\n"
        "<b>\"Sebuah mahakarya anggur merah untuk malam yang istimewa.\"</b>"
    ),
}

# --- KATALOG MAKANAN REGULER (GRATIS) ---
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

# --- KATALOG MAKANAN EKSKLUSIF VIP (GRATIS VIP / 15 VC REGULER) ---
VIP_FOODS_MENU = {
    "vip_caviar": (
        "🥄 <b>Imperial Beluga Caviar & Blini</b>",
        "<i>Clara membawa mangkuk kristal berisi es serut dengan kaleng Beluga Caviar hitam berkilau, dilengkapi sendok mutiara, crème fraîche, dan blini hangat.</i>\n\n"
        "<b>\"Hidangan pembuka paling prestisius di ruang VIP The Velvet Hour.\"</b>"
    ),
    "vip_lobster": (
        "🦞 <b>Butter-Poached Maine Lobster Tail</b>",
        "<i>Piring porselen berpinggir emas diletakkan di mejamu, menyajikan ekor lobster Maine lembut yang disiram saus mentega saffron dan perasan lemon Amalfi.</i>\n\n"
        "<b>\"Manis alami daging lobster yang dimasak presisi oleh kepala koki kami.\"</b>"
    ),
    "vip_a5": (
        "🥩 <b>Miyazaki A5 Wagyu Tenderloin (24K Gold Leaf)</b>",
        "<i>Clara menyajikan potongan daging Miyazaki A5 dengan marbling sempurna yang dipanggang di atas arang binchotan dan dihiasi lembaran emas 24 karat.</i>\n\n"
        "<b>\"Lumer seketika di lidah tanpa perlu banyak usaha.\"</b>"
    ),
    "vip_gold": (
        "🍫 <b>Valrhona 24K Gold Truffle Fondant</b>",
        "<i>Hidangan penutup cokelat Valrhona hangat dengan lelehan ganache truffle hitam di bagian tengah dan taburan serpihan emas murni di atasnya.</i>\n\n"
        "<b>\"Penutup malam yang mewah khusus untuk tamu terhormat kami.\"</b>"
    ),
}

# --- DAFTAR COMMAND DINAMIS PER PEKERJAAN ---
BASE_GROUP_COMMANDS = [
    BotCommand(command="order", description="Buku menu minuman (Reguler & VIP) — Contoh: /order negroni"),
    BotCommand(command="eat", description="Buku menu makanan (Reguler & VIP) — Contoh: /eat steak"),
    BotCommand(command="treat", description="Traktir tamu (20 VC, +5 Charm) — Contoh: /treat @clara negroni"),
    BotCommand(command="booth", description="Reservasi Private Booth VIP — Contoh: /booth Velvet Corner #1"),
    BotCommand(command="dice", description="Tantang dadu 1v1 — Contoh: /dice @alvaro 25"),
    BotCommand(command="mystery", description="Putar Bar Roulette (40 VC) — Contoh: /mystery"),
    BotCommand(command="toast", description="Ajak bersulang — Contoh: /toast @username"),
    BotCommand(command="lapak", description="Lihat katalog toko partner — Contoh: /lapak"),
    BotCommand(command="bill", description="Cek saldo VC, VIP & Charm — Contoh: /bill"),
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
        "• <code>/welcome [@username / nama tamu]</code> — Menyambut tamu baru.\n"
        "  Contoh: <code>/welcome @clara</code>\n"
        "• <code>/dish [Nama Makanan Bebas]</code> — Mengantarkan hidangan.\n"
        "  Contoh: <code>/dish Wagyu Steak</code>"
    ),
    "bartender": (
        "🍸 <b>BARTENDER SHIFT</b>",
        "• <code>/mix [Nama Minuman Bebas]</code> — Meracik minuman bar.\n"
        "  Contoh: <code>/mix Velvet Sunset</code>\n"
        "• <code>/sober [@username / nama tamu]</code> — Menyajikan kopi penetral.\n"
        "  Contoh: <code>/sober @alvaro</code>"
    ),
    "host": (
        "🕯️ <b>LOUNGE HOST SHIFT</b>",
        "• <code>/ambience</code> — Mengatur pencahayaan lilin lounge.\n"
        "• <code>/toastall</code> — Memimpin bersulang untuk seluruh tamu."
    ),
    "dj": (
        "🎧 <b>RESIDENT DJ SHIFT</b>",
        "• <code>/spinmusic [Judul Lagu - Penyanyi]</code> — Putar lagu prioritas.\n"
        "• <code>/dedicate [@username] [Judul - Penyanyi] | [Pesan]</code> — Dedikasi lagu."
    )
}

async def ensure_julian_schema():
    async with db.pool.acquire() as conn:
        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS daily_shift_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_shift_date DATE,
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
        await conn.execute("ALTER TABLE active_shifts ADD PRIMARY KEY (user_id);")

async def log_wallet_tx(conn, user_id: int, amount: int, reason: str):
    await conn.execute(
        "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
        user_id, amount, reason
    )

async def add_bar_quest_progress(user_id: int):
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
            VALUES ($1, $2, 'bar_social', 1, FALSE)
            ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
            SET progress = LEAST(daily_quests.progress + 1, 1);
        """, user_id, today)

async def update_member_shift_commands(user_id: int, role: str | None):
    scope = BotCommandScopeChatMember(chat_id=GROUP_ID, user_id=user_id)
    try:
        if role and role in SHIFT_COMMANDS_MAP:
            await bot.set_my_commands(SHIFT_COMMANDS_MAP[role] + BASE_GROUP_COMMANDS, scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception as e:
        logging.warning(f"Gagal update member commands untuk {user_id}: {e}")

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

async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def is_vip_user(user_id: int) -> bool:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())

async def get_user_booth_tag(user_id: int) -> str:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user_id
        )
    if not row:
        return ""
    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    if is_vip and row["vip_booth_name"]:
        return f" <i>(di 🍾 {row['vip_booth_name']})</i>"
    return ""
