import html
from datetime import datetime, timedelta

from aiogram import Router, F, types
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import OWNER_ID, GROUP_ID
from julian_bartender.helpers import (
    bot,
    hans_bot,
    SHIFT_MAX_MINUTES,
    SHIFT_REQUIRED_ACTIONS,
    SHIFT_REWARD_VC,
    MAX_SHIFTS_PER_DAY,
    SHIFT_ROLES,
    set_guest_tag,
    restore_default_guest_tag,
    update_member_shift_commands,
    add_shift_action,
    format_shift_progress_note,
    reply_and_autodelete,
    is_staff_or_owner,
    log_tx,
)

router = Router()


async def get_active_shift(user_id: int):
    now = datetime.utcnow()
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role_name, started_at, ends_at, service_count FROM active_shifts WHERE user_id = $1",
            user_id,
        )
        if not row or row["ends_at"] <= now:
            return None
        return row


# --- LAMAR, CEK PROGRES & AKHIRI SHIFT ---
@router.message(Command("apply"), F.chat.id == GROUP_ID)
async def cmd_apply(message: types.Message, command: CommandObject):
    role = (command.args or "").strip().lower()
    now = datetime.utcnow()

    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM active_shifts WHERE ends_at <= $1", now)
        counts_rows = await conn.fetch("SELECT role_name, COUNT(*) as cnt FROM active_shifts GROUP BY role_name")
        counts = {r["role_name"]: r["cnt"] for r in counts_rows}

    if role not in SHIFT_ROLES:
        lines = []
        for r_key, meta in SHIFT_ROLES.items():
            lines.append(
                f"• <code>/apply {r_key}</code> — Slot: <b>{counts.get(r_key, 0)}/{meta['quota']}</b> — {meta['title']}"
            )
        return await reply_and_autodelete(
            message,
            f"💼 <b>PILIH POSISI SHIFT — {SHIFT_MAX_MINUTES} MENIT • UPAH {SHIFT_REWARD_VC} VC</b>\n"
            f"<i>Batas kerja harian: Maksimal <b>{MAX_SHIFTS_PER_DAY}x shift/hari</b></i>\n\n"
            + "\n".join(lines)
            + "\n\n💡 <b>Contoh:</b> Ketik <code>/apply waiter</code> untuk melamar sebagai Waiter.",
            90,
        )

    user_id = message.from_user.id
    today = now.date()
    meta = SHIFT_ROLES[role]

    async with db.pool.acquire() as conn:
        already_working = await conn.fetchrow("SELECT role_name FROM active_shifts WHERE user_id = $1", user_id)
        if already_working:
            return await reply_and_autodelete(
                message,
                f"Kamu sudah bertugas sebagai <b>{already_working['role_name'].upper()}</b>.\n"
                "Ketik <code>/myshift</code> untuk cek progres atau <code>/endshift</code> untuk selesai.",
                60,
            )

        used_today = await conn.fetchval(
            "SELECT count FROM shift_daily_counts WHERE user_id = $1 AND shift_date = $2",
            user_id,
            today,
        ) or 0
        if used_today >= MAX_SHIFTS_PER_DAY:
            return await reply_and_autodelete(
                message,
                f"⏳ <b>Kuota Shift Harian Habis — {used_today}/{MAX_SHIFTS_PER_DAY}</b>\n\n"
                f"Kamu sudah mencapai batas maksimal <b>{MAX_SHIFTS_PER_DAY}x kerja</b> hari ini. Silakan kembali bekerja besok!",
                60,
            )

        active_in_role = await conn.fetchval("SELECT COUNT(*) FROM active_shifts WHERE role_name = $1", role) or 0
        if active_in_role >= meta["quota"]:
            return await reply_and_autodelete(
                message,
                f"🚫 <b>Slot Posisi {role.upper()} Penuh — {active_in_role}/{meta['quota']}</b>\n\n"
                "Kuota staf aktif untuk posisi ini sudah penuh. Silakan pilih posisi lain yang masih tersedia.",
                60,
            )

        new_used_today = used_today + 1
        ends_at = now + timedelta(minutes=SHIFT_MAX_MINUTES)
        await conn.execute(
            """
            INSERT INTO shift_daily_counts (user_id, shift_date, count)
            VALUES ($1, $2, 1)
            ON CONFLICT (user_id, shift_date) DO UPDATE SET count = shift_daily_counts.count + 1
            """,
            user_id,
            today,
        )
        await conn.execute(
            """
            INSERT INTO active_shifts (user_id, role_name, started_at, ends_at, service_count)
            VALUES ($1, $2, $3, $4, 0)
            """,
            user_id,
            role,
            now,
            ends_at,
        )

    await set_guest_tag(GROUP_ID, user_id, meta["tag"])
    await update_member_shift_commands(user_id, role)

    await message.answer(
        f"💼 <b>SHIFT DIMULAI — {meta['title'].upper()}</b>\n\n"
        f"<b>{html.escape(message.from_user.first_name)}</b> resmi bertugas selama <b>{SHIFT_MAX_MINUTES} menit</b>! "
        f"Kuota harian: <b>{new_used_today}/{MAX_SHIFTS_PER_DAY}</b>\n\n"
        f"<b>Daftar Tugas — {SHIFT_REQUIRED_ACTIONS}x Layanan:</b>\n"
        f"• {meta['cmds']}\n\n"
        "• Cek progres: <code>/myshift</code>\n"
        f"• Cairkan gaji <b>{SHIFT_REWARD_VC} VC</b>: <code>/endshift</code>",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("myshift"), F.chat.id == GROUP_ID)
async def cmd_myshift(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if not shift:
        return await reply_and_autodelete(
            message,
            "Kamu sedang tidak dalam jadwal shift kerja.\nContoh melamar: <code>/apply waiter</code>",
            60,
        )

    rem_mins = max(0, int((shift["ends_at"] - datetime.utcnow()).total_seconds() // 60) + 1)
    srv_count = shift["service_count"] or 0
    status_gaji = (
        f"✅ <b>Siap Cair!</b> Ketik <code>/endshift</code> untuk klaim <b>+{SHIFT_REWARD_VC} VC</b>."
        if srv_count >= SHIFT_REQUIRED_ACTIONS
        else f"⏳ Kurang <b>{SHIFT_REQUIRED_ACTIONS - srv_count}x layanan lagi</b>."
    )

    meta = SHIFT_ROLES.get(shift["role_name"], {"cmds": "-"})
    await reply_and_autodelete(
        message,
        f"📋 <b>STATUS SHIFT — {html.escape(message.from_user.first_name)}</b>\n\n"
        f"• <b>Posisi:</b> {shift['role_name'].upper()}\n"
        f"• <b>Progres Layanan:</b> {srv_count} / {SHIFT_REQUIRED_ACTIONS} kali\n"
        f"• <b>Sisa Waktu:</b> {rem_mins} menit dari {SHIFT_MAX_MINUTES} menit\n"
        f"• <b>Status Upah:</b> {status_gaji}\n\n"
        f"<b>Command Tugasmu:</b>\n• {meta['cmds']}",
        60,
    )


@router.message(Command("endshift"), F.chat.id == GROUP_ID)
async def cmd_endshift(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        shift = await conn.fetchrow("SELECT role_name, service_count FROM active_shifts WHERE user_id = $1", user_id)
        if not shift:
            return await reply_and_autodelete(message, "Kamu sedang tidak dalam jadwal shift kerja.", 60)

        await conn.execute("DELETE FROM active_shifts WHERE user_id = $1", user_id)
        srv_count = shift["service_count"] or 0
        if srv_count >= SHIFT_REQUIRED_ACTIONS:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", SHIFT_REWARD_VC, user_id)
            await log_tx(conn, user_id, SHIFT_REWARD_VC, f"Upah Shift {shift['role_name'].upper()}")
            msg_txt = (
                f"💵 <b>SHIFT SELESAI — UPAH {SHIFT_REWARD_VC} VC CAIR!</b>\n\n"
                f"Bartender Julian menyerahkan amplop berisi <b>+{SHIFT_REWARD_VC} Velvet Coins</b> kepada <b>{html.escape(message.from_user.first_name)}</b> "
                f"atas dedikasinya sebagai <b>{shift['role_name'].upper()}</b> — {srv_count} layanan."
            )
        else:
            msg_txt = (
                f"📋 <b>SHIFT DIAKHIRI</b>\n\n"
                f"<b>{html.escape(message.from_user.first_name)}</b> melepas pin <b>{shift['role_name'].upper()}</b>.\n\n"
                f"<i>Upah tidak cair karena layanan baru mencapai {srv_count}/{SHIFT_REQUIRED_ACTIONS} kali.</i>"
            )

        await restore_default_guest_tag(conn, GROUP_ID, user_id)

    await update_member_shift_commands(user_id, None)
    await message.answer(msg_txt, parse_mode=ParseMode.HTML)


# --- AKSI STAF PARUH WAKTU ---
@router.message(Command("mix"), F.chat.id == GROUP_ID)
async def cmd_mix(message: types.Message, command: CommandObject):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role_name"] != "bartender") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Bartender</b>. Contoh melamar: <code>/apply bartender</code>", 45)
    drink = (command.args or "").strip()
    if not drink:
        return await reply_and_autodelete(message, "Tuliskan nama minuman yang ingin diracik.\nContoh: <code>/mix Midnight Negroni</code>", 45)
    cnt, is_active = await add_shift_action(message.from_user.id, ("bartender",))
    prog = format_shift_progress_note(cnt, is_active)
    await reply_and_autodelete(
        message,
        f"🍸 <b>Bartender {html.escape(message.from_user.first_name)}</b> mengocok shaker perak dengan lihai dan menuangkan <b>{html.escape(drink)}</b> ke gelas kristal dingin!{prog}",
        120,
    )


@router.message(Command("sober"), F.chat.id == GROUP_ID)
async def cmd_sober(message: types.Message, command: CommandObject):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role_name"] != "bartender") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Bartender</b>. Contoh melamar: <code>/apply bartender</code>", 45)
    target = (command.args or "").strip()
    if not target and message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
    if not target:
        return await reply_and_autodelete(message, "Tuliskan username/nama tamu atau balas pesannya.\nContoh: <code>/sober @alvaro</code>", 45)
    cnt, is_active = await add_shift_action(message.from_user.id, ("bartender",))
    prog = format_shift_progress_note(cnt, is_active)
    await reply_and_autodelete(
        message,
        f"☕ <b>Bartender {html.escape(message.from_user.first_name)}</b> menyodorkan secangkir kopi hitam pekat dan air dingin kepada <b>{html.escape(target)}</b> agar kembali segar.{prog}",
        120,
    )


@router.message(Command("welcome"), F.chat.id == GROUP_ID)
async def cmd_welcome_staff(message: types.Message, command: CommandObject):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role_name"] != "waiter") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Waiter</b>. Contoh melamar: <code>/apply waiter</code>", 45)
    target = (command.args or "").strip()
    if not target and message.reply_to_message:
        target = message.reply_to_message.from_user.first_name
    if not target:
        return await reply_and_autodelete(message, "Tuliskan username/nama tamu yang disambut.\nContoh: <code>/welcome @clara</code>", 45)
    cnt, is_active = await add_shift_action(message.from_user.id, ("waiter",))
    prog = format_shift_progress_note(cnt, is_active)
    await reply_and_autodelete(
        message,
        f"🍽️ <b>Waiter {html.escape(message.from_user.first_name)}</b> menyambut <b>{html.escape(target)}</b> dengan senyum hangat, mengantar ke meja beludru, dan menyalakan lilin meja.{prog}",
        120,
    )


@router.message(Command("dish"), F.chat.id == GROUP_ID)
async def cmd_dish(message: types.Message, command: CommandObject):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role_name"] != "waiter") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Waiter</b>. Contoh melamar: <code>/apply waiter</code>", 45)
    dish_name = (command.args or "").strip()
    if not dish_name:
        return await reply_and_autodelete(message, "Tuliskan nama hidangan yang diantar.\nContoh: <code>/dish Wagyu Cube Bites</code>", 45)
    cnt, is_active = await add_shift_action(message.from_user.id, ("waiter",))
    prog = format_shift_progress_note(cnt, is_active)
    await reply_and_autodelete(
        message,
        f"🍽️ <b>Waiter {html.escape(message.from_user.first_name)}</b> menyajikan <b>{html.escape(dish_name)}</b> hangat dari dapur langsung ke meja tamu.{prog}",
        120,
    )


@router.message(Command("ambience"), F.chat.id == GROUP_ID)
async def cmd_ambience(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role_name"] != "host") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Host</b>. Contoh melamar: <code>/apply host</code>", 45)
    cnt, is_active = await add_shift_action(message.from_user.id, ("host",))
    prog = format_shift_progress_note(cnt, is_active)
    await reply_and_autodelete(
        message,
        f"🕯️ <b>Host {html.escape(message.from_user.first_name)}</b> meredupkan lampu gantung kristal, menyisakan pendar cahaya lilin hangat yang intim di seluruh penjuru lounge...{prog}",
        120,
    )


@router.message(Command("toastall"), F.chat.id == GROUP_ID)
async def cmd_toastall(message: types.Message):
    shift = await get_active_shift(message.from_user.id)
    if (not shift or shift["role_name"] != "host") and not await is_staff_or_owner(message.from_user.id):
        return await reply_and_autodelete(message, "Khusus staf <b>Host</b>. Contoh melamar: <code>/apply host</code>", 45)
    cnt, is_active = await add_shift_action(message.from_user.id, ("host",))
    prog = format_shift_progress_note(cnt, is_active)
    await reply_and_autodelete(
        message,
        f"🥂 <b>Host {html.escape(message.from_user.first_name)}</b> berdiri di tengah ruangan sambil mengangkat gelas:\n\n<b>\"Mari bersulang untuk malam yang tak terlupakan di The Velvet Hour!\"</b>{prog}",
        120,
    )


# --- MODERASI ADMIN & OWNER ---
@router.message(Command("mute"), F.chat.id == GROUP_ID)
async def cmd_mute(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id) or not message.reply_to_message:
        return
    target = message.reply_to_message.from_user
    until = datetime.utcnow() + timedelta(minutes=15)
    try:
        await bot.restrict_chat_member(GROUP_ID, target.id, types.ChatPermissions(can_send_messages=False), until_date=until)
        await message.answer(
            f"🔇 <i>Bouncer Hans melangkah mendekat ke meja <b>{html.escape(target.first_name)}</b> dan memberi isyarat tenang.</i>\n\n"
            f"<b>\"Harap tenangkan diri selama 15 menit sebelum kembali berbincang.\"</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await reply_and_autodelete(message, f"Gagal mute: {e}", 30)


@router.message(Command("kick"), F.chat.id == GROUP_ID)
async def cmd_kick(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id) or not message.reply_to_message:
        return
    target = message.reply_to_message.from_user
    try:
        await hans_bot.ban_chat_member(GROUP_ID, target.id)
        await hans_bot.unban_chat_member(GROUP_ID, target.id)
        async with db.pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_in_bar = FALSE, vip_booth_name = NULL WHERE user_id = $1", target.id)
        await message.answer(
            f"🚪 <i>Bouncer Hans mencengkeram bahu <b>{html.escape(target.first_name)}</b> dengan tegas dan mengantarnya keluar pintu mahoni.</i>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await reply_and_autodelete(message, f"Gagal kick: {e}", 30)


@router.message(Command("round"), F.chat.id == GROUP_ID)
async def cmd_round(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    async with db.pool.acquire() as conn:
        active_users = await conn.fetch("SELECT user_id FROM users WHERE is_in_bar = TRUE")
        await conn.execute("UPDATE users SET coins = coins + 25 WHERE is_in_bar = TRUE")
        for u in active_users:
            await log_tx(conn, u["user_id"], 25, "Traktiran On The House dari Owner")
    await message.answer(
        "🍾 <b>ON THE HOUSE — TRAKTIRAN OWNER!</b>\n\n"
        "<i>Bartender Julian membunyikan lonceng kuningan di atas meja bar! Seluruh tamu yang sedang berada di dalam lounge mendapatkan <b>+25 Velvet Coins</b>!</i>",
        parse_mode=ParseMode.HTML,
    )
