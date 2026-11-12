import os
import re
import html
import random
import asyncio
import logging
from collections import deque
from datetime import datetime

from aiogram.enums import ParseMode
from pyrogram import Client
from pyrogram.raw import functions
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality

from shared.config import GROUP_ID, MUSIC_VAULT_ID
from kaelen_dj.helpers import bot, has_active_guests_in_bar

INLINE_MUSIC_BOTS = ["vkmusic_bot", "lybot", "DeezerMusicBot", "music"]

# State pemutaran global yang diakses bersama oleh handlers & main
assistant: Client | None = None
call_py: PyTgCalls | None = None

song_queue: deque = deque()
skip_voters: set[int] = set()
play_lock = asyncio.Lock()

state = {
    "is_playing": False,
    "current_track": None,
    "started_at": None,
    "idle_leave_task": None,
    "current_local_file": None,
    "current_stream_token": 0,
}

# --- PARSING & VALIDASI AKURASI LAGU ---
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
    if MUSIC_VAULT_ID == 0 or assistant is None:
        return None
    try:
        os.makedirs("downloads", exist_ok=True)
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
                "is_radio": True,
            }
    except Exception as e:
        logging.warning(f"Lounge radio fetch gagal: {e}")
    return None

async def find_song_source(query: str, user_id: int):
    os.makedirs("downloads", exist_ok=True)
    clean_query = re.sub(r"\s+", " ", query.replace("-", " ")).strip()
    errors_log = []

    # 1. Cek di Channel Gudang Musik
    if MUSIC_VAULT_ID != 0 and assistant is not None:
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
                        "is_local_file": True,
                    }, None
        except Exception as e:
            errors_log.append(f"Vault: {e}")

    # 2. Tarik dari Bot Musik Inline
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
                result_id=best_res.id,
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
                        "is_local_file": True,
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

# --- KONTROL VOICE CHAT & PEMUTARAN STREAM ---
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
                    title="🎶 The Velvet Hour — Lounge Audio",
                )
            )
            await asyncio.sleep(1)
            full_chat = await assistant.invoke(functions.channels.GetFullChannel(channel=peer))
            call = full_chat.full_chat.call

        if call:
            await assistant.invoke(
                functions.phone.ToggleGroupCallSettings(
                    call=call,
                    join_muted=True,
                )
            )
    except Exception as e:
        logging.info(f"Voice Chat lock info: {e}")

async def auto_leave_when_idle():
    await asyncio.sleep(180)
    async with play_lock:
        if not state["is_playing"] and len(song_queue) == 0:
            state["current_track"] = None
            state["started_at"] = None
            skip_voters.clear()
            try:
                await call_py.leave_call(GROUP_ID)
                await bot.send_message(
                    GROUP_ID,
                    "🎧 <i>Kaelen mematikan meja turntable karena antrean lagu telah usai dan ruangan sedang tenang.</i>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

async def play_next_song(expected_token: int | None = None, allow_radio_fallback: bool = False):
    async with play_lock:
        if expected_token is not None and expected_token != state["current_stream_token"]:
            return

        if state["current_local_file"] and os.path.exists(state["current_local_file"]):
            try:
                os.remove(state["current_local_file"])
            except Exception:
                pass
            state["current_local_file"] = None

        idle_task = state["idle_leave_task"]
        if idle_task and not idle_task.done():
            idle_task.cancel()

        skip_voters.clear()

        if not song_queue and allow_radio_fallback and await has_active_guests_in_bar():
            radio_track = await get_random_vault_track()
            if radio_track:
                song_queue.append(radio_track)

        if not song_queue:
            state["is_playing"] = False
            state["current_track"] = None
            state["started_at"] = None
            state["current_stream_token"] += 1
            state["idle_leave_task"] = asyncio.create_task(auto_leave_when_idle())
            return

        state["is_playing"] = True
        state["current_stream_token"] += 1
        track = song_queue.popleft()
        state["current_track"] = track
        state["started_at"] = datetime.utcnow()
        state["current_local_file"] = track["stream_url"]

        await ensure_voice_chat_locked()

        stream = MediaStream(
            track["stream_url"],
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.IGNORE,
        )

        try:
            await call_py.play(GROUP_ID, stream)
            dedication_txt = (
                f"\n💌 <i>Dedikasi untuk <b>{track['dedicate_to']}</b>: \"{track['dedicate_note']}\"</i>"
                if track.get("dedicate_to") else ""
            )
            header = (
                "📻 <b>VELVET LOUNGE RADIO — AUTO PLAYLIST</b>"
                if track.get("is_radio")
                else "🎶 <b>NOW PLAYING — LOUNGE SPEAKER</b>"
            )
            await bot.send_message(
                GROUP_ID,
                f"{header}\n\n"
                f"• <b>Lagu:</b> {html.escape(track['title'])}\n"
                f"• <b>Diputar oleh:</b> {html.escape(track['requester'])}{dedication_txt}\n\n"
                f"<i>Tekan <b>Gabung</b> di bilah atas untuk mendengarkan (Gunakan <code>/nowplaying</code>, <code>/queue</code>, atau <code>/voteskip</code>).</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.error(f"Gagal memutar stream: {e}")
            await bot.send_message(
                GROUP_ID,
                f"⚠️ <b>Asisten gagal masuk/memutar audio di Obrolan Suara:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=ParseMode.HTML,
            )
            state["is_playing"] = False
            state["current_track"] = None
            state["started_at"] = None

    if not state["is_playing"] and song_queue:
        await play_next_song()
