import os
import json
import html
import glob
import asyncio
import logging
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import yt_dlp
from pyrogram import Client
from pyrogram.raw import functions, types as raw_types
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream, AudioQuality

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, ReactionTypeEmoji
from aiogram.enums import ParseMode

import shared.database as db
import shared.config as cfg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kaelen_dj")

GROUP_ID = cfg.GROUP_ID
OWNER_ID = int(cfg.OWNER_ID)
SONG_REQUEST_COST = 10
AUTO_DELETE_DELAY = 45
CACHE_DIR = "/tmp/kaelen_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def _get_music_vault_id() -> int | str | None:
    raw = getattr(cfg, "MUSIC_VAULT_ID", None) or os.environ.get("MUSIC_VAULT_ID")
    if not raw:
        return None
    val = str(raw).strip()
    return int(val) if val.lstrip("-").isdigit() else val


MUSIC_VAULT_ID = _get_music_vault_id()
SESSION_STRING = getattr(cfg, "SESSION_STRING", None) or os.environ.get("SESSION_STRING")
API_ID = int(getattr(cfg, "API_ID", 0) or os.environ.get("API_ID", 0))
API_HASH = str(getattr(cfg, "API_HASH", "") or os.environ.get("API_HASH", ""))

bot = Bot(token=cfg.TOKEN_KAELEN)
dp = Dispatcher(storage=MemoryStorage())

# Diinisialisasi di dalam main() agar terikat ke event loop yang sama dengan aiogram
assistant: Client | None = None
call_py: PyTgCalls | None = None
_play_lock: asyncio.Lock | None = None
_tg_bot_lock: asyncio.Lock | None = None


@dataclass
class TrackItem:
    title: str
    stream_url: str
    webpage_url: str
    duration: str
    requester_id: int
    requester_name: str
    thread_id: int | None = None
    db_req_id: int | None = None
    source_label: str = "Music Vault"


music_queue: deque[TrackItem] = deque()
current_track: TrackItem | None = None
is_paused: bool = False
_bg_tasks: set[asyncio.Task] = set()
_assistant_user_id: int = 0


def _spawn_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


def _mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'


def _format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "Live / ∞"
    sec = int(seconds)
    mins, rem = divmod(sec, 60)
    hrs, mins = divmod(mins, 60)
    return f"{hrs}:{mins:02d}:{rem:02d}" if hrs else f"{mins}:{rem:02d}"


def _cleanup_old_cache(keep_path: str | None = None):
    try:
        files = sorted(glob.glob(os.path.join(CACHE_DIR, "*")), key=os.path.getmtime)
        for f in files[:-3]:
            if keep_path and os.path.abspath(f) == os.path.abspath(keep_path):
                continue
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


def _extract_audio_meta(msg, fallback_title: str) -> tuple[bool, str, int | None]:
    media_obj = msg.audio or msg.document or msg.voice
    if not media_obj:
        return False, fallback_title, None

    if msg.document and not msg.audio:
        fname = (msg.document.file_name or "").lower()
        mime = (msg.document.mime_type or "").lower()
        if not (mime.startswith("audio/") or fname.endswith((".mp3", ".m4a", ".flac", ".ogg", ".wav", ".opus"))):
            return False, fallback_title, None

    raw_title = (
        getattr(msg.audio, "title", None)
        or getattr(msg.audio, "file_name", None)
        or getattr(msg.document, "file_name", None)
        or (msg.caption.splitlines()[0] if msg.caption else None)
        or fallback_title
    )
    performer = getattr(msg.audio, "performer", None)
    display_title = (
        f"{raw_title} - {performer}"
        if (performer and performer.lower() not in raw_title.lower())
        else raw_title
    )
    for ext in (".mp3", ".m4a", ".flac", ".ogg", ".wav", ".opus"):
        if display_title.lower().endswith(ext):
            display_title = display_title[:-len(ext)]

    duration_sec = getattr(msg.audio, "duration", None) or getattr(msg.voice, "duration", None)
    return True, display_title, duration_sec


async def react_msg(chat_id: int, message_id: int, emoji: str = "🎧"):
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass


def _schedule_delete(chat_id: int, message_ids: list[int], delay: int = AUTO_DELETE_DELAY):
    async def _worker():
        await asyncio.sleep(delay)
        for mid in message_ids:
            if not mid:
                continue
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    _spawn_task(_worker())


async def ensure_kaelen_schema():
    async with db.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS song_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                requester_name TEXT,
                song_title TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                thread_id BIGINT,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)
        await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_thread_id BIGINT;")


async def _send_kaelen_msg(text: str, thread_id: int | None = None, auto_delete: int = AUTO_DELETE_DELAY):
    clean_tid = thread_id if (thread_id and thread_id != 1) else None
    attempts = [clean_tid, None] if clean_tid else [None]
    for tid in attempts:
        kwargs = {"message_thread_id": tid} if tid else {}
        try:
            sent = await bot.send_message(
                chat_id=GROUP_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                **kwargs,
            )
            if sent and auto_delete > 0:
                _schedule_delete(GROUP_ID, [sent.message_id], delay=auto_delete)
            return sent
        except Exception as e:
            if tid and "thread not found" in str(e).lower():
                continue
            logger.warning("Gagal kirim pesan Kaelen: %s", e)
            return None


# --- AUTO-OPEN OS & AUTO-MUTE PENDENGAR (KECUALI OWNER & ASISTEN) ---
async def _ensure_voice_chat_open_and_muted():
    try:
        peer = await assistant.resolve_peer(GROUP_ID)
        full = await assistant.invoke(functions.channels.GetFullChannel(channel=peer))
        call = getattr(full.full_chat, "call", None)

        if not call:
            logger.info("OS belum terbuka. Akun asisten membuka Obrolan Suara...")
            await assistant.invoke(
                functions.phone.CreateGroupCall(
                    peer=peer,
                    random_id=assistant.rnd_id(),
                    title="🎶 The Velvet Hour — DJ Booth",
                )
            )
            await asyncio.sleep(1.0)
            full = await assistant.invoke(functions.channels.GetFullChannel(channel=peer))
            call = getattr(full.full_chat, "call", None)

        if call:
            try:
                await assistant.invoke(
                    functions.phone.ToggleGroupCallSettings(
                        call=call,
                        join_muted=True,
                    )
                )
            except Exception:
                pass
        return call
    except Exception as e:
        logger.error("Gagal membuka/mengatur OS: %s", e)
        return None


async def _unmute_assistant_in_call(call):
    if not call or not _assistant_user_id:
        return
    try:
        self_peer = await assistant.resolve_peer(_assistant_user_id)
        await assistant.invoke(
            functions.phone.EditGroupCallParticipant(
                call=call,
                participant=self_peer,
                muted=False,
            )
        )
    except Exception:
        pass


async def _enforce_os_listener_mute(client: Client, update, users, chats):
    if not isinstance(update, raw_types.UpdateGroupCallParticipants):
        return
    try:
        for p in update.participants:
            peer_uid = getattr(getattr(p, "peer", None), "user_id", None)
            if not peer_uid or peer_uid in (OWNER_ID, _assistant_user_id):
                continue
            if not getattr(p, "muted", True) or getattr(p, "can_self_unmute", False):
                target_peer = await client.resolve_peer(peer_uid)
                await client.invoke(
                    functions.phone.EditGroupCallParticipant(
                        call=update.call,
                        participant=target_peer,
                        muted=True,
                    )
                )
    except Exception:
        pass


# --- JALUR 1: MUSIC_VAULT_ID (GUDANG CHANNEL MUSIK) ---
async def _search_music_vault(query: str) -> dict | None:
    if not MUSIC_VAULT_ID:
        logger.warning("MUSIC_VAULT_ID belum terpasang!")
        return None
    try:
        async for msg in assistant.search_messages(chat_id=MUSIC_VAULT_ID, query=query, limit=10):
            is_audio, display_title, duration_sec = _extract_audio_meta(msg, query)
            if not is_audio:
                continue

            dest_path = os.path.join(CACHE_DIR, f"vault_{msg.id}_{int(datetime.utcnow().timestamp())}")
            downloaded_path = await assistant.download_media(msg, file_name=dest_path)
            if downloaded_path and os.path.exists(downloaded_path):
                _cleanup_old_cache(keep_path=downloaded_path)
                logger.info("Lagu ditemukan di MUSIC_VAULT_ID: %s", display_title)
                return {
                    "title": display_title,
                    "stream_url": downloaded_path,
                    "webpage_url": msg.link or "",
                    "duration": _format_duration(duration_sec),
                    "source_label": "Music Vault",
                }
    except Exception as e:
        logger.warning("Gagal mencari di MUSIC_VAULT_ID (%s): %s", MUSIC_VAULT_ID, e)
    return None


# --- JALUR 2: BOT MUSIK TELEGRAM -> SIMPAN KE MUSIC_VAULT_ID ---
async def _fetch_via_tg_music_bot(query: str) -> dict | None:
    music_bots = ["vkmusic_bot", "SpotSeekBot"]
    async with _tg_bot_lock:
        for bot_usn in music_bots:
            try:
                last_id = 0
                async for m in assistant.get_chat_history(bot_usn, limit=1):
                    last_id = m.id

                await assistant.send_message(bot_usn, query)
                target_audio_msg = None
                clicked = False

                for _ in range(12):
                    await asyncio.sleep(1.0)
                    recent = []
                    async for m in assistant.get_chat_history(bot_usn, limit=6):
                        if m.id <= last_id:
                            break
                        if not m.outgoing:
                            recent.append(m)

                    for m in recent:
                        is_audio, _, _ = _extract_audio_meta(m, query)
                        if is_audio:
                            target_audio_msg = m
                            break
                    if target_audio_msg:
                        break

                    if not clicked:
                        for m in recent:
                            if m.reply_markup and getattr(m.reply_markup, "inline_keyboard", None):
                                for row in m.reply_markup.inline_keyboard:
                                    btn = row[0] if row else None
                                    if btn and getattr(btn, "callback_data", None):
                                        try:
                                            await assistant.request_callback_answer(
                                                chat_id=bot_usn,
                                                message_id=m.id,
                                                callback_data=btn.callback_data,
                                            )
                                            clicked = True
                                            break
                                        except Exception:
                                            pass
                                    if clicked:
                                        break

                if not target_audio_msg:
                    continue

                is_audio, display_title, duration_sec = _extract_audio_meta(target_audio_msg, query)
                if not is_audio:
                    continue

                archived_link = ""
                if MUSIC_VAULT_ID:
                    try:
                        copied = await assistant.copy_message(
                            chat_id=MUSIC_VAULT_ID,
                            from_chat_id=bot_usn,
                            message_id=target_audio_msg.id,
                        )
                        archived_link = getattr(copied, "link", "") or ""
                        logger.info("Lagu '%s' disimpan ke MUSIC_VAULT_ID.", display_title)
                    except Exception as arch_err:
                        logger.debug("Skip simpan ke vault: %s", arch_err)

                dest_path = os.path.join(CACHE_DIR, f"tgbot_{target_audio_msg.id}_{int(datetime.utcnow().timestamp())}")
                downloaded_path = await assistant.download_media(target_audio_msg, file_name=dest_path)
                if downloaded_path and os.path.exists(downloaded_path):
                    _cleanup_old_cache(keep_path=downloaded_path)
                    return {
                        "title": display_title,
                        "stream_url": downloaded_path,
                        "webpage_url": archived_link,
                        "duration": _format_duration(duration_sec),
                        "source_label": "Music Vault",
                    }
            except Exception as e:
                logger.warning("Gagal ambil dari @%s: %s", bot_usn, e)
                continue
    return None


# --- JALUR 3: STREAMING CADANGAN ---
def _search_jiosaavn_sync(query: str) -> dict | None:
    encoded = urllib.parse.quote_plus(query)
    for api_url in (
        f"https://saavn.dev/api/search/songs?query={encoded}&limit=1",
        f"https://jiosaavn-api-privatecvc2.vercel.app/search/songs?query={encoded}&limit=1",
    ):
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            results = ((data or {}).get("data") or {}).get("results") or []
            if not results:
                continue
            song = results[0]
            dl_urls = song.get("downloadUrl") or []
            best_url = dl_urls[-1].get("url") or dl_urls[-1].get("link") if dl_urls else None
            if not best_url:
                continue
            artists = ", ".join(
                a.get("name", "") for a in ((song.get("artists") or {}).get("primary") or []) if a.get("name")
            )
            title = html.unescape(song.get("name") or query)
            return {
                "title": f"{title} - {artists}" if artists else title,
                "stream_url": best_url,
                "webpage_url": song.get("url") or "",
                "duration": _format_duration(song.get("duration")),
                "source_label": "Streaming",
            }
        except Exception:
            continue
    return None


async def resolve_audio_track(query: str) -> dict | None:
    vault_res = await _search_music_vault(query)
    if vault_res:
        return vault_res

    tg_bot_res = await _fetch_via_tg_music_bot(query)
    if tg_bot_res:
        return tg_bot_res

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _search_jiosaavn_sync, query)


async def _mark_db_song_status(req_id: int | None, status: str):
    if not req_id:
        return
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("UPDATE song_requests SET status = $1 WHERE id = $2", status, req_id)
    except Exception:
        pass


async def _play_next_in_queue():
    global current_track, is_paused
    async with _play_lock:
        if current_track and current_track.db_req_id:
            await _mark_db_song_status(current_track.db_req_id, "done")

        if not music_queue:
            current_track = None
            is_paused = False
            try:
                await call_py.leave_call(GROUP_ID)
            except Exception:
                pass
            return

        next_track = music_queue.popleft()
        current_track = next_track
        is_paused = False

        if next_track.db_req_id:
            await _mark_db_song_status(next_track.db_req_id, "playing")

        try:
            call = await _ensure_voice_chat_open_and_muted()

            stream = MediaStream(
                next_track.stream_url,
                audio_parameters=AudioQuality.HIGH,
                video_flags=MediaStream.Flags.IGNORE,
            )
            await call_py.play(GROUP_ID, stream)
            await _unmute_assistant_in_call(call)

            link_part = (
                f'<a href="{html.escape(next_track.webpage_url)}">{html.escape(next_track.title)}</a>'
                if next_track.webpage_url
                else f"<b>{html.escape(next_track.title)}</b>"
            )
            await _send_kaelen_msg(
                f"🎧 <b>Now Spinning — Kaelen Booth</b> (📀 {html.escape(next_track.source_label)})\n"
                f"• Lagu: {link_part} (<code>{next_track.duration}</code>)\n"
                f"• Permintaan: {_mention(next_track.requester_id, next_track.requester_name)}",
                thread_id=next_track.thread_id,
                auto_delete=55,
            )
        except Exception as e:
            logger.error("PyTgCalls play error: %s", e)
            await _send_kaelen_msg(
                f"⚠️ Asisten Kaelen gagal memutar <b>{html.escape(next_track.title)}</b> di OS.\n"
                f"<i>({html.escape(str(e))})</i>",
                thread_id=next_track.thread_id,
                auto_delete=30,
            )
            current_track = None
            if music_queue:
                _spawn_task(_play_next_in_queue())


async def on_tgcalls_update(_, update):
    update_name = type(update).__name__
    if "StreamEnded" in update_name or "StreamAudioEnded" in update_name:
        await _play_next_in_queue()


async def enqueue_song_request(
    query: str,
    uid: int,
    requester_name: str,
    thread_id: int | None = None,
    db_req_id: int | None = None,
    announce_queue: bool = True,
) -> bool:
    info = await resolve_audio_track(query)
    if not info:
        if db_req_id:
            await _mark_db_song_status(db_req_id, "failed")
        await _send_kaelen_msg(
            f"🥀 Kaelen tidak menemukan lagu untuk <b>{html.escape(query)}</b>.",
            thread_id=thread_id,
            auto_delete=25,
        )
        return False

    track = TrackItem(
        title=info["title"],
        stream_url=info["stream_url"],
        webpage_url=info["webpage_url"],
        duration=info["duration"],
        requester_id=uid,
        requester_name=requester_name,
        thread_id=thread_id,
        db_req_id=db_req_id,
        source_label=info.get("source_label", "Music Vault"),
    )
    music_queue.append(track)

    if current_track is None:
        await _play_next_in_queue()
    elif announce_queue:
        pos = len(music_queue)
        await _send_kaelen_msg(
            f"💿 <b>Ditambahkan ke Antrean (#{pos})</b>\n"
            f"• Lagu: <b>{html.escape(track.title)}</b> (<code>{track.duration}</code>)\n"
            f"• Oleh: {_mention(uid, requester_name)}",
            thread_id=thread_id,
            auto_delete=35,
        )
    return True


async def _poll_webapp_song_queue():
    await asyncio.sleep(3)
    while True:
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, user_id, requester_name, song_title, thread_id
                    FROM song_requests
                    WHERE status = 'pending'
                    ORDER BY id ASC
                    LIMIT 5
                """)
                for r in rows:
                    await conn.execute(
                        "UPDATE song_requests SET status = 'queued' WHERE id = $1",
                        r["id"],
                    )

            for r in rows:
                uid = int(r["user_id"] or 0)
                rname = r["requester_name"] or "Tamu Lounge"
                title = r["song_title"]
                tid = r["thread_id"]
                logger.info("Sinkron request lagu dari Mini App: %s (oleh %s)", title, rname)
                await enqueue_song_request(
                    query=title,
                    uid=uid,
                    requester_name=rname,
                    thread_id=tid,
                    db_req_id=r["id"],
                    announce_queue=(current_track is not None),
                )
        except Exception as e:
            logger.error("Error polling song_requests: %s", e)

        await asyncio.sleep(3)


@dp.message(Command("play", "reqsong"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_play_song(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        err = await message.reply(
            "🎶 Format: <code>/play Judul Lagu - Penyanyi</code> (<b>10 VC</b>, Gratis VIP).",
            parse_mode=ParseMode.HTML,
        )
        _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=20)
        return

    query = parts[1].strip()[:120]
    today = datetime.utcnow().date()

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO users (user_id, username, full_name, coins, last_thread_id)
                VALUES ($1, $2, $3, 50, $4)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = COALESCE(EXCLUDED.username, users.username),
                    full_name = EXCLUDED.full_name,
                    last_thread_id = COALESCE($4, users.last_thread_id);
            """, user.id, user.username, user.full_name, message.message_thread_id)

            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            is_vip = bool(row and row["is_vip"] and (not row["vip_until"] or row["vip_until"] > datetime.utcnow()))
            cost = 0 if is_vip else SONG_REQUEST_COST
            coins = (row["coins"] or 0) if row else 0

            if coins < cost:
                err = await message.reply(
                    f"Saldo tidak cukup untuk memutar lagu (butuh <b>{cost} VC</b>, saldo kamu: <b>{coins} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )
                _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=20)
                return

            if cost > 0:
                await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
                await conn.execute(
                    "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
                    user.id, -cost, f"Request lagu DJ: {query[:50]}"
                )

            await conn.execute("""
                INSERT INTO daily_quests (user_id, quest_date, quest_key, progress, claimed)
                VALUES ($1, $2, 'music_vibe', 1, FALSE)
                ON CONFLICT (user_id, quest_date, quest_key) DO UPDATE
                SET progress = LEAST(daily_quests.progress + 1, 1);
            """, user.id, today)

    await react_msg(message.chat.id, message.message_id, "🎶")
    search_msg = await message.reply(
        f"🔎 <i>Kaelen mencari piringan hitam <b>{html.escape(query)}</b>...</i>",
        parse_mode=ParseMode.HTML,
    )

    ok = await enqueue_song_request(
        query=query,
        uid=user.id,
        requester_name=user.first_name,
        thread_id=message.message_thread_id,
    )
    _schedule_delete(message.chat.id, [message.message_id, search_msg.message_id], delay=5 if ok else 15)


@dp.message(Command("np", "nowplaying"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_now_playing(message: types.Message):
    if not current_track:
        err = await message.reply("🔇 Booth DJ sedang hening. Ketik <code>/play judul lagu</code> untuk memutar musik.", parse_mode=ParseMode.HTML)
        _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
        return

    state = "⏸ Dijeda" if is_paused else "▶️ Sedang Diputar"
    msg = await message.reply(
        f"🎧 <b>{state}</b>\n"
        f"• Lagu: <b>{html.escape(current_track.title)}</b> (<code>{current_track.duration}</code>)\n"
        f"• Request oleh: {_mention(current_track.requester_id, current_track.requester_name)}\n"
        f"• Antrean berikutnya: <b>{len(music_queue)}</b> lagu",
        parse_mode=ParseMode.HTML,
    )
    _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=35)


@dp.message(Command("queue"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_music_queue(message: types.Message):
    if not current_track and not music_queue:
        err = await message.reply("📭 Daftar antrean lagu kosong.")
        _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
        return

    lines = []
    if current_track:
        lines.append(f"▶️ <b>Sekarang:</b> {html.escape(current_track.title)} ({html.escape(current_track.requester_name)})")
    for idx, t in enumerate(list(music_queue)[:10], start=1):
        lines.append(f"{idx}. {html.escape(t.title)} — <i>{html.escape(t.requester_name)}</i>")

    msg = await message.reply("🎶 <b>Daftar Putar Booth Kaelen</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML)
    _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=40)


@dp.message(Command("skip"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_skip_song(message: types.Message):
    if not current_track:
        err = await message.reply("Tidak ada lagu yang sedang diputar.")
        _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
        return

    uid = message.from_user.id
    if uid != OWNER_ID and uid != current_track.requester_id:
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status not in ("administrator", "creator"):
            err = await message.reply("Hanya pemesan lagu ini atau Admin yang bisa melewati lagu.")
            _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
            return

    skipped_title = current_track.title
    await react_msg(message.chat.id, message.message_id, "⏭️")
    msg = await message.reply(f"⏭️ Kaelen mengangkat jarum gramofon dan melewati <b>{html.escape(skipped_title)}</b>.", parse_mode=ParseMode.HTML)
    _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=20)
    await _play_next_in_queue()


@dp.message(Command("pause"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_pause_song(message: types.Message):
    global is_paused
    if not current_track or is_paused:
        return
    try:
        await call_py.pause(GROUP_ID)
        is_paused = True
        msg = await message.reply("⏸️ Kaelen menjeda musik di OS.")
        _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=20)
    except Exception as e:
        err = await message.reply(f"Gagal menjeda: {e}")
        _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)


@dp.message(Command("resume"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_resume_song(message: types.Message):
    global is_paused
    if not current_track or not is_paused:
        return
    try:
        await call_py.resume(GROUP_ID)
        is_paused = False
        msg = await message.reply("▶️ Kaelen melanjutkan alunan musik.")
        _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=20)
    except Exception as e:
        err = await message.reply(f"Gagal melanjutkan: {e}")
        _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)


@dp.message(Command("stop"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_stop_music(message: types.Message):
    global current_track, is_paused
    uid = message.from_user.id
    if uid != OWNER_ID:
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status not in ("administrator", "creator"):
            err = await message.reply("Perintah <code>/stop</code> hanya untuk Admin atau Owner.", parse_mode=ParseMode.HTML)
            _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
            return

    music_queue.clear()
    if current_track and current_track.db_req_id:
        await _mark_db_song_status(current_track.db_req_id, "stopped")
    current_track = None
    is_paused = False

    try:
        await call_py.leave_call(GROUP_ID)
    except Exception:
        pass

    msg = await message.reply("⏹️ Kaelen mematikan turntable dan mengosongkan antrean lagu.")
    _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=25)


@dp.message(Command("vibe"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dj_vibe(message: types.Message):
    msg = await message.reply(
        "🕯️ <i>Kaelen menyesuaikan equalizer di meja DJ, membiarkan dentuman bass lembut berpadu dengan cahaya temaram The Velvet Hour...</i>",
        parse_mode=ParseMode.HTML,
    )
    _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=35)


async def register_kaelen_commands():
    cmds = [
        BotCommand(command="play", description="Putar lagu di OS (10 VC / Gratis VIP)"),
        BotCommand(command="np", description="Lihat lagu yang sedang diputar"),
        BotCommand(command="queue", description="Lihat daftar antrean lagu DJ"),
        BotCommand(command="skip", description="Lewati lagu saat ini"),
        BotCommand(command="pause", description="Jeda musik di OS"),
        BotCommand(command="resume", description="Lanjutkan musik yang dijeda"),
        BotCommand(command="stop", description="[Admin] Hentikan musik & bersihkan antrean"),
        BotCommand(command="vibe", description="Atur atmosfer musik lounge"),
    ]
    await bot.set_my_commands(cmds, scope=BotCommandScopeAllGroupChats())


async def main():
    global assistant, call_py, _play_lock, _tg_bot_lock, _assistant_user_id

    _play_lock = asyncio.Lock()
    _tg_bot_lock = asyncio.Lock()

    await db.init_db()
    await ensure_kaelen_schema()
    await register_kaelen_commands()

    # Inisialisasi Pyrogram & PyTgCalls di dalam event loop aktif
    assistant = Client(
        name="kaelen_assistant",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    )
    assistant.on_raw_update()(_enforce_os_listener_mute)

    call_py = PyTgCalls(assistant)
    call_py.on_update()(on_tgcalls_update)

    await assistant.start()
    me = await assistant.get_me()
    _assistant_user_id = me.id
    await call_py.start()
    logger.info(
        "Akun Asisten Kaelen (@%s / %s) & PyTgCalls aktif! MUSIC_VAULT_ID: %s",
        me.username or me.first_name,
        me.id,
        MUSIC_VAULT_ID,
    )

    _spawn_task(_poll_webapp_song_queue())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
