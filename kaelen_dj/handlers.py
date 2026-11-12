import os
import html
import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import GROUP_ID, SONG_REQ_COST
from kaelen_dj.helpers import (
    bot, SHIFT_REQUIRED_ACTIONS, VOTESKIP_REQUIRED,
    schedule_delete, is_staff_or_owner, is_vip_user,
    is_active_dj, add_dj_shift_action, log_music_tx_and_quest
)
from kaelen_dj.audio_engine import (
    song_queue, skip_voters, play_lock, state, call_py,
    find_song_source, play_next_song
)

router = Router()

def _fmt_sec(sec: int) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"

# --- START DI PRIVATE CHAT ---
@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start_kaelen(message: types.Message):
    await message.answer(
        "🎧 <i>Jarum piringan hitam berputar perlahan di sudut ruangan...</i>\n\n"
        "<b>\"Selamat malam. Saya Kaelen, kurator musik di <i>The Velvet Hour</i>.</b>\n\n"
        "Gunakan format di bawah ini untuk memutar musik pribadi:\n"
        "• Format: <code>/myearphone Judul Lagu - Nama Penyanyi</code>\n"
        "• Contoh: <code>/myearphone Sunsetz - Cigarettes After Sex</code>\"",
        parse_mode=ParseMode.HTML,
    )

# --- INFO LAGU SAAT INI (/nowplaying) ---
@router.message(Command("nowplaying"), F.chat.id == GROUP_ID)
async def cmd_nowplaying(message: types.Message):
    track = state["current_track"]
    if not state["is_playing"] or not track:
        sent = await message.reply(
            "💿 <i>Meja turntable sedang sunyi—belum ada lagu yang diputar saat ini.</i>",
            parse_mode=ParseMode.HTML,
        )
        return asyncio.create_task(schedule_delete(sent, 45))

    elapsed = int((datetime.utcnow() - state["started_at"]).total_seconds()) if state["started_at"] else 0
    dur = track.get("duration", 0) or 0
    dur_txt = f"{_fmt_sec(elapsed)} / {_fmt_sec(dur)}" if dur > 0 else f"{_fmt_sec(elapsed)} diputar"

    dedication_txt = (
        f"\n• <b>Dedikasi:</b> Untuk <b>{track['dedicate_to']}</b> — <i>\"{track['dedicate_note']}\"</i>"
        if track.get("dedicate_to") else ""
    )
    sent = await message.reply(
        "🎶 <b>SEDANG DIPUTAR — THE VELVET TURNTABLE</b>\n\n"
        f"• <b>Judul:</b> {html.escape(track['title'])}\n"
        f"• <b>Diputar oleh:</b> {html.escape(track['requester'])}\n"
        f"• <b>Durasi:</b> {dur_txt}{dedication_txt}\n"
        f"• <b>Vote Skip:</b> {len(skip_voters)}/{VOTESKIP_REQUIRED} suara (<code>/voteskip</code>)",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(schedule_delete(sent, 60))

# --- LIHAT ANTREAN LAGU (/queue) ---
@router.message(Command("queue"), F.chat.id == GROUP_ID)
async def cmd_queue(message: types.Message):
    track = state["current_track"]
    if not state["is_playing"] and not song_queue:
        sent = await message.reply(
            "💿 <i>Meja turntable sedang sunyi—belum ada lagu yang diputar atau mengantre.</i>\n"
            "Contoh memutar lagu: <code>/reqsong Apocalypse - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML,
        )
        return asyncio.create_task(schedule_delete(sent, 45))

    lines = []
    if state["is_playing"] and track:
        lines.append(
            f"▶️ <b>Sedang Diputar:</b>\n"
            f"   🎶 {html.escape(track['title'])} <i>({html.escape(track['requester'])})</i>\n"
        )

    if song_queue:
        lines.append(f"📋 <b>Antrean Berikutnya ({len(song_queue)} lagu):</b>")
        for idx, item in enumerate(list(song_queue)[:10], start=1):
            lines.append(f"   <b>{idx}.</b> {html.escape(item['title'])} — <i>{html.escape(item['requester'])}</i>")
        if len(song_queue) > 10:
            lines.append(f"   <i>...dan {len(song_queue) - 10} lagu lainnya.</i>")
    else:
        lines.append("📋 <b>Antrean Berikutnya:</b> <i>Kosong (Radio Lounge akan menyala otomatis jika bar ramai).</i>")

    sent = await message.reply(
        "🎧 <b>VELVET JUKEBOX QUEUE</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(schedule_delete(sent, 60))

# --- VOTING SKIP LAGU (/voteskip) ---
@router.message(Command("voteskip"), F.chat.id == GROUP_ID)
async def cmd_voteskip(message: types.Message):
    track = state["current_track"]
    if not state["is_playing"] or not track:
        sent = await message.reply("<i>Tidak ada lagu yang sedang diputar saat ini.</i>", parse_mode=ParseMode.HTML)
        return asyncio.create_task(schedule_delete(sent, 30))

    user_id = message.from_user.id

    if await is_active_dj(user_id) or await is_staff_or_owner(user_id):
        await message.answer(
            f"⏭️ <b>{html.escape(message.from_user.first_name)}</b> melewati lagu <i>{html.escape(track['title'])}</i>...",
            parse_mode=ParseMode.HTML,
        )
        return await play_next_song(allow_radio_fallback=False)

    if user_id in skip_voters:
        sent = await message.reply(
            f"Kamu sudah memberikan suara skip untuk lagu ini (<b>{len(skip_voters)}/{VOTESKIP_REQUIRED}</b> suara).",
            parse_mode=ParseMode.HTML,
        )
        return asyncio.create_task(schedule_delete(sent, 30))

    skip_voters.add(user_id)
    current_votes = len(skip_voters)

    if current_votes >= VOTESKIP_REQUIRED:
        await message.answer(
            f"⏭️ <b>VOTESKIP TERCAPAI ({current_votes}/{VOTESKIP_REQUIRED})!</b>\n"
            f"Kaelen mengangkat jarum piringan hitam dari <i>{html.escape(track['title'])}</i> dan beralih ke lagu berikutnya...",
            parse_mode=ParseMode.HTML,
        )
        await play_next_song(allow_radio_fallback=False)
    else:
        sent = await message.reply(
            f"🗳️ <b>Vote Skip Diterima ({current_votes}/{VOTESKIP_REQUIRED} suara)</b>\n"
            f"<i>Butuh <b>{VOTESKIP_REQUIRED - current_votes} suara lagi</b> untuk melewati lagu ini. Ketik <code>/voteskip</code> untuk ikut memilih.</i>",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(schedule_delete(sent, 45))

# --- REQUEST LAGU DI GRUP (/reqsong) + MUTASI DOMPET & MISI HARIAN ---
@router.message(Command("reqsong"), F.chat.id == GROUP_ID)
async def cmd_reqsong(message: types.Message):
    query = message.text.replace("/reqsong", "").strip()
    if not query or "-" not in query:
        return await message.reply(
            "Sertakan <b>judul lagu dan nama penyanyinya</b> agar tidak salah versi.\n\n"
            "• Format: <code>/reqsong Judul Lagu - Nama Penyanyi</code>\n"
            "• Contoh: <code>/reqsong Apocalypse - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML,
        )

    user_id = message.from_user.id
    free_pass = await is_vip_user(user_id) or await is_active_dj(user_id) or await is_staff_or_owner(user_id)

    if not free_pass:
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
                if not coins or coins < SONG_REQ_COST:
                    return await message.reply(
                        f"Saldo tidak cukup (butuh <b>{SONG_REQ_COST} VC</b> untuk request lagu di lounge, gratis untuk VIP & DJ).",
                        parse_mode=ParseMode.HTML,
                    )
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", SONG_REQ_COST, user_id)

    wait_msg = await message.reply(f"🔎 <i>Kaelen mencari piringan hitam <b>{html.escape(query)}</b>...</i>", parse_mode=ParseMode.HTML)
    info, err_reason = await find_song_source(query, user_id)

    if not info:
        if not free_pass:
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", SONG_REQ_COST, user_id)
        return await wait_msg.edit_text(f"❌ {err_reason}", parse_mode=ParseMode.HTML)

    await log_music_tx_and_quest(user_id, 0 if free_pass else SONG_REQ_COST, info["title"])
    info["requester"] = message.from_user.first_name
    song_queue.append(info)

    if not state["is_playing"]:
        await wait_msg.delete()
        await play_next_song()
    else:
        await wait_msg.edit_text(
            f"💿 <b>Ditambahkan ke Antrean Jukebox (#{len(song_queue)})</b>\n\n"
            f"• <b>Lagu:</b> {html.escape(info['title'])}\n"
            f"• <b>Pemesan:</b> {html.escape(message.from_user.first_name)}",
            parse_mode=ParseMode.HTML,
        )

# --- COMMAND EKSKLUSIF RESIDENT DJ ---
@router.message(Command("spinmusic"), F.chat.id == GROUP_ID)
async def cmd_spinmusic(message: types.Message):
    user_id = message.from_user.id
    dj_active = await is_active_dj(user_id)
    if not dj_active and not await is_staff_or_owner(user_id):
        return await message.reply(
            "Khusus staf <b>Resident DJ</b> (kuota 1 orang).\n"
            "Contoh melamar: <code>/apply dj</code>",
            parse_mode=ParseMode.HTML,
        )

    query = message.text.replace("/spinmusic", "").strip()
    if not query or "-" not in query:
        return await message.reply(
            "• Format: <code>/spinmusic Judul Lagu - Nama Penyanyi</code>\n"
            "• Contoh: <code>/spinmusic Sunsetz - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML,
        )

    wait_msg = await message.reply("🎧 <i>Resident DJ menyiapkan piringan hitam prioritas...</i>", parse_mode=ParseMode.HTML)
    info, err_reason = await find_song_source(query, user_id)
    if not info:
        return await wait_msg.edit_text(f"❌ {err_reason}", parse_mode=ParseMode.HTML)

    info["requester"] = f"Resident DJ {message.from_user.first_name}"
    song_queue.appendleft(info)

    prog_txt = ""
    if dj_active:
        cnt = await add_dj_shift_action(user_id)
        prog_txt = f"\n📊 <i>Progres Shift DJ: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>"

    await wait_msg.delete()
    if not state["is_playing"]:
        await play_next_song()
        if prog_txt:
            await message.answer(prog_txt.strip(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            f"⚡ <b>DJ Priority:</b> <i>{html.escape(info['title'])}</i> akan diputar tepat setelah lagu ini!{prog_txt}",
            parse_mode=ParseMode.HTML,
        )

@router.message(Command("dedicate"), F.chat.id == GROUP_ID)
async def cmd_dedicate(message: types.Message):
    user_id = message.from_user.id
    dj_active = await is_active_dj(user_id)
    if not dj_active and not await is_staff_or_owner(user_id):
        return await message.reply(
            "Khusus staf <b>Resident DJ</b> (kuota 1 orang).\n"
            "Contoh melamar: <code>/apply dj</code>",
            parse_mode=ParseMode.HTML,
        )

    raw = message.text.replace("/dedicate", "").strip()
    if "|" not in raw or "-" not in raw or len(raw.split()) < 4:
        return await message.reply(
            "• Format: <code>/dedicate @username Judul Lagu - Penyanyi | Pesan singkat</code>\n"
            "• Contoh: <code>/dedicate @clara Perfect - Ed Sheeran | Buat kamu yang lagi santai</code>",
            parse_mode=ParseMode.HTML,
        )

    left_part, note = raw.split("|", 1)
    parts = left_part.strip().split(" ", 1)
    target_user = parts[0]
    query = parts[1]

    wait_msg = await message.reply("🎶 <i>Resident DJ menyiapkan lagu dedikasi spesial...</i>", parse_mode=ParseMode.HTML)
    info, err_reason = await find_song_source(query, user_id)
    if not info:
        return await wait_msg.edit_text(f"❌ {err_reason}", parse_mode=ParseMode.HTML)

    info["requester"] = f"Resident DJ {message.from_user.first_name}"
    info["dedicate_to"] = html.escape(target_user)
    info["dedicate_note"] = html.escape(note.strip())
    song_queue.appendleft(info)

    prog_txt = ""
    if dj_active:
        cnt = await add_dj_shift_action(user_id)
        prog_txt = f"\n📊 <i>Progres Shift DJ: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>"

    await wait_msg.delete()
    if not state["is_playing"]:
        await play_next_song()
        if prog_txt:
            await message.answer(prog_txt.strip(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            f"💌 Lagu dedikasi untuk <b>{html.escape(target_user)}</b> telah masuk antrean teratas!{prog_txt}",
            parse_mode=ParseMode.HTML,
        )

@router.message(Command("skip"), F.chat.id == GROUP_ID)
async def cmd_skip(message: types.Message):
    user_id = message.from_user.id
    dj_active = await is_active_dj(user_id)
    if not dj_active and not await is_staff_or_owner(user_id):
        return await message.reply("Khusus staf <b>Resident DJ</b>. Contoh melamar: <code>/apply dj</code>", parse_mode=ParseMode.HTML)

    prog_txt = ""
    if dj_active:
        cnt = await add_dj_shift_action(user_id)
        prog_txt = f"\n📊 <i>Progres Shift DJ: {cnt}/{SHIFT_REQUIRED_ACTIONS} layanan</i>"

    await message.answer(f"⏭️ <b>{html.escape(message.from_user.first_name)}</b> melewati lagu saat ini...{prog_txt}", parse_mode=ParseMode.HTML)
    await play_next_song(allow_radio_fallback=False)

@router.message(Command("stopmusic"), F.chat.id == GROUP_ID)
async def cmd_stopmusic(message: types.Message):
    user_id = message.from_user.id
    if not await is_active_dj(user_id) and not await is_staff_or_owner(user_id):
        return await message.reply("Khusus staf <b>Resident DJ</b>. Contoh melamar: <code>/apply dj</code>", parse_mode=ParseMode.HTML)

    async with play_lock:
        song_queue.clear()
        skip_voters.clear()
        state["is_playing"] = False
        state["current_track"] = None
        state["started_at"] = None
        state["current_stream_token"] += 1
        try:
            await call_py.leave_call(GROUP_ID)
        except Exception:
            pass
    await message.answer("⏹️ <b>Pemutaran musik dihentikan</b> dan antrean dibersihkan.", parse_mode=ParseMode.HTML)

# --- PERSONAL HEADPHONE (/myearphone) + PROGRES MISI HARIAN ---
@router.message(Command("myearphone"))
async def cmd_myearphone(message: types.Message):
    query = message.text.replace("/myearphone", "").strip()
    if not query or "-" not in query:
        return await message.reply(
            "Sertakan <b>judul lagu dan nama penyanyinya</b> agar akurat.\n\n"
            "• Format: <code>/myearphone Judul Lagu - Nama Penyanyi</code>\n"
            "• Contoh: <code>/myearphone Sunsetz - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML,
        )

    user_id = message.from_user.id
    status_msg = await message.reply("🎧 <i>Kaelen sedang menyiapkan headphone nirkabel khusus untukmu...</i>", parse_mode=ParseMode.HTML)

    result, err_reason = await find_song_source(query, user_id)
    if not result:
        return await status_msg.edit_text(f"❌ {err_reason}", parse_mode=ParseMode.HTML)

    try:
        audio_file = types.FSInputFile(result["stream_url"])
        await bot.send_audio(
            chat_id=user_id,
            audio=audio_file,
            title=result["title"],
            performer=result["uploader"],
            caption=(
                "🎧 <b>PERSONAL HEADPHONE — THE VELVET HOUR</b>\n\n"
                "<i>\"Ini lagu yang kamu minta. Nikmati di mejamu sendiri tanpa terganggu keramaian bar.\"</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        await log_music_tx_and_quest(user_id, 0, result["title"])
        if message.chat.type != "private":
            await status_msg.edit_text(
                f"🎧 <b>Kaelen</b> telah menyerahkan headphone pribadi ke <b>Private Chat</b> milik {html.escape(message.from_user.first_name)}!",
                parse_mode=ParseMode.HTML,
            )
        else:
            await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(
            f"Gagal mengirim lagu ke PC-mu (<code>{html.escape(str(e))}</code>). Pastikan kamu sudah menekan <b>/start</b> di bot ini!",
            parse_mode=ParseMode.HTML,
        )
    finally:
        if isinstance(result, dict) and os.path.exists(result["stream_url"]):
            os.remove(result["stream_url"])
