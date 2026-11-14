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


def _resolve_warehouse_channel() -> int | str | None:
    keys = (
        "MUSIC_CHANNEL_ID",
        "WAREHOUSE_CHANNEL_ID",
        "GUDANG_CHANNEL_ID",
        "MUSIC_WAREHOUSE_ID",
        "GUDANG_MUSIK_ID",
        "STORAGE_CHANNEL_ID",
        "DB_CHANNEL_ID",
    )
    for k in keys:
        val = getattr(cfg, k, None) or os.environ.get(k)
        if val:
            s = str(val).strip()
            if s.lstrip("-").isdigit():
                return int(s)
            return s
    return None


WAREHOUSE_CHANNEL_ID = _resolve_warehouse_channel()

bot = Bot(token=cfg.TOKEN_KAELEN)
dp = Dispatcher(storage=MemoryStorage())

ASSISTANT_SESSION = (
    getattr(cfg, "KAELEN_ASSISTANT_SESSION", None)
    or getattr(cfg, "ASSISTANT_SESSION", None)
    or getattr(cfg, "SESSION_ASSISTANT", None)
    or getattr(cfg, "KAELEN_SESSION_STRING", None)
    or getattr(cfg, "SESSION_STRING", None)
    or os.environ.get("SESSION_STRING")
    or os.environ.get("ASSISTANT_SESSION")
)
API_ID = int(getattr(cfg, "API_ID", 0) or os.environ.get("API_ID", 0))
API_HASH = str(getattr(cfg, "API_HASH", "") or os.environ.get("API_HASH", ""))

if ASSISTANT_SESSION:
    assistant = Client(
        name="kaelen_assistant",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=ASSISTANT_SESSION,
    )
else:
    assistant = Client(
        name="kaelen_assistant",
        api_id=API_ID,
        api_hash=API_HASH,
    )

call_py = PyTgCalls(assistant)


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
    is_local_file: bool = False


music_queue: deque[TrackItem] = deque()
current_track: TrackItem | None = None
is_paused: bool = False
_play_lock = asyncio.Lock()
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


# --- AKUN ASISTEN: BUKA OS OTOMATIS & AUTO-MUTE PENDENGAR (KECUALI OWNER & ASISTEN) ---
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
        logger.error("Akun asisten gagal membuka/mengatur OS: %s", e)
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


@assistant.on_raw_update()
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


# --- 1. PENCARIAN DI GUDANG CHANNEL MUSIK TELEGRAM ---
async def _search_warehouse_channel(query: str) -> dict | None:
    if not WAREHOUSE_CHANNEL_ID:
        return None
    try:
        async for msg in assistant.search_messages(chat_id=WAREHOUSE_CHANNEL_ID, query=query, limit=8):
            media_obj = msg.audio or msg.document or msg.voice
            if not media_obj:
                continue

            if msg.document and not msg.audio:
                fname = (msg.document.file_name or "").lower()
                mime = (msg.document.mime_type or "").lower()
                if not (mime.startswith("audio/") or fname.endswith((".mp3", ".m4a", ".flac", ".ogg", ".wav", ".opus"))):
                    continue

            raw_title = (
                getattr(msg.audio, "title", None)
                or getattr(msg.audio, "file_name", None)
                or getattr(msg.document, "file_name", None)
                or (msg.caption.splitlines()[0] if msg.caption else None)
                or query
            )
            performer = getattr(msg.audio, "performer", None)
            display_title = f"{raw_title} - {performer}" if (performer and performer.lower() not in raw_title.lower()) else raw_title
            for ext in (".mp3", ".m4a", ".flac", ".ogg", ".wav", ".opus"):
                if display_title.lower().endswith(ext):
                    display_title = display_title[:-len(ext)]

            duration_sec = getattr(msg.audio, "duration", None) or getattr(msg.voice, "duration", None)
            dest_path = os.path.join(CACHE_DIR, f"wh_{msg.id}_{int(datetime.utcnow().timestamp())}")
            downloaded_path = await assistant.download_media(msg, file_name=dest_path)

            if downloaded_path and os.path.exists(downloaded_path):
                _cleanup_old_cache(keep_path=downloaded_path)
                logger.info("Lagu ditemukan di Gudang Channel Musik: %s", display_title)
                return {
                    "title": display_title,
                    "stream_url": downloaded_path,
                    "webpage_url": msg.link or "",
                    "duration": _format_duration(duration_sec),
                    "is_local_file": True,
                }
    except Exception as e:
        logger.warning("Gagal mencari di gudang channel musik (%s): %s", WAREHOUSE_CHANNEL_ID, e)
    return None


# --- 2. PENCARIAN ONLINE (JIOSAAVN, PIPED, YOUTUBE, SOUNDCLOUD) ---
def _get_cookie_file_path() -> str | None:
    if os.path.exists("cookies.txt"):
        return "cookies.txt"
    env_cookies = os.environ.get("YT_COOKIES") or os.environ.get("YOUTUBE_COOKIES")
    if env_cookies and "youtube.com" in env_cookies:
        path = "/tmp/yt_cookies.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(env_cookies)
        return path
    return None


def _http_get_json(url: str, timeout: int = 8) -> dict | list | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _search_jiosaavn_sync(query: str) -> dict | None:
    encoded = urllib.parse.quote_plus(query)
    endpoints = [
        f"https://saavn.dev/api/search/songs?query={encoded}&limit=1",
        f"https://jiosaavn-api-privatecvc2.vercel.app/search/songs?query={encoded}&limit=1",
    ]
    for api_url in endpoints:
        try:
            data = _http_get_json(api_url, timeout=8)
            if not isinstance(data, dict):
                continue
            results = (data.get("data") or {}).get("results") or []
            if not results:
                continue
            song = results[0]
            dl_urls = song.get("downloadUrl") or []
            if not dl_urls:
                continue
            best_url = dl_urls[-1].get("url") or dl_urls[-1].get("link")
            if not best_url:
                continue

            artists = ", ".join(
                a.get("name", "") for a in ((song.get("artists") or {}).get("primary") or []) if a.get("name")
            )
            title = html.unescape(song.get("name") or query)
            full_title = f"{title} - {artists}" if artists else title
            return {
                "title": full_title,
                "stream_url": best_url,
                "webpage_url": song.get("url") or "",
                "duration": _format_duration(song.get("duration")),
                "is_local_file": False,
            }
        except Exception:
            continue
    return None


def _search_piped_sync(query: str) -> dict | None:
    encoded = urllib.parse.quote_plus(query)
    instances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.moomoo.me",
        "https://api.piped.private.coffee",
    ]
    for base in instances:
        try:
            search_data = _http_get_json(f"{base}/search?q={encoded}&filter=music_songs", timeout=7)
            items = (search_data or {}).get("items") or []
            if not items:
                continue
            vid_url = items[0].get("url", "")
            vid_id = vid_url.split("v=")[-1].split("&")[0] if "v=" in vid_url else ""
            if not vid_id:
                continue

            stream_data = _http_get_json(f"{base}/streams/{vid_id}", timeout=7)
            audio_streams = (stream_data or {}).get("audioStreams") or []
            if not audio_streams:
                continue
            audio_streams.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
            best_audio = audio_streams[0].get("url")
            if not best_audio:
                continue

            return {
                "title": stream_data.get("title") or items[0].get("title") or query,
                "stream_url": best_audio,
                "webpage_url": f"https://www.youtube.com/watch?v={vid_id}",
                "duration": _format_duration(stream_data.get("duration")),
                "is_local_file": False,
            }
        except Exception:
            continue
    return None


def _extract_ytdlp_sync(target: str, cookie_file: str | None = None) -> dict | None:
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "source_address": "0.0.0.0",
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "android", "mweb"],
            }
        },
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)
        if not info:
            return None
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                return None
            info = entries[0]

        stream_url = info.get("url")
        if not stream_url:
            for fmt in reversed(info.get("formats", [])):
                if fmt.get("acodec") != "none" and fmt.get("url"):
                    stream_url = fmt["url"]
                    break

        if not stream_url:
            return None

        return {
            "title": info.get("title") or target,
            "stream_url": stream_url,
            "webpage_url": info.get("webpage_url") or "",
            "duration": _format_duration(info.get("duration")),
            "is_local_file": False,
        }


def _extract_online_sync(query: str) -> dict | None:
    is_url = query.startswith(("http://", "https://"))
    cookie_file = _get_cookie_file_path()

    if is_url or cookie_file:
        try:
            target = query if is_url else f"ytsearch1:{query}"
            res = _extract_ytdlp_sync(target, cookie_file)
            if res:
                return res
        except Exception as e:
            logger.warning("yt-dlp primary gagal untuk '%s': %s", query, e)

    if not is_url:
        saavn_res = _search_jiosaavn_sync(query)
        if saavn_res:
            return saavn_res

        piped_res = _search_piped_sync(query)
        if piped_res:
            return piped_res

        for fallback_target in (f"ytsearch1:{query}", f"scsearch1:{query}"):
            try:
                res = _extract_ytdlp_sync(fallback_target, cookie_file)
                if res:
                    return res
            except Exception as e:
                logger.warning("Pencarian fallback gagal (%s): %s", fallback_target, e)

    return None


async def resolve_audio_track(query: str) -> dict | None:
    is_url = query.startswith(("http://", "https://"))
    # Prioritas 1: Cek Gudang Channel Musik terlebih dahulu
    if not is_url:
        wh_res = await _search_warehouse_channel(query)
        if wh_res:
            return wh_res

    # Prioritas 2: Cari dari sumber online
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract_online_sync, query)


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
            source_badge = "📀 Gudang Koleksi" if next_track.is_local_file else "🌐 Streaming"
            await _send_kaelen_msg(
                f"🎧 <b>Now Spinning — Kaelen Booth</b> ({source_badge})\n"
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


@call_py.on_update()
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
        is_local_file=info.get("is_local_file", False),
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
    global _assistant_user_id
    await db.init_db()
    await ensure_kaelen_schema()
    await register_kaelen_commands()

    await assistant.start()
    me = await assistant.get_me()
    _assistant_user_id = me.id
    await call_py.start()
    logger.info(
        "Akun Asisten Kaelen (@%s / %s) & PyTgCalls aktif! Gudang Musik: %s",
        me.username or me.first_name,
        me.id,
        WAREHOUSE_CHANNEL_ID or "Belum diset",
    )

    _spawn_task(_poll_webapp_song_queue())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
