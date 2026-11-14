import html
import random
import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode

import shared.database as db
import shared.config as cfg
from julian_bartender.helpers import (
    bot,
    OWNER_ID,
    BARTENDER_GREETINGS,
    JULIAN_RC_REPLIES,
    DRINKS_CATALOG,
    FOODS_CATALOG,
    GIFTS_CATALOG,
    sync_tg_user,
    restore_default_guest_tag,
    resolve_target_smart,
    log_tx,
    add_bar_quest,
    add_shift_action,
    format_shift_progress_note,
    get_setting,
    set_setting,
    get_service_media,
    react_msg,
    schedule_delete,
    mention_user,
    miniapp_menu_kb,
)

router = Router()


@router.message(F.chat.type.in_({"group", "supergroup"}), F.new_chat_members)
async def on_member_join_bar(message: types.Message):
    new_guests = [u for u in (message.new_chat_members or []) if not u.is_bot]
    if not new_guests:
        return

    async with db.pool.acquire() as conn:
        for guest in new_guests:
            await sync_tg_user(conn, guest, message.message_thread_id)
            await restore_default_guest_tag(conn, message.chat.id, guest.id)

    mentions = ", ".join(mention_user(u.id, u.first_name) for u in new_guests)
    greeting_text = random.choice(BARTENDER_GREETINGS).format(mention=mentions)
    greeting_text += "\n\n<i>Saldo awal <b>50 VC</b> telah disiapkan di tab Anda. Tekan tombol di bawah atau ketik <code>/menu</code> untuk melihat daftar sajian.</i>"

    sent = await message.answer(
        greeting_text,
        parse_mode=ParseMode.HTML,
        reply_markup=miniapp_menu_kb(is_private=False, thread_id=message.message_thread_id),
    )
    await schedule_delete(message.chat.id, [sent.message_id], delay=60)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_private_start(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user)

    await react_msg(message.chat.id, message.message_id, "🥂")
    await message.answer(
        f"🥂 <i>Julian meletakkan buku menu berlapis beludru merah di atas meja bar untuk {mention_user(user.id, user.first_name)}.</i>\n\n"
        f"Selamat datang di <b>The Velvet Hour</b>.\n"
        f"Untuk membuka katalog minuman, hidangan, lapak, dan jukebox interaktif:\n"
        f"• Tekan tombol <b>Menu</b> di pojok kiri bawah kolom ketik Anda,\n"
        f"• Ketik perintah <code>/menu</code>, atau\n"
        f"• Tekan tombol di bawah ini:",
        parse_mode=ParseMode.HTML,
        reply_markup=miniapp_menu_kb(is_private=True),
    )


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def handle_private_text_prompt(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user)

    await message.answer(
        "🍸 <i>Julian mengangguk sopan dari balik meja bar.</i>\n\n"
        "Silakan tekan tombol <b>Menu</b> di pojok kiri bawah keyboard, ketik <code>/menu</code>, atau klik tombol di bawah untuk membuka Buku Menu Web:",
        parse_mode=ParseMode.HTML,
        reply_markup=miniapp_menu_kb(is_private=True),
    )


@router.message(Command("setmenumedia"))
async def cmd_set_menu_media(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    valid = {"drink", "custom_mix", "food", "song"}
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in valid:
        return await message.reply(
            "Reply GIF atau Foto dengan:\n<code>/setmenumedia kategori</code>\n\n"
            "Kategori: <code>drink</code>, <code>custom_mix</code>, <code>food</code>, <code>song</code>",
            parse_mode=ParseMode.HTML,
        )

    rep = message.reply_to_message
    if not rep or (not rep.photo and not rep.animation):
        return await message.reply("Harap <b>reply</b> pesan berisi GIF atau Foto.", parse_mode=ParseMode.HTML)

    cat = parts[1].lower()
    file_id, mtype = (rep.animation.file_id, "animation") if rep.animation else (rep.photo[-1].file_id, "photo")

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gift_custom_media (gift_code, file_id, media_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (gift_code) DO UPDATE SET file_id = EXCLUDED.file_id, media_type = EXCLUDED.media_type;
        """, f"menu_{cat}", file_id, mtype)

    await message.reply(f"✅ Media <code>{cat}</code> diperbarui.", parse_mode=ParseMode.HTML)


@router.message(Command("setgiftimg"))
async def cmd_set_gift_image(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in GIFTS_CATALOG:
        codes = ", ".join(f"<code>{k}</code>" for k in GIFTS_CATALOG.keys())
        return await message.reply(
            f"Reply foto atau GIF dengan:\n<code>/setgiftimg kode</code>\n\nKode: {codes}",
            parse_mode=ParseMode.HTML,
        )

    rep = message.reply_to_message
    if not rep or (not rep.photo and not rep.animation):
        return await message.reply("Harap <b>reply</b> pesan berisi Foto atau GIF.", parse_mode=ParseMode.HTML)

    code = parts[1].lower()
    file_id, mtype = (rep.animation.file_id, "animation") if rep.animation else (rep.photo[-1].file_id, "photo")

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gift_custom_media (gift_code, file_id, media_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (gift_code) DO UPDATE SET file_id = EXCLUDED.file_id, media_type = EXCLUDED.media_type;
        """, code, file_id, mtype)

    await message.reply(
        f"✅ Media hadiah <b>{GIFTS_CATALOG[code]['name']}</b> — <code>{code}</code> diperbarui.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("setgiftch"))
async def cmd_set_gift_channel(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        cur = await get_setting("gift_channel_id") or getattr(cfg, "GIFT_CHANNEL_ID", "Belum diatur")
        return await message.reply(
            f"Format: <code>/setgiftch -1001234567890</code> atau <code>off</code>.\nChannel saat ini: <code>{cur}</code>",
            parse_mode=ParseMode.HTML,
        )

    val = parts[1].strip()
    if val.lower() == "off":
        await set_setting("gift_channel_id", "")
        return await message.reply("✅ Channel hadiah istimewa dimatikan.")

    await set_setting("gift_channel_id", val)
    await message.reply(f"✅ Channel hadiah istimewa diatur ke: <code>{html.escape(val)}</code>", parse_mode=ParseMode.HTML)


@router.message(Command("gift"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_send_gift(message: types.Message):
    sender = message.from_user
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot)

    if (has_reply and len(parts) < 2) or (not has_reply and len(parts) < 3):
        reg_lines = []
        sp_lines = []
        for code, g in GIFTS_CATALOG.items():
            line = f"• <code>{code}</code> — {g['emoji']} {g['name']} • {g['price']} VC | +{g['charm']} ✨"
            (sp_lines if g["special"] else reg_lines).append(line)

        catalog_text = (
            "🎁 <b>Katalog Hadiah The Velvet Hour</b>\n\n"
            + "\n".join(reg_lines)
            + "\n\n👑 <b>Hadiah Istimewa</b> — <i>Auto-Pin & Channel</i>\n"
            + "\n".join(sp_lines)
            + "\n\nCara kirim: <code>/gift @username kode</code> atau reply pesan target dengan <code>/gift kode</code>"
        )
        cat_msg = await message.reply(catalog_text, parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, cat_msg.message_id], delay=45)
        return

    if has_reply:
        target_ident = None
        gift_code = parts[1].lower().strip()
        custom_note = " ".join(parts[2:]).strip()[:80] if len(parts) > 2 else ""
    else:
        target_ident = parts[1]
        gift_code = parts[2].lower().strip()
        custom_note = " ".join(parts[3:]).strip()[:80] if len(parts) > 3 else ""

    if gift_code not in GIFTS_CATALOG:
        err_msg = await message.reply(
            f"Kode hadiah <code>{html.escape(gift_code)}</code> tidak ditemukan. Ketik <code>/gift</code> untuk melihat daftar kode.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
        return

    gift = GIFTS_CATALOG[gift_code]
    cost, charm_gain, is_special = gift["price"], gift["charm"], gift["special"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await sync_tg_user(conn, sender, message.message_thread_id)
            target = await resolve_target_smart(conn, message, target_ident)
            if not target:
                err_msg = await message.reply(
                    f"Penerima belum tercatat. Reply salah satu pesannya dengan <code>/gift {gift_code}</code>.",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            if target["user_id"] == sender.id:
                err_msg = await message.reply("Kamu tidak bisa mengirim hadiah untuk dirimu sendiri.")
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
                return

            s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if not s_row or (s_row["coins"] or 0) < cost:
                err_msg = await message.reply(
                    f"Saldo tidak cukup untuk <b>{gift['name']}</b> — butuh <b>{cost} VC</b>, saldo kamu: <b>{(s_row['coins'] or 0) if s_row else 0} VC</b>.",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, sender.id)
            await conn.execute(
                "UPDATE users SET charm_points = COALESCE(charm_points, 0) + $1 WHERE user_id = $2",
                charm_gain, target["user_id"]
            )
            await log_tx(conn, sender.id, -cost, f"Kirim Gift {gift['name']} ke {target['full_name']}")
            await add_bar_quest(conn, sender.id)

        custom_media = await conn.fetchrow(
            "SELECT file_id, media_type FROM gift_custom_media WHERE gift_code = $1",
            gift_code
        )

    await react_msg(message.chat.id, message.message_id, gift["emoji"])

    note_line = f"\n\n<i>\"{html.escape(custom_note)}\"</i>" if custom_note else ""
    prefix_crown = "👑 " if is_special else ""
    verb = "mempersembahkan" if is_special else "mengirimkan"
    caption = (
        f"{prefix_crown}{gift['emoji']} <b>{gift['name']}</b>\n"
        f"{mention_user(sender.id, sender.first_name)} {verb} {gift['desc']} kepada {mention_user(target['user_id'], target['full_name'])} • <b>+{charm_gain} Charm ✨</b>."
        f"{note_line}"
    )

    send_kwargs = {"message_thread_id": message.message_thread_id} if message.message_thread_id else {}
    try:
        if custom_media and custom_media["media_type"] == "animation":
            sent_msg = await bot.send_animation(message.chat.id, animation=custom_media["file_id"], caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        else:
            media_source = custom_media["file_id"] if custom_media else gift["default_img"]
            sent_msg = await bot.send_photo(message.chat.id, photo=media_source, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
    except Exception:
        sent_msg = await bot.send_message(message.chat.id, text=caption, parse_mode=ParseMode.HTML, **send_kwargs)

    await schedule_delete(message.chat.id, [message.message_id], delay=5)

    if is_special and sent_msg:
        try:
            await bot.pin_chat_message(chat_id=message.chat.id, message_id=sent_msg.message_id, disable_notification=True)
        except Exception:
            pass

        ch_id_raw = await get_setting("gift_channel_id") or getattr(cfg, "GIFT_CHANNEL_ID", None)
        if ch_id_raw:
            ch_caption = (
                f"👑 {gift['emoji']} <b>{gift['name']}</b>\n"
                f"{mention_user(sender.id, sender.first_name)} → {mention_user(target['user_id'], target['full_name'])} • <b>+{charm_gain} Charm ✨</b>"
                f"{note_line}"
            )
            try:
                ch_target = int(ch_id_raw) if str(ch_id_raw).lstrip("-").isdigit() else str(ch_id_raw)
                if custom_media and custom_media["media_type"] == "animation":
                    await bot.send_animation(ch_target, animation=custom_media["file_id"], caption=ch_caption, parse_mode=ParseMode.HTML)
                else:
                    media_source = custom_media["file_id"] if custom_media else gift["default_img"]
                    await bot.send_photo(ch_target, photo=media_source, caption=ch_caption, parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await bot.send_message(ch_target, text=ch_caption, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
    elif sent_msg:
        await schedule_delete(message.chat.id, [sent_msg.message_id], delay=45)


@router.message(Command("menu"))
async def cmd_menu_miniapp(message: types.Message):
    is_private = message.chat.type == "private"
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, message.from_user, None if is_private else message.message_thread_id)
    await react_msg(message.chat.id, message.message_id, "🥂")

    if is_private:
        await message.answer(
            "🥂 <i>Julian membuka tablet menu beludru di hadapanmu.</i>\n"
            "Klik tombol di bawah atau tombol <b>Menu</b> di kiri bawah keyboard untuk membuka Web Menu & Jukebox:",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(is_private=True),
        )
        return

    msg = await message.reply(
        "🥂 <i>Julian meletakkan tablet menu beludru di atas meja bar.</i>\n"
        "Silakan pilih minuman, racik koktail, hidangan, atau lagu jukebox:",
        parse_mode=ParseMode.HTML,
        reply_markup=miniapp_menu_kb(is_private=False, thread_id=message.message_thread_id),
    )
    await schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)


@router.message(Command("order"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_order_drink(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await react_msg(message.chat.id, message.message_id, "🍸")
        msg = await message.reply(
            "🍸 <i>Julian menyodorkan kartu menu ke hadapanmu.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(is_private=False, thread_id=message.message_thread_id),
        )
        await schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)
        return

    raw_arg = parts[1].strip()
    key = raw_arg.lower()
    item_name, base_price, is_vip_item = DRINKS_CATALOG[key] if key in DRINKS_CATALOG else (html.escape(raw_arg[:60]), 0, False)

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else base_price
            coins = (row["coins"] or 0) if row else 0

            if coins < cost:
                err_msg = await message.reply(
                    f"Saldo VC tidak cukup untuk memesan <b>{item_name}</b> — butuh <b>{cost} VC</b>, saldo kamu: <b>{coins} VC</b>.",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await log_tx(conn, user.id, -cost, f"Pesan minuman: {item_name}")
            await add_bar_quest(conn, user.id)

    cnt, is_shift = await add_shift_action(user.id, ("bartender", "waiter"))
    shift_note = format_shift_progress_note(cnt, is_shift)

    await react_msg(message.chat.id, message.message_id, "🍸")
    send_kwargs = {"message_thread_id": message.message_thread_id} if message.message_thread_id else {}
    prep_msg = await message.reply(
        f"🧊 <i>Julian menyiapkan gelas kristal dingin dan mengocok shaker untuk {mention_user(user.id, user.first_name)}...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.5)
    try:
        await prep_msg.delete()
    except Exception:
        pass

    vip_tag = " 👑" if (is_vip_item or is_vip) else ""
    caption = (
        f"🍸 Julian menggeser segelas <b>{item_name}</b> di atas meja bar mahoni menuju {mention_user(user.id, user.first_name)}{vip_tag}.\n\n"
        f"<i>\"Silakan dinikmati malam ini.\"</i>{shift_note}"
    )
    media_src, mtype = await get_service_media("drink")
    try:
        if mtype == "photo":
            await bot.send_photo(message.chat.id, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        else:
            await bot.send_animation(message.chat.id, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
    except Exception:
        await bot.send_message(message.chat.id, caption, parse_mode=ParseMode.HTML, **send_kwargs)


@router.message(Command("eat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_eat_food(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await react_msg(message.chat.id, message.message_id, "🍽️")
        msg = await message.reply(
            "🍽️ <i>Julian membukakan daftar hidangan dapur malam ini.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=miniapp_menu_kb(is_private=False, thread_id=message.message_thread_id),
        )
        await schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)
        return

    raw_arg = parts[1].strip()
    key = raw_arg.lower()
    item_name, base_price, is_vip_item = FOODS_CATALOG[key] if key in FOODS_CATALOG else (html.escape(raw_arg[:60]), 0, False)

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else base_price
            coins = (row["coins"] or 0) if row else 0

            if coins < cost:
                err_msg = await message.reply(
                    f"Saldo VC tidak cukup untuk memesan <b>{item_name}</b> — butuh <b>{cost} VC</b>.",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await log_tx(conn, user.id, -cost, f"Pesan makanan: {item_name}")
            await add_bar_quest(conn, user.id)

    cnt, is_shift = await add_shift_action(user.id, ("waiter",))
    shift_note = format_shift_progress_note(cnt, is_shift)

    await react_msg(message.chat.id, message.message_id, "🍽️")
    send_kwargs = {"message_thread_id": message.message_thread_id} if message.message_thread_id else {}
    prep_msg = await message.reply(
        f"🔥 <i>Chef di dapur sedang menata hidangan hangat untuk {mention_user(user.id, user.first_name)}...</i>",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(1.6)
    try:
        await prep_msg.delete()
    except Exception:
        pass

    vip_tag = " 👑" if (is_vip_item or is_vip) else ""
    caption = (
        f"🍽️ Hidangan hangat <b>{item_name}</b> baru saja keluar dari dapur dan disajikan ke meja {mention_user(user.id, user.first_name)}{vip_tag}.\n\n"
        f"<i>\"Selamat menikmati santapan malam Anda.\"</i>{shift_note}"
    )
    media_src, mtype = await get_service_media("food")
    try:
        if mtype == "photo":
            await bot.send_photo(message.chat.id, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        else:
            await bot.send_animation(message.chat.id, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
    except Exception:
        await bot.send_message(message.chat.id, caption, parse_mode=ParseMode.HTML, **send_kwargs)


@router.message(Command("treat"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_treat_guest(message: types.Message):
    sender = message.from_user
    parts = (message.text or "").split(maxsplit=2)
    has_reply = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.from_user.is_bot
    )

    if len(parts) < 2 and not has_reply:
        err_msg = await message.reply(
            "Format: <code>/treat @username nama menu</code> atau reply pesan temanmu dengan <code>/treat nama menu</code> — 20 VC, +5 Charm.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    target_ident = None if has_reply else parts[1]
    if has_reply:
        menu_text = html.escape((message.text or "").split(maxsplit=1)[1][:60]) if len(parts) >= 2 else "Signature Velvet Cocktail"
    else:
        menu_text = html.escape(parts[2].strip()[:60]) if len(parts) >= 3 else "Signature Velvet Cocktail"

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await sync_tg_user(conn, sender, message.message_thread_id)
            target = await resolve_target_smart(conn, message, target_ident)
            if not target:
                err_msg = await message.reply("Tamu tujuan belum tercatat.")
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return
            if target["user_id"] == sender.id:
                err_msg = await message.reply("Kamu tidak bisa mentraktir dirimu sendiri.")
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
                return

            s_row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if not s_row or (s_row["coins"] or 0) < 20:
                err_msg = await message.reply("Saldo kamu kurang dari <b>20 VC</b> untuk mentraktir tamu.", parse_mode=ParseMode.HTML)
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            await conn.execute("UPDATE users SET coins = coins - 20 WHERE user_id = $1", sender.id)
            await conn.execute("UPDATE users SET charm_points = COALESCE(charm_points, 0) + 5 WHERE user_id = $1", target["user_id"])
            await log_tx(conn, sender.id, -20, f"Traktir {target['full_name']} — {menu_text}")
            await add_bar_quest(conn, sender.id)

    cnt, is_shift = await add_shift_action(sender.id, ("bartender", "waiter"))
    shift_note = format_shift_progress_note(cnt, is_shift)

    await react_msg(message.chat.id, message.message_id, "🥂")
    await message.reply(
        f"🥂 {mention_user(sender.id, sender.first_name)} mentraktir <b>{menu_text}</b> untuk {mention_user(target['user_id'], target['full_name'])} • <b>+5 Charm ✨</b>.{shift_note}",
        parse_mode=ParseMode.HTML,
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text, ~F.text.startswith("/"))
async def on_julian_rp_interaction(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return

    me = await bot.get_me()
    bot_username = (me.username or "").lower()
    text_lower = message.text.lower()

    is_reply_to_julian = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == me.id
    )
    is_mentioned = bool(bot_username and f"@{bot_username}" in text_lower)
    is_called_name = "julian" in text_lower.split()

    if not (is_reply_to_julian or is_mentioned or is_called_name):
        return

    reply_text = random.choice(JULIAN_RC_REPLIES).format(name=html.escape(message.from_user.first_name))
    sent = await message.reply(reply_text, parse_mode=ParseMode.HTML)
    await schedule_delete(message.chat.id, [sent.message_id], delay=60)
