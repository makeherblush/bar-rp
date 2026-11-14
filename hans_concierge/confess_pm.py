import re
import html
from datetime import datetime, timedelta
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import (
    CH_INFO_ID,
    CH_PROMOTE_ID,
    CH_INFO_LINK,
    CH_PROMOTE_LINK,
    PROMOTE_CD_REG,
    PROMOTE_CD_VIP,
)
from hans_concierge.helpers import (
    bot,
    CONFESS_COST_VC,
    PM_COST_VC,
    react_message,
    get_bar_setting,
    log_wallet_tx,
    insufficient_vc_kb,
    main_lobby_kb,
)
from hans_concierge.card_gen import generate_channel_post_card, EFFECT_HEART

router = Router()

PROMOTE_COST_VC = PM_COST_VC


class ConfessPromoteState(StatesGroup):
    waiting_confess_text = State()
    waiting_promote_title = State()
    waiting_promote_text = State()


def _format_user_html(raw_text: str) -> str:
    escaped = html.escape(raw_text)
    return re.sub(
        r"\[spoiler\](.+?)\[/spoiler\]",
        r"<tg-spoiler>\1</tg-spoiler>",
        escaped,
        flags=re.IGNORECASE | re.DOTALL,
    )


async def _resolve_info_channel_id() -> int | str | None:
    db_ch = await get_bar_setting("target_channel_id")
    if db_ch:
        return int(db_ch) if str(db_ch).lstrip("-").isdigit() else db_ch
    return CH_INFO_ID if CH_INFO_ID != 0 else None


async def _resolve_promote_channel_id() -> int | str | None:
    db_ch = await get_bar_setting("promote_channel_id")
    if db_ch:
        return int(db_ch) if str(db_ch).lstrip("-").isdigit() else db_ch
    return CH_PROMOTE_ID if CH_PROMOTE_ID != 0 else None


def _build_post_link(ch_id: int | str, sent_msg: types.Message, fallback_link: str = "") -> str | None:
    if sent_msg.chat and sent_msg.chat.username:
        return f"https://t.me/{sent_msg.chat.username}/{sent_msg.message_id}"
    if isinstance(ch_id, str) and ch_id.startswith("@"):
        return f"https://t.me/{ch_id.lstrip('@')}/{sent_msg.message_id}"
    raw_id = str(ch_id)
    if raw_id.startswith("-100"):
        return f"https://t.me/c/{raw_id[4:]}/{sent_msg.message_id}"
    if fallback_link and fallback_link.startswith("https://") and fallback_link != "https://t.me/":
        return fallback_link
    return None


async def _edit_or_replace(call: types.CallbackQuery, text: str, kb: InlineKeyboardMarkup):
    if call.message.photo:
        try:
            await call.message.delete()
        except Exception:
            pass
        return await call.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# --- MENU CONFESS ANONIM KE CH_INFO_ID ---
@router.callback_query(F.data == "menu_confess")
async def cb_menu_confess(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ch_id = await _resolve_info_channel_id()
    if not ch_id:
        return await _edit_or_replace(
            call,
            "⚠️ <b>Channel Confess Belum Dikonfigurasi</b>\n\n"
            "<i>Owner dapat mengatur channel tujuan melalui Panel Kontrol Admin atau perintah <code>/setch -100xxxx</code>.</i>",
            await main_lobby_kb(call.from_user.id),
        )

    await state.set_state(ConfessPromoteState.waiting_confess_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await _edit_or_replace(
        call,
        "🕯️ <b>RUANG PENGAKUAN & CURHAT ANONIM</b>\n\n"
        f"• <b>Biaya Kirim:</b> <b>{CONFESS_COST_VC} VC</b> — Gratis untuk VIP\n"
        "• <b>Tampilan:</b> Dicetak otomatis menjadi <b>Kartu Poster Velvet</b> di Channel Info.\n"
        "• <b>Tips Spoiler:</b> Gunakan <code>[spoiler]teks rahasia[/spoiler]</code> untuk menyensor bagian tertentu.\n\n"
        "<i>Silakan ketik dan kirim isi curhatanmu sekarang — minimal 5 karakter:</i>",
        kb,
    )


@router.message(Command("confess"), F.chat.type == "private")
async def cmd_confess_direct(message: types.Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(ConfessPromoteState.waiting_confess_text)
        return await message.answer(
            f"🕯️ Ketik isi curhatan anonim kamu — Biaya <b>{CONFESS_COST_VC} VC</b>, Gratis VIP, atau /cancel untuk batal:",
            parse_mode=ParseMode.HTML,
        )
    await _publish_confess(message, parts[1].strip())


@router.message(ConfessPromoteState.waiting_confess_text, F.chat.type == "private")
async def fsm_receive_confess(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman confess dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))
    await state.clear()
    await _publish_confess(message, message.text.strip())


async def _publish_confess(message: types.Message, content: str):
    user = message.from_user
    ch_id = await _resolve_info_channel_id()
    if not ch_id:
        return await message.answer("Channel tujuan confess belum diatur oleh Owner.", reply_markup=await main_lobby_kb(user.id))

    if len(content) < 5:
        return await message.answer(
            "⚠️ Isi curhatan terlalu singkat — minimal 5 karakter. Silakan ulangi dari menu lobi.",
            reply_markup=await main_lobby_kb(user.id),
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
                    f"Butuh <b>{cost} VC</b> untuk mengirim confess — saldo kamu saat ini <b>{coins} VC</b>.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=insufficient_vc_kb(coins, cost),
                )

            new_bal = coins - cost
            if cost > 0:
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_bal, user.id)
                await log_wallet_tx(conn, user.id, -cost, "Kirim Curhat Anonim Confess")

            post_id = await conn.fetchval("""
                INSERT INTO channel_posts (user_id, post_type, content)
                VALUES ($1, 'confess', $2) RETURNING id
            """, user.id, content)

    me = await bot.get_me()
    code_tag = f"VH-{post_id:03d}"
    card_bytes = generate_channel_post_card(post_type="confess", post_number=code_tag, content=content)

    formatted_body = _format_user_html(content)
    caption = (
        f"🕯️ <b>VELVET CONFESSION — {code_tag}</b>\n\n"
        f"“{formatted_body}”\n\n"
        f"— <i>Anonymous Guest</i> | @{me.username}"
    )
    if len(caption) > 1000:
        caption = f"🕯️ <b>VELVET CONFESSION — {code_tag}</b>\n\n— <i>Anonymous Guest</i> | @{me.username}"

    try:
        sent_msg = await bot.send_photo(
            ch_id,
            photo=BufferedInputFile(card_bytes, filename=f"confess_{post_id}.png"),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
        await react_message(message.chat.id, message.message_id, "🕯️")
        post_url = _build_post_link(ch_id, sent_msg, CH_INFO_LINK)
        rows = []
        if post_url:
            rows.append([InlineKeyboardButton(text="🔗 Lihat Postingan di Channel", url=post_url)])
        rows.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")])

        cost_note = "Gratis VIP Pass" if cost == 0 else f"-{cost} VC — Sisa saldo <b>{new_bal} VC</b>"
        await message.answer(
            f"✅ <b>Kartu Confess {code_tag} Berhasil Diterbitkan!</b>\n"
            f"• <b>Biaya:</b> {cost_note}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            message_effect_id=EFFECT_HEART,
        )
    except Exception as e:
        await message.answer(
            f"⚠️ <b>Gagal mengirim ke channel confess</b> — <code>{html.escape(str(ch_id))}</code>\n"
            f"Detail: <code>{html.escape(str(e))}</code>\n"
            f"<i>Pastikan @{me.username} sudah dijadikan Admin dengan izin Post Messages di Channel Info.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(user.id),
        )


# --- MENU PROMOTE KE CH_PROMOTE_ID ---
@router.callback_query(F.data.in_({"menu_pm", "menu_promote"}))
async def cb_menu_promote(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    ch_id = await _resolve_promote_channel_id()
    if not ch_id:
        return await _edit_or_replace(
            call,
            "⚠️ <b>Channel Promote Belum Dikonfigurasi</b>\n\n"
            "<i>Owner dapat mengatur channel promosi melalui Panel Kontrol Admin atau perintah <code>/setpromotech -100xxxx</code>.</i>",
            await main_lobby_kb(call.from_user.id),
        )

    await state.set_state(ConfessPromoteState.waiting_promote_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await _edit_or_replace(
        call,
        "📣 <b>PAPAN PROMOSI & LAPAK TAMU — CHANNEL PROMOTE</b>\n\n"
        f"• <b>Biaya Tayang:</b> <b>{PROMOTE_COST_VC} VC</b> — Gratis untuk VIP\n"
        f"• <b>Jeda Kirim:</b> {PROMOTE_CD_REG} menit Reguler | {PROMOTE_CD_VIP} menit VIP\n"
        "• <b>Langkah 1 dari 2:</b> Masukkan <b>Judul Promosi / Nama Jasa / Kontak @username</b> kamu:",
        kb,
    )


@router.message(Command("promote"), F.chat.type == "private")
async def cmd_promote_direct(message: types.Message, state: FSMContext):
    ch_id = await _resolve_promote_channel_id()
    if not ch_id:
        return await message.answer("Channel Promote belum diatur oleh Owner.", reply_markup=await main_lobby_kb(message.from_user.id))

    await state.set_state(ConfessPromoteState.waiting_promote_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await message.answer(
        "📣 <b>PAPAN PROMOSI & LAPAK TAMU</b>\n\n"
        f"• <b>Biaya Tayang:</b> <b>{PROMOTE_COST_VC} VC</b> — Gratis VIP\n"
        "• <b>Langkah 1 dari 2:</b> Ketik <b>Judul Promosi / Nama Lapak / Kontak @username</b> kamu:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@router.message(ConfessPromoteState.waiting_promote_title, F.chat.type == "private")
async def fsm_promote_title(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman promosi dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))

    await react_message(message.chat.id, message.message_id, "✍️")
    promo_title = message.text.strip()[:80]
    await state.update_data(promo_title=promo_title)
    await state.set_state(ConfessPromoteState.waiting_promote_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal & Kembali ke Lobi", callback_data="cancel_confess_pm")]
    ])
    await message.answer(
        f"✍️ <b>Langkah 2 dari 2 — Judul: {_format_user_html(promo_title)}</b>\n\n"
        "Sekarang ketik <b>deskripsi lengkap promosi / detail jasa / tautan</b> yang ingin ditayangkan di Channel Promote:",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@router.message(ConfessPromoteState.waiting_promote_text, F.chat.type == "private")
async def fsm_promote_text(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman promosi dibatalkan.", reply_markup=await main_lobby_kb(message.from_user.id))

    data = await state.get_data()
    promo_title = data.get("promo_title", "Velvet Partner")
    content = message.text.strip()
    await state.clear()

    user = message.from_user
    ch_id = await _resolve_promote_channel_id()
    if not ch_id:
        return await message.answer("Channel Promote belum diatur oleh Owner.", reply_markup=await main_lobby_kb(user.id))

    if len(content) < 5:
        return await message.answer(
            "⚠️ Deskripsi promosi terlalu singkat — minimal 5 karakter. Silakan ulangi dari menu lobi.",
            reply_markup=await main_lobby_kb(user.id),
        )

    now = datetime.utcnow()
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > now)
            cd_minutes = PROMOTE_CD_VIP if is_vip else PROMOTE_CD_REG

            last_promo = await conn.fetchval(
                "SELECT created_at FROM channel_posts WHERE user_id = $1 AND post_type = 'promote' ORDER BY id DESC LIMIT 1",
                user.id,
            )
            if last_promo and (now - last_promo) < timedelta(minutes=cd_minutes):
                rem = int(((last_promo + timedelta(minutes=cd_minutes)) - now).total_seconds() // 60) + 1
                return await message.answer(
                    f"⏳ <b>Jeda Promosi Masih Aktif</b>\n\n"
                    f"Kamu baru saja menayangkan promosi. Silakan tunggu sekitar <b>{rem} menit</b> lagi sebelum mengirim promosi berikutnya.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=await main_lobby_kb(user.id),
                )

            cost = 0 if is_vip else PROMOTE_COST_VC
            coins = row["coins"] if row else 0

            if coins < cost:
                return await message.answer(
                    f"💸 <b>Saldo VC Tidak Cukup</b>\n\n"
                    f"Butuh <b>{cost} VC</b> untuk menayangkan promosi — saldo kamu saat ini <b>{coins} VC</b>.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=insufficient_vc_kb(coins, cost),
                )

            new_bal = coins - cost
            if cost > 0:
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_bal, user.id)
                await log_wallet_tx(conn, user.id, -cost, f"Promosi Channel: {promo_title}")

            post_id = await conn.fetchval("""
                INSERT INTO channel_posts (user_id, post_type, target_to, content)
                VALUES ($1, 'promote', $2, $3) RETURNING id
            """, user.id, promo_title, content)

    me = await bot.get_me()
    code_tag = f"PR-{post_id:03d}"
    card_bytes = generate_channel_post_card(
        post_type="pm",
        post_number=code_tag,
        content=content,
        target_to=promo_title,
    )

    sender_tag = f"@{user.username}" if user.username else html.escape(user.first_name)
    caption = (
        f"📣 <b>VELVET PROMOTE — {code_tag}</b>\n\n"
        f"<b>Tajuk:</b> {_format_user_html(promo_title)}\n"
        f"<b>Detail:</b> {_format_user_html(content)}\n\n"
        f"— <i>Dipromosikan oleh</i> {sender_tag} | @{me.username}"
    )
    if len(caption) > 1000:
        caption = (
            f"📣 <b>VELVET PROMOTE — {code_tag}</b>\n"
            f"<b>Tajuk:</b> {_format_user_html(promo_title)}\n\n"
            f"— <i>Dipromosikan oleh</i> {sender_tag} | @{me.username}"
        )

    try:
        sent_msg = await bot.send_photo(
            ch_id,
            photo=BufferedInputFile(card_bytes, filename=f"promote_{post_id}.png"),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
        await react_message(message.chat.id, message.message_id, "📣")
        post_url = _build_post_link(ch_id, sent_msg, CH_PROMOTE_LINK)
        rows = []
        if post_url:
            rows.append([InlineKeyboardButton(text="🔗 Lihat Postingan di Channel Promote", url=post_url)])
        rows.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")])

        cost_note = "Gratis VIP Pass" if cost == 0 else f"-{cost} VC — Sisa saldo <b>{new_bal} VC</b>"
        await message.answer(
            f"✅ <b>Promosi {code_tag} Berhasil Ditayangkan!</b>\n"
            f"• <b>Biaya:</b> {cost_note}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            message_effect_id=EFFECT_HEART,
        )
    except Exception as e:
        await message.answer(
            f"⚠️ <b>Gagal mengirim ke channel promote</b> — <code>{html.escape(str(ch_id))}</code>\n"
            f"Detail: <code>{html.escape(str(e))}</code>\n"
            f"<i>Pastikan @{me.username} sudah dijadikan Admin dengan izin Post Messages di Channel Promote.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=await main_lobby_kb(user.id),
        )


@router.callback_query(F.data == "cancel_confess_pm")
async def cb_cancel_confess_pm(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Dibatalkan")
    await _edit_or_replace(
        call,
        "🏛️ <b>LOBI RESEPSIONIS — THE VELVET HOUR</b>\n\nSilakan pilih layanan yang kamu perlukan:",
        await main_lobby_kb(call.from_user.id),
    )
