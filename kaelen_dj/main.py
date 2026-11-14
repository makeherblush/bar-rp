import html
import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import yt_dlp
from pyrogram import Client
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
OWNER_ID = cfg.OWNER_ID
SONG_REQUEST_COST = 10

# --- BOT & USERBOT CLIENT ---
bot = Bot(token=cfg.TOKEN_KAELEN)
dp = Dispatcher(storage=MemoryStorage())

# Session string / credentials Pyrogram untuk stream audio ke Voice Chat
SESSION_STRING = getattr(cfg, "KAELEN_SESSION_STRING", None) or getattr(cfg, "SESSION_STRING", None)
API_ID = int(getattr(cfg, "API_ID", 0))
API_HASH = str(getattr(cfg, "API_HASH", ""))

if SESSION_STRING:
    app = Client(
        name="kaelen_dj_userbot",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    )
else:
    app = Client(
        name="kaelen_dj_userbot",
        api_id=API_ID,
        api_hash=API_HASH,
    )

call_py = PyTgCalls(app)


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


music_queue: deque[TrackItem] = deque()
current_track: TrackItem | None = None
is_paused: bool = False
_play_lock = asyncio.Lock()


def _mention(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'


def _format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "Live / ∞"
    sec = int(seconds)
    mins, rem = divmod(sec, 60)
    hrs, mins = divmod(mins, 60)
    if hrs:
        return f"{hrs}:{mins:02d}:{rem:02d}"
    return f"{mins}:{rem:02d}"


async def react_msg(chat_id: int, message_id: int, emoji: str = "🎧"):
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        pass


async def _schedule_delete(chat_id: int, message_ids: list[int], delay: int = 35):
    async def _worker():
        await asyncio.sleep(delay)
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    asyncio.create_task(_worker())


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


async def _send_kaelen_msg(text: str, thread_id: int | None = None):
    attempts = [thread_id, None] if thread_id else [None]
    for tid in attempts:
        kwargs = {"message_thread_id": tid} if tid else {}
        try:
            return await bot.send_message(
                chat_id=GROUP_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                **kwargs,
            )
        except Exception as e:
            if tid and "thread not found" in str(e).lower():
                continue
            logger.warning("Gagal kirim pesan Kaelen: %s", e)
            return None


def _extract_audio_sync(query: str) -> dict | None:
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch1",
        "extract_flat": False,
        "geo_bypass": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
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
                "title": info.get("title") or query,
                "stream_url": stream_url,
                "webpage_url": info.get("webpage_url") or "",
                "duration": _format_duration(info.get("duration")),
            }
    except Exception as e:
        logger.error("yt-dlp extract error untuk '%s': %s", query, e)
        return None


async def extract_audio_info(query: str) -> dict | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract_audio_sync, query)


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
            stream = MediaStream(
                next_track.stream_url,
                audio_parameters=AudioQuality.HIGH,
                video_flags=MediaStream.Flags.IGNORE,
            )
            await call_py.play(GROUP_ID, stream)

            link_part = (
                f'<a href="{html.escape(next_track.webpage_url)}">{html.escape(next_track.title)}</a>'
                if next_track.webpage_url
                else f"<b>{html.escape(next_track.title)}</b>"
            )
            await _send_kaelen_msg(
                f"🎧 <b>Now Spinning — Kaelen Booth</b>\n"
                f"• Lagu: {link_part} (<code>{next_track.duration}</code>)\n"
                f"• Permintaan: {_mention(next_track.requester_id, next_track.requester_name)}",
                thread_id=next_track.thread_id,
            )
        except Exception as e:
            logger.error("PyTgCalls play error: %s", e)
            await _send_kaelen_msg(
                f"⚠️ Kaelen gagal memutar <b>{html.escape(next_track.title)}</b> di Voice Chat. Pastikan <b>Obrolan Suara (Voice Chat)</b> grup sedang aktif!\n"
                f"<i>({html.escape(str(e))})</i>",
                thread_id=next_track.thread_id,
            )
            current_track = None
            if music_queue:
                asyncio.create_task(_play_next_in_queue())


@call_py.on_update()
async def on_tgcalls_update(_, update):
    # Deteksi otomatis ketika audio selesai diputar agar lanjut ke lagu berikutnya
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
    info = await extract_audio_info(query)
    if not info:
        if db_req_id:
            await _mark_db_song_status(db_req_id, "failed")
        await _send_kaelen_msg(
            f"🥀 Kaelen tidak menemukan piringan hitam untuk <b>{html.escape(query)}</b>.",
            thread_id=thread_id,
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
    )
    music_queue.append(track)

    if current_track is None:
        await _play_next_in_queue()
    elif announce_queue:
        pos = len(music_queue)
        msg = await _send_kaelen_msg(
            f"💿 <b>Ditambahkan ke Antrean (#{pos})</b>\n"
            f"• Lagu: <b>{html.escape(track.title)}</b> (<code>{track.duration}</code>)\n"
            f"• Oleh: {_mention(uid, requester_name)}",
            thread_id=thread_id,
        )
        if msg:
            await _schedule_delete(GROUP_ID, [msg.message_id], delay=35)
    return True


# --- WORKER POLLING ANTREAN LAGU DARI MINI APP JUKEBOX ---
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
                logger.info("Menerima request lagu dari Mini App: %s (oleh %s)", title, rname)
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


# --- COMMANDS GRUP KAELEN DJ ---
@dp.message(Command("play", "reqsong"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_play_song(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        err = await message.reply(
            "🎶 Format: <code>/play Judul Lagu - Penyanyi</code> atau link YouTube (<b>10 VC</b>, Gratis VIP).",
            parse_mode=ParseMode.HTML,
        )
        await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=20)
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
            is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            cost = 0 if is_vip else SONG_REQUEST_COST
            coins = (row["coins"] or 0) if row else 0

            if coins < cost:
                err = await message.reply(
                    f"Saldo tidak cukup untuk memutar lagu (butuh <b>{cost} VC</b>, saldo kamu: <b>{coins} VC</b>).",
                    parse_mode=ParseMode.HTML,
                )
                await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=20)
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
    await _schedule_delete(message.chat.id, [message.message_id, search_msg.message_id], delay=4 if ok else 15)


@dp.message(Command("np", "nowplaying"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_now_playing(message: types.Message):
    if not current_track:
        err = await message.reply("🔇 Booth DJ sedang hening. Ketik <code>/play judul lagu</code> untuk memutar musik.", parse_mode=ParseMode.HTML)
        await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
        return

    state = "⏸ Dijeda" if is_paused else "▶️ Sedang Diputar"
    msg = await message.reply(
        f"🎧 <b>{state}</b>\n"
        f"• Lagu: <b>{html.escape(current_track.title)}</b> (<code>{current_track.duration}</code>)\n"
        f"• Request oleh: {_mention(current_track.requester_id, current_track.requester_name)}\n"
        f"• Antrean berikutnya: <b>{len(music_queue)}</b> lagu",
        parse_mode=ParseMode.HTML,
    )
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=35)


@dp.message(Command("queue"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_music_queue(message: types.Message):
    if not current_track and not music_queue:
        err = await message.reply("📭 Daftar antrean lagu kosong.")
        await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
        return

    lines = []
    if current_track:
        lines.append(f"▶️ <b>Sekarang:</b> {html.escape(current_track.title)} ({html.escape(current_track.requester_name)})")
    for idx, t in enumerate(list(music_queue)[:10], start=1):
        lines.append(f"{idx}. {html.escape(t.title)} — <i>{html.escape(t.requester_name)}</i>")

    msg = await message.reply("🎶 <b>Daftar Putar Booth Kaelen</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML)
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=40)


@dp.message(Command("skip"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_skip_song(message: types.Message):
    if not current_track:
        err = await message.reply("Tidak ada lagu yang sedang diputar.")
        await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
        return

    uid = message.from_user.id
    if uid != OWNER_ID and uid != current_track.requester_id:
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status not in ("administrator", "creator"):
            err = await message.reply("Hanya pemesan lagu ini atau Admin yang bisa melewati lagu.")
            await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
            return

    skipped_title = current_track.title
    await react_msg(message.chat.id, message.message_id, "⏭️")
    msg = await message.reply(f"⏭️ Kaelen mengangkat jarum gramofon dan melewati <b>{html.escape(skipped_title)}</b>.", parse_mode=ParseMode.HTML)
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=20)
    await _play_next_in_queue()


@dp.message(Command("pause"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_pause_song(message: types.Message):
    global is_paused
    if not current_track or is_paused:
        return
    try:
        await call_py.pause(GROUP_ID)
        is_paused = True
        msg = await message.reply("⏸️ Kaelen menjeda musik di ruang lounge.")
        await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=20)
    except Exception as e:
        await message.reply(f"Gagal menjeda: {e}")


@dp.message(Command("resume"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_resume_song(message: types.Message):
    global is_paused
    if not current_track or not is_paused:
        return
    try:
        await call_py.resume(GROUP_ID)
        is_paused = False
        msg = await message.reply("▶️ Kaelen melanjutkan alunan musik.")
        await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=20)
    except Exception as e:
        await message.reply(f"Gagal melanjutkan: {e}")


@dp.message(Command("stop"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_stop_music(message: types.Message):
    global current_track, is_paused
    uid = message.from_user.id
    if uid != OWNER_ID:
        member = await bot.get_chat_member(message.chat.id, uid)
        if member.status not in ("administrator", "creator"):
            err = await message.reply("Perintah <code>/stop</code> hanya untuk Admin atau Owner.", parse_mode=ParseMode.HTML)
            await _schedule_delete(message.chat.id, [message.message_id, err.message_id], delay=15)
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
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=25)


@dp.message(Command("vibe"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dj_vibe(message: types.Message):
    msg = await message.reply(
        "🕯️ <i>Kaelen menyesuaikan equalizer di meja DJ, membiarkan dentuman bass lembut berpadu dengan cahaya temaram The Velvet Hour...</i>",
        parse_mode=ParseMode.HTML,
    )
    await _schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=35)


async def register_kaelen_commands():
    cmds = [
        BotCommand(command="play", description="Putar lagu di Voice Chat (10 VC / Gratis VIP)"),
        BotCommand(command="np", description="Lihat lagu yang sedang diputar"),
        BotCommand(command="queue", description="Lihat daftar antrean lagu DJ"),
        BotCommand(command="skip", description="Lewati lagu saat ini"),
        BotCommand(command="pause", description="Jeda musik di Voice Chat"),
        BotCommand(command="resume", description="Lanjutkan musik yang dijeda"),
        BotCommand(command="stop", description="[Admin] Hentikan musik & bersihkan antrean"),
        BotCommand(command="vibe", description="Atur atmosfer musik lounge"),
    ]
    await bot.set_my_commands(cmds, scope=BotCommandScopeAllGroupChats())


async def main():
    await db.init_db()
    await ensure_kaelen_schema()
    await register_kaelen_commands()

    await app.start()
    await call_py.start()
    logger.info("Kaelen Pyrogram & PyTgCalls aktif!")

    asyncio.create_task(_poll_webapp_song_queue())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
