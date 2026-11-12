import os
import re
import html
import random
import asyncio
import logging
from datetime import datetime, timedelta
from collections import deque

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand, BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats, BotCommandScopeChatMember
)
from aiogram.enums import ParseMode

from pyrogram import Client
from pyrogram.raw import functions
from pytgcalls import PyTgCalls, filters
from pytgcalls.types import MediaStream, AudioQuality

import shared.database as db
from shared.config import (
    TOKEN_KAELEN, API_ID, API_HASH, SESSION_STRING,
    OWNER_ID, GROUP_ID, SONG_REQ_COST, MUSIC_VAULT_ID
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN_KAELEN)
dp = Dispatcher()

assistant: Client = None
call_py: PyTgCalls = None

song_queue = deque()
is_playing = False
current_track = None
idle_leave_task = None
current_local_file = None
current_stream_token = 0
play_lock = asyncio.Lock()

# Voting skip state (reset otomatis tiap lagu berganti)
skip_voters: set[int] = set()
VOTESKIP_REQUIRED = 3

SHIFT_MAX_MINUTES = 20
SHIFT_REQUIRED_ACTIONS = 5

INLINE_MUSIC_BOTS = ["vkmusic_bot", "lybot", "DeezerMusicBot", "music"]

ALL_GROUP_COMMANDS = [
    BotCommand(command="reqsong", description="Putar lagu di bar — Contoh: /reqsong Apocalypse - Cigarettes After Sex"),
    BotCommand(command="queue", description="Lihat lagu yang diputar & daftar antrean — Contoh: /queue"),
    BotCommand(command="voteskip", description="Voting lewati lagu saat ini (3 suara) — Contoh: /voteskip"),
    BotCommand(command="myearphone", description="Kirim lagu pribadi — Contoh: /myearphone Sunsetz - Cigarettes After Sex"),
    BotCommand(command="spinmusic", description="[Shift DJ] Putar lagu prioritas — Contoh: /spinmusic Sunsetz - CAS"),
    BotCommand(command="dedicate", description="[Shift DJ] Dedikasi lagu — Contoh: /dedicate @clara Perfect - Ed Sheeran | Buat kamu"),
    BotCommand(command="skip", description="[Shift DJ] Lewati lagu yang sedang diputar — Contoh: /skip"),
    BotCommand(command="stopmusic", description="[Shift DJ] Hentikan musik & bersihkan antrean — Contoh: /stopmusic"),
]

DJ_PRIORITY_COMMANDS = [
    BotCommand(command="spinmusic", description="[Tugas DJ] Putar lagu prioritas — Contoh: /spinmusic Sunsetz - CAS"),
    BotCommand(command="dedicate", description="[Tugas DJ] Dedikasi lagu — Contoh: /dedicate @clara Perfect - Ed Sheeran | Buat kamu"),
    BotCommand(command="skip", description="[Tugas DJ] Lewati lagu yang sedang diputar — Contoh: /skip"),
    BotCommand(command="stopmusic", description="[Tugas DJ] Hentikan musik & bersihkan antrean — Contoh: /stopmusic"),
    BotCommand(command="queue", description="Lihat daftar antrean jukebox — Contoh: /queue"),
    BotCommand(command="reqsong", description="Putar lagu di bar — Contoh: /reqsong Apocalypse - Cigarettes After Sex"),
    BotCommand(command="myearphone", description="Kirim lagu pribadi — Contoh: /myearphone Sunsetz - Cigarettes After Sex"),
]

async def schedule_delete(msg: types.Message, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

async def sync_dj_member_commands(user_id: int, active: bool):
    scope = BotCommandScopeChatMember(chat_id=GROUP_ID, user_id=user_id)
    try:
        if active:
            await bot.set_my_commands(DJ_PRIORITY_COMMANDS, scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception as e:
        logging.warning(f"Gagal sync DJ commands untuk {user_id}: {e}")

# --- PARSING & VALIDASI AKURASI LAGU (JUDUL + PENYANYI) ---
def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _parse_song_query(query: str):
    if "-" in query:
        parts = query.split("-", 1)
        return _normalize_text(parts[0]), _normalize_text(parts[1])
    return _normalize_text(query), ""

def _match_score(query: str, cand_title: str, cand_artist: str) -> float:
    q_song, q_artist = _parse_song_query(query)
    full_cand = _normalize_text(f"{cand_title} {cand_artist}")

    if not full_cand:
        return 0.0

    noise_words = ["remix", "sped up", "slowed", "reverb", "karaoke", "instrumental", "cover", "nightcore", "8d"]
    q_norm = _normalize_text(query)
    for nw in noise_words:
        if nw in full_cand and nw not in q_norm:
            return 0.1

    song_words = [w for w in q_song.split() if len(w) > 1]
    artist_words = [w for w in q_artist.split() if len(w) > 1]

    if not song_words:
        return 0.0

    song_hits = sum(1 for w in song_words if w in full_cand) / len(song_words)
    if song_hits < 0.75:
        return 0.0

    if artist_words:
        artist_hits = sum(1 for w in artist_words if w in full_cand) / len(artist_words)
        if artist_hits < 0.5:
            return 0.0
        return (song_hits * 0.6) + (artist_hits * 0.4)

    return song_hits

async def get_random_vault_track():
    """Mengambil 1 lagu acak dari Channel Gudang Musik untuk Lounge Radio Mode."""
    if MUSIC_VAULT_ID == 0:
        return None
    try:
        candidates = []
        async for msg in assistant.get_chat_history(MUSIC_VAULT_ID, limit=40):
            if msg.audio or msg.document:
                media = msg.audio or msg.document
                duration = getattr(media, "duration", 0) or 0
                if 60 <= duration <= 480:
                    candidates.append(msg)
        if not candidates:
            return None

        chosen = random.choice(candidates)
        media = chosen.audio or chosen.document
        title = getattr(media, "title", None) or getattr(media, "file_name", None) or "Velvet Lounge Selection"
        performer = getattr(media, "performer", None) or "The Velvet Radio"
        duration = getattr(media, "duration", 0) or 0

        file_path = await assistant.download_media(
            chosen,
            file_name=f"downloads/radio_{chosen.id}_{random.randint(100,999)}.mp3"
        )
        if file_path and os.path.exists(file_path):
            display_title = f"{performer} - {title}" if performer and performer.lower() not in title.lower() else title
            return {
                "title": display_title,
                "uploader": performer,
                "duration": duration,
                "stream_url": file_path,
                "is_local_file": True,
                "requester": "📻 Velvet Lounge Radio (Auto-Playlist)",
                "is_radio": True
            }
    except Exception as e:
        logging.warning(f"Lounge radio fetch gagal: {e}")
    return None

async def find_song_source(query: str, user_id: int):
    os.makedirs("downloads", exist_ok=True)
    clean_query = re.sub(r"\s+", " ", query.replace("-", " ")).strip()
    errors_log = []

    # 1. Cek di Channel Gudang Musik
    if MUSIC_VAULT_ID != 0:
        try:
            best_vault_msg = None
            best_vault_score = 0.0

            async for msg in assistant.search_messages(MUSIC_VAULT_ID, query=clean_query, limit=15):
                if msg.audio or msg.document:
                    media = msg.audio or msg.document
                    title = getattr(media, "title", None) or getattr(media, "file_name", None) or ""
                    performer = getattr(media, "performer", None) or ""
                    duration = getattr(media, "duration", 0) or 0
                    if duration > 480:
                        continue

                    score = _match_score(query, title, performer)
                    if score > best_vault_score:
                        best_vault_score = score
                        best_vault_msg = msg

            if best_vault_msg and best_vault_score >= 0.75:
                media = best_vault_msg.audio or best_vault_msg.document
                title = getattr(media, "title", None) or getattr(media, "file_name", None) or query
                performer = getattr(media, "performer", None) or ""
                duration = getattr(media, "duration", 0) or 0

                file_path = await assistant.download_media(
                    best_vault_msg,
                    file_name=f"downloads/vault_{user_id}_{best_vault_msg.id}_{random.randint(100,999)}.mp3"
                )
                if file_path and os.path.exists(file_path):
                    display_title = f"{performer} - {title}" if performer and performer.lower() not in title.lower() else title
                    return {
                        "title": display_title,
                        "uploader": performer or "The Velvet Vault",
                        "duration": duration,
                        "stream_url": file_path,
                        "is_local_file": True
                    }, None
        except Exception as e:
            errors_log.append(f"Vault: {e}")

    # 2. Tarik dari Bot Musik Inline dengan seleksi skor terbaik & cek pesan terbaru
    target_chat = MUSIC_VAULT_ID if MUSIC_VAULT_ID != 0 else "me"

    for bot_username in INLINE_MUSIC_BOTS:
        try:
            inline_res = await assistant.get_inline_bot_results(bot_username, clean_query)
            if not inline_res or not inline_res.results:
                errors_log.append(f"@{bot_username}: kosong")
                continue

            best_res = None
            best_score = 0.0
            for res in inline_res.results[:10]:
                res_title = getattr(res, "title", "") or ""
                res_desc = getattr(res, "description", "") or ""
                score = _match_score(query, res_title, res_desc)
                if score > best_score:
                    best_score = score
                    best_res = res

            if not best_res or best_score < 0.70:
                errors_log.append(f"@{bot_username}: tidak ada judul/penyanyi yang cocok")
                continue

            last_msg_id = 0
            async for m in assistant.get_chat_history(target_chat, limit=1):
                last_msg_id = m.id

            await assistant.send_inline_bot_result(
                chat_id=target_chat,
                query_id=inline_res.query_id,
                result_id=best_res.id
            )

            new_audio_msg = None
            for _ in range(5):
                await asyncio.sleep(1)
                async for msg in assistant.get_chat_history(target_chat, limit=3):
                    if msg.id > last_msg_id and (msg.audio or msg.document):
                        new_audio_msg = msg
                        break
                if new_audio_msg:
                    break

            if new_audio_msg:
                media = new_audio_msg.audio or new_audio_msg.document
                duration = getattr(media, "duration", 0) or 0
                if duration > 480:
                    return None, "Durasi lagu terlalu panjang (maksimal 8 menit)."

                title = getattr(media, "title", None) or getattr(media, "file_name", None) or query
                performer = getattr(media, "performer", None) or ""
                display_title = f"{performer} - {title}" if performer and performer.lower() not in title.lower() else title

                file_path = await assistant.download_media(
                    new_audio_msg,
                    file_name=f"downloads/vk_{user_id}_{new_audio_msg.id}_{random.randint(100,999)}.mp3"
                )
                if file_path and os.path.exists(file_path):
                    return {
                        "title": display_title,
                        "uploader": performer or "Velvet Jukebox",
                        "duration": duration,
                        "stream_url": file_path,
                        "is_local_file": True
                    }, None
        except Exception as e:
            errors_log.append(f"@{bot_username}: {e}")
            continue

    detail = html.escape(" | ".join(errors_log)) if errors_log else "Tidak ada hasil."
    return None, (
        f"Lagu <b>{html.escape(query)}</b> tidak ditemukan dengan versi yang akurat.\n"
        f"<i>Pastikan penulisan judul & nama penyanyi benar (Contoh: <code>Apocalypse - Cigarettes After Sex</code>).</i>\n"
        f"<small>({detail})</small>"
    )

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
        row = await conn.fetchrow(
            "SELECT user_id FROM active_shifts WHERE role = 'dj' AND user_id = $1 AND started_at > $2",
            user_id, datetime.utcnow() - timedelta(minutes=SHIFT_MAX_MINUTES)
        )
        return bool(row)

async def add_dj_shift_action(user_id: int) -> int:
    async with db.pool.acquire() as conn:
        new_val = await conn.fetchval(
            "UPDATE active_shifts SET actions_count = actions_count + 1 WHERE role = 'dj' AND user_id = $1 RETURNING actions_count",
            user_id
        )
        return new_val or 0

async def has_active_guests_in_bar() -> bool:
    async with db.pool.acquire() as conn:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE is_in_bar = TRUE AND last_active > $1",
            datetime.utcnow() - timedelta(minutes=30)
        )
        return (cnt or 0) > 0

# --- WORKER SINKRONISASI COMMAND DJ OTOMATIS DI MENU / ---
async def dj_command_sync_loop():
    known_active_djs = set()
    while True:
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_id FROM active_shifts WHERE role = 'dj' AND started_at > $1",
                    datetime.utcnow() - timedelta(minutes=SHIFT_MAX_MINUTES)
                )
            current_djs = {r["user_id"] for r in rows}

            for uid in current_djs - known_active_djs:
                await sync_dj_member_commands(uid, True)
            for uid in known_active_djs - current_djs:
                await sync_dj_member_commands(uid, False)

            known_active_djs = current_djs
        except Exception as e:
            logging.error(f"DJ command sync error: {e}")
        await asyncio.sleep(3)

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
                    random_id=random.randint(1, 2147483647),
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
        logging.info(f"Voice Chat lock info: {e}")

async def auto_leave_when_idle():
    global is_playing, current_track
    await asyncio.sleep(180)
    async with play_lock:
        if not is_playing and len(song_queue) == 0:
            current_track = None
            skip_voters.clear()
            try:
                await call_py.leave_call(GROUP_ID)
                await bot.send_message(
                    GROUP_ID,
                    "🎧 <i>Kaelen mematikan meja turntable karena antrean lagu telah usai dan ruangan sedang tenang.</i>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

async def play_next_song(expected_token: int | None = None, allow_radio_fallback: bool = False):
    """Memutar lagu berikutnya (termasuk Lounge Radio Mode saat antrean kosong namun bar ramai)."""
    global is_playing, idle_leave_task, current_local_file, current_stream_token, current_track

    async with play_lock:
        if expected_token is not None and expected_token != current_stream_token:
            return

        if current_local_file and os.path.exists(current_local_file):
            try:
                os.remove(current_local_file)
            except Exception:
                pass
            current_local_file = None

        if idle_leave_task and not idle_leave_task.done():
            idle_leave_task.cancel()

        skip_voters.clear()

        # Jika antrean kosong namun masih ada tamu aktif & mode radio diizinkan -> putar 1 lagu lounge dari Vault
        if not song_queue and allow_radio_fallback and await has_active_guests_in_bar():
            radio_track = await get_random_vault_track()
            if radio_track:
                song_queue.append(radio_track)

        if not song_queue:
            is_playing = False
            current_track = None
            current_stream_token += 1
            idle_leave_task = asyncio.create_task(auto_leave_when_idle())
            return

        is_playing = True
        current_stream_token += 1
        track = song_queue.popleft()
        current_track = track
        current_local_file = track["stream_url"]

        await ensure_voice_chat_locked()

        stream = MediaStream(
            track["stream_url"],
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.IGNORE
        )

        try:
            await call_py.play(GROUP_ID, stream)
            dedication_txt = (
                f"\n💌 <i>Dedikasi untuk <b>{track['dedicate_to']}</b>: \"{track['dedicate_note']}\"</i>"
                if track.get("dedicate_to") else ""
            )
            header = "📻 <b>VELVET LOUNGE RADIO — AUTO PLAYLIST</b>" if track.get("is_radio") else "🎶 <b>NOW PLAYING — LOUNGE SPEAKER</b>"
            await bot.send_message(
                GROUP_ID,
                f"{header}\n\n"
                f"• <b>Lagu:</b> {html.escape(track['title'])}\n"
                f"• <b>Diputar oleh:</b> {html.escape(track['requester'])}{dedication_txt}\n\n"
                f"<i>Tekan tombol <b>Gabung</b> di bilah atas untuk mendengarkan (Gunakan <code>/queue</code> untuk antrean atau <code>/voteskip</code> untuk melewati).</i>",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logging.error(f"Gagal memutar stream: {e}")
            await bot.send_message(
                GROUP_ID,
                f"⚠️ <b>Asisten gagal masuk/memutar audio di Obrolan Suara:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML
            )
            is_playing = False
            current_track = None

    if not is_playing and song_queue:
        await play_next_song()

# --- START DI PRIVATE CHAT ---
@dp.message(CommandStart(), F.chat.type == "private")
async def cmd_start_kaelen(message: types.Message):
    await message.answer(
        "🎧 <i>Jarum piringan hitam berputar perlahan di sudut ruangan...</i>\n\n"
        "<b>\"Selamat malam. Saya Kaelen, kurator musik di <i>The Velvet Hour</i>.</b>\n\n"
        "Gunakan format di bawah ini untuk memutar musik pribadi:\n"
        "• Format: <code>/myearphone Judul Lagu - Nama Penyanyi</code>\n"
        "• Contoh: <code>/myearphone Sunsetz - Cigarettes After Sex</code>\"",
        parse_mode=ParseMode.HTML
    )

# --- FITUR BARU 1: LIHAT ANTREAN LAGU (/queue) ---
@dp.message(Command("queue"), F.chat.id == GROUP_ID)
async def cmd_queue(message: types.Message):
    if not is_playing and not song_queue:
        sent = await message.reply(
            "💿 <i>Meja turntable sedang sunyi—belum ada lagu yang diputar atau mengantre.</i>\n"
            "Contoh memutar lagu: <code>/reqsong Apocalypse - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML
        )
        return asyncio.create_task(schedule_delete(sent, 45))

    lines = []
    if is_playing and current_track:
        lines.append(
            f"▶️ <b>Sedang Diputar:</b>\n"
            f"   🎶 {html.escape(current_track['title'])} <i>({html.escape(current_track['requester'])})</i>\n"
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
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(schedule_delete(sent, 60))

# --- FITUR BARU 2: VOTING SKIP LAGU (/voteskip) ---
@dp.message(Command("voteskip"), F.chat.id == GROUP_ID)
async def cmd_voteskip(message: types.Message):
    if not is_playing or not current_track:
        sent = await message.reply("<i>Tidak ada lagu yang sedang diputar saat ini.</i>", parse_mode=ParseMode.HTML)
        return asyncio.create_task(schedule_delete(sent, 30))

    user_id = message.from_user.id

    # Jika Resident DJ aktif atau Staff/Owner yang menekan, langsung skip tanpa menunggu 3 suara
    if await is_active_dj(user_id) or await is_staff_or_owner(user_id):
        await message.answer(
            f"⏭️ <b>{html.escape(message.from_user.first_name)}</b> melewati lagu <i>{html.escape(current_track['title'])}</i>...",
            parse_mode=ParseMode.HTML
        )
        return await play_next_song(allow_radio_fallback=False)

    if user_id in skip_voters:
        sent = await message.reply(
            f"Kamu sudah memberikan suara skip untuk lagu ini (<b>{len(skip_voters)}/{VOTESKIP_REQUIRED}</b> suara).",
            parse_mode=ParseMode.HTML
        )
        return asyncio.create_task(schedule_delete(sent, 30))

    skip_voters.add(user_id)
    current_votes = len(skip_voters)

    if current_votes >= VOTESKIP_REQUIRED:
        await message.answer(
            f"⏭️ <b>VOTESKIP TERCAPAI ({current_votes}/{VOTESKIP_REQUIRED})!</b>\n"
            f"Kaelen mengangkat jarum piringan hitam dari <i>{html.escape(current_track['title'])}</i> dan beralih ke lagu berikutnya...",
            parse_mode=ParseMode.HTML
        )
        await play_next_song(allow_radio_fallback=False)
    else:
        sent = await message.reply(
            f"🗳️ <b>Vote Skip Diterima ({current_votes}/{VOTESKIP_REQUIRED} suara)</b>\n"
            f"<i>Butuh <b>{VOTESKIP_REQUIRED - current_votes} suara lagi</b> untuk melewati lagu ini. Ketik <code>/voteskip</code> untuk ikut memilih.</i>",
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(schedule_delete(sent, 45))

# --- COMMAND MUSIK DI GRUP ---
@dp.message(Command("reqsong"), F.chat.id == GROUP_ID)
async def cmd_reqsong(message: types.Message):
    query = message.text.replace("/reqsong", "").strip()
    if not query or "-" not in query:
        return await message.reply(
            "Sertakan <b>judul lagu dan nama penyanyinya</b> agar tidak salah versi.\n\n"
            "• Format: <code>/reqsong Judul Lagu - Nama Penyanyi</code>\n"
            "• Contoh: <code>/reqsong Apocalypse - Cigarettes After Sex</code>",
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
                        f"Saldo tidak cukup (butuh <b>{SONG_REQ_COST} VC</b> untuk request lagu di lounge, gratis untuk VIP & DJ).",
                        parse_mode=ParseMode.HTML
                    )
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", SONG_REQ_COST, user_id)

    wait_msg = await message.reply(f"🔎 <i>Kaelen mencari piringan hitam <b>{html.escape(query)}</b>...</i>", parse_mode=ParseMode.HTML)
    info, err_reason = await find_song_source(query, user_id)

    if not info:
        if not free_pass:
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", SONG_REQ_COST, user_id)
        return await wait_msg.edit_text(f"❌ {err_reason}", parse_mode=ParseMode.HTML)

    info["requester"] = message.from_user.first_name
    song_queue.append(info)

    if not is_playing:
        await wait_msg.delete()
        await play_next_song()
    else:
        await wait_msg.edit_text(
            f"💿 <b>Ditambahkan ke Antrean Jukebox (#{len(song_queue)})</b>\n\n"
            f"• <b>Lagu:</b> {html.escape(info['title'])}\n"
            f"• <b>Pemesan:</b> {html.escape(message.from_user.first_name)}",
            parse_mode=ParseMode.HTML
        )

# --- COMMAND EKSKLUSIF RESIDENT DJ ---
@dp.message(Command("spinmusic"), F.chat.id == GROUP_ID)
async def cmd_spinmusic(message: types.Message):
    user_id = message.from_user.id
    dj_active = await is_active_dj(user_id)
    if not dj_active and not await is_staff_or_owner(user_id):
        return await message.reply(
            "Khusus staf <b>Resident DJ</b> (kuota 1 orang).\n"
            "Contoh melamar: <code>/apply dj</code>",
            parse_mode=ParseMode.HTML
        )

    query = message.text.replace("/spinmusic", "").strip()
    if not query or "-" not in query:
        return await message.reply(
            "• Format: <code>/spinmusic Judul Lagu - Nama Penyanyi</code>\n"
            "• Contoh: <code>/spinmusic Sunsetz - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML
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
    if not is_playing:
        await play_next_song()
        if prog_txt:
            await message.answer(prog_txt.strip(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            f"⚡ <b>DJ Priority:</b> <i>{html.escape(info['title'])}</i> akan diputar tepat setelah lagu ini!{prog_txt}",
            parse_mode=ParseMode.HTML
        )

@dp.message(Command("dedicate"), F.chat.id == GROUP_ID)
async def cmd_dedicate(message: types.Message):
    user_id = message.from_user.id
    dj_active = await is_active_dj(user_id)
    if not dj_active and not await is_staff_or_owner(user_id):
        return await message.reply(
            "Khusus staf <b>Resident DJ</b> (kuota 1 orang).\n"
            "Contoh melamar: <code>/apply dj</code>",
            parse_mode=ParseMode.HTML
        )

    raw = message.text.replace("/dedicate", "").strip()
    if "|" not in raw or "-" not in raw or len(raw.split()) < 4:
        return await message.reply(
            "• Format: <code>/dedicate @username Judul Lagu - Penyanyi | Pesan singkat</code>\n"
            "• Contoh: <code>/dedicate @clara Perfect - Ed Sheeran | Buat kamu yang lagi santai</code>",
            parse_mode=ParseMode.HTML
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
    if not is_playing:
        await play_next_song()
        if prog_txt:
            await message.answer(prog_txt.strip(), parse_mode=ParseMode.HTML)
    else:
        await message.answer(
            f"💌 Lagu dedikasi untuk <b>{html.escape(target_user)}</b> telah masuk antrean teratas!{prog_txt}",
            parse_mode=ParseMode.HTML
        )

@dp.message(Command("skip"), F.chat.id == GROUP_ID)
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

@dp.message(Command("stopmusic"), F.chat.id == GROUP_ID)
async def cmd_stopmusic(message: types.Message):
    user_id = message.from_user.id
    if not await is_active_dj(user_id) and not await is_staff_or_owner(user_id):
        return await message.reply("Khusus staf <b>Resident DJ</b>. Contoh melamar: <code>/apply dj</code>", parse_mode=ParseMode.HTML)

    global is_playing, current_stream_token, current_track
    async with play_lock:
        song_queue.clear()
        skip_voters.clear()
        is_playing = False
        current_track = None
        current_stream_token += 1
        try:
            await call_py.leave_call(GROUP_ID)
        except Exception:
            pass
    await message.answer("⏹️ <b>Pemutaran musik dihentikan</b> dan antrean dibersihkan.", parse_mode=ParseMode.HTML)

# --- MODE B: PERSONAL HEADPHONE (/myearphone) ---
@dp.message(Command("myearphone"))
async def cmd_myearphone(message: types.Message):
    query = message.text.replace("/myearphone", "").strip()
    if not query or "-" not in query:
        return await message.reply(
            "Sertakan <b>judul lagu dan nama penyanyinya</b> agar akurat.\n\n"
            "• Format: <code>/myearphone Judul Lagu - Nama Penyanyi</code>\n"
            "• Contoh: <code>/myearphone Sunsetz - Cigarettes After Sex</code>",
            parse_mode=ParseMode.HTML
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
            parse_mode=ParseMode.HTML
        )
        if message.chat.type != "private":
            await status_msg.edit_text(
                f"🎧 <b>Kaelen</b> telah menyerahkan headphone pribadi ke <b>Private Chat</b> milik {html.escape(message.from_user.first_name)}!",
                parse_mode=ParseMode.HTML
            )
        else:
            await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(
            f"Gagal mengirim lagu ke PC-mu (<code>{html.escape(str(e))}</code>). Pastikan kamu sudah menekan <b>/start</b> di bot ini!",
            parse_mode=ParseMode.HTML
        )
    finally:
        if isinstance(result, dict) and os.path.exists(result["stream_url"]):
            os.remove(result["stream_url"])

# --- REGISTER MENU COMMAND ---
async def register_kaelen_commands():
    private_cmds = [
        BotCommand(command="start", description="Mulai sesi dengan kurator musik Kaelen"),
        BotCommand(command="myearphone", description="Dengarkan lagu pribadi — Contoh: /myearphone Sunsetz - CAS"),
    ]
    await bot.set_my_commands(ALL_GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())

async def main():
    global assistant, call_py
    await db.init_db()
    await register_kaelen_commands()
    asyncio.create_task(dj_command_sync_loop())

    assistant = Client(
        name="kaelen_assistant",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        in_memory=True
    )
    call_py = PyTgCalls(assistant)

    @call_py.on_update(filters.stream_end)
    async def on_stream_end_handler(_, update):
        if update.chat_id == GROUP_ID:
            token_snapshot = current_stream_token
            await asyncio.sleep(0.5)
            # Aktifkan Lounge Radio Mode jika antrean kosong namun bar sedang ramai
            await play_next_song(expected_token=token_snapshot, allow_radio_fallback=True)

    await assistant.start()
    async for _ in assistant.get_dialogs():
        pass
    await call_py.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
