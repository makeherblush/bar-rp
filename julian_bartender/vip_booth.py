import html
import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup

import shared.database as db
from julian_bartender.helpers import (
    bot,
    OWNER_ID,
    VIP_DEFAULT_TAG,
    booth_access_cache,
    reload_booth_cache,
    sync_tg_user,
    resolve_target_smart,
    set_guest_tag,
    styled_btn,
    react_msg,
    schedule_delete,
    mention_user,
)

router = Router()


@router.message(Command("booth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_open_vip_booth(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    booth_name = parts[1].strip()[:32] if len(parts) > 1 and parts[1].strip() else f"VIP Booth {user.first_name[:18]}"

    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)
        row = await conn.fetchrow(
            "SELECT is_vip, vip_until, vip_booth_thread_id, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )
        is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
        if not is_vip and user.id != OWNER_ID:
            err_msg = await message.reply(
                "🥂 <b>VIP Booth</b> hanya tersedia untuk tamu pemegang <b>VIP Pass</b>.\n"
                "Gunakan <code>/menu</code> untuk mengaktifkan keanggotaan VIP.",
                parse_mode=ParseMode.HTML,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        if row and row["vip_booth_thread_id"]:
            tid = int(row["vip_booth_thread_id"])
            chat_id_clean = str(message.chat.id).replace("-100", "")
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[styled_btn("🥂 Masuk ke VIP Booth", url=f"https://t.me/c/{chat_id_clean}/{tid}", style="primary")]]
            )
            err_msg = await message.reply(
                f"Kamu sudah memiliki topik aktif: <b>{html.escape(row['vip_booth_name'] or 'VIP Booth')}</b>.\n"
                f"Gunakan <code>/closebooth</code> di dalam topik tersebut untuk menutupnya terlebih dahulu.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=30)
            return

    try:
        topic = await bot.create_forum_topic(
            chat_id=message.chat.id,
            name=f"👑 {booth_name}",
        )
        thread_id = topic.message_thread_id
    except Exception as e:
        err_msg = await message.reply(
            f"Gagal membuat topik VIP Booth. Pastikan grup ini mengaktifkan mode <b>Topics</b> dan bot memiliki izin <b>Manage Topics</b>.\n<code>{html.escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=25)
        return

    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET vip_booth_name = $1, vip_booth_thread_id = $2 WHERE user_id = $3",
            booth_name,
            thread_id,
            user.id,
        )
        await conn.execute("DELETE FROM vip_booth_invites WHERE thread_id = $1", thread_id)

    await reload_booth_cache()
    await set_guest_tag(message.chat.id, user.id, VIP_DEFAULT_TAG)
    await react_msg(message.chat.id, message.message_id, "👑")

    chat_id_clean = str(message.chat.id).replace("-100", "")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[styled_btn("🥂 Masuk ke VIP Booth", url=f"https://t.me/c/{chat_id_clean}/{thread_id}", style="primary")]]
    )

    lobby_msg = await message.reply(
        f"👑 <b>VIP Booth Dibuka!</b>\n"
        f"Topik privat <b>{html.escape(booth_name)}</b> telah disiapkan untuk {mention_user(user.id, user.first_name)}.\n"
        f"<i>Hanya pemilik booth dan tamu yang diundang via <code>/invitebooth @user</code> yang dapat berbicara di dalam topik ini.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    await schedule_delete(message.chat.id, [message.message_id, lobby_msg.message_id], delay=60)

    await bot.send_message(
        chat_id=message.chat.id,
        message_thread_id=thread_id,
        text=(
            f"🥂 <b>Selamat datang di {html.escape(booth_name)}</b>\n"
            f"Tuan rumah: {mention_user(user.id, user.first_name)}\n\n"
            f"• Undang tamu: <code>/invitebooth @username</code>\n"
            f"• Keluarkan tamu: <code>/kickbooth @username</code>\n"
            f"• Tutup booth: <code>/closebooth</code>\n"
            f"• Pesan menu atau jukebox langsung di dalam booth: <code>/menu</code>"
        ),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("invitebooth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_invite_booth(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    ident = parts[1].strip() if len(parts) > 1 else None

    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)
        owner_row = await conn.fetchrow(
            "SELECT vip_booth_thread_id, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )
        if not owner_row or not owner_row["vip_booth_thread_id"]:
            err_msg = await message.reply(
                "Kamu belum membuka topik VIP Booth. Ketik <code>/booth Nama Booth</code> terlebih dahulu.",
                parse_mode=ParseMode.HTML,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        target = await resolve_target_smart(conn, message, ident)
        if not target:
            err_msg = await message.reply(
                "Tamu tidak ditemukan. Gunakan <code>/invitebooth @username</code> atau reply pesan tamu tersebut.",
                parse_mode=ParseMode.HTML,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        tid = int(owner_row["vip_booth_thread_id"])
        booth_name = owner_row["vip_booth_name"] or "VIP Booth"
        await conn.execute(
            """
            INSERT INTO vip_booth_invites (thread_id, guest_id, invited_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (thread_id, guest_id) DO NOTHING
            """,
            tid,
            target["user_id"],
            user.id,
        )

    await reload_booth_cache()
    await react_msg(message.chat.id, message.message_id, "🎟️")

    chat_id_clean = str(message.chat.id).replace("-100", "")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[styled_btn("🥂 Masuk ke VIP Booth", url=f"https://t.me/c/{chat_id_clean}/{tid}", style="primary")]]
    )
    notice = await message.reply(
        f"🎟️ {mention_user(user.id, user.first_name)} mengundang {mention_user(target['user_id'], target['full_name'])} ke <b>{html.escape(booth_name)}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
    await schedule_delete(message.chat.id, [message.message_id, notice.message_id], delay=60)


@router.message(Command("kickbooth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_kick_booth(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    ident = parts[1].strip() if len(parts) > 1 else None

    async with db.pool.acquire() as conn:
        owner_row = await conn.fetchrow(
            "SELECT vip_booth_thread_id, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )
        if not owner_row or not owner_row["vip_booth_thread_id"]:
            err_msg = await message.reply("Kamu tidak memiliki topik VIP Booth aktif.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        target = await resolve_target_smart(conn, message, ident)
        if not target:
            err_msg = await message.reply("Tamu tidak ditemukan.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        tid = int(owner_row["vip_booth_thread_id"])
        await conn.execute(
            "DELETE FROM vip_booth_invites WHERE thread_id = $1 AND guest_id = $2",
            tid,
            target["user_id"],
        )

    await reload_booth_cache()
    notice = await message.reply(
        f"🚫 Akses {mention_user(target['user_id'], target['full_name'])} ke topik VIP Booth telah dicabut.",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, notice.message_id], delay=20)


@router.message(Command("closebooth"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_close_booth(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        owner_row = await conn.fetchrow(
            "SELECT vip_booth_thread_id, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )
        if not owner_row or not owner_row["vip_booth_thread_id"]:
            err_msg = await message.reply("Kamu tidak memiliki topik VIP Booth yang sedang terbuka.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
            return

        tid = int(owner_row["vip_booth_thread_id"])
        booth_name = owner_row["vip_booth_name"] or "VIP Booth"
        await conn.execute("UPDATE users SET vip_booth_name = NULL, vip_booth_thread_id = NULL WHERE user_id = $1", user.id)
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
        notice = await message.reply(
            f"🔒 Topik <b>{html.escape(booth_name)}</b> milik {mention_user(user.id, user.first_name)} telah ditutup.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, notice.message_id], delay=20)


@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.message_thread_id.func(lambda tid: tid is not None and int(tid) in booth_access_cache),
)
async def enforce_vip_booth_privacy(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return

    tid = int(message.message_thread_id)
    booth = booth_access_cache.get(tid)
    if not booth:
        return

    uid = message.from_user.id
    if uid == OWNER_ID or uid == booth["owner_id"] or uid in booth["guests"]:
        return

    try:
        await message.delete()
    except Exception:
        pass

    warn = await bot.send_message(
        chat_id=message.chat.id,
        message_thread_id=tid,
        text=(
            f"🔒 {mention_user(uid, message.from_user.first_name)}, topik <b>{html.escape(booth['booth_name'])}</b> bersifat privat. "
            f"Hanya tamu undangan pemilik booth yang diizinkan berbicara di sini."
        ),
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(8)
    try:
        await warn.delete()
    except Exception:
        pass
