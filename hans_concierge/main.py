import html
import asyncio
import logging

from aiogram import Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import OWNER_ID
from hans_concierge.helpers import (
    bot, ensure_hans_schema, is_staff_or_owner, resolve_target_user,
    log_wallet_tx, get_bar_setting, set_bar_setting
)
from hans_concierge.gate_wallet import router as gate_wallet_router
from hans_concierge.shop_gift import router as shop_gift_router
from hans_concierge.confess_pm import router as confess_pm_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(gate_wallet_router)
dp.include_router(shop_gift_router)
dp.include_router(confess_pm_router)


class AdminActionState(StatesGroup):
    waiting_new_pw = State()
    waiting_channel_id = State()
    waiting_givevc = State()
    waiting_addshop = State()
    waiting_delshop = State()
    waiting_addadmin = State()
    waiting_deladmin = State()


async def _build_admin_dashboard(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    is_owner = (user_id == OWNER_ID)
    cur_pw = await get_bar_setting("door_password")
    pw_status = f"<code>{html.escape(cur_pw)}</code> (🟢 Aktif)" if cur_pw else "<i>Nonaktif (Bebas masuk dengan CN)</i>"
    cur_ch = await get_bar_setting("target_channel_id") or "<i>Belum diatur</i>"

    async with db.pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        total_vip = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_vip = TRUE AND vip_until > NOW()") or 0
        total_shops = await conn.fetchval("SELECT COUNT(*) FROM partner_shops") or 0
        total_posts = await conn.fetchval("SELECT COUNT(*) FROM channel_posts") or 0

    if is_owner:
        text = (
            "👑 <b>PANEL KONTROL UTAMA — OWNER THE VELVET HOUR</b>\n\n"
            f"📊 <b>Ringkasan Bar:</b> {total_users} Tamu | {total_vip} VIP Aktif | {total_shops} Lapak | {total_posts} Confess/PM\n"
            f"🔐 <b>Password Pintu:</b> {pw_status}\n"
            f"📢 <b>Channel Confess/PM:</b> <code>{html.escape(str(cur_ch))}</code>\n\n"
            "<i>Pilih tombol aksi di bawah ini atau gunakan slash command cepat:</i>"
        )
        buttons = [
            [
                InlineKeyboardButton(text="🔐 Ganti Password Pintu", callback_data="adm_setpw"),
                InlineKeyboardButton(text="🔓 Matikan Password", callback_data="adm_delpw"),
            ],
            [
                InlineKeyboardButton(text="📢 Atur Channel CH", callback_data="adm_setch"),
                InlineKeyboardButton(text="💰 Suntik Saldo VC", callback_data="adm_givevc"),
            ],
            [
                InlineKeyboardButton(text="🏪 Tambah Lapak", callback_data="adm_addshop"),
                InlineKeyboardButton(text="🗑️ Hapus Lapak", callback_data="adm_delshop"),
            ],
            [
                InlineKeyboardButton(text="👮 Angkat Admin", callback_data="adm_addadmin"),
                InlineKeyboardButton(text="🚫 Cabut Admin", callback_data="adm_deladmin"),
            ],
            [InlineKeyboardButton(text="📋 Daftar Lapak & Staf Admin", callback_data="adm_list_overview")],
            [InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
        ]
    else:
        text = (
            "🛡️ <b>PANEL STAF ADMIN — THE VELVET HOUR</b>\n\n"
            f"📊 <b>Ringkasan Bar:</b> {total_users} Tamu | {total_shops} Lapak Partner\n\n"
            "<i>Pilih aksi pengelolaan lapak partner di bawah ini:</i>"
        )
        buttons = [
            [
                InlineKeyboardButton(text="🏪 Tambah Lapak Partner", callback_data="adm_addshop"),
                InlineKeyboardButton(text="🗑️ Hapus Lapak Partner", callback_data="adm_delshop"),
            ],
            [InlineKeyboardButton(text="📋 Lihat Daftar Lapak", callback_data="adm_list_overview")],
            [InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")],
        ]

    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


# --- ENTRY POINT PANEL ADMIN/OWNER (TOMBOL & /admin) ---
@dp.callback_query(F.data == "open_admin_panel")
async def cb_open_admin_panel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    if not await is_staff_or_owner(user_id):
        return await call.answer("Akses ditolak. Khusus Staf Admin dan Owner.", show_alert=True)
    await call.answer()
    text, kb = await _build_admin_dashboard(user_id)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("admin"), F.chat.type == "private")
async def cmd_admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    if not await is_staff_or_owner(user_id):
        return
    text, kb = await _build_admin_dashboard(user_id)
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.callback_query(F.data == "adm_list_overview")
async def cb_adm_list_overview(call: types.CallbackQuery):
    if not await is_staff_or_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer()

    async with db.pool.acquire() as conn:
        shops = await conn.fetch("SELECT id, shop_name, owner_username FROM partner_shops ORDER BY id ASC")
        admins = await conn.fetch("SELECT user_id, username, full_name FROM users WHERE is_admin = TRUE")

    shop_lines = [
        f"• ID <code>{s['id']}</code> — <b>{html.escape(s['shop_name'])}</b> (@{s['owner_username'] or 'NoUsername'})"
        for s in shops
    ] or ["<i>Belum ada lapak terdaftar.</i>"]

    admin_lines = [
        f"• <b>{html.escape(a['full_name'])}</b> (@{a['username'] or a['user_id']})"
        for a in admins
    ] or ["<i>Belum ada Staf Admin tambahan.</i>"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]
    ])
    await call.message.edit_text(
        "📋 <b>DAFTAR LAPAK PARTNER & STAF ADMIN</b>\n\n"
        "<b>🏪 Lapak Partner Aktif:</b>\n" + "\n".join(shop_lines) + "\n\n"
        "<b>👮 Staf Admin Aktif:</b>\n" + "\n".join(admin_lines),
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


# --- INTERAKTIF: PASSWORD PINTU BAR ---
@dp.callback_query(F.data == "adm_setpw")
async def cb_adm_setpw(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return await call.answer("Khusus Owner bar!", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_new_pw)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "🔐 <b>GANTI PASSWORD PINTU MASUK BAR</b>\n\n"
        "Ketik kata sandi baru yang harus dimasukkan tamu sebelum menerima tautan grup:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_new_pw, F.chat.type == "private")
async def fsm_adm_setpw(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    new_pw = message.text.strip()
    await set_bar_setting("door_password", new_pw)
    await state.clear()
    text, kb = await _build_admin_dashboard(message.from_user.id)
    await message.answer(
        f"✅ <b>Password pintu bar berhasil diatur ke:</b> <code>{html.escape(new_pw)}</code>\n\n" + text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.callback_query(F.data == "adm_delpw")
async def cb_adm_delpw(call: types.CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return await call.answer("Khusus Owner bar!", show_alert=True)
    await set_bar_setting("door_password", None)
    await call.answer("Password pintu dimatikan!", show_alert=True)
    text, kb = await _build_admin_dashboard(call.from_user.id)
    await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("setpw"), F.chat.type == "private")
async def cmd_setpw(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        cur_pw = await get_bar_setting("door_password")
        status = f"<code>{html.escape(cur_pw)}</code>" if cur_pw else "<i>Belum dipasang</i>"
        return await message.answer(
            f"🔐 <b>Password Pintu Saat Ini:</b> {status}\n\n"
            f"Format ganti password: <code>/setpw katasandibaru</code>\n"
            f"Untuk mematikan password: <code>/delpw</code>",
            parse_mode=ParseMode.HTML
        )

    new_pw = parts[1].strip()
    await set_bar_setting("door_password", new_pw)
    await message.answer(
        f"✅ <b>Password pintu masuk bar berhasil diperbarui!</b>\n"
        f"Kata sandi baru: <code>{html.escape(new_pw)}</code>",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("delpw"), F.chat.type == "private")
async def cmd_delpw(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    await set_bar_setting("door_password", None)
    await message.answer("🔓 <b>Password pintu masuk bar dimatikan.</b> Tamu dengan simbol CN dapat langsung masuk.", parse_mode=ParseMode.HTML)


# --- INTERAKTIF & VALIDASI LIVE: ATUR CHANNEL CONFESS & PM ---
async def _apply_and_verify_channel(raw_ch: str) -> str:
    ch_val = raw_ch.strip()
    target = int(ch_val) if ch_val.lstrip("-").isdigit() else ch_val
    try:
        chat = await bot.get_chat(target)
        me = await bot.get_me()
        member = await bot.get_chat_member(target, me.id)
        can_post = getattr(member, "can_post_messages", False) or member.status in ("administrator", "creator")
        await set_bar_setting("target_channel_id", str(chat.id))
        if can_post:
            return (
                f"✅ <b>Channel Terhubung & Terverifikasi!</b>\n"
                f"• <b>Nama Channel:</b> {html.escape(chat.title or str(chat.id))}\n"
                f"• <b>ID Channel:</b> <code>{chat.id}</code>\n"
                f"• <b>Status Bot:</b> Admin siap memposting #confess & #pm."
            )
        return (
            f"⚠️ <b>Channel Tersimpan, Namun Izin Posting Belum Aktif</b>\n"
            f"• <b>Nama Channel:</b> {html.escape(chat.title or str(chat.id))} (<code>{chat.id}</code>)\n"
            f"• <b>Tindakan:</b> Jadikan @{me.username} sebagai <b>Admin</b> dengan izin <i>Post Messages</i> di channel tersebut."
        )
    except Exception as e:
        await set_bar_setting("target_channel_id", ch_val)
        return (
            f"⚠️ <b>ID Channel Disimpan (<code>{html.escape(ch_val)}</code>), Namun Gagal Verifikasi Otomatis</b>\n"
            f"• <b>Alasan:</b> <code>{html.escape(str(e))}</code>\n"
            f"• <i>Pastikan Hans sudah dimasukkan sebagai Admin ke dalam channel tersebut.</i>"
        )


@dp.callback_query(F.data == "adm_setch")
async def cb_adm_setch(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return await call.answer("Khusus Owner bar!", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_channel_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "📢 <b>ATUR CHANNEL TUJUAN #CONFESS & #PM</b>\n\n"
        "Kirimkan <b>ID Channel</b> (contoh: <code>-1001234567890</code>) atau <b>@username_channel</b>.\n"
        "<i>Hans akan langsung memeriksa koneksi dan izin posting di channel tersebut:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_channel_id, F.chat.type == "private")
async def fsm_adm_setch(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    res = await _apply_and_verify_channel(message.text)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]])
    await message.answer(res, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("setch"), F.chat.type == "private")
async def cmd_setch(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Format: <code>/setch -1001234567890</code> (atau <code>@usernamechannel</code>)", parse_mode=ParseMode.HTML)

    res = await _apply_and_verify_channel(parts[1])
    await message.answer(res, parse_mode=ParseMode.HTML)


# --- INTERAKTIF & SLASH: SUNTIK SALDO VC (/givevc) ---
async def _execute_givevc(target_ident: str, amount: int) -> str:
    async with db.pool.acquire() as conn:
        user = await resolve_target_user(conn, target_ident)
        if not user:
            return (
                f"❌ Tamu <code>{html.escape(target_ident)}</code> tidak ditemukan di database.\n"
                f"<i>Pastikan tamu tersebut sudah pernah menekan /start pada bot Hans atau mengirim pesan di grup.</i>"
            )
        new_coins = (user["coins"] or 0) + amount
        await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, user["user_id"])
        await log_wallet_tx(conn, user["user_id"], amount, "Penyesuaian saldo eksklusif oleh Owner")

    try:
        sign_txt = f"+{amount}" if amount > 0 else str(amount)
        await bot.send_message(
            user["user_id"],
            f"💎 <b>PENYESUAIAN SALDO OLEH OWNER</b>\n\n"
            f"Saldo dompet kamu diperbarui sebesar <b>{sign_txt} VC</b>.\n"
            f"• <b>Total Saldo Sekarang:</b> <b>{new_coins} VC</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    return (
        f"✅ <b>Saldo Berhasil Diperbarui!</b>\n"
        f"• <b>Tamu:</b> {html.escape(user['full_name'])} (@{user['username']})\n"
        f"• <b>Perubahan:</b> {'+' if amount > 0 else ''}{amount} VC\n"
        f"• <b>Saldo Akhir:</b> <b>{new_coins} VC</b>"
    )


@dp.callback_query(F.data == "adm_givevc")
async def cb_adm_givevc(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return await call.answer("Khusus Owner bar!", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_givevc)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "💰 <b>SUNTIK / SESUAIKAN SALDO VC TAMU</b>\n\n"
        "Ketik <b>@username</b> (atau User ID) diikuti <b>jumlah VC</b>:\n"
        "<i>Contoh: <code>@clara 100</code> atau <code>@alvaro -50</code></i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_givevc, F.chat.type == "private")
async def fsm_adm_givevc(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        return await message.answer("Format salah. Ketik: <code>@username 100</code>", parse_mode=ParseMode.HTML)

    res = await _execute_givevc(parts[0], int(parts[1]))
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]])
    await message.answer(res, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("givevc"), F.chat.type == "private")
async def cmd_givevc(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    parts = message.text.split()
    if len(parts) < 3 or not parts[2].lstrip("-").isdigit():
        return await message.answer("Format: <code>/givevc @username jumlah</code>", parse_mode=ParseMode.HTML)

    res = await _execute_givevc(parts[1], int(parts[2]))
    await message.answer(res, parse_mode=ParseMode.HTML)


# --- INTERAKTIF & SLASH: LAPAK PARTNER (/addshop & /delshop) ---
async def _execute_addshop(target_ident: str, shop_name: str) -> str:
    async with db.pool.acquire() as conn:
        user = await resolve_target_user(conn, target_ident)
        if not user:
            return (
                f"❌ User <code>{html.escape(target_ident)}</code> belum terdaftar di database Hans.\n"
                f"<i>Minta calon pemilik toko membuka PC Hans (/start) terlebih dahulu.</i>"
            )
        shop_id = await conn.fetchval("""
            INSERT INTO partner_shops (owner_id, owner_username, shop_name)
            VALUES ($1, $2, $3) RETURNING id
        """, user["user_id"], user["username"], shop_name)

    try:
        await bot.send_message(
            user["user_id"],
            f"🏪 <b>LAPAK PARTNER KAMU TELAH DIBUKA!</b>\n\n"
            f"• <b>Nama Lapak:</b> {html.escape(shop_name)} (ID: <code>{shop_id}</code>)\n"
            f"• <b>Cara Mengisi Etalase:</b> Buka menu <i>Pojok Lapak Partner</i> → pilih lapakmu → klik <b>➕ Tambah Item Baru</b>.",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    return (
        f"✅ <b>Lapak Partner Berhasil Didaftarkan!</b>\n"
        f"• <b>ID Toko:</b> <code>{shop_id}</code>\n"
        f"• <b>Nama Toko:</b> {html.escape(shop_name)}\n"
        f"• <b>Pemilik:</b> {html.escape(user['full_name'])} (@{user['username']})"
    )


@dp.callback_query(F.data == "adm_addshop")
async def cb_adm_addshop(call: types.CallbackQuery, state: FSMContext):
    if not await is_staff_or_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_addshop)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "🏪 <b>DAFTARKAN LAPAK PARTNER BARU</b>\n\n"
        "Ketik <b>@username pemilik</b> diikuti <b>Nama Toko</b>:\n"
        "<i>Contoh: <code>@clara Velvet Atelier</code></i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_addshop, F.chat.type == "private")
async def fsm_adm_addshop(message: types.Message, state: FSMContext):
    if not await is_staff_or_owner(message.from_user.id):
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Format salah. Ketik: <code>@username Nama Toko</code>", parse_mode=ParseMode.HTML)

    res = await _execute_addshop(parts[0], parts[1].strip())
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]])
    await message.answer(res, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("addshop"), F.chat.type == "private")
async def cmd_addshop(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.answer("Format: <code>/addshop @username Nama Toko</code>", parse_mode=ParseMode.HTML)

    res = await _execute_addshop(parts[1], parts[2].strip())
    await message.answer(res, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "adm_delshop")
async def cb_adm_delshop(call: types.CallbackQuery, state: FSMContext):
    if not await is_staff_or_owner(call.from_user.id):
        return await call.answer("Akses ditolak.", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_delshop)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "🗑️ <b>HAPUS LAPAK PARTNER</b>\n\n"
        "Ketik <b>ID Toko</b> (angka) yang ingin dihapus (cek ID di menu <i>Daftar Lapak & Staf Admin</i>):",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_delshop, F.chat.type == "private")
async def fsm_adm_delshop(message: types.Message, state: FSMContext):
    if not await is_staff_or_owner(message.from_user.id):
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    if not message.text.strip().isdigit():
        return await message.answer("Masukkan angka ID Toko yang valid.")

    shop_id = int(message.text.strip())
    async with db.pool.acquire() as conn:
        deleted = await conn.fetchval("DELETE FROM partner_shops WHERE id = $1 RETURNING shop_name", shop_id)

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]])
    if deleted:
        await message.answer(f"🗑️ Lapak <b>{html.escape(deleted)}</b> (ID: <code>{shop_id}</code>) telah dihapus.", parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.answer(f"⚠️ Lapak dengan ID <code>{shop_id}</code> tidak ditemukan.", parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("delshop"), F.chat.type == "private")
async def cmd_delshop(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("Format: <code>/delshop ID_Toko</code>", parse_mode=ParseMode.HTML)
    shop_id = int(parts[1])
    async with db.pool.acquire() as conn:
        deleted = await conn.fetchval("DELETE FROM partner_shops WHERE id = $1 RETURNING shop_name", shop_id)
    if deleted:
        await message.answer(f"🗑️ Lapak <b>{html.escape(deleted)}</b> (ID: <code>{shop_id}</code>) telah dihapus.", parse_mode=ParseMode.HTML)
    else:
        await message.answer(f"⚠️ Lapak ID <code>{shop_id}</code> tidak ditemukan.", parse_mode=ParseMode.HTML)


# --- INTERAKTIF & SLASH: KELOLA STAF ADMIN (/addadmin & /deladmin) ---
async def _set_admin_role(target_ident: str, make_admin: bool) -> str:
    async with db.pool.acquire() as conn:
        user = await resolve_target_user(conn, target_ident)
        if not user:
            return f"❌ User <code>{html.escape(target_ident)}</code> tidak ditemukan di database Hans."
        await conn.execute("UPDATE users SET is_admin = $1 WHERE user_id = $2", make_admin, user["user_id"])

    if make_admin:
        return f"✅ <b>{html.escape(user['full_name'])}</b> (@{user['username']}) sekarang memiliki akses <b>Staf Admin</b>."
    return f"🗑️ Akses Staf Admin untuk <b>{html.escape(user['full_name'])}</b> (@{user['username']}) telah dicabut."


@dp.callback_query(F.data == "adm_addadmin")
async def cb_adm_addadmin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return await call.answer("Khusus Owner bar!", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_addadmin)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "👮 <b>ANGKAT STAF ADMIN BARU</b>\n\nKetik <b>@username</b> (atau User ID) yang ingin diangkat menjadi Staf Admin:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_addadmin, F.chat.type == "private")
async def fsm_adm_addadmin(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    res = await _set_admin_role(message.text.strip().split()[0], True)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]])
    await message.answer(res, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.callback_query(F.data == "adm_deladmin")
async def cb_adm_deladmin(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return await call.answer("Khusus Owner bar!", show_alert=True)
    await call.answer()
    await state.set_state(AdminActionState.waiting_deladmin)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data="open_admin_panel")]])
    await call.message.edit_text(
        "🚫 <b>CABUT AKSES STAF ADMIN</b>\n\nKetik <b>@username</b> (atau User ID) yang ingin dicabut akses adminnya:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@dp.message(AdminActionState.waiting_deladmin, F.chat.type == "private")
async def fsm_adm_deladmin(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        text, kb = await _build_admin_dashboard(message.from_user.id)
        return await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)

    res = await _set_admin_role(message.text.strip().split()[0], False)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Kembali ke Panel Kontrol", callback_data="open_admin_panel")]])
    await message.answer(res, parse_mode=ParseMode.HTML, reply_markup=kb)


@dp.message(Command("addadmin"), F.chat.type == "private")
async def cmd_addadmin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Format: <code>/addadmin @username</code>", parse_mode=ParseMode.HTML)
    await message.answer(await _set_admin_role(parts[1], True), parse_mode=ParseMode.HTML)


@dp.message(Command("deladmin"), F.chat.type == "private")
async def cmd_deladmin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)
    parts = message.text.split()
    if len(parts) < 2:
        return await message.answer("Format: <code>/deladmin @username</code>", parse_mode=ParseMode.HTML)
    await message.answer(await _set_admin_role(parts[1], False), parse_mode=ParseMode.HTML)


async def register_hans_commands():
    private_cmds = [
        BotCommand(command="start", description="Buka Lobi Resepsionis & Pintu Masuk Bar"),
        BotCommand(command="daily", description="Klaim Absen Harian (+20 VC)"),
        BotCommand(command="confess", description="Kirim Curhat Anonim ke Channel (#confess)"),
        BotCommand(command="admin", description="[Staf/Owner] Panel Kontrol Bar, Password & Lapak"),
    ]
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())


async def main():
    await db.init_db()
    await ensure_hans_schema()
    await register_hans_commands()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
