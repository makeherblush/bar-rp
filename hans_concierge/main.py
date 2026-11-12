import html
import asyncio
import logging

from aiogram import Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import OWNER_ID
from hans_concierge.helpers import (
    bot, ensure_hans_schema, is_staff_or_owner, log_wallet_tx, main_lobby_kb
)
from hans_concierge.gate_wallet import router as gate_wallet_router
from hans_concierge.shop_gift import router as shop_gift_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(gate_wallet_router)
dp.include_router(shop_gift_router)

# --- PANEL ADMIN & OWNER DI PRIVATE CHAT ---
@dp.message(Command("admin"), F.chat.type == "private")
async def cmd_admin_panel(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id):
        return
    text = (
        "🛡️ <b>PANEL KONTROL STAFF & OWNER — HANS CONCIERGE</b>\n\n"
        "• <code>/addshop @username Nama Toko</code> — Daftarkan lapak partner baru\n"
        "• <code>/delshop ID_Toko</code> — Hapus lapak partner\n"
        "• <code>/givevc @username jumlah</code> — Suntik saldo VC ke tamu\n"
        "• <code>/addadmin @username</code> — Angkat staf Admin baru (Owner)\n"
        "• <code>/deladmin @username</code> — Cabut akses Admin (Owner)"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(Command("addshop"), F.chat.type == "private")
async def cmd_addshop(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].startswith("@"):
        return await message.answer("Format: <code>/addshop @username Nama Toko</code>", parse_mode=ParseMode.HTML)

    uname = parts[1].lstrip("@").lower()
    shop_name = parts[2].strip()

    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id, username FROM users WHERE LOWER(username) = $1", uname)
        if not user:
            return await message.answer("User belum terdaftar di database Hans.")
        shop_id = await conn.fetchval("""
            INSERT INTO partner_shops (owner_id, owner_username, shop_name)
            VALUES ($1, $2, $3) RETURNING id
        """, user["user_id"], user["username"], shop_name)

    await message.answer(f"✅ Lapak <b>{html.escape(shop_name)}</b> (ID: <code>{shop_id}</code>) berhasil dibuat untuk @{uname}!", parse_mode=ParseMode.HTML)

@dp.message(Command("delshop"), F.chat.type == "private")
async def cmd_delshop(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await message.answer("Format: <code>/delshop ID_Toko</code>", parse_mode=ParseMode.HTML)
    shop_id = int(parts[1])
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM shop_items WHERE shop_id = $1", shop_id)
        await conn.execute("DELETE FROM partner_shops WHERE id = $1", shop_id)
    await message.answer(f"🗑️ Lapak ID <code>{shop_id}</code> beserta seluruh dagangannya telah dihapus.", parse_mode=ParseMode.HTML)

@dp.message(Command("givevc"), F.chat.type == "private")
async def cmd_givevc(message: types.Message):
    if not await is_staff_or_owner(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 3 or not parts[1].startswith("@") or not parts[2].lstrip("-").isdigit():
        return await message.answer("Format: <code>/givevc @username jumlah</code>", parse_mode=ParseMode.HTML)

    uname = parts[1].lstrip("@").lower()
    amount = int(parts[2])
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE LOWER(username) = $1", uname)
        if not user:
            return await message.answer("User tidak ditemukan.")
        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", amount, user["user_id"])
        await log_wallet_tx(conn, user["user_id"], amount, "Penyesuaian saldo oleh Staff/Owner")

    await message.answer(f"✅ Berhasil menambahkan <b>{amount} VC</b> ke <b>{html.escape(user['full_name'])}</b>.", parse_mode=ParseMode.HTML)

@dp.message(Command("addadmin"), F.chat.type == "private")
async def cmd_addadmin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].startswith("@"):
        return await message.answer("Format: <code>/addadmin @username</code>", parse_mode=ParseMode.HTML)
    uname = parts[1].lstrip("@").lower()
    async with db.pool.acquire() as conn:
        res = await conn.execute("UPDATE users SET is_admin = TRUE WHERE LOWER(username) = $1", uname)
    await message.answer(f"✅ @{uname} sekarang memiliki akses Staf Admin ({res}).")

@dp.message(Command("deladmin"), F.chat.type == "private")
async def cmd_deladmin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].startswith("@"):
        return await message.answer("Format: <code>/deladmin @username</code>", parse_mode=ParseMode.HTML)
    uname = parts[1].lstrip("@").lower()
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_admin = FALSE WHERE LOWER(username) = $1", uname)
    await message.answer(f"🗑️ Akses Admin @{uname} telah dicabut.")

async def register_hans_commands():
    private_cmds = [
        BotCommand(command="start", description="Buka Lobi Resepsionis & Pintu Masuk Bar"),
        BotCommand(command="daily", description="Klaim Absen Harian (+20 VC)"),
        BotCommand(command="admin", description="[Staff/Owner] Panel Kontrol Bar & Lapak"),
    ]
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())

async def main():
    await db.init_db()
    await ensure_hans_schema()
    await register_hans_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
