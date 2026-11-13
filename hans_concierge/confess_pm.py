import re
import html
from datetime import datetime
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import shared.database as db
from hans_concierge.helpers import (
    bot, CHANNEL_ID, CONFESS_COST_VC, PM_COST_VC,
    get_bar_setting, log_wallet_tx, insufficient_vc_kb, main_lobby_kb
)

router = Router()


class ConfessPMState(StatesGroup):
    waiting_confess_text = State()
    waiting_pm_target = State()
    waiting_pm_text = State()


def _format_user_html(raw_text: str) -> str:
    """Escape HTML safely while converting [spoiler]...[/spoiler] into <tg-spoiler>...</tg-spoiler>."""
    escaped = html.escape(raw_text)
    return re.sub(
        r"\[spoiler\](.+?)\[/spoiler\]",
        r"<tg-spoiler>\1</tg-spoiler>",
        escaped,
        flags=re.IGNORECASE | re.DOTALL,
    )


async def _resolve_channel_id() -> int | str | None:
    db_ch = await get_bar_setting("target_channel_id")
    if db_ch:
        return int(db_ch) if db_ch.lstrip("-").isdigit() else db_ch
    return CHANNEL_ID


def _build_post_link(ch_id: int | str, sent_msg: types.Message) -> str | None:
    if sent_msg.chat and sent_msg.chat.username:
        return f"https://t.me/{sent_msg.chat.username}/{sent_msg.message_id}"
    if isinstance(ch_id, str) and ch_id.startswith("@"):
        return f"https://t.me/{ch_id.lstrip('@')}/{sent_msg.message_id}"
    raw_id = str(ch_id)
    if raw_id.startswith("-100"):
        return f"https://t.me/c/{raw_id[4:]}/{sent_msg.message_id}"
    return None


# --- MENU CURHAT (#confess) ---
@router.callback_query(F.data == "menu_confess")
async def cb_menu_confess(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ch_id = await _resolve_channel_id()
    if not ch_id:
        return await call.message.edit_text(
            "⚠️ <b>Channel Confession Belum Dikonfigurasi</b>\n\n"
            "<i>Owner dapat mengatur channel tujuan melalui <b>Panel Kontrol Admin / Owner</b> atau perintah <code>/setch -100xxxx</code>.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(call.from_user.id)
        )

    await state.set_state(ConfessPMState.waiting_confess_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await call.message.edit_text(
        "🕯️ <b>RUANG PENGAKUAN & CURHAT ANONIM (#confess)</b>\n\n"
        f"• <b>Biaya Kirim:</b> <b>{CONFESS_COST_VC} VC</b> (Gratis untuk VIP)\n"
        "• <b>Privasi:</b> Identitasmu 100% dirahasiakan di Channel.\n"
        "• <b>Tips Efek Spoiler:</b> Gunakan <code>[spoiler]teks rahasia[/spoiler]</code> untuk menyembunyikan nama/kalimat tertentu.\n\n"
        "<i>Silakan ketik dan kirim isi curhatanmu sekarang (minimal 5 karakter):</i>",
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
        return await message.answer(
            "⚠️ Isi curhatan terlalu singkat (minimal 5 karakter). Silakan ulangi dari menu lobi.",
            reply_markup=await main_lobby_kb(user.id)
        )

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else CONFESS_COST_VC
            coins = row["coins"] if row else 0

            if coins < cost:
                return await message.answer(
                    f"💸 <b>Saldo VC Tidak Cukup</b>\n\n"
                    f"Butuh <b>{cost} VC</b> untuk mengirim curhat (saldo kamu: <b>{coins} VC</b>).",
                    parse_mode=ParseMode.HTML,
                    reply_markup=insufficient_vc_kb(coins, cost)
                )

            new_bal = coins - cost
            if cost > 0:
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_bal, user.id)
                await log_wallet_tx(conn, user.id, -cost, "Kirim Curhat Anonim (#confess)")

            post_id = await conn.fetchval("""
                INSERT INTO channel_posts (user_id, post_type, content)
                VALUES ($1, 'confess', $2) RETURNING id
            """, user.id, content)

    me = await bot.get_me()
    formatted_body = _format_user_html(content)
    ch_text = (
        f"🕯️ <b>CONFESSION — #VH{post_id:03d}</b>\n\n"
        f"“{formatted_body}”\n\n"
        f"— <i>Anonymous Guest</i> | #confess\n"
        f"<i>Kirim curhat atau PM rahasia via @{me.username}</i>"
    )
    try:
        sent_msg = await bot.send_message(ch_id, ch_text, parse_mode=ParseMode.HTML)
        post_url = _build_post_link(ch_id, sent_msg)
        rows = []
        if post_url:
            rows.append([InlineKeyboardButton(text="🔗 Lihat Postingan di Channel", url=post_url)])
        rows.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")])

        cost_note = "Gratis (VIP Pass)" if cost == 0 else f"-{cost} VC (Sisa saldo: <b>{new_bal} VC</b>)"
        await message.answer(
            f"✅ <b>Curhat #VH{post_id:03d} Berhasil Diterbitkan!</b>\n"
            f"• <b>Biaya:</b> {cost_note}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    except Exception as e:
        await message.answer(
            f"⚠️ <b>Gagal mengirim ke channel</b>\n"
            f"Detail: <code>{html.escape(str(e))}</code>\n"
            f"<i>Pastikan @HansVolkovVH_bot sudah dijadikan Admin dengan izin 'Post Messages' di Channel tersebut.</i>",
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
            "<i>Owner dapat mengatur channel tujuan melalui <b>Panel Kontrol Admin / Owner</b> atau perintah <code>/setch -100xxxx</code>.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(call.from_user.id)
        )

    await state.set_state(ConfessPMState.waiting_pm_target)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await call.message.edit_text(
        "💌 <b>KIRIM PRIVATE MESSAGE / MENFESS KE CHANNEL (#pm)</b>\n\n"
        f"• <b>Biaya Kirim:</b> <b>{PM_COST_VC} VC</b> (Gratis untuk VIP)\n"
        "• <b>Langkah 1/2:</b> Masukkan <b>Nama / @username / Inisial Penerima</b> pesan ini:\n"
        "<i>(Bisa gunakan <code>[spoiler]@username[/spoiler]</code> jika ingin nama penerima disensor)</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )


@router.message(ConfessPMState.waiting_pm_target, F.chat.type == "private")
async def fsm_pm_target(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman PM dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))

    target_to = message.text.strip()[:80]
    await state.update_data(target_to=target_to)
    await state.set_state(ConfessPMState.waiting_pm_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await message.answer(
        f"✍️ <b>Langkah 2/2 — Penerima: {_format_user_html(target_to)}</b>\n\n"
        "Sekarang ketik <b>isi pesan rahasia</b> yang ingin kamu sampaikan kepadanya "
        "(mendukung <code>[spoiler]...[/spoiler]</code>):",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
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
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else PM_COST_VC
            coins = row["coins"] if row else 0

            if coins < cost:
                return await message.answer(
                    f"💸 <b>Saldo VC Tidak Cukup</b>\n\n"
                    f"Butuh <b>{cost} VC</b> untuk mengirim PM ke Channel (saldo kamu: <b>{coins} VC</b>).",
                    parse_mode=ParseMode.HTML,
                    reply_markup=insufficient_vc_kb(coins, cost)
                )

            new_bal = coins - cost
            if cost > 0:
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_bal, user.id)
                await log_wallet_tx(conn, user.id, -cost, f"Kirim PM Channel untuk {target_to}")

            post_id = await conn.fetchval("""
                INSERT INTO channel_posts (user_id, post_type, target_to, content)
                VALUES ($1, 'pm', $2, $3) RETURNING id
            """, user.id, target_to, content)

    me = await bot.get_me()
    ch_text = (
        f"💌 <b>VELVET MENFESS — #PM{post_id:03d}</b>\n\n"
        f"<b>To:</b> {_format_user_html(target_to)}\n"
        f"<b>Message:</b>\n“{_format_user_html(content)}”\n\n"
        f"— <i>Secret Admirer</i> | #pm\n"
        f"<i>Kirim curhat atau PM rahasia via @{me.username}</i>"
    )
    try:
        sent_msg = await bot.send_message(ch_id, ch_text, parse_mode=ParseMode.HTML)
        post_url = _build_post_link(ch_id, sent_msg)
        rows = []
        if post_url:
            rows.append([InlineKeyboardButton(text="🔗 Lihat Postingan di Channel", url=post_url)])
        rows.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")])

        cost_note = "Gratis (VIP Pass)" if cost == 0 else f"-{cost} VC (Sisa saldo: <b>{new_bal} VC</b>)"
        await message.answer(
            f"✅ <b>Pesan #PM{post_id:03d} Berhasil Dikirim!</b>\n"
            f"• <b>Biaya:</b> {cost_note}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    except Exception as e:
        await message.answer(
            f"⚠️ <b>Gagal mengirim ke channel</b>\n"
            f"Detail: <code>{html.escape(str(e))}</code>",
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
