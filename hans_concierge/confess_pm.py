import html
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import shared.database as db
from hans_concierge.helpers import (
    bot, OWNER_ID, CHANNEL_ID, CONFESS_COST_VC, PM_COST_VC,
    get_bar_setting, log_wallet_tx, main_lobby_kb
)

router = Router()

class ConfessPMState(StatesGroup):
    waiting_confess_text = State()
    waiting_pm_target = State()
    waiting_pm_text = State()

async def _resolve_channel_id() -> int | str | None:
    db_ch = await get_bar_setting("target_channel_id")
    if db_ch:
        return int(db_ch) if db_ch.lstrip("-").isdigit() else db_ch
    return CHANNEL_ID

# --- MENU CURHAT (#confess) ---
@router.callback_query(F.data == "menu_confess")
async def cb_menu_confess(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ch_id = await _resolve_channel_id()
    if not ch_id:
        return await call.message.edit_text(
            "⚠️ <b>Channel Confession Belum Dikonfigurasi</b>\n\n"
            "<i>Owner dapat mengatur channel tujuan menggunakan perintah <code>/setch -100xxxx</code> di PC Hans.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(call.from_user.id)
        )

    await state.set_state(ConfessPMState.waiting_confess_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal", callback_data="cancel_confess_pm")]
    ])
    await call.message.edit_text(
        "🕯️ <b>RUANG PENGAKUAN & CURHAT ANONIM (#confess)</b>\n\n"
        f"• <b>Biaya Kirim:</b> <b>{CONFESS_COST_VC} VC</b> (Gratis untuk VIP)\n"
        "• <b>Privasi:</b> Identitasmu 100% dirahasiakan di Channel.\n\n"
        "<i>Silakan ketik dan kirim isi curhatanmu sekarang:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@router.message(Command("confess"), F.chat.type == "private")
async def cmd_confess_direct(message: types.Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(ConfessPMState.waiting_confess_text)
        return await message.answer(
            f"🕯️ Ketik isi curhatan anonim kamu (Biaya: <b>{CONFESS_COST_VC} VC</b>, Gratis VIP), atau /cancel untuk batal:",
            parse_mode=ParseMode.HTML
        )
    await _publish_confess(message, parts[1].strip())

@router.message(ConfessPMState.waiting_confess_text, F.chat.type == "private")
async def fsm_receive_confess(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman curhat dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))
    await state.clear()
    await _publish_confess(message, message.text.strip())

async def _publish_confess(message: types.Message, content: str):
    user = message.from_user
    ch_id = await _resolve_channel_id()
    if not ch_id:
        return await message.answer("Channel tujuan belum diatur oleh Owner.", reply_markup=await main_lobby_kb(user.id))

    if len(content) < 5:
        return await message.answer("Isi curhatan terlalu singkat (minimal 5 karakter).", reply_markup=await main_lobby_kb(user.id))

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            from datetime import datetime
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else CONFESS_COST_VC
            coins = row["coins"] if row else 0

            if coins < cost:
                return await message.answer(
                    f"Saldo VC tidak cukup! Butuh <b>{cost} VC</b> untuk mengirim curhat.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=await main_lobby_kb(user.id)
                )

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await log_wallet_tx(conn, user.id, -cost, "Kirim Curhat Anonim (#confess)")

            post_id = await conn.fetchval("""
                INSERT INTO channel_posts (user_id, post_type, content)
                VALUES ($1, 'confess', $2) RETURNING id
            """, user.id, content)

    me = await bot.get_me()
    ch_text = (
        f"🕯️ <b>CONFESSION — #VH{post_id:03d}</b>\n\n"
        f"“{html.escape(content)}”\n\n"
        f"— <i>Anonymous Guest</i> | #confess\n"
        f"<i>Kirim curhat atau PM rahasia via @{me.username}</i>"
    )
    try:
        await bot.send_message(ch_id, ch_text, parse_mode=ParseMode.HTML)
        await message.answer(
            f"✅ <b>Curhat #VH{post_id:03d} berhasil diterbitkan secara anonim ke Channel!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(user.id)
        )
    except Exception as e:
        await message.answer(
            f"⚠️ Gagal mengirim ke channel (<code>{html.escape(str(e))}</code>). Pastikan Hans sudah menjadi admin di Channel.",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(user.id)
        )

# --- MENU PM / MENFESS KE CHANNEL (#pm) ---
@router.callback_query(F.data == "menu_pm")
async def cb_menu_pm(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ch_id = await _resolve_channel_id()
    if not ch_id:
        return await call.message.edit_text(
            "⚠️ <b>Channel Menfess Belum Dikonfigurasi</b>\n\n"
            "<i>Owner dapat mengatur channel tujuan menggunakan perintah <code>/setch -100xxxx</code> di PC Hans.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(call.from_user.id)
        )

    await state.set_state(ConfessPMState.waiting_pm_target)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal", callback_data="cancel_confess_pm")]
    ])
    await call.message.edit_text(
        "💌 <b>KIRIM PRIVATE MESSAGE / MENFESS KE CHANNEL (#pm)</b>\n\n"
        f"• <b>Biaya Kirim:</b> <b>{PM_COST_VC} VC</b> (Gratis untuk VIP)\n"
        "• <b>Langkah 1/2:</b> Masukkan <b>Nama / @username / Inisial Penerima</b> pesan ini:\n"
        "<i>(Contoh: <code>@clara</code> atau <code>Untuk si pemilik mata teduh di sudut bar</code>)</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@router.message(ConfessPMState.waiting_pm_target, F.chat.type == "private")
async def fsm_pm_target(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman PM dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))

    await state.update_data(target_to=message.text.strip()[:60])
    await state.set_state(ConfessPMState.waiting_pm_text)
    await message.answer(
        "✍️ <b>Langkah 2/2:</b> Sekarang ketik <b>isi pesan rahasia</b> yang ingin kamu sampaikan kepadanya:",
        parse_mode=ParseMode.HTML
    )

@router.message(ConfessPMState.waiting_pm_text, F.chat.type == "private")
async def fsm_pm_text(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman PM dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))

    data = await state.get_data()
    target_to = data.get("target_to", "Someone")
    content = message.text.strip()
    await state.clear()

    user = message.from_user
    ch_id = await _resolve_channel_id()
    if not ch_id:
        return await message.answer("Channel tujuan belum diatur oleh Owner.", reply_markup=await main_lobby_kb(user.id))

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            from datetime import datetime
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else PM_COST_VC
            coins = row["coins"] if row else 0

            if coins < cost:
                return await message.answer(
                    f"Saldo VC tidak cukup! Butuh <b>{cost} VC</b> untuk mengirim PM ke Channel.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=await main_lobby_kb(user.id)
                )

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await log_wallet_tx(conn, user.id, -cost, f"Kirim PM Channel untuk {target_to}")

            post_id = await conn.fetchval("""
                INSERT INTO channel_posts (user_id, post_type, target_to, content)
                VALUES ($1, 'pm', $2, $3) RETURNING id
            """, user.id, target_to, content)

    me = await bot.get_me()
    ch_text = (
        f"💌 <b>VELVET MENFESS — #PM{post_id:03d}</b>\n\n"
        f"<b>To:</b> {html.escape(target_to)}\n"
        f"<b>Message:</b>\n“{html.escape(content)}”\n\n"
        f"— <i>Secret Admirer</i> | #pm\n"
        f"<i>Kirim curhat atau PM rahasia via @{me.username}</i>"
    )
    try:
        await bot.send_message(ch_id, ch_text, parse_mode=ParseMode.HTML)
        await message.answer(
            f"✅ <b>Pesan #PM{post_id:03d} untuk {html.escape(target_to)} berhasil dikirim ke Channel!</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(user.id)
        )
    except Exception as e:
        await message.answer(
            f"⚠️ Gagal mengirim ke channel (<code>{html.escape(str(e))}</code>).",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(user.id)
        )

@router.callback_query(F.data == "cancel_confess_pm")
async def cb_cancel_confess_pm(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Dibatalkan")
    await call.message.edit_text(
        "🏛️ <b>LOBI RESEPSIONIS — THE VELVET HOUR</b>\n\nSilakan pilih layanan yang kamu perlukan:",
        parse_mode=ParseMode.HTML,
        reply_markup=await main_lobby_kb(call.from_user.id)
        )
          
