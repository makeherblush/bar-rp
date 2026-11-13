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
    bot, ensure_hans_schema, is_staff_or_owner, log_wallet_tx,
    get_bar_setting, set_bar_setting
)
from hans_concierge.gate_wallet import router as gate_wallet_router
from hans_concierge.shop_gift import router as shop_gift_router
from hans_concierge.confess_pm import router as confess_pm_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher(storage=MemoryStorage())
dp.include_router(gate_wallet_router)
dp.include_router(shop_gift_router)
dp.include_router(confess_pm_router)

# --- PANEL ADMIN & OWNER DI PRIVATE CHAT ---
@dp.message(Command("admin"), F.chat.type == "private")
async def cmd_admin_panel(message: types.Message):
    user_id = message.from_user.id
    if not await is_staff_or_owner(user_id):
        return

    is_owner = (user_id == OWNER_ID)
    cur_pw = await get_bar_setting("door_password")
    pw_status = f"<code>{html.escape(cur_pw)}</code> (Aktif)" if cur_pw else "<i>Nonaktif</i>"

    if is_owner:
        text = (
            "👑 <b>PANEL KONTROL UTAMA — OWNER THE VELVET HOUR</b>\n\n"
            f"🔐 <b>Password Pintu Masuk:</b> {pw_status}\n\n"
            "• <code>/setpw katasandi</code> — Pasang / ganti password pintu bar\n"
            "• <code>/delpw</code> — Hapus / matikan password pintu bar\n"
            "• <code>/setch -100xxxx</code> — Set ID Channel untuk #confess & #pm\n"
            "• <code>/addshop @username Nama Toko</code> — Daftarkan lapak partner baru\n"
            "• <code>/delshop ID_Toko</code> — Hapus lapak partner\n"
            "• <code>/givevc @username jumlah</code> — Suntik saldo VC ke tamu\n"
            "• <code>/addadmin @username</code> — Angkat Staf Admin baru\n"
            "• <code>/deladmin @username</code> — Cabut akses Staf Admin"
        )
    else:
        text = (
            "🛡️ <b>PANEL STAF ADMIN — THE VELVET HOUR</b>\n\n"
            "• <code>/addshop @username Nama Toko</code> — Daftarkan lapak partner baru\n"
            "• <code>/delshop ID_Toko</code> — Hapus lapak partner"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)

# --- GANTI / MATIKAN PASSWORD PINTU MASUK (KHUSUS OWNER) ---
@dp.message(Command("setpw"), F.chat.type == "private")
async def cmd_setpw(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        cur_pw = await get_bar_setting("door_password")
        status = f"<code>{html.escape(cur_pw)}</code>" if cur_pw else "<i>Belum dipasang</i>"
        return await message.answer(
            f"🔐 <b>Password Pintu Saat Ini:</b> {status}\n\n"
            f"Format ganti password: <code>/setpw katasandibaru</code>\n"
            f"Untuk mematikan password: <code>/delpw</code>",
            parse_mode=ParseMode.HTML
        )

    new_pw = parts[1].strip()
    await set_bar_setting("door_password", new_pw)
    await message.answer(
        f"✅ <b>Password pintu masuk bar berhasil diperbarui!</b>\n"
        f"Kata sandi baru: <code>{html.escape(new_pw)}</code>",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("delpw"), F.chat.type == "private")
async def cmd_delpw(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    await set_bar_setting("door_password", None)
    await message.answer("🔓 <b>Password pintu masuk bar dimatikan.</b> Tamu dengan simbol CN dapat langsung masuk.", parse_mode=ParseMode.HTML)

# --- ATUR CHANNEL CONFESS & PM (KHUSUS OWNER) ---
@dp.message(Command("setch"), F.chat.type == "private")
async def cmd_setch(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Format: <code>/setch -1001234567890</code> (atau <code>@usernamechannel</code>)", parse_mode=ParseMode.HTML)

    ch_val = parts[1].strip()
    await set_bar_setting("target_channel_id", ch_val)
    await message.answer(
        f"✅ Channel tujuan #confess & #pm berhasil diatur ke: <code>{html.escape(ch_val)}</code>\n"
        f"<i>Pastikan @HansVolkovVH_bot sudah dijadikan Admin di channel tersebut.</i>",
        parse_mode=ParseMode.HTML
    )

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
            return await message.answer("User belum terdaftar di database Hans (belum pernah membuka bot/masuk bar).")
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
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)

    parts = message.text.split()
    if len(parts) < 3 or not parts[1].startswith("@") or not parts[2].lstrip("-").isdigit():
        return await message.answer("Format: <code>/givevc @username jumlah</code>", parse_mode=ParseMode.HTML)

    uname = parts[1].lstrip("@").lower()
    amount = int(parts[2])
    async with db.pool.acquire() as conn:
        user = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE LOWER(username) = $1", uname)
        if not user:
            return await message.answer("User tidak ditemukan di database.")
        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", amount, user["user_id"])
        await log_wallet_tx(conn, user["user_id"], amount, "Penyesuaian saldo eksklusif oleh Owner")

    await message.answer(f"✅ Berhasil menambahkan <b>{amount} VC</b> ke <b>{html.escape(user['full_name'])}</b>.", parse_mode=ParseMode.HTML)

@dp.message(Command("addadmin"), F.chat.type == "private")
async def cmd_addadmin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].startswith("@"):
        return await message.answer("Format: <code>/addadmin @username</code>", parse_mode=ParseMode.HTML)
    uname = parts[1].lstrip("@").lower()
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_admin = TRUE WHERE LOWER(username) = $1", uname)
    await message.answer(f"✅ @{uname} sekarang memiliki akses Staf Admin bar.")

@dp.message(Command("deladmin"), F.chat.type == "private")
async def cmd_deladmin(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return await message.answer("⚠️ Perintah ini merupakan hak eksklusif <b>Owner</b> bar.", parse_mode=ParseMode.HTML)
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
        BotCommand(command="confess", description="Kirim Curhat Anonim ke Channel (#confess)"),
        BotCommand(command="admin", description="[Staf/Owner] Panel Kontrol Bar, Password & Lapak"),
    ]
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())

async def main():
    await db.init_db()
    await ensure_hans_schema()
    await register_hans_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
