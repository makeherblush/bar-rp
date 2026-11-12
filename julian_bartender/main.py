import asyncio
import random
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import shared.database as db
from shared.config import (
    TOKEN_JULIAN, OWNER_ID, GROUP_ID, REQUIRED_CN_SYMBOL
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN_JULIAN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- HELPER FUNCTIONS ---
async def auto_delete(msg: types.Message, delay: int = 90):
    """Menghapus pesan sementara agar grup tidak nyampah"""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

async def is_staff_or_owner(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_admin FROM users WHERE user_id = $1", user_id)
        return bool(row and row["is_admin"])

async def get_active_shift(role: str):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, started_at, actions_count FROM active_shifts WHERE role = $1", role)
        if row:
            # Cek apakah shift 2 jam sudah habis
            if datetime.utcnow() - row["started_at"] > timedelta(hours=2):
                await finish_shift(role, row["user_id"], row["actions_count"])
                return None
            # Cek jika 30 menit pertama 0 aksi -> copot otomatis
            if datetime.utcnow() - row["started_at"] > timedelta(minutes=30) and row["actions_count"] == 0:
                await conn.execute("DELETE FROM active_shifts WHERE role = $1", role)
                try:
                    await bot.send_message(GROUP_ID, f"⚠️ Shift <b>{role.upper()}</b> milik <a href='tg://user?id={row['user_id']}'>staf</a> dicabut otomatis karena tidak ada aktivitas pelayanan dalam 30 menit pertama.", parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                return None
            return row
    return None

async def finish_shift(role: str, user_id: int, actions: int):
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM active_shifts WHERE role = $1", role)
        if actions >= 5:
            await conn.execute("UPDATE users SET coins = coins + 120 WHERE user_id = $1", user_id)
            msg = f"💼 <b>Shift {role.upper()} Selesai!</b> Terima kasih atas kerja kerasmu ({actions} pelayanan). Upah <b>+120 VC</b> telah masuk ke dompetmu."
        else:
            msg = f"💼 <b>Shift {role.upper()} Selesai.</b> Pelayanan kurang dari 5 kali ({actions}/5), sehingga upah shift tidak cair."
    try:
        await bot.send_message(GROUP_ID, f"<a href='tg://user?id={user_id}'>Staf</a> — {msg}", parse_mode=ParseMode.HTML)
    except Exception:
        pass

async def add_shift_action(user_id: int, role: str):
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE active_shifts SET actions_count = actions_count + 1 WHERE user_id = $1 AND role = $2", user_id, role)

async def kick_from_bar(user_id: int, reason_text: str):
    """Mengeluarkan member (kick + unban) agar bisa masuk lagi lewat bot nanti"""
    try:
        await bot.ban_chat_member(GROUP_ID, user_id)
        await asyncio.sleep(1)
        await bot.unban_chat_member(GROUP_ID, user_id)
    except Exception:
        pass
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_in_bar = FALSE, warned_idle = FALSE WHERE user_id = $1", user_id)
    m = await bot.send_message(GROUP_ID, reason_text, parse_mode=ParseMode.HTML)
    asyncio.create_task(auto_delete(m, 120))

# --- PELACAK AKTIVITAS & SIMBOL CN DI GRUP ---
@dp.message(F.chat.id == GROUP_ID, F.new_chat_members)
async def on_user_join(message: types.Message):
    for member in message.new_chat_members:
        if member.is_bot:
            continue
        # Cek apakah masuk lewat jalur resmi bot & pakai simbol CN
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT is_in_bar, is_vip FROM users WHERE user_id = $1", member.id)
        if (not row or not row["is_in_bar"] or REQUIRED_CN_SYMBOL not in (member.full_name or "")) and not await is_staff_or_owner(member.id):
            await kick_from_bar(
                member.id,
                f"🦍 <b>Bouncer Hans</b> mencegat <a href='tg://user?id={member.id}'>{member.first_name}</a> di pintu. "
                f"<i>\"Kamu belum melapor ke meja resepsionis atau belum mengenakan atribut {REQUIRED_CN_SYMBOL}.\"</i>"
            )
            continue

        if row and row["is_vip"]:
            await message.answer(
                f"✨ <i>Lampu sorot menyala lembut saat tirai beludru tersibak.</i>\n"
                f"<b>\"Selamat datang kembali di meja VIP, <a href='tg://user?id={member.id}'>{member.first_name}</a>.\"</b>",
                parse_mode=ParseMode.HTML
            )

# --- COMMAND UTILITAS TAMU ---
@dp.message(Command("checkin"), F.chat.id == GROUP_ID)
async def cmd_checkin(message: types.Message):
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET last_active = NOW(), warned_idle = FALSE, is_in_bar = TRUE WHERE user_id = $1", message.from_user.id)
    m = await message.reply("🥂 <i>Julian mengangguk ke arah mejamu: \"Baik, gelasmu masih saya jaga. Selamat menikmati obrolan.\"</i>", parse_mode=ParseMode.HTML)
    asyncio.create_task(auto_delete(m, 45))

@dp.message(Command("checkout"), F.chat.id == GROUP_ID)
async def cmd_checkout(message: types.Message):
    user = message.from_user
    await kick_from_bar(
        user.id,
        f"🧥 <b><a href='tg://user?id={user.id}'>{user.first_name}</a></b> meletakkan sejumlah koin di atas meja, mengambil mantelnya, dan melangkah keluar pintu bar. <i>Sampai jumpa di kunjungan berikutnya!</i>"
    )

@dp.message(Command("bill"), F.chat.id == GROUP_ID)
async def cmd_bill(message: types.Message):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins, charm_points, is_vip FROM users WHERE user_id = $1", message.from_user.id)
    if not row:
        return
    status = "🍾 VIP Member" if row["is_vip"] else "🥂 Regular Guest"
    m = await message.reply(
        f"🧾 <b>CATATAN MEJA — {message.from_user.first_name}</b>\n"
        f"• Status: {status}\n"
        f"• Dompet: <b>{row['coins']} VC</b>\n"
        f"• Charm: <b>{row['charm_points']} Poin</b>",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(auto_delete(m, 45))

@dp.message(Command("guests"), F.chat.id == GROUP_ID)
async def cmd_guests(message: types.Message):
    async with db.pool.acquire() as conn:
        guests = await conn.fetch("SELECT user_id, full_name, is_vip FROM users WHERE is_in_bar = TRUE LIMIT 25")
        shifts = await conn.fetch("SELECT role, user_id FROM active_shifts")

    shift_txt = "\n".join([f"• <b>{s['role'].title()}:</b> <a href='tg://user?id={s['user_id']}'>Bertugas</a>" for s in shifts]) or "<i>Semua posisi ditangani oleh Staf Otomatis (NPC).</i>"
    guest_txt = ", ".join([f"{'🍾' if g['is_vip'] else '🥂'} {g['full_name']}" for g in guests]) or "Belum ada tamu."

    m = await message.reply(
        f"🏛️ <b>SUASANA THE VELVET HOUR SAAT INI</b>\n\n"
        f"<b>Staf Paruh Waktu Aktif:</b>\n{shift_txt}\n\n"
        f"<b>Tamu di Ruangan ({len(guests)}):</b>\n{guest_txt}",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(auto_delete(m, 90))

# --- PELAYANAN RP & MODE ANTI-BENTROK ---
@dp.message(Command("order"), F.chat.id == GROUP_ID)
async def cmd_order(message: types.Message):
    args = message.text.replace("/order", "").strip()
    if not args:
        m = await message.reply("Sebutkan nama minumannya. Contoh: <code>/order Negroni</code> atau <code>/order Tequila @username</code>", parse_mode=ParseMode.HTML)
        return asyncio.create_task(auto_delete(m, 30))

    shift = await get_active_shift("bartender")
    if shift and shift["user_id"] != message.from_user.id:
        m = await message.reply(
            f"🔔 <i>Pesanan masuk di meja bar!</i>\n"
            f"<b>Bartender <a href='tg://user?id={shift['user_id']}'>bertugas</a></b>, ada pesanan <b>{args}</b> dari {message.from_user.first_name}. Gunakan <code>/mix</code> atau <code>/serve</code> untuk melayani!",
            parse_mode=ParseMode.HTML
        )
    else:
        m = await message.reply(
            f"🍸 <b>Bartender Julian</b> menggeser segelas <b>{args}</b> melintasi meja kayu yang licin ke hadapan <b>{message.from_user.first_name}</b>.\n"
            f"<i>\"Silakan dinikmati selagi dingin.\"</i>",
            parse_mode=ParseMode.HTML
        )
    asyncio.create_task(auto_delete(m, 120))

@dp.message(Command("eat"), F.chat.id == GROUP_ID)
async def cmd_eat(message: types.Message):
    args = message.text.replace("/eat", "").strip()
    if not args:
        m = await message.reply("Sebutkan nama hidangannya. Contoh: <code>/eat Truffle Fries</code>", parse_mode=ParseMode.HTML)
        return asyncio.create_task(auto_delete(m, 30))

    shift = await get_active_shift("waiter")
    if shift and shift["user_id"] != message.from_user.id:
        m = await message.reply(
            f"🔔 <i>Pesanan dapur siap diantar!</i>\n"
            f"<b>Waiter/Waitress <a href='tg://user?id={shift['user_id']}'>bertugas</a></b>, antarkan <b>{args}</b> ke meja {message.from_user.first_name} dengan <code>/dish</code>!",
            parse_mode=ParseMode.HTML
        )
    else:
        m = await message.reply(
            f"🍽️ <b>Waitress Clara</b> meletakkan sepiring <b>{args}</b> hangat di meja <b>{message.from_user.first_name}</b>.\n"
            f"<i>\"Hati-hati panas ya, selamat menikmati!\"</i>",
            parse_mode=ParseMode.HTML
        )
    asyncio.create_task(auto_delete(m, 120))

@dp.message(Command("toast"), F.chat.id == GROUP_ID)
async def cmd_toast(message: types.Message):
    target = message.text.replace("/toast", "").strip() or "seluruh penjuru ruangan"
    m = await message.reply(
        f"🥂 <b>{message.from_user.first_name}</b> mengangkat gelas kristalnya tinggi-tinggi ke arah <b>{target}</b>! "
        f"Denting gelas terdengar nyaring di tengah hangatnya malam.",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(auto_delete(m, 120))

@dp.message(Command("table"), F.chat.id == GROUP_ID)
async def cmd_table(message: types.Message):
    if not message.reply_to_message:
        m = await message.reply("Balas (reply) pesan tamu yang ingin kamu ajak berbagi meja lalu ketik <code>/table</code>.", parse_mode=ParseMode.HTML)
        return asyncio.create_task(auto_delete(m, 30))

    target = message.reply_to_message.from_user
    if target.id == message.from_user.id or target.is_bot:
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🥂 Terima Ajakan Meja", callback_data=f"accept_table_{message.from_user.id}_{target.id}")
    ]])
    await message.reply(
        f"🕯️ <b>{message.from_user.first_name}</b> mengundang <b>{target.first_name}</b> untuk duduk satu meja malam ini.\n"
        f"<i>(Berbagi meja memberikan tambahan +15 menit batas waktu santai untuk kalian berdua).</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("accept_table_"))
async def cb_accept_table(call: types.CallbackQuery):
    _, _, u1, u2 = call.data.split("_")
    u1, u2 = int(u1), int(u2)
    if call.from_user.id != u2:
        return await call.answer("Undangan meja ini bukan untukmu.", show_alert=True)

    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE users SET last_active = last_active + INTERVAL '15 minutes' WHERE user_id = ANY($1::bigint[])", [u1, u2])

    await call.message.edit_text(
        f"🥂 <b>Meja Diresmikan!</b> <a href='tg://user?id={u1}'>Tamu</a> dan <a href='tg://user?id={u2}'>Tamu</a> kini resmi berbagi meja. "
        f"<i>(+15 menit waktu lounge ditambahkan).</i>",
        parse_mode=ParseMode.HTML
    )

# --- PERMAINAN MEJA BAR (MYSTERY & SPIN) ---
@dp.message(Command("mystery"), F.chat.id == GROUP_ID)
async def cmd_mystery(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if not coins or coins < 40:
                return await message.reply("Saldo tidak cukup (butuh <b>40 VC</b> untuk memesan Mystery Shot).", parse_mode=ParseMode.HTML)
            await conn.execute("UPDATE users SET coins = coins - 40 WHERE user_id = $1", user_id)

    outcomes = [
        ("jackpot", "🌟 <b>GOLDEN ELIXIR!</b> Racikan langka! Kamu memenangkan <b>+120 Velvet Coins</b> dari meja bandar!"),
        ("truth", "🍷 <b>CRIMSON TRUTH!</b> Efek minuman ini memaksamu jujur: <i>Sebutkan tipe karakter RP idamanmu di bar ini sekarang!</i>"),
        ("dare", "🔥 <b>MIDNIGHT DARE!</b> Tantangan bartender: <i>Puji atau ajak bersulang member yang chat tepat di atasmu sekarang!</i>"),
        ("zonk", "💧 <b>WARM WATER!</b> Julian terkekeh pelan: <i>\"Maaf, sepertinya gelasmu tertukar dengan air putih hangat.\"</i>")
    ]
    kind, text = random.choice(outcomes)
    if kind == "jackpot":
        async with db.pool.acquire() as conn:
            await conn.execute("UPDATE users SET coins = coins + 120 WHERE user_id = $1", user_id)

    await message.reply(f"🎲 <b>COCKTAIL ROULETTE — {message.from_user.first_name}</b>\n\n{text}", parse_mode=ParseMode.HTML)

@dp.message(Command("spin"), F.chat.id == GROUP_ID)
async def cmd_spin(message: types.Message):
    async with db.pool.acquire() as conn:
        guests = await conn.fetch("SELECT user_id, full_name FROM users WHERE is_in_bar = TRUE")
    if len(guests) < 2:
        return await message.reply("Tamu di ruangan belum cukup ramai untuk memutar botol.")
    chosen = random.choice(guests)
    m = await message.reply(
        f"🍾 <b>{message.from_user.first_name}</b> memutar botol kosong di atas meja bar...\n"
        f"Ujung botol berhenti menunjuk tepat ke arah <a href='tg://user?id={chosen['user_id']}'>{chosen['full_name']}</a>! <i>Truth or Dare?</i>",
        parse_mode=ParseMode.HTML
    )
    asyncio.create_task(auto_delete(m, 120))

@dp.message(Command("round"), F.chat.id == GROUP_ID)
async def cmd_round(message: types.Message):
    user_id = message.from_user.id
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user_id)
            if not coins or coins < 400:
                return await message.reply("Butuh <b>400 VC</b> untuk mentraktir satu bar.", parse_mode=ParseMode.HTML)
            await conn.execute("UPDATE users SET coins = coins - 400 WHERE user_id = $1", user_id)
            await conn.execute("UPDATE users SET last_active = NOW(), warned_idle = FALSE WHERE is_in_bar = TRUE")

    await message.answer(
        f"🔔🥂 <b>OPEN TAB! TRAKTIRAN SATU BAR!</b> 🥂🔔\n\n"
        f"<b>{message.from_user.first_name}</b> baru saja membuka tab untuk seluruh ruangan! "
        f"Bartender Julian menuangkan sampanye gratis ke setiap meja—<i>waktu pasif seluruh
