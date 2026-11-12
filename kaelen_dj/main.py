import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Dispatcher
from aiogram.types import (
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
)
from pyrogram import Client
from pytgcalls import PyTgCalls, filters

import shared.database as db
from shared.config import API_ID, API_HASH, SESSION_STRING, GROUP_ID
from kaelen_dj.helpers import (
    bot, ALL_GROUP_COMMANDS, SHIFT_MAX_MINUTES,
    ensure_kaelen_schema, sync_dj_member_commands
)
import kaelen_dj.audio_engine as engine
from kaelen_dj.handlers import router as kaelen_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()
dp.include_router(kaelen_router)

# --- WORKER SINKRONISASI COMMAND DJ OTOMATIS DI MENU / ---
async def dj_command_sync_loop():
    known_active_djs = set()
    while True:
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_id FROM active_shifts WHERE role = 'dj' AND started_at > $1",
                    datetime.utcnow() - timedelta(minutes=SHIFT_MAX_MINUTES),
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

async def register_kaelen_commands():
    private_cmds = [
        BotCommand(command="start", description="Mulai sesi dengan kurator musik Kaelen"),
        BotCommand(command="myearphone", description="Dengarkan lagu pribadi — Contoh: /myearphone Sunsetz - CAS"),
    ]
    await bot.set_my_commands(ALL_GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())

async def main():
    await db.init_db()
    await ensure_kaelen_schema()
    await register_kaelen_commands()
    asyncio.create_task(dj_command_sync_loop())

    engine.assistant = Client(
        name="kaelen_assistant",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
        in_memory=True,
    )
    engine.call_py = PyTgCalls(engine.assistant)

    @engine.call_py.on_update(filters.stream_end)
    async def on_stream_end_handler(_, update):
        if update.chat_id == GROUP_ID:
            token_snapshot = engine.state["current_stream_token"]
            await asyncio.sleep(0.5)
            await engine.play_next_song(expected_token=token_snapshot, allow_radio_fallback=True)

    await engine.assistant.start()
    async for _ in engine.assistant.get_dialogs():
        pass
    await engine.call_py.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
