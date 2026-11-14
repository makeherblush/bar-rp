import html
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode

import shared.database as db
from julian_bartender.helpers import (
    bot,
    OWNER_ID,
    booth_access_cache,
    reload_booth_cache,
    sync_tg_user,
    resolve_target_smart,
    react_msg,
    schedule_delete,
    mention_user,
)

router = Router()


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.message_thread_id,
    lambda m: int(m.message_thread_id) in booth_access_cache,
)
async def enforce_vip_booth_privacy(message: types.Message):
    user = message.from_user
    if not user or user.is_bot:
        return

    tid = int(message.message_thread_id)
    booth = booth_access_cache.get(tid)
    if not booth:
        return

    uid = user.id
    if uid == OWNER_ID or uid == booth["owner_id"] or uid in booth["guests"]:
        return

    try:
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    try:
        await message.delete()
    except Exception:
        return

    warn = await bot.send_message(
        chat_id=message.chat.id,
        message_thread_id=tid,
        text=(
            f"🔒 Maaf {mention_user(uid, user.first_name)}, ruangan <b>{html.escape(booth['booth_name'])}</b> bersifat privat. "
            f"Hanya pemilik booth dan tamu undangan yang diizinkan masuk."
        ),
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [warn.message_id], delay=8)


@router.message(Command("booth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_vip_booth(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        err_msg = await message.reply(
            "Format: <code>/booth Nama Booth Eksklusif</code> (Khusus pemegang VIP Pass)",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    booth_name = parts[1].strip()[:32]
    topic_title = f"👑 {booth_name}"

    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)
        row = await conn.fetchrow(
            "SELECT is_vip, vip_until, vip_booth_thread_id FROM users WHERE user_id = $1",
            user.id,
        )
        is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
        if not is_vip:
            err_msg = await message.reply(
                "🔒 Reservasi Booth hanya tersedia untuk tamu dengan <b>VIP Reserve Pass</b>.",
                parse_mode=ParseMode.HTML,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        existing_tid = row["vip_booth_thread_id"]
        thread_id = None
        is_renamed = False

        if existing_tid:
            try:
                await bot.edit_forum_topic(
                    chat_id=message.chat.id,
                    message_thread_id=existing_tid,
                    name=topic_title,
                )
                thread_id = existing_tid
                is_renamed = True
            except Exception:
                thread_id = None

        if not thread_id:
            try:
                topic = await bot.create_forum_topic(chat_id=message.chat.id, name=topic_title)
                thread_id = topic.message_thread_id
            except Exception as e:
                err_msg = await message.reply(
                    f"⚠️ Gagal membuat topik VIP Booth. Pastikan fitur <b>Topics</b> aktif dan Julian memiliki izin <b>Manage Topics</b>.\n<i>({html.escape(str(e))})</i>",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=25)
                return

        await conn.execute(
            "UPDATE users SET vip_booth_name = $1, vip_booth_thread_id = $2, last_thread_id = $2 WHERE user_id = $3",
            booth_name,
            thread_id,
            user.id,
        )

    await reload_booth_cache()
    await react_msg(message.chat.id, message.message_id, "👑")

    try:
        if is_renamed:
            await bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=thread_id,
                text=(
                    f"🍾 Julian mengganti papan nama emas di pintu booth menjadi <b>{html.escape(booth_name)}</b> "
                    f"untuk {mention_user(user.id, user.first_name)}."
                ),
                parse_mode=ParseMode.HTML,
            )
        else:
            await bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=thread_id,
                text=(
                    f"🍾 <i>Julian membukakan tirai beludru merah dan menyalakan lampu kristal di balkon pribadi.</i>\n\n"
                    f"Selamat datang di <b>{html.escape(booth_name)}</b>, {mention_user(user.id, user.first_name)}. "
                    f"Ruangan ini bersifat <b>Privat</b> — hanya Anda dan tamu undangan yang dapat berbicara di sini.\n\n"
                    f"• Undang tamu: <code>/invitebooth @username</code>\n"
                    f"• Keluarkan tamu: <code>/kickbooth @username</code>\n"
                    f"• Tutup ruangan: <code>/closebooth</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        pass

    chat_str = str(message.chat.id)
    link_text = f' (<a href="https://t.me/c/{chat_str[4:]}/{thread_id}">Masuk ke Booth</a>)' if chat_str.startswith("-100") else ""
    action_desc = "memperbarui papan nama" if is_renamed else "membuka topik ruangan pribadi"

    conf_msg = await message.reply(
        f"🍾 Julian {action_desc} <b>{html.escape(booth_name)}</b> untuk {mention_user(user.id, user.first_name)}{link_text}.",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, conf_msg.message_id], delay=45)


@router.message(Command("invitebooth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_invite_booth(message: types.Message):
    owner = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    has_reply = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.from_user.is_bot
    )

    if len(parts) < 2 and not has_reply:
        err_msg = await message.reply(
            "Format: <code>/invitebooth @username</code> atau reply pesan tamu yang ingin diundang.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    target_ident = None if has_reply else parts[1]

    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, owner, message.message_thread_id)
        owner_row = await conn.fetchrow(
            "SELECT vip_booth_name, vip_booth_thread_id FROM users WHERE user_id = $1",
            owner.id,
        )
        if not owner_row or not owner_row["vip_booth_thread_id"]:
            err_msg = await message.reply(
                "Kamu belum memiliki VIP Booth aktif. Gunakan <code>/booth Nama Booth</code> terlebih dahulu.",
                parse_mode=ParseMode.HTML,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        target = await resolve_target_smart(conn, message, target_ident)
        if not target:
            err_msg = await message.reply("Tamu belum tercatat di database.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        if target["user_id"] == owner.id:
            err_msg = await message.reply("Kamu adalah pemilik booth ini.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        tid = int(owner_row["vip_booth_thread_id"])
        bname = owner_row["vip_booth_name"] or "VIP Booth"

        await conn.execute("""
            INSERT INTO vip_booth_invites (thread_id, guest_id, invited_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (thread_id, guest_id) DO NOTHING;
        """, tid, target["user_id"], owner.id)

    await reload_booth_cache()
    await react_msg(message.chat.id, message.message_id, "🎟️")

    chat_str = str(message.chat.id)
    link_text = f' (<a href="https://t.me/c/{chat_str[4:]}/{tid}">Masuk ke Booth</a>)' if chat_str.startswith("-100") else ""
    conf_msg = await message.reply(
        f"🎟️ {mention_user(owner.id, owner.first_name)} memberikan akses VIP ke <b>{html.escape(bname)}</b> "
        f"untuk {mention_user(target['user_id'], target['full_name'])}{link_text}.",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, conf_msg.message_id], delay=35)


@router.message(Command("kickbooth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_kick_booth(message: types.Message):
    owner = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    has_reply = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.from_user.is_bot
    )

    if len(parts) < 2 and not has_reply:
        err_msg = await message.reply("Format: <code>/kickbooth @username</code> atau reply pesan tamu.", parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    target_ident = None if has_reply else parts[1]

    async with db.pool.acquire() as conn:
        owner_row = await conn.fetchrow(
            "SELECT vip_booth_name, vip_booth_thread_id FROM users WHERE user_id = $1",
            owner.id,
        )
        if not owner_row or not owner_row["vip_booth_thread_id"]:
            err_msg = await message.reply("Kamu tidak memiliki VIP Booth aktif.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        target = await resolve_target_smart(conn, message, target_ident)
        if not target:
            err_msg = await message.reply("Tamu tidak ditemukan.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        tid = int(owner_row["vip_booth_thread_id"])
        bname = owner_row["vip_booth_name"] or "VIP Booth"
        deleted = await conn.fetchval(
            "DELETE FROM vip_booth_invites WHERE thread_id = $1 AND guest_id = $2 RETURNING guest_id",
            tid,
            target["user_id"],
        )

    await reload_booth_cache()
    if not deleted:
        err_msg = await message.reply(
            f"{mention_user(target['user_id'], target['full_name'])} tidak ada dalam daftar undangan booth kamu.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
        return

    await react_msg(message.chat.id, message.message_id, "🚪")
    conf_msg = await message.reply(
        f"🚪 Julian mencabut akses {mention_user(target['user_id'], target['full_name'])} dari <b>{html.escape(bname)}</b>.",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, conf_msg.message_id], delay=30)


@router.message(Command("closebooth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_close_vip_booth(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT vip_booth_name, vip_booth_thread_id FROM users WHERE user_id = $1",
            user.id,
        )
        if not row or not row["vip_booth_thread_id"]:
            err_msg = await message.reply("Kamu tidak memiliki topik VIP Booth yang sedang aktif.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        tid = int(row["vip_booth_thread_id"])
        bname = row["vip_booth_name"] or "VIP Booth"
        await conn.execute(
            "UPDATE users SET vip_booth_name = NULL, vip_booth_thread_id = NULL WHERE user_id = $1",
            user.id,
        )
        await conn.execute("DELETE FROM vip_booth_invites WHERE thread_id = $1", tid)

    await reload_booth_cache()

    try:
        await bot.delete_forum_topic(chat_id=message.chat.id, message_thread_id=tid)
    except Exception:
        try:
            await bot.close_forum_topic(chat_id=message.chat.id, message_thread_id=tid)
        except Exception:
            pass

    if message.message_thread_id != tid:
        conf_msg = await message.reply(
            f"🥂 Julian menutup tirai <b>{html.escape(bname)}</b> milik {mention_user(user.id, user.first_name)}.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, conf_msg.message_id], delay=30)
