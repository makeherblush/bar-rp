import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Dispatcher
from aiogram.types import BotCommandScopeAllGroupChats
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import GROUP_ID
from julian_bartender.helpers import (
    bot, hans_bot, BASE_GROUP_COMMANDS,
    SHIFT_MAX_MINUTES, SHIFT_REQUIRED_ACTIONS, SHIFT_REWARD_VC,
    ensure_julian_schema, update_member_shift_commands,
    schedule_delete, is_staff_or_owner, log_wallet_tx
)
from julian_bartender.guest_social import router as guest_social_router, active_dice_challenges
from julian_bartender.shifts_mod import router as shifts_mod_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()
dp.include_router(guest_social_router)
dp.include_router(shifts_mod_router)

# --- BACKGROUND WORKER: PENGAWAS TAMU PASIF, SHIFT & DICE EXPIRE ---
async def idle_watcher_loop():
    while True:
        await asyncio.sleep(60)
        try:
            async with db.pool.acquire() as conn:
                now = datetime.utcnow()

                # 1. Bersihkan tantangan dadu kedaluwarsa (> 2 menit)
                expired_duels = [k for k, v in active_dice_challenges.items() if (now - v["created_at"]).total_seconds() > 120]
                for k in expired_duels:
                    active_dice_challenges.pop(k, None)

                # 2. Bersihkan nama booth jika VIP telah habis
                await conn.execute("""
                    UPDATE users SET vip_booth_name = NULL
                    WHERE vip_booth_name IS NOT NULL AND (is_vip = FALSE OR vip_until <= $1)
                """, now)

                # 3. Cek Shift Kerja Melebihi 20 Menit
                expired_shifts = await conn.fetch(
                    "SELECT role, user_id, actions_count FROM active_shifts WHERE started_at <= $1",
                    now - timedelta(minutes=SHIFT_MAX_MINUTES)
                )
                for sh in expired_shifts:
                    await conn.execute("DELETE FROM active_shifts WHERE user_id = $1", sh["user_id"])
                    await update_member_shift_commands(sh["user_id"], None)
                    if sh["actions_count"] >= SHIFT_REQUIRED_ACTIONS:
                        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", SHIFT_REWARD_VC, sh["user_id"])
                        await log_wallet_tx(conn, sh["user_id"], SHIFT_REWARD_VC, f"Upah Shift {sh['role'].upper()} (Otomatis 20m)")
                        try:
                            await bot.send_message(
                                GROUP_ID,
                                f"💼 <b>SHIFT {SHIFT_MAX_MINUTES} MENIT SELESAI — UPAH {SHIFT_REWARD_VC} VC CAIR!</b>\n\n"
                                f"Waktu shift untuk posisi <b>{sh['role'].upper()}</b> telah berakhir. "
                                f"Upah <b>+{SHIFT_REWARD_VC} VC</b> otomatis ditransfer ke dompet staf!",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
                    else:
                        try:
                            await bot.send_message(
                                GROUP_ID,
                                f"⏰ <b>SHIFT {SHIFT_MAX_MINUTES} MENIT BERAKHIR</b>\n\n"
                                f"Waktu shift <b>{sh['role'].upper()}</b> telah habis (layanan tercapai {sh['actions_count']}/{SHIFT_REQUIRED_ACTIONS}).",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass

                # 4. Cek Tamu Pasif (Idle 60m / VIP 120m)
                guests = await conn.fetch(
                    "SELECT user_id, full_name, is_vip, vip_until, last_active, warned_idle FROM users WHERE is_in_bar = TRUE"
                )
                for g in guests:
                    uid = g["user_id"]
                    if await is_staff_or_owner(uid):
                        continue

                    is_vip = bool(g["is_vip"] and g["vip_until"] and g["vip_until"] > now)
                    limit_mins = 120 if is_vip else 60
                    warn_mins = limit_mins - 10
                    idle_mins = (now - g["last_active"]).total_seconds() / 60

                    if idle_mins >= limit_mins:
                        await conn.execute("UPDATE users SET is_in_bar = FALSE, warned_idle = FALSE, vip_booth_name = NULL WHERE user_id = $1", uid)
                        try:
                            await hans_bot.ban_chat_member(GROUP_ID, uid)
                            await hans_bot.unban_chat_member(GROUP_ID, uid)
                            await bot.send_message(
                                GROUP_ID,
                                f"🚪 <i>Bouncer Hans mengantar <b>{g['full_name']}</b> yang tertidur di sudut meja keluar pintu mahoni. "
                                f"Saldo koin dan hadiah tetap tersimpan aman.</i>",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass
                    elif idle_mins >= warn_mins and not g["warned_idle"]:
                        await conn.execute("UPDATE users SET warned_idle = TRUE WHERE user_id = $1", uid)
                        warn_msg = await bot.send_message(
                            GROUP_ID,
                            f"🕯️ <i>Waitress Clara menyentuh bahu <a href='tg://user?id={uid}'>{g['full_name']}</a> dengan lembut:</i>\n\n"
                            f"<b>\"Permisi, meja ini akan segera dirapikan dalam 10 menit jika tidak ada aktivitas. Ketik obrolan atau <code>/checkin</code> jika masih bersantai.\"</b>",
                            parse_mode=ParseMode.HTML
                        )
                        asyncio.create_task(schedule_delete(warn_msg, 120))
        except Exception as e:
            logging.error(f"Idle watcher error: {e}")

async def register_julian_commands():
    await bot.set_my_commands(BASE_GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())

async def main():
    await db.init_db()
    await ensure_julian_schema()
    await register_julian_commands()
    asyncio.create_task(idle_watcher_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
