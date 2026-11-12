import os
import asyncio
import logging
from datetime import datetime
from collections import deque

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from aiogram.enums import ParseMode

from pyrogram import Client
from pyrogram.raw import functions
from pytgcalls import PyTgCalls, filters
from pytgcalls.types import MediaStream, AudioQuality
import yt_dlp

import shared.database as db
from shared.config import (
    TOKEN_KAELEN, API_ID, API_HASH, SESSION_STRING,
    OWNER_ID, GROUP_ID, SONG_REQ_COST, MUSIC_VAULT_ID
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN_KAELEN)
dp = Dispatcher()

assistant = Client(
    name="kaelen_assistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)
call_py = PyTgCalls(assistant)

song_queue = deque()
is_playing = False
idle_leave_task = None

# --- PENCARIAN LAGU: 1. CHANNEL GUDANG TELEGRAM -> 2. SOUNDCLOUD FALLBACK ---
async def find_song_source(query: str, user_id: int):
    """Mencari file audio langsung di Channel Gudang Telegram, jika tidak ada cari ke SoundCloud"""
    os.makedirs("downloads", exist_ok=True)

    # 1. Cari di Channel Gudang Musik Telegram (Paling cepat & bebas blokir)
    if MUSIC_VAULT_ID != 0:
        try:
            async for msg in assistant.search_messages(MUSIC_VAULT_ID, query=query, limit=5):
                if msg.audio or msg.document:
                    media = msg.audio or msg.document
                    title = getattr(media, "title", None) or getattr(media, "file_name", None) or query
                    performer = getattr(media, "performer", None) or "The Velvet Vault"
                    duration = getattr(media, "duration", 0) or 0

                    file_path = await assistant.download_media(
                        msg,
                        file_name=f"downloads/vault_{user_id}_{msg.id}.mp3"
                    )
                    if file_path and os.path.exists(file_path):
                        return {
                            "title": title,
                            "uploader": performer,
                            "duration": duration,
                            "stream_url": file_path,
                            "is_local_file": True
                        }
        except Exception as e:
            logging.warning(f"Gagal cari di Music Vault: {e}")

    # 2. Cadangan: Cari via SoundCloud
    def _sc_search():
        opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"scsearch1:{query}", download=False)
                if "entries" in info and info["entries"]:
                    entry = info["entries"][0]
                    if entry.get("duration", 0) > 480:
                        return "TOO_LONG"
                    return {
                        "title": entry.get("title", query),
                        "uploader": entry.get("uploader", "SoundCloud"),
                        "duration": entry.get("duration", 0),
                        "stream_url": entry["url"],
                        "webpage_url": entry.get("webpage_url", ""),
                        "is_local_file": False
                    }
        except Exception as e:
            logging.warning(f"SoundCloud fallback gagal: {e}")
        return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sc_search)

async def get_personal_audio_file(query: str, user_id: int):
    """Ambil file MP3 lokal dari Vault atau unduh dari SoundCloud untuk /myearphone"""
    info = await find_song_source(query, user_id)
    if not info or info == "TOO_LONG":
        return info

    if info.get("is_local_file"):
        return {
            "file_path": info["stream_url"],
            "title": info["title"],
            "uploader": info["uploader"]
        }

    # Jika dari SoundCloud, unduh dulu ke file lokal
    def _dl_sc():
        out_tmpl = f"downloads/sc_{user_id}_%(id)s.%(ext)s"
        opts = {
            "format": "bestaudio/best",
            "outtmpl": out_tmpl,
            "noplaylist": True,
            "quiet": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(info["webpage_url"], download=True)
                return {
                    "file_path": ydl.prepare_filename(data),
                    "title": info["title"],
                    "uploader": info["uploader"]
                }
        except Exception:
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _dl_sc)

# --- HELPER DATABASE & HAK AKSES ---
async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def is_vip_user(user_id: int) -> bool:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())

async def is_active_dj(user_id: int) -> bool:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM active_shifts WHERE role = 'dj' AND user_id = $1", user_id)
        return bool(row)

async def add_dj_shift_action(user_id: int):
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE active_shifts SET actions_count = actions_count + 1 WHERE role = 'dj' AND user_id = $1", user_id)

# --- KONTROL VOICE CHAT & AUTO-MUTE PENDENGAR ---
async def ensure_voice_chat_locked():
    try:
        peer = await assistant.resolve_peer(GROUP_ID)
        full_chat = await assistant.invoke(functions.channels.GetFullChannel(channel=peer))
        call = full_chat.full_chat.call

        if not call:
            await assistant.invoke(
                functions.phone.CreateGroupCall(
                    peer=peer,
                    random_id=assistant.rnd_id() // 2147483647,
                    title="🎶 The Velvet Hour — Lounge Audio"
                )
            )
            await asyncio.sleep(1)
            full_chat = await assistant.invoke(functions.channels.GetFullChannel(channel=peer))
            call = full_chat.full_chat.call

        if call:
            await assistant.invoke(
                functions.phone.ToggleGroupCallSettings(
                    call=call,
                    join_muted=True
                )
            )
    except Exception as e:
        logging.warning(f"Voice Chat lock info: {e}")

async def auto_leave_when_idle():
    global is_playing
    await asyncio.sleep(180)
    if not is_playing and len(song_queue) == 0:
        try:
            await call_py.leave_call(GROUP_ID)
            await bot.send_message(
                GROUP_ID,
                "🎧 <i>Kaelen mematikan meja turntable karena antrean lagu telah usai.</i>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

current_local_file = None

async def play_next_song():
    global is_playing, idle_leave_task, current_local_file

    # Bersihkan file sementara lagu sebelumnya jika ada
    if current_local_file and os.path.exists(current_local_file):
        try:
            os.remove(current_local_file)
        except Exception:
            pass
        current_local_file = None

    if idle_leave_task and not idle_leave_task.done():
        idle_leave_task.cancel()

    if not song_queue:
        is_playing = False
        idle_leave_task = asyncio.create_task(auto_leave_when_idle())
        return

    is_playing = True
    track = song_queue.popleft()
    if track.get("is_local_file"):
        current_local_file = track["stream_url"]

    await ensure_voice_chat_locked()

    stream = MediaStream(
        track["stream_url"],
        audio_parameters=AudioQuality.HIGH,
        video_flags=MediaStream.Flags.IGNORE
    )

    try:
        await call_py.play(GROUP_ID, stream)
        dedication_txt = f"\n💌 <i>Dedikasi untuk <b>{track['dedicate_to']}</b>: \"{track['dedicate_note']}\"</i>" if track.get("dedicate_to") else ""
        await bot.send_message(
            GROUP_ID,
            f"🎶 <b>NOW PLAYING — LOUNGE SPEAKER</b>\n"
            f"• <b>Lagu:</b> {track['title']}\n"
            f"• <b>Diputar oleh:</b> {track['requester']}{dedication_txt}\n\n"
            f"<i>Tekan tombol <b>Gabung</b> di bilah atas untuk mendengarkan (Mikrofon tamu dikunci).</i>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error(f"Gagal memutar stream: {e}")
        is_playing = False
        await play_next_song()

@call_py.on_update(filters.stream_end)
async def on_stream_end_handler(_, update):
    if update.chat_id == GROUP_ID:
        await play_next_song()

# --- START DI PRIVATE CHAT ---
@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start_kaelen(message: types.Message):
    await message.answer(
        "🎧 <i>Jarum piringan hitam berputar perlahan di sudut ruangan...</i>\n\n"
        "<b>\"Selamat malam. Saya Kaelen, kurator musik di <i>The Velvet Hour</i>. "
        "Gunakan perintah <code>/myearphone judul lagu</code> di sini untuk mendengarkan musik secara pribadi.\"</b>",
        parse_mode=ParseMode.HTML
    )

# --- COMMAND MUSIK DI GRUP ---
@dp.message(Command("reqsong"), F.chat.id == GROUP_ID)
async def cmd_reqsong(message: types.Message):
    query = message.text.replace("/reqsong", "").strip()
    if not query:
        return await message.reply(
            "Sebutkan judul lagu dan penyanyinya.\nContoh: <code>/reqsong Apocalypse</code>",
            parse_mode=ParseMode.HTML
        )

    user_id = message.from_user.id
    free_pass = await is_vip_user(user_id) or await is_active_dj(user_id) or await is_staff_or_owner(user_id)

    if not free_pass:
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
                if not coins or coins < SONG_REQ_COST:
                    return await message.reply(
                        f"Saldo tidak cukup (butuh <b>{SONG_REQ_COST} VC</b> untuk request lagu di lounge, gratis untuk VIP).",
                        parse_mode=ParseMode.HTML
                    )
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", SONG_REQ_COST, user_id)

    wait_msg = await message.reply("🔎 <i>Kaelen sedang mencari piringan hitam di rak koleksi...</i>", parse_mode=ParseMode.HTML)
    info = await find_song_source(query, user_id)

    if not info:
        return await wait_msg.edit_text("Lagu belum tersedia di koleksi rak musik. Coba ketik judul yang lebih singkat.")
    if info == "TOO_LONG":
        return await wait_msg.edit_text("Durasi lagu terlalu panjang (maksimal 8 menit).")

    info["requester"] = message.from_user.first_name
    song_queue.append(info)

    if not is_playing:
        await wait_msg.delete()
        await play_next_song()
    else:
        await wait_msg.edit_text(
            f"💿 <b>Ditambahkan ke Antrean Jukebox (#{len(song_queue)})</b>\n"
            f"• <b>Lagu:</b> {info['title']}\n"
            f"• <b>Pemesan:</b> {message.from_user.first_name}",
            parse_mode=ParseMode.HTML
        )

# --- COMMAND EKSKLUSIF RESIDENT DJ ---
@dp.message(Command("spinmusic"), F.chat.id == GROUP_ID)
async def cmd_spinmusic(message: types.Message):
    user_id = message.from_user.id
    if not await is_active_dj(user_id) and not await is_staff_or_owner(user_id):
        return

    query = message.text.replace("/spinmusic", "").strip()
    if not query:
        return

    wait_msg = await message.reply("🎧 <i>Resident DJ menyiapkan piringan hitam prioritas...</i>", parse_mode=ParseMode.HTML)
    info = await find_song_source(query, user_id)
    if not info or info == "TOO_LONG":
        return await wait_msg.edit_text("Lagu tidak ditemukan di koleksi rak musik.")

    info["requester"] = f"Resident DJ {message.from_user.first_name}"
    song_queue.appendleft(info)
    await add_dj_shift_action(user_id)

    await wait_msg.delete()
    if not is_playing:
        await play_next_song()
    else:
        await message.answer(f"⚡ <b>DJ Priority:</b> <i>{info['title']}</i> akan diputar tepat setelah lagu ini!", parse_mode=ParseMode.HTML)

@dp.message(Command("dedicate"), F.chat.id == GROUP_ID)
async def cmd_dedicate(message: types.Message):
    user_id = message.from_user.id
    if not await is_active_dj(user_id) and not await is_staff_or_owner(user_id):
        return

    raw = message.text.replace("/dedicate", "").strip()
    if "|" not in raw or len(raw.split()) < 3:
        return await message.reply(
            "Format dedikasi:\n<code>/dedicate @username Judul Lagu | Pesan singkat</code>",
            parse_mode=ParseMode.HTML
        )

    left_part, note = raw.split("|", 1)
    parts = left_part.strip().split(" ", 1)
    target_user = parts[0]
    query = parts[1]

    wait_msg = await message.reply("🎶 <i>Resident DJ menyiapkan lagu dedikasi spesial...</i>", parse_mode=ParseMode.HTML)
    info = await find_song_source(query, user_id)
    if not info or info == "TOO_LONG":
        return await wait_msg.edit_text("Lagu tidak ditemukan di koleksi rak musik.")

    info["requester"] = f"Resident DJ {message.from_user.first_name}"
    info["dedicate_to"] = target_user
    info["dedicate_note"] = note.strip()
    song_queue.appendleft(info)
    await add_dj_shift_action(user_id)

    await wait_msg.delete()
    if not is_playing:
        await play_next_song()
    else:
        await message.answer(f"💌 Lagu dedikasi untuk <b>{target_user}</b> telah masuk antrean teratas!", parse_mode=ParseMode.HTML)

@dp.message(Command("skip"), F.chat.id == GROUP_ID)
async def cmd_skip(message: types.Message):
    user_id = message.from_user.id
    if not await is_active_dj(user_id) and not await is_staff_or_owner(user_id):
        return
    await message.answer(f"⏭️ <b>{message.from_user.first_name}</b> melewati lagu saat ini...", parse_mode=ParseMode.HTML)
    await play_next_song()

@dp.message(Command("stopmusic"), F.chat.id == GROUP_ID)
async def cmd_stopmusic(message: types.Message):
    user_id = message.from_user.id
    if not await is_active_dj(user_id) and not await is_staff_or_owner(user_id):
        return
    global is_playing
    song_queue.clear()
    is_playing = False
    try:
        await call_py.leave_call(GROUP_ID)
    except Exception:
        pass
    await message.answer("⏹️ <b>Pemutaran musik dihentikan</b> dan antrean dibersihkan.", parse_mode=ParseMode.HTML)

# --- MODE B: PERSONAL HEADPHONE (/myearphone) ---
@dp.message(Command("myearphone"))
async def cmd_myearphone(message: types.Message):
    query = message.text.replace("/myearphone", "").strip()
    if not query:
        return await message.reply(
            "Sebutkan judul lagu.\nContoh: <code>/myearphone Sunsetz</code>",
            parse_mode=ParseMode.HTML
        )

    user_id = message.from_user.id
    status_msg = await message.reply("🎧 <i>Kaelen sedang menyiapkan headphone nirkabel khusus untukmu...</i>", parse_mode=ParseMode.HTML)

    result = await get_personal_audio_file(query, user_id)

    if not result:
        return await status_msg.edit_text("Lagu belum tersedia di rak koleksi.")
    if result == "TOO_LONG":
        return await status_msg.edit_text("Durasi lagu maksimal 8 menit.")

    try:
        audio_file = types.FSInputFile(result["file_path"])
        await bot.send_audio(
            chat_id=user_id,
            audio=audio_file,
            title=result["title"],
            performer=result["uploader"],
            caption=(
                "🎧 <b>PERSONAL HEADPHONE — THE VELVET HOUR</b>\n"
                "<i>\"Ini lagu yang kamu minta. Nikmati di mejamu sendiri tanpa terganggu keramaian bar.\"</i>"
            ),
            parse_mode=ParseMode.HTML
        )
        if message.chat.type != "private":
            await status_msg.edit_text(
                f"🎧 <b>Kaelen</b> telah menyerahkan headphone pribadi ke <b>Private Chat</b> milik {message.from_user.first_name}!",
                parse_mode=ParseMode.HTML
            )
        else:
            await status_msg.delete()
    except Exception:
        await status_msg.edit_text(
            "Gagal mengirim lagu ke PC-mu. Pastikan kamu sudah menekan <b>/start</b> di bot ini terlebih dahulu!",
            parse_mode=ParseMode.HTML
        )
    finally:
        if isinstance(result, dict) and os.path.exists(result["file_path"]):
            os.remove(result["file_path"])

# --- REGISTER MENU COMMAND ---
async def register_kaelen_commands():
    group_cmds = [
        BotCommand(command="reqsong", description="Putar lagu di Voice Chat Lounge (15 VC / Gratis VIP)"),
        BotCommand(command="myearphone", description="Kirim lagu pribadi (MP3) ke Private Chat"),
        BotCommand(command="spinmusic", description="[Resident DJ] Putar lagu prioritas antrean teratas"),
        BotCommand(command="dedicate", description="[Resident DJ] Dedikasikan lagu untuk tamu tertentu"),
        BotCommand(command="skip", description="[Resident DJ] Lewati lagu yang sedang diputar"),
        BotCommand(command="stopmusic", description="[Resident DJ] Hentikan musik & bersihkan antrean"),
    ]
    private_cmds = [
        BotCommand(command="start", description="Mulai sesi dengan kurator musik Kaelen"),
        BotCommand(command="myearphone", description="Dengarkan lagu secara pribadi di sini"),
    ]
    await bot.set_my_commands(group_cmds, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())

async def main():
    await db.init_db()
    await register_kaelen_commands()
    await assistant.start()
    await call_py.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
