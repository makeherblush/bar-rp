import html
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import shared.database as db
from hans_concierge.helpers import (
    bot, GROUP_ID, REQUIRED_CN_SYMBOL, VIP_COST_24H, DAILY_REWARD_VC,
    REFERRAL_BONUS_VC, DAILY_QUESTS,
    get_or_create_referral_code, log_wallet_tx, add_quest_progress,
    main_lobby_kb, info_categories_kb, back_info_kb
)

router = Router()

# --- GERBANG UTAMA (/start + KODE REFERRAL) ---
@router.message(CommandStart(), F.chat.type == "private")
# --- GERBANG UTAMA (/start + KODE REFERRAL) ---
@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start_hans(message: types.Message):
    user = message.from_user
    args = message.text.split(maxsplit=1)
    ref_param = args[1].strip() if len(args) > 1 else ""

    # Deep link langsung ke lapak
    if ref_param == "lapak":
        from hans_concierge.shop_gift import send_lapak_list
        return await send_lapak_list(message)

    async with db.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT user_id, referred_by FROM users WHERE user_id = $1", user.id)
        if not existing:
            referrer_id = None
            if ref_param.startswith("ref_"):
                ref_code = ref_param.replace("ref_", "").strip().upper()
                ref_row = await conn.fetchrow("SELECT user_id FROM users WHERE referral_code = $1", ref_code)
                if ref_row and ref_row["user_id"] != user.id:
                    referrer_id = ref_row["user_id"]

            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, coins, referred_by)
                VALUES ($1, $2, $3, 50, $4)
            """, user.id, user.username or "NoUsername", user.full_name, referrer_id)
            await log_wallet_tx(conn, user.id, 50, "Bonus tamu baru pertama kali hadir")

    await get_or_create_referral_code(user.id)

    text = (
        "🚪 <i>Lampu gantung kristal menyala temaram di balik tirai beludru merah...</i>\n\n"
        f"<b>\"Selamat malam, {html.escape(user.first_name)}. Saya Hans, Kepala Concierge di <i>The Velvet Hour</i>.\"</b>\n\n"
        f"Sebelum melangkah masuk ke ruang lounge utama, pastikan nama tampilan Telegram kamu menyertakan simbol resmi bar: <b>{REQUIRED_CN_SYMBOL}</b>.\n\n"
        "<i>Gunakan panel resepsionis di bawah ini untuk masuk ke ruangan, memeriksa mutasi dompet, menyelesaikan misi harian, atau mengundang teman:</i>"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

@router.callback_query(F.data == "back_lobby")
async def cb_back_lobby(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        f"🏛️ <b>LOBI RESEPSIONIS — THE VELVET HOUR</b>\n\n"
        f"<i>Hans merapikan buku tamu kulit di atas meja mahoni.</i>\n"
        f"Silakan pilih layanan yang kamu perlukan, <b>{html.escape(call.from_user.first_name)}</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_lobby_kb()
    )

# --- VERIFIKASI MASUK BAR & PENCAIRAN BONUS REFERRAL ---
@router.callback_query(F.data == "enter_bar")
async def cb_enter_bar(call: types.CallbackQuery):
    user = call.from_user
    if REQUIRED_CN_SYMBOL not in (user.full_name or ""):
        return await call.answer(
            f"Atribut CN ({REQUIRED_CN_SYMBOL}) belum terpasang pada nama tampilan Telegram kamu!",
            show_alert=True
        )

    await call.answer("Verifikasi CN berhasil!")
    ref_bonus_note = ""

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT referred_by, referral_rewarded FROM users WHERE user_id = $1 FOR UPDATE",
                user.id
            )
            if row and row["referred_by"] and not row["referral_rewarded"]:
                ref_id = row["referred_by"]
                await conn.execute(
                    "UPDATE users SET coins = coins + $1, referral_rewarded = TRUE WHERE user_id = $2",
                    REFERRAL_BONUS_VC, user.id
                )
                await conn.execute(
                    "UPDATE users SET coins = coins + $1, referral_count = referral_count + 1 WHERE user_id = $2",
                    REFERRAL_BONUS_VC, ref_id
                )
                await log_wallet_tx(conn, user.id, REFERRAL_BONUS_VC, "Bonus undangan teman (Referral)")
                await log_wallet_tx(conn, ref_id, REFERRAL_BONUS_VC, f"Bonus mengundang {user.first_name}")
                ref_bonus_note = f"\n🎉 <b>Bonus Referral Aktif:</b> Kamu dan pengundangmu masing-masing mendapat <b>+{REFERRAL_BONUS_VC} VC</b>!\n"

    try:
        invite = await bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,
            expire_date=datetime.utcnow() + timedelta(minutes=10)
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🥂 Melangkah Masuk ke Ruang Utama", url=invite.invite_link)],
            [InlineKeyboardButton(text="⬅️ Kembali ke Lobi", callback_data="back_lobby")]
        ])
        await call.message.edit_text(
            f"✅ <b>VERIFIKASI ATRIBUT ({REQUIRED_CN_SYMBOL}) BERHASIL</b>\n"
            f"{ref_bonus_note}\n"
            "<i>Hans membukakan pintu kayu mahoni dan mempersilakanmu masuk. Tautan pintu sekali pakai di bawah ini berlaku selama 10 menit:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb
        )
    except Exception as e:
        await call.message.edit_text(
            f"⚠️ Gagal membuat tautan masuk otomatis (<code>{html.escape(str(e))}</code>). Hubungi Owner.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_lobby_kb()
        )

# --- DOMPET & RIWAYAT MUTASI TRANSAKSI ---
@router.callback_query(F.data == "my_wallet")
async def cb_my_wallet(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user_id
        )
        txs = await conn.fetch(
            "SELECT amount, reason, created_at FROM wallet_transactions WHERE user_id = $1 ORDER BY id DESC LIMIT 6",
            user_id
        )

    coins = row["coins"] if row else 0
    charm = row["charm_points"] if row else 0
    is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    vip_txt = f"🍾 VIP Reserve (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "🥂 Regular Guest"
    booth_txt = f"\n• <b>Booth Aktif:</b> {html.escape(row['vip_booth_name'])}" if (is_vip and row.get("vip_booth_name")) else ""

    if txs:
        tx_lines = []
        for t in txs:
            sign = f"+{t['amount']}" if t["amount"] > 0 else f"{t['amount']}"
            icon = "🟢" if t["amount"] > 0 else "🔴"
            tgl = t["created_at"].strftime("%d/%m %H:%M")
            tx_lines.append(f"{icon} <b>{sign} VC</b> — {html.escape(t['reason'])} <i>({tgl})</i>")
        mutasi_block = "\n".join(tx_lines)
    else:
        mutasi_block = "<i>Belum ada catatan transaksi terbaru.</i>"

    text = (
        f"💰 <b>DOMPET & MUTASI — {html.escape(call.from_user.first_name)}</b>\n\n"
        f"• <b>Saldo Velvet Coins:</b> {coins} VC\n"
        f"• <b>Charm Points:</b> {charm} Poin\n"
        f"• <b>Status Keanggotaan:</b> {vip_txt}{booth_txt}\n\n"
        f"📜 <b>6 Mutasi Transaksi Terakhir:</b>\n{mutasi_block}"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

# --- ABSEN HARIAN (/daily & TOMBOL) ---
async def _process_daily_claim(user_id: int, full_name: str) -> str:
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT last_daily FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if row and row["last_daily"] == today:
                return "⏳ <i>Kamu sudah mengambil jatah uang saku harian hari ini. Kembali lagi besok!</i>"
            await conn.execute(
                "UPDATE users SET coins = coins + $1, last_daily = $2 WHERE user_id = $3",
                DAILY_REWARD_VC, today, user_id
            )
            await log_wallet_tx(conn, user_id, DAILY_REWARD_VC, "Absen harian (/daily)")
    await add_quest_progress(user_id, "daily_checkin", 1)
    return (
        f"📅 <b>ABSEN HARIAN BERHASIL!</b>\n\n"
        f"<i>Hans menyerahkan amplop beludru berisi <b>+{DAILY_REWARD_VC} Velvet Coins</b> kepada <b>{html.escape(full_name)}</b>.</i>"
    )

@router.message(Command("daily"), F.chat.type == "private")
async def cmd_daily_pc(message: types.Message):
    res = await _process_daily_claim(message.from_user.id, message.from_user.first_name)
    await message.answer(res, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

@router.callback_query(F.data == "claim_daily")
async def cb_claim_daily(call: types.CallbackQuery):
    await call.answer()
    res = await _process_daily_claim(call.from_user.id, call.from_user.first_name)
    await call.message.edit_text(res, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

# --- MISI HARIAN (/quests & TOMBOL) ---
@router.callback_query(F.data == "daily_quests")
async def cb_daily_quests(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    today = datetime.utcnow().date()

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT quest_key, progress, claimed FROM daily_quests WHERE user_id = $1 AND quest_date = $2",
            user_id, today
        )
    prog_map = {r["quest_key"]: r for r in rows}

    lines = []
    buttons = []
    for q_key, meta in DAILY_QUESTS.items():
        r = prog_map.get(q_key)
        cur = r["progress"] if r else 0
        claimed = r["claimed"] if r else False
        target = meta["target"]

        if claimed:
            status = "✅ <i>Sudah diklaim</i>"
        elif cur >= target:
            status = f"🎁 <b>Siap Klaim (+{meta['reward']} VC)!</b>"
            buttons.append([InlineKeyboardButton(text=f"🎁 Klaim {meta['title']} (+{meta['reward']} VC)", callback_data=f"claimq_{q_key}")])
        else:
            status = f"⏳ Progres: <b>{cur}/{target}</b> (Hadiah: +{meta['reward']} VC)"

        lines.append(f"• <b>{meta['title']}</b>\n  {meta['desc']}\n  {status}")

    buttons.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")])
    await call.message.edit_text(
        "🎯 <b>MISI HARIAN — THE VELVET HOUR</b>\n"
        "<i>Selesaikan aktivitas ringan setiap hari untuk mendapatkan bonus Velvet Coins:</i>\n\n"
        + "\n\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("claimq_"))
async def cb_claim_quest(call: types.CallbackQuery):
    q_key = call.data.replace("claimq_", "")
    meta = DAILY_QUESTS.get(q_key)
    if not meta:
        return await call.answer("Misi tidak valid.", show_alert=True)

    user_id = call.from_user.id
    today = datetime.utcnow().date()
    reward = meta["reward"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT progress, claimed FROM daily_quests WHERE user_id = $1 AND quest_date = $2 AND quest_key = $3 FOR UPDATE",
                user_id, today, q_key
            )
            if not row or row["progress"] < meta["target"]:
                return await call.answer("Progres misi belum selesai!", show_alert=True)
            if row["claimed"]:
                return await call.answer("Hadiah misi ini sudah diklaim!", show_alert=True)

            await conn.execute(
                "UPDATE daily_quests SET claimed = TRUE WHERE user_id = $1 AND quest_date = $2 AND quest_key = $3",
                user_id, today, q_key
            )
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", reward, user_id)
            await log_wallet_tx(conn, user_id, reward, f"Hadiah Misi: {meta['title']}")

    await call.answer(f"Berhasil klaim +{reward} VC!", show_alert=True)
    await cb_daily_quests(call)

# --- KODE REFERRAL / UNDANG TEMAN ---
@router.callback_query(F.data == "my_referral")
async def cb_my_referral(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    code = await get_or_create_referral_code(user_id)
    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{code}"

    async with db.pool.acquire() as conn:
        total_invited = await conn.fetchval("SELECT referral_count FROM users WHERE user_id = $1", user_id) or 0

    text = (
        "🎟️ <b>PROGRAM UNDANGAN TAMU (REFERRAL)</b>\n\n"
        f"Bagikan tautan undangan eksklusif milikmu kepada teman RP. "
        f"Saat temanmu mendaftar lewat tautan ini dan lolos verifikasi pintu masuk ({REQUIRED_CN_SYMBOL}), "
        f"kalian berdua langsung memperoleh <b>+{REFERRAL_BONUS_VC} Velvet Coins</b>!\n\n"
        f"• <b>Kode Undanganmu:</b> <code>{code}</code>\n"
        f"• <b>Total Teman Berhasil Diundang:</b> {total_invited} orang\n"
        f"• <b>Tautan Undanganmu:</b>\n<code>{ref_link}</code>"
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

# --- BELI VIP PASS (24 JAM) ---
@router.callback_query(F.data == "buy_vip")
async def cb_buy_vip(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            coins = row["coins"] if row else 0
            if coins < VIP_COST_24H:
                return await call.answer(f"Saldo tidak cukup! Butuh {VIP_COST_24H} VC.", show_alert=True)

            now = datetime.utcnow()
            base_time = row["vip_until"] if (row and row["is_vip"] and row["vip_until"] and row["vip_until"] > now) else now
            new_until = base_time + timedelta(hours=24)

            await conn.execute(
                "UPDATE users SET coins = coins - $1, is_vip = TRUE, vip_until = $2 WHERE user_id = $3",
                VIP_COST_24H, new_until, user_id
            )
            await log_wallet_tx(conn, user_id, -VIP_COST_24H, "Aktivasi VIP Reserve Pass (24 Jam)")

    await call.answer("VIP Pass aktif selama 24 jam!", show_alert=True)
    await call.message.edit_text(
        f"🍾 <b>VIP RESERVE PASS AKTIF!</b>\n\n"
        f"• <b>Berlaku hingga:</b> {new_until.strftime('%d %b %Y %H:%M UTC')}\n"
        f"• <b>Keuntungan VIP:</b>\n"
        f"  1. Gratis request lagu di grup (<code>/reqsong</code>)\n"
        f"  2. Reservasi meja eksklusif (<code>/booth Nama Booth</code>)\n"
        f"  3. Batas anti-idle 2x lebih lama (120 menit)",
        parse_mode=ParseMode.HTML,
        reply_markup=main_lobby_kb()
    )

# --- MENU PANDUAN & COMMAND LENGKAP ---
@router.callback_query(F.data == "info_menu")
async def cb_info_menu(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "📖 <b>BUKU PANDUAN & COMMAND — THE VELVET HOUR</b>\n\n"
        "<i>Pilih kategori di bawah ini untuk melihat seluruh perintah dan contoh penggunaannya di dalam bar:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=info_categories_kb()
    )

@router.callback_query(F.data == "info_cmd_bar")
async def cb_info_cmd_bar(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🥂 <b>COMMAND BAR, BOOTH & MINI-GAME (JULIAN)</b>\n\n"
        "• <code>/order [nama minuman]</code> — Pesan minuman di bar.\n"
        "  Contoh: <code>/order negroni</code> atau <code>/order Iced Matcha Latte</code>\n\n"
        "• <code>/eat [nama makanan]</code> — Pesan hidangan dari dapur.\n"
        "  Contoh: <code>/eat steak</code> atau <code>/eat Beef Lasagna</code>\n\n"
        "• <code>/treat @username [menu]</code> — Traktir tamu lain (<b>20 VC</b>, penerima dapat <b>+5 Charm</b>).\n"
        "  Contoh: <code>/treat @clara negroni</code>\n\n"
        "• <code>/booth [Nama Booth]</code> <i>(Khusus VIP)</i> — Reservasi meja VIP eksklusif.\n"
        "  Contoh: <code>/booth Velvet Corner #1</code>\n\n"
        "• <code>/dice @username [taruhan 10-100 VC]</code> — Duel dadu 1v1 berhadiah VC.\n"
        "  Contoh: <code>/dice @alvaro 25</code>\n\n"
        "• <code>/mystery</code> (40 VC), <code>/toast @user</code>, <code>/bill</code>, <code>/guests</code>, <code>/topcharm</code>, <code>/lapak</code>."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@router.callback_query(F.data == "info_cmd_music")
async def cb_info_cmd_music(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🎶 <b>COMMAND MUSIK & JUKEBOX LOUNGE (KAELEN DJ)</b>\n\n"
        "• <code>/reqsong Judul Lagu - Nama Penyanyi</code>\n"
        "  Memutar lagu di Obrolan Suara grup (<b>10 VC</b>, gratis untuk VIP & DJ).\n"
        "  Contoh: <code>/reqsong Apocalypse - Cigarettes After Sex</code>\n\n"
        "• <code>/nowplaying</code> — Melihat detail lagu yang sedang diputar beserta durasinya.\n"
        "• <code>/queue</code> — Melihat daftar antrean lagu jukebox berikutnya.\n"
        "• <code>/voteskip</code> — Voting bersama tamu lain (butuh <b>3 suara</b>) untuk melewati lagu.\n\n"
        "• <code>/myearphone Judul Lagu - Nama Penyanyi</code>\n"
        "  Mengirim file MP3 lagu langsung ke Private Chat kamu (Gratis).\n\n"
        "📻 <b>Velvet Lounge Radio:</b> Jika antrean kosong namun bar sedang ramai, Kaelen otomatis memutar lagu pilihan dari gudang musik."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@router.callback_query(F.data == "info_cmd_shift")
async def cb_info_cmd_shift(call: types.CallbackQuery):
    await call.answer()
    text = (
        "💼 <b>SISTEM SHIFT KERJA (20 MENIT — UPAH 50 VC)</b>\n"
        "<i>Maksimal 3x shift/hari per tamu. Selesaikan minimal 5x layanan selama shift berlangsung:</i>\n\n"
        "• <code>/apply waiter</code> (Kuota 4) — Tugas: <code>/welcome @user</code> & <code>/dish Nama Makanan</code>\n"
        "• <code>/apply bartender</code> (Kuota 2) — Tugas: <code>/mix Nama Minuman</code> & <code>/sober @user</code>\n"
        "• <code>/apply host</code> (Kuota 2) — Tugas: <code>/ambience</code> & <code>/toastall</code>\n"
        "• <code>/apply dj</code> (Kuota 1) — Tugas: <code>/spinmusic Lagu - Penyanyi</code>, <code>/dedicate</code>, <code>/skip</code>\n\n"
        "• <code>/myshift</code> — Cek sisa waktu & jumlah layanan shift.\n"
        "• <code>/endshift</code> — Selesaikan shift & cairkan upah <b>50 VC</b>."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())

@router.callback_query(F.data == "info_economy")
async def cb_info_economy(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🎯 <b>EKONOMI VC, MISI HARIAN & REFERRAL (HANS)</b>\n\n"
        "• <b>Bonus Tamu Baru:</b> +50 VC saat pertama kali menyapa Hans.\n"
        "• <b>Chat RP Aktif di Grup:</b> +1 VC/menit untuk obrolan minimal 3 kata.\n"
        "• <b>Absen Harian (<code>/daily</code>):</b> +20 VC setiap hari.\n"
        "• <b>Misi Harian:</b> Cek menu <i>Misi Harian</i> di PC Hans untuk klaim hingga +55 VC tambahan setiap hari.\n"
        "• <b>Undang Teman (Referral):</b> Bagikan tautan undanganmu di menu <i>Undang Teman</i>—kamu dan temanmu sama-sama mendapat <b>+50 VC</b>.\n"
        "• <b>Mutasi Dompet:</b> Seluruh pemasukan dan pengeluaran VC tercatat di menu <i>Dompet & Mutasi</i>."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())
