import os
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Dispatcher, F, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonWebApp,
    WebAppInfo,
)

import shared.database as db
from julian_bartender.helpers import (
    bot,
    GROUP_ID,
    VIP_DEFAULT_TAG,
    WEBAPP_DIRECT_URL,
    SHIFT_MAX_MINUTES,
    ensure_julian_schema,
    set_guest_tag,
    restore_default_guest_tag,
    update_member_shift_commands,
)
from julian_bartender.vip_booth import router as vip_booth_router
from julian_bartender.bar_service import router as bar_service_router
from julian_bartender.games import router as games_router
from julian_bartender.shifts import router as shifts_router

try:
    from hans_concierge.webapp_server import start_webapp_server
except Exception as e:
    start_webapp_server = None
    logging.warning("Gagal import start_webapp_server: %s", e)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("julian_bartender")

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(vip_booth_router)
dp.include_router(bar_service_router)
dp.include_router(games_router)
dp.include_router(shifts_router)

_last_chat_earn: dict[int, datetime] = {}


async def _sync_member_tags_worker():
    await asyncio.sleep(5)
    while True:
        try:
            now = datetime.utcnow()
            cutoff_shift = now - timedelta(minutes=SHIFT_MAX_MINUTES)
            async with db.pool.acquire() as conn:
                expired_shifts = await conn.fetch(
                    "DELETE FROM active_shifts WHERE started_at <= $1 RETURNING user_id",
                    cutoff_shift,
                )
                for r in expired_shifts:
                    await restore_default_guest_tag(conn, GROUP_ID, r["user_id"])
                    await update_member_shift_commands(r["user_id"], None)

                active_vips = await conn.fetch("""
                    SELECT u.user_id
                    FROM users u
                    LEFT JOIN active_shifts s ON s.user_id = u.user_id
                    WHERE u.is_vip = TRUE
                      AND u.vip_until > $1
                      AND s.user_id IS NULL
                """, now)
                for r in active_vips:
                    await set_guest_tag(GROUP_ID, r["user_id"], VIP_DEFAULT_TAG)

                expired_vips = await conn.fetch("""
                    UPDATE users
                    SET is_vip = FALSE
                    WHERE is_vip = TRUE AND vip_until <= $1
                    RETURNING user_id
                """, now)
                for r in expired_vips:
                    in_shift = await conn.fetchval(
                        "SELECT 1 FROM active_shifts WHERE user_id = $1",
                        r["user_id"],
                    )
                    if not in_shift:
                        await set_guest_tag(GROUP_ID, r["user_id"], None)
        except Exception as e:
            logger.warning("Tag sync worker skip: %s", e)

        await asyncio.sleep(30)


@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def passive_rp_coin_earner(message: types.Message):
    if not message.from_user or message.from_user.is_bot:
        return
    if message.text.startswith("/"):
        return

    uid = message.from_user.id
    now = datetime.utcnow()
    last = _last_chat_earn.get(uid)
    earn_delta = 1 if (len(message.text.split()) >= 3 and (not last or (now - last).total_seconds() >= 60)) else 0
    if earn_delta:
        _last_chat_earn[uid] = now

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, full_name, coins, charm_points, last_thread_id)
            VALUES ($1, $2, $3, $4, 0, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                username = COALESCE(EXCLUDED.username, users.username),
                full_name = EXCLUDED.full_name,
                coins = users.coins + $6,
                last_thread_id = COALESCE($5, users.last_thread_id);
        """, uid, message.from_user.username, message.from_user.full_name, 50 + earn_delta, message.message_thread_id, earn_delta)


async def register_julian_commands():
    group_cmds = [
        BotCommand(command="menu", description="Buka Buku Menu & Jukebox Interaktif"),
        BotCommand(command="gift", description="Kirim hadiah mewah bergambar +Charm"),
        BotCommand(command="order", description="Pesan minuman atau buka daftar minuman"),
        BotCommand(command="eat", description="Pesan hidangan dapur atau buka menu makanan"),
        BotCommand(command="treat", description="Traktir tamu lain +5 Charm untuk penerima"),
        BotCommand(command="booth", description="VIP Buka topik VIP Booth eksklusif"),
        BotCommand(command="invitebooth", description="VIP Undang tamu ke topik VIP Booth kamu"),
        BotCommand(command="kickbooth", description="VIP Cabut akses tamu dari VIP Booth kamu"),
        BotCommand(command="closebooth", description="VIP Tutup topik VIP Booth aktif"),
        BotCommand(command="slot", description="Putar mesin slot bar 10-100 VC"),
        BotCommand(command="dart", description="Duel lempar dart 1v1 berhadiah VC"),
        BotCommand(command="dice", description="Duel dadu 1v1 berhadiah VC"),
        BotCommand(command="mystery", description="Buka Velvet Mystery Box 40 VC"),
        BotCommand(command="bill", description="Cek saldo VC, Charm & status VIP"),
        BotCommand(command="topcharm", description="Lihat Top 10 Tamu Paling Memesona"),
        BotCommand(command="apply", description="Ambil shift kerja waiter/bartender/host/dj"),
        BotCommand(command="myshift", description="Cek sisa waktu & progres layanan shift"),
        BotCommand(command="endshift", description="Selesaikan shift & cairkan upah VC"),
        BotCommand(command="mix", description="Tugas Bartender: racik minuman"),
        BotCommand(command="sober", description="Tugas Bartender: sadarkan tamu"),
        BotCommand(command="welcome", description="Tugas Waiter: sambut tamu baru"),
        BotCommand(command="dish", description="Tugas Waiter: antar hidangan"),
        BotCommand(command="ambience", description="Tugas Host: atur suasana lounge"),
        BotCommand(command="toastall", description="Tugas Host: ajak seluruh tamu bersulang"),
    ]
    private_cmds = [
        BotCommand(command="start", description="Sapaan Bartender & Panduan Buku Menu"),
        BotCommand(command="menu", description="Buka Buku Menu & Jukebox Interaktif"),
    ]

    await bot.set_my_commands(group_cmds, scope=BotCommandScopeAllGroupChats())
    if GROUP_ID:
        try:
            await bot.set_my_commands(group_cmds, scope=BotCommandScopeChat(chat_id=GROUP_ID))
        except Exception as e:
            logger.warning("Gagal set command scope chat GROUP_ID: %s", e)

    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())

    if WEBAPP_DIRECT_URL.startswith("https://") and not WEBAPP_DIRECT_URL.startswith("https://t.me/"):
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🍸 Menu",
                    web_app=WebAppInfo(url=WEBAPP_DIRECT_URL),
                )
            )
            logger.info("MenuButtonWebApp terpasang ke: %s", WEBAPP_DIRECT_URL)
        except Exception as e:
            logger.warning("Gagal pasang MenuButtonWebApp: %s", e)
    else:
        logger.warning("MINIAPP_MENU_URL di Railway harus berupa URL https:// domain Railway, saat ini: %s", WEBAPP_DIRECT_URL)


async def main():
    await db.init_db()
    await ensure_julian_schema()

    if start_webapp_server is not None:
        try:
            await start_webapp_server()
            logger.info("Web App server aktif di 0.0.0.0:%s", os.environ.get("PORT", "8080"))
        except Exception as e:
            logger.exception("Gagal menjalankan Web App server: %s", e)

    await register_julian_commands()
    await bot.delete_webhook(drop_pending_updates=False)
    asyncio.create_task(_sync_member_tags_worker())
    logger.info("Julian Vance bot mulai polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
