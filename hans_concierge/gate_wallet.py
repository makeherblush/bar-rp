import io
import html
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.enums import ParseMode

import shared.database as db
from hans_concierge.helpers import (
    bot, OWNER_ID, GROUP_ID, REQUIRED_CN_SYMBOL, VIP_COST_24H, DAILY_REWARD_VC,
    REFERRAL_BONUS_VC, DAILY_QUESTS, get_bar_setting, react_message,
    get_or_create_referral_code, log_wallet_tx, add_quest_progress,
    insufficient_vc_kb, main_lobby_kb, info_categories_kb, back_info_kb
)
from hans_concierge.card_gen import (
    generate_member_card, EFFECT_CONFETTI, EFFECT_FIRE
)

router = Router()


class GatePasswordState(StatesGroup):
    waiting_password = State()


async def _fetch_user_avatar_bytes(user_id: int) -> bytes | None:
    """Mengunduh foto profil Telegram terbaru milik user dalam memori."""
    try:
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
        if not photos.photos:
            return None
        best_photo = photos.photos[0][-1]
        file_info = await bot.get_file(best_photo.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        return None


async def _send_or_edit_lobby(
    target: types.Message | types.CallbackQuery,
    text: str,
    kb: InlineKeyboardMarkup,
    effect_id: str | None = None,
):
    if isinstance(target, types.CallbackQuery):
        msg = target.message
        if msg.photo or effect_id:
            try:
                await msg.delete()
            except Exception:
                pass
            return await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb, message_effect_id=effect_id)
        return await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return await target.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb, message_effect_id=effect_id)


# --- GERBANG UTAMA (/start + KODE REFERRAL) ---
@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start_hans(message: types.Message, state: FSMContext):
    await state.clear()
    user = message.from_user
    await react_message(message.chat.id, message.message_id, "🥂")

    args = message.text.split(maxsplit=1)
    ref_param = args[1].strip() if len(args) > 1 else ""

    if ref_param == "lapak":
        from hans_concierge.shop_gift import send_lapak_list
        return await send_lapak_list(message)

    is_new_guest = False
    async with db.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT user_id, coins FROM users WHERE user_id = $1", user.id)
        if not existing:
            is_new_guest = True
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
            cur_coins = 50
        else:
            await conn.execute(
                "UPDATE users SET username = $1, full_name = $2 WHERE user_id = $3",
                user.username or "NoUsername", user.full_name, user.id
            )
            cur_coins = existing["coins"] or 0

    await get_or_create_referral_code(user.id)
    has_cn = REQUIRED_CN_SYMBOL in (user.full_name or "")
    cn_badge = (
        f"✅ Terpasang (<code>{html.escape(user.full_name)}</code>)"
        if has_cn
        else f"⚠️ Belum terpasang (Wajib simbol <b>{REQUIRED_CN_SYMBOL}</b>)"
    )

    text = (
        "🚪 <i>Lampu gantung kristal menyala temaram di balik tirai beludru merah...</i>\n\n"
        f"<b>\"Selamat malam, {html.escape(user.first_name)}. Saya Hans, Kepala Concierge di <i>The Velvet Hour</i>.\"</b>\n\n"
        f"• <b>Status CN:</b> {cn_badge}\n"
        f"• <b>Saldo Dompet:</b> <b>{cur_coins} VC</b>\n\n"
        "<i>Gunakan panel resepsionis di bawah ini untuk masuk ke ruangan, mengirim curhat/PM ke channel, memeriksa kartu member & mutasi dompet, atau mengundang teman:</i>"
    )
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=await main_lobby_kb(user.id),
        message_effect_id=EFFECT_CONFETTI if is_new_guest else None,
    )


@router.callback_query(F.data == "back_lobby")
async def cb_back_lobby(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    user = call.from_user
    async with db.pool.acquire() as conn:
        coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id) or 0

    text = (
        f"🏛️ <b>LOBI RESEPSIONIS — THE VELVET HOUR</b>\n\n"
        f"<i>Hans merapikan buku tamu kulit di atas meja mahoni.</i>\n"
        f"Tamu: <b>{html.escape(user.first_name)}</b> | Saldo: <b>{coins} VC</b>\n\n"
        f"Silakan pilih layanan yang kamu perlukan:"
    )
    await _send_or_edit_lobby(call, text, await main_lobby_kb(user.id))


# --- VERIFIKASI MASUK BAR (+ CEK CN DETAIL & PASSWORD PINTU) ---
async def _grant_bar_entry(user: types.User, target_msg: types.Message, edit: bool = True):
    ref_bonus_note = ""
    has_ref_bonus = False
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT referred_by, referral_rewarded FROM users WHERE user_id = $1 FOR UPDATE",
                user.id
            )
            if row and row["referred_by"] and not row["referral_rewarded"]:
                has_ref_bonus = True
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
                ref_bonus_note = (
                    f"\n🎉 <b>Bonus Referral Aktif:</b> Kamu dan pengundangmu masing-masing mendapat "
                    f"<b>+{REFERRAL_BONUS_VC} VC</b>!\n"
                )

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
        out = (
            f"✅ <b>VERIFIKASI ATRIBUT ({REQUIRED_CN_SYMBOL}) BERHASIL</b>\n"
            f"{ref_bonus_note}\n"
            "<i>Hans membukakan pintu kayu mahoni dan mempersilakanmu masuk. Tautan pintu sekali pakai di bawah ini berlaku selama 10 menit:</i>"
        )
        if edit and not has_ref_bonus:
            await target_msg.edit_text(out, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            if edit:
                try:
                    await target_msg.delete()
                except Exception:
                    pass
            await target_msg.answer(
                out,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                message_effect_id=EFFECT_CONFETTI if has_ref_bonus else None,
            )
    except Exception as e:
        err_out = (
            f"⚠️ <b>Gagal membuat tautan masuk otomatis</b>\n"
            f"Detail teknis: <code>{html.escape(str(e))}</code>\n"
            f"<i>Pastikan Hans memiliki izin 'Invite Users via Link' di grup utama, atau hubungi Owner.</i>"
        )
        if edit:
            await target_msg.edit_text(err_out, parse_mode=ParseMode.HTML, reply_markup=await main_lobby_kb(user.id))
        else:
            await target_msg.answer(err_out, parse_mode=ParseMode.HTML, reply_markup=await main_lobby_kb(user.id))


@router.callback_query(F.data == "enter_bar")
async def cb_enter_bar(call: types.CallbackQuery, state: FSMContext):
    user = call.from_user
    current_name = user.full_name or ""

    if REQUIRED_CN_SYMBOL not in current_name:
        await call.answer(f"Simbol {REQUIRED_CN_SYMBOL} belum terdeteksi di nama Telegram kamu!", show_alert=True)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Saya Sudah Pasang Simbol, Cek Ulang", callback_data="enter_bar")],
            [InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
        ])
        return await _send_or_edit_lobby(
            call,
            f"🚫 <b>VERIFIKASI ATRIBUT CN BELUM LOLOS</b>\n\n"
            f"• <b>Nama Telegram kamu saat ini:</b> <code>{html.escape(current_name)}</code>\n"
            f"• <b>Simbol wajib bar:</b> <b>{REQUIRED_CN_SYMBOL}</b>\n\n"
            f"<b>Cara memasang:</b>\n"
            f"1. Buka <i>Settings / Pengaturan Telegram</i> → <i>Edit Name</i>.\n"
            f"2. Tambahkan simbol <b>{REQUIRED_CN_SYMBOL}</b> pada nama depan atau belakangmu "
            f"(contoh: <code>{html.escape(user.first_name)} {REQUIRED_CN_SYMBOL}</code>).\n"
            f"3. Tekan tombol <b>Cek Ulang</b> di bawah ini.",
            kb,
        )

    door_pw = await get_bar_setting("door_password")
    if door_pw and user.id != OWNER_ID:
        await call.answer()
        await state.set_state(GatePasswordState.waiting_password)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="back_lobby")]
        ])
        return await _send_or_edit_lobby(
            call,
            "🔐 <b>KATA SANDI PINTU LOUNGE DIPERLUKAN</b>\n\n"
            f"✅ Atribut CN (<code>{html.escape(current_name)}</code>) terverifikasi.\n"
            "<i>Namun malam ini pintu ruang lounge dikunci dengan kata sandi khusus. Silakan ketik kata sandi masuk sekarang:</i>",
            kb,
        )

    await call.answer("Verifikasi CN berhasil!")
    await _grant_bar_entry(user, call.message, edit=(not call.message.photo))


@router.message(GatePasswordState.waiting_password, F.chat.type == "private")
async def fsm_check_door_password(message: types.Message, state: FSMContext):
    user = message.from_user
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Verifikasi pintu dibatalkan.", reply_markup=await main_lobby_kb(user.id))

    door_pw = await get_bar_setting("door_password")
    if not door_pw or message.text.strip() == door_pw:
        await react_message(message.chat.id, message.message_id, "🥂")
        await state.clear()
        return await _grant_bar_entry(user, message, edit=False)

    await react_message(message.chat.id, message.message_id, "👎")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="back_lobby")]
    ])
    await message.answer(
        "❌ <b>Kata sandi tidak cocok!</b>\n"
        "<i>Periksa kembali huruf besar/kecil kata sandi yang diberikan Owner, lalu ketik ulang (atau tekan Batal):</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


# --- DOMPET & KARTU MEMBER VISUAL (AUTO NAMA, USN & PP TELEGRAM) ---
@router.callback_query(F.data == "my_wallet")
async def cb_my_wallet(call: types.CallbackQuery):
    await call.answer("Mencetak kartu keanggotaan...")
    user = call.from_user
    user_id = user.id
    ref_code = await get_or_create_referral_code(user_id)
    avatar_bytes = await _fetch_user_avatar_bytes(user_id)

    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET username = $1, full_name = $2 WHERE user_id = $3",
            user.username or "NoUsername", user.full_name, user_id
        )
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user_id
        )
        txs = await conn.fetch(
            "SELECT amount, reason, created_at FROM wallet_transactions WHERE user_id = $1 ORDER BY id DESC LIMIT 8",
            user_id
        )

    coins = row["coins"] if row else 0
    charm = row["charm_points"] if row else 0
    is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    vip_until_str = row["vip_until"].strftime("%d %b %H:%M UTC") if is_vip else ""
    booth_name = (row["vip_booth_name"] or "") if row else ""

    card_bytes = generate_member_card(
        full_name=user.full_name,
        username=user.username or "",
        coins=coins,
        charm=charm,
        is_vip=is_vip,
        vip_until_str=vip_until_str,
        booth_name=booth_name,
        ref_code=ref_code,
        avatar_bytes=avatar_bytes,
    )

    if txs:
        tx_lines = []
        for t in txs:
            sign = f"+{t['amount']}" if t["amount"] > 0 else f"{t['amount']}"
            icon = "🟢" if t["amount"] > 0 else "🔴"
            tgl = t["created_at"].strftime("%d/%m %H:%M")
            tx_lines.append(f"{icon} <b>{sign} VC</b> — {html.escape(t['reason'])} <i>({tgl})</i>")
        mutasi_block = f"<blockquote expandable>{chr(10).join(tx_lines)}</blockquote>"
    else:
        mutasi_block = "<i>Belum ada catatan transaksi terbaru.</i>"

    caption = (
        f"💳 <b>KARTU KEANGGOTAAN — {html.escape(user.full_name)}</b>\n\n"
        f"📜 <b>Riwayat Transaksi Terakhir:</b>\n{mutasi_block}"
    )

    try:
        await call.message.delete()
    except Exception:
        pass

    await call.message.answer_photo(
        photo=BufferedInputFile(card_bytes, filename=f"velvet_card_{user_id}.png"),
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=await main_lobby_kb(user_id),
    )


# --- ABSEN HARIAN (/daily & TOMBOL + REACTION + EFEK API) ---
async def _process_daily_claim(user_id: int, full_name: str) -> tuple[str, bool]:
    today = datetime.utcnow().date()
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, last_daily FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if row and row["last_daily"] == today:
                return (
                    f"⏳ <b>Jatah Absen Hari Ini Sudah Diambil</b>\n\n"
                    f"Saldo kamu saat ini: <b>{row['coins'] or 0} VC</b>.\n"
                    f"<i>Kembali lagi besok (reset pukul 00:00 UTC) atau selesaikan Misi Harian untuk bonus VC tambahan!</i>",
                    False,
                )
            new_bal = (row["coins"] if row else 0) + DAILY_REWARD_VC
            await conn.execute(
                "UPDATE users SET coins = $1, last_daily = $2 WHERE user_id = $3",
                new_bal, today, user_id
            )
            await log_wallet_tx(conn, user_id, DAILY_REWARD_VC, "Absen harian (/daily)")
    await add_quest_progress(user_id, "daily_checkin", 1)
    return (
        f"📅 <b>ABSEN HARIAN BERHASIL!</b>\n\n"
        f"<i>Hans menyerahkan amplop beludru berisi <b>+{DAILY_REWARD_VC} Velvet Coins</b> kepada <b>{html.escape(full_name)}</b>.</i>\n"
        f"• <b>Saldo Sekarang:</b> <b>{new_bal} VC</b>",
        True,
    )


@router.message(Command("daily"), F.chat.type == "private")
async def cmd_daily_pc(message: types.Message):
    res, claimed_now = await _process_daily_claim(message.from_user.id, message.from_user.first_name)
    await react_message(message.chat.id, message.message_id, "🔥" if claimed_now else "⏳")
    await message.answer(
        res,
        parse_mode=ParseMode.HTML,
        reply_markup=await main_lobby_kb(message.from_user.id),
        message_effect_id=EFFECT_FIRE if claimed_now else None,
    )


@router.callback_query(F.data == "claim_daily")
async def cb_claim_daily(call: types.CallbackQuery):
    await call.answer()
    res, claimed_now = await _process_daily_claim(call.from_user.id, call.from_user.first_name)
    await _send_or_edit_lobby(
        call,
        res,
        await main_lobby_kb(call.from_user.id),
        effect_id=EFFECT_FIRE if claimed_now else None,
    )


# --- MISI HARIAN ---
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
    text = (
        "🎯 <b>MISI HARIAN — THE VELVET HOUR</b>\n"
        "<i>Selesaikan aktivitas ringan setiap hari untuk mendapatkan bonus Velvet Coins:</i>\n\n"
        + "\n\n".join(lines)
    )
    await _send_or_edit_lobby(call, text, InlineKeyboardMarkup(inline_keyboard=buttons))


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
                return await call.answer("Progres misi belum selesai! Ikuti deskripsi misi terlebih dahulu.", show_alert=True)
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
        f"• <b>Tautan Undanganmu (klik untuk salin):</b>\n<code>{ref_link}</code>"
    )
    await _send_or_edit_lobby(call, text, await main_lobby_kb(user_id))


# --- BELI VIP PASS (24 JAM + EFEK KONFETI LAYAR PENUH) ---
@router.callback_query(F.data == "buy_vip")
async def cb_buy_vip(call: types.CallbackQuery):
    user_id = call.from_user.id
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            coins = row["coins"] if row else 0
            if coins < VIP_COST_24H:
                kurang = VIP_COST_24H - coins
                await call.answer(f"Saldo kurang {kurang} VC!", show_alert=True)
                return await _send_or_edit_lobby(
                    call,
                    f"💸 <b>SALDO VELVET COINS BELUM MENCUKUPI</b>\n\n"
                    f"• <b>Harga VIP Pass (24 Jam):</b> {VIP_COST_24H} VC\n"
                    f"• <b>Saldo kamu saat ini:</b> {coins} VC (Kurang <b>{kurang} VC</b>)\n\n"
                    f"<i>Kumpulkan VC gratis dari Absen Harian, Misi Harian, atau chat RP di grup utama:</i>",
                    insufficient_vc_kb(coins, VIP_COST_24H),
                )

            now = datetime.utcnow()
            base_time = row["vip_until"] if (row and row["is_vip"] and row["vip_until"] and row["vip_until"] > now) else now
            new_until = base_time + timedelta(hours=24)

            await conn.execute(
                "UPDATE users SET coins = coins - $1, is_vip = TRUE, vip_until = $2 WHERE user_id = $3",
                VIP_COST_24H, new_until, user_id
            )
            await log_wallet_tx(conn, user_id, -VIP_COST_24H, "Aktivasi VIP Reserve Pass (24 Jam)")

    await call.answer("VIP Pass aktif selama 24 jam!", show_alert=True)
    vip_text = (
        f"🍾 <b>VIP RESERVE PASS AKTIF!</b>\n\n"
        f"• <b>Berlaku hingga:</b> {new_until.strftime('%d %b %Y %H:%M UTC')}\n"
        f"• <b>Sisa Saldo:</b> {coins - VIP_COST_24H} VC\n\n"
        f"• <b>Keuntungan VIP:</b>\n"
        f"  1. Gratis request lagu di grup (<code>/reqsong</code>)\n"
        f"  2. Gratis menu makanan & minuman eksklusif VIP (<code>/order</code> & <code>/eat</code>)\n"
        f"  3. Gratis kirim Curhat (#confess) & PM (#pm) ke Channel\n"
        f"  4. Reservasi meja eksklusif (<code>/booth Nama Booth</code>)\n"
        f"  5. Batas anti-idle 2x lebih lama (120 menit)"
    )
    await _send_or_edit_lobby(call, vip_text, await main_lobby_kb(user_id), effect_id=EFFECT_CONFETTI)


# --- MENU PANDUAN & COMMAND LENGKAP ---
@router.callback_query(F.data == "info_menu")
async def cb_info_menu(call: types.CallbackQuery):
    await call.answer()
    await _send_or_edit_lobby(
        call,
        "📖 <b>BUKU PANDUAN & COMMAND — THE VELVET HOUR</b>\n\n"
        "<i>Pilih kategori di bawah ini untuk melihat seluruh perintah dan contoh penggunaannya di dalam bar:</i>",
        info_categories_kb(),
    )


@router.callback_query(F.data == "info_cmd_bar")
async def cb_info_cmd_bar(call: types.CallbackQuery):
    await call.answer()
    text = (
        "🥂 <b>COMMAND BAR, MENU VIP, BOOTH & MINI-GAME (JULIAN)</b>\n\n"
        "<blockquote expandable>"
        "• <code>/order [nama minuman]</code> — Lihat & pesan minuman:\n"
        "  - <b>Reguler (Gratis):</b> <code>espresso</code>, <code>latte</code>, <code>negroni</code>, <code>whisky</code>, <code>mojito</code>, <code>mocktail</code>, <code>tea</code>, <code>water</code>, atau custom bebas.\n"
        "  - <b>Eksklusif VIP (Gratis VIP / 15 VC):</b> <code>vip_dom</code>, <code>vip_blue</code>, <code>vip_absinthe</code>, <code>vip_royal</code>.\n\n"
        "• <code>/eat [nama makanan]</code> — Lihat & pesan hidangan dapur:\n"
        "  - <b>Reguler (Gratis):</b> <code>fries</code>, <code>steak</code>, <code>pasta</code>, <code>croissant</code>, <code>platter</code>, <code>cake</code>, <code>tiramisu</code>, atau custom bebas.\n"
        "  - <b>Eksklusif VIP (Gratis VIP / 15 VC):</b> <code>vip_caviar</code>, <code>vip_lobster</code>, <code>vip_a5</code>, <code>vip_gold</code>.\n\n"
        "• <code>/treat @username [menu]</code> — Traktir tamu lain (<b>20 VC</b>, penerima dapat <b>+5 Charm</b>).\n"
        "• <code>/booth [Nama Booth]</code> <i>(Khusus VIP)</i> — Reservasi meja VIP eksklusif.\n"
        "• <code>/dice @username [taruhan 10-100 VC]</code> — Duel dadu 1v1 berhadiah VC.\n"
        "• <code>/mystery</code> (40 VC), <code>/toast @user</code>, <code>/bill</code>, <code>/guests</code>, <code>/topcharm</code>, <code>/lapak</code>."
        "</blockquote>"
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
        "  Mengirim file MP3 lagu langsung ke Private Chat kamu (Gratis)."
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
        "• <b>Curhat & PM Channel:</b> Kirim curhat anonim (5 VC) atau PM menfess (10 VC) langsung dari lobi Hans (Gratis untuk VIP).\n"
        "• <b>Undang Teman (Referral):</b> Bagikan tautan undanganmu—kamu dan temanmu sama-sama mendapat <b>+50 VC</b>."
    )
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_info_kb())
