import html
import random
import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup

import shared.database as db
from julian_bartender.helpers import (
    bot,
    VIP_DEFAULT_TAG,
    sync_tg_user,
    set_guest_tag,
    resolve_target_smart,
    log_tx,
    styled_btn,
    react_msg,
    schedule_delete,
    mention_user,
)

router = Router()

_active_duels: dict[str, dict] = {}


@router.message(Command("slot"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_slot_machine(message: types.Message):
    user = message.from_user
    parts = (message.text or "").split()
    bet = 10
    if len(parts) > 1 and parts[1].isdigit():
        bet = max(10, min(100, int(parts[1])))

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await sync_tg_user(conn, user, message.message_thread_id)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            coins = (row["coins"] or 0) if row else 0
            if coins < bet:
                err_msg = await message.reply(
                    f"Saldo VC tidak cukup untuk taruhan <b>{bet} VC</b> — saldo kamu: <b>{coins} VC</b>.",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
                return

            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, user.id)
            await log_tx(conn, user.id, -bet, f"Taruhan Slot Bar — {bet} VC")

    dice_msg = await message.reply_dice(emoji="🎰")
    val = dice_msg.dice.value
    await asyncio.sleep(2.2)

    payout = 0
    if val == 64:
        payout = bet * 10
        result_title = "👑 <b>JACKPOT 777!</b>"
    elif val in (1, 22, 43):
        payout = bet * 4
        result_title = "✨ <b>TRIPLE BAR!</b>"
    elif val in (2, 3, 4, 16, 17, 32, 33, 48, 49, 60, 61, 62, 63):
        payout = int(bet * 1.5)
        result_title = "🍸 <b>DOUBLE MATCH!</b>"
    else:
        result_title = "🥀 <b>Belum Beruntung</b>"

    async with db.pool.acquire() as conn:
        if payout > 0:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", payout, user.id)
            await log_tx(conn, user.id, payout, f"Menang Slot Bar +{payout} VC")
        bal = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user.id)

    summary = (
        f"🎰 {result_title}\n"
        f"{mention_user(user.id, user.first_name)} • Taruhan: <b>{bet} VC</b>\n"
        + (f"Hadiah: <b>+{payout} VC</b> | Saldo: <b>{bal} VC</b>" if payout > 0 else f"Saldo tersisa: <b>{bal} VC</b>")
    )
    res_msg = await dice_msg.reply(summary, parse_mode=ParseMode.HTML)
    await schedule_delete(message.chat.id, [message.message_id, dice_msg.message_id, res_msg.message_id], delay=30)


async def _start_duel(message: types.Message, game_type: str):
    challenger = message.from_user
    parts = (message.text or "").split()
    has_reply = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.from_user.is_bot
    )

    bet = 20
    target_ident = None
    for p in parts[1:]:
        if p.isdigit():
            bet = max(10, min(200, int(p)))
        elif not has_reply:
            target_ident = p

    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, challenger, message.message_thread_id)
        target = await resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            err_msg = await message.reply(
                f"Format: <code>/{game_type} @username taruhan</code> atau reply pesan lawan dengan <code>/{game_type} 20</code>",
                parse_mode=ParseMode.HTML,
            )
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id) or 0
        t_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", target["user_id"]) or 0

    if c_coins < bet or t_coins < bet:
        err_msg = await message.reply(
            f"Saldo salah satu pemain tidak cukup untuk taruhan <b>{bet} VC</b>.",
            parse_mode=ParseMode.HTML,
        )
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
        return

    duel_id = f"{game_type}_{challenger.id}_{target['user_id']}_{message.message_id}"
    _active_duels[duel_id] = {
        "game": game_type,
        "c_id": challenger.id,
        "c_name": challenger.first_name,
        "t_id": target["user_id"],
        "t_name": target["full_name"],
        "bet": bet,
        "chat_id": message.chat.id,
        "thread_id": message.message_thread_id,
    }

    emoji = "🎯" if game_type == "dart" else "🎲"
    title = "Duel Dart" if game_type == "dart" else "Duel Dadu"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        styled_btn("✅ Terima Duel", callback_data=f"duel_acc:{duel_id}", style="success"),
        styled_btn("✖ Tolak", callback_data=f"duel_dec:{duel_id}", style="danger"),
    ]])
    await react_msg(message.chat.id, message.message_id, emoji)
    await message.reply(
        f"{emoji} <b>{title} — Taruhan {bet} VC</b>\n\n"
        f"{mention_user(challenger.id, challenger.first_name)} menantang {mention_user(target['user_id'], target['full_name'])}!\n"
        f"<i>Pemenang mengambil seluruh pot <b>{bet * 2} VC</b>.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@router.message(Command("dart"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dart_duel(message: types.Message):
    await _start_duel(message, "dart")


@router.message(Command("dice"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dice_duel(message: types.Message):
    await _start_duel(message, "dice")


@router.callback_query(F.data.startswith("duel_"))
async def cb_handle_duel(callback: types.CallbackQuery):
    action, duel_id = callback.data.split(":", 1)
    duel = _active_duels.get(duel_id)
    if not duel:
        return await callback.answer("Tantangan duel sudah kedaluwarsa.", show_alert=True)

    if callback.from_user.id != duel["t_id"]:
        return await callback.answer("Hanya pemain yang ditantang yang dapat merespons.", show_alert=True)

    _active_duels.pop(duel_id, None)
    if action == "duel_dec":
        await callback.message.edit_text("✖ Tantangan duel ditolak.")
        await schedule_delete(callback.message.chat.id, [callback.message.message_id], delay=15)
        return await callback.answer()

    bet = duel["bet"]
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", duel["c_id"]) or 0
            t_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", duel["t_id"]) or 0
            if c_coins < bet or t_coins < bet:
                await callback.message.edit_text("Saldo salah satu pemain tidak lagi mencukupi.")
                return await callback.answer()
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, duel["c_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, duel["t_id"])

    await callback.message.edit_text("⚔️ <b>Duel Dimulai!</b> Melempar giliran...", parse_mode=ParseMode.HTML)
    await callback.answer()

    emoji = "🎯" if duel["game"] == "dart" else "🎲"
    send_kwargs = {"message_thread_id": duel["thread_id"]} if duel["thread_id"] else {}
    d1 = await bot.send_dice(duel["chat_id"], emoji=emoji, **send_kwargs)
    await asyncio.sleep(1.5)
    d2 = await bot.send_dice(duel["chat_id"], emoji=emoji, **send_kwargs)
    await asyncio.sleep(2.5)

    v1, v2 = d1.dice.value, d2.dice.value
    pot = bet * 2
    async with db.pool.acquire() as conn:
        if v1 > v2:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", pot, duel["c_id"])
            await log_tx(conn, duel["c_id"], pot, f"Menang {duel['game'].upper()} +{pot} VC")
            winner_line = f"🏆 Pemenang: {mention_user(duel['c_id'], duel['c_name'])} — <b>+{pot} VC</b>!"
        elif v2 > v1:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", pot, duel["t_id"])
            await log_tx(conn, duel["t_id"], pot, f"Menang {duel['game'].upper()} +{pot} VC")
            winner_line = f"🏆 Pemenang: {mention_user(duel['t_id'], duel['t_name'])} — <b>+{pot} VC</b>!"
        else:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, duel["c_id"])
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, duel["t_id"])
            winner_line = f"🤝 <b>Seri!</b> Taruhan <b>{bet} VC</b> dikembalikan ke masing-masing pemain."

    res = await bot.send_message(
        duel["chat_id"],
        f"{emoji} <b>Hasil Duel</b>\n"
        f"• {html.escape(duel['c_name'])}: <b>{v1}</b>\n"
        f"• {html.escape(duel['t_name'])}: <b>{v2}</b>\n\n"
        f"{winner_line}",
        parse_mode=ParseMode.HTML,
        **send_kwargs,
    )
    await schedule_delete(duel["chat_id"], [callback.message.message_id, d1.message_id, d2.message_id, res.message_id], delay=35)


@router.message(Command("mystery"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_mystery_box(message: types.Message):
    user = message.from_user
    cost = 40

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await sync_tg_user(conn, user, message.message_thread_id)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            coins = (row["coins"] or 0) if row else 0
            if coins < cost:
                err_msg = await message.reply(
                    f"Saldo VC tidak cukup untuk <b>Velvet Mystery Box</b> — butuh <b>{cost} VC</b>.",
                    parse_mode=ParseMode.HTML,
                )
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
                return

            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", cost, user.id)
            await log_tx(conn, user.id, -cost, "Buka Velvet Mystery Box")

            roll = random.randint(1, 100)
            if roll <= 40:
                reward_vc = random.choice([25, 35, 50])
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", reward_vc, user.id)
                prize_text = f"🪙 Kantong Koin Beludru berisi <b>+{reward_vc} VC</b>!"
            elif roll <= 75:
                charm_gain = random.choice([10, 15, 25])
                await conn.execute("UPDATE users SET charm_points = COALESCE(charm_points, 0) + $1 WHERE user_id = $2", charm_gain, user.id)
                prize_text = f"✨ Parfum Kristal Langka memberikan <b>+{charm_gain} Charm</b>!"
            elif roll <= 93:
                reward_vc = 90
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", reward_vc, user.id)
                prize_text = f"💎 Kepingan Berlian Velvet senilai <b>+{reward_vc} VC</b>!"
            else:
                await conn.execute(
                    "UPDATE users SET is_vip = TRUE, vip_until = GREATEST(COALESCE(vip_until, NOW()), NOW()) + INTERVAL '1 day' WHERE user_id = $1",
                    user.id,
                )
                prize_text = "👑 <b>JACKPOT! VIP Pass 24 Jam</b> langsung aktif di akunmu!"

    if roll > 93:
        await set_guest_tag(message.chat.id, user.id, VIP_DEFAULT_TAG)

    await react_msg(message.chat.id, message.message_id, "🎁")
    res_msg = await message.reply(
        f"🎁 <b>Velvet Mystery Box</b>\n"
        f"{mention_user(user.id, user.first_name)} membuka kotak beludru hitam dan mendapatkan:\n\n"
        f"{prize_text}",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, res_msg.message_id], delay=35)


@router.message(Command("bill"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_check_bill(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )

    coins = (row["coins"] or 0) if row else 50
    charm = (row["charm_points"] or 0) if row else 0
    is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    vip_status = f"👑 VIP Aktif — s/d {row['vip_until'].strftime('%d %b %H:%M UTC')}" if is_vip else "Reguler"
    booth_line = f"\n• <b>VIP Booth:</b> {html.escape(row['vip_booth_name'])}" if (row and row["vip_booth_name"]) else ""

    await react_msg(message.chat.id, message.message_id, "🧾")
    bill_msg = await message.reply(
        f"🧾 <b>Tab & Profil Tamu — {html.escape(user.first_name)}</b>\n\n"
        f"• <b>Saldo:</b> {coins} VC\n"
        f"• <b>Charm:</b> {charm} ✨\n"
        f"• <b>Status:</b> {vip_status}{booth_line}",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, bill_msg.message_id], delay=25)


@router.message(Command("topcharm"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top_charm(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, full_name, charm_points, is_vip, vip_until
            FROM users
            WHERE COALESCE(charm_points, 0) > 0
            ORDER BY charm_points DESC
            LIMIT 10
        """)

    if not rows:
        empty_msg = await message.reply("✨ Belum ada tamu yang mengumpulkan poin Charm malam ini.")
        await schedule_delete(message.chat.id, [message.message_id, empty_msg.message_id], delay=15)
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, r in enumerate(rows):
        prefix = medals[idx] if idx < 3 else f"<b>{idx + 1}.</b>"
        vip_mark = " 👑" if (r["is_vip"] and r["vip_until"] and r["vip_until"] > datetime.utcnow()) else ""
        lines.append(f"{prefix} {html.escape(r['full_name'] or 'Tamu')}{vip_mark} — <b>{r['charm_points']} ✨</b>")

    top_msg = await message.reply(
        "✨ <b>Top 10 Tamu Paling Memesona — The Velvet Hour</b>\n\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, top_msg.message_id], delay=35)
