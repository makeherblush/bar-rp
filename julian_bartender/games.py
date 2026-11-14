import html
import random
import asyncio
from datetime import datetime

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup
from aiogram.enums import ParseMode

import shared.database as db
from julian_bartender.helpers import (
    sync_tg_user,
    resolve_target_smart,
    log_tx,
    react_msg,
    schedule_delete,
    mention_user,
    styled_btn,
)

router = Router()


@router.message(Command("mystery"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_mystery_box(message: types.Message):
    user = message.from_user
    cost = 40
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await sync_tg_user(conn, user, message.message_thread_id)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            if not row or (row["coins"] or 0) < cost:
                err_msg = await message.reply("Butuh <b>40 VC</b> untuk membuka Velvet Mystery Box.", parse_mode=ParseMode.HTML)
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return

            roll = random.randint(1, 100)
            if roll <= 35:
                prize_vc, prize_charm, label = 20, 2, "Gelang Beludru (+20 VC & +2 Charm)"
            elif roll <= 70:
                prize_vc, prize_charm, label = 45, 5, "Kunci Gudang Anggur (+45 VC & +5 Charm)"
            elif roll <= 92:
                prize_vc, prize_charm, label = 75, 10, "Koin Emas Antik (+75 VC & +10 Charm)"
            else:
                prize_vc, prize_charm, label = 150, 20, "JACKPOT! Mahkota Velvet (+150 VC & +20 Charm)"

            net = prize_vc - cost
            await conn.execute(
                "UPDATE users SET coins = coins + $1, charm_points = COALESCE(charm_points, 0) + $2 WHERE user_id = $3",
                net, prize_charm, user.id
            )
            await log_tx(conn, user.id, net, f"Velvet Mystery Box ({label})")

    await react_msg(message.chat.id, message.message_id, "🎁")
    await message.reply(
        f"🎁 {mention_user(user.id, user.first_name)} membuka kotak beludru hitam dan mendapatkan <b>{label}</b>!",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("slot"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_slot_machine(message: types.Message):
    parts = (message.text or "").split()
    bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 15
    if not (10 <= bet <= 100):
        err_msg = await message.reply("Taruhan mesin slot harus antara <b>10 hingga 100 VC</b>. Contoh: <code>/slot 20</code>", parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    user = message.from_user
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await sync_tg_user(conn, user, message.message_thread_id)
            row = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", user.id)
            if not row or (row["coins"] or 0) < bet:
                err_msg = await message.reply(f"Saldo kamu kurang dari <b>{bet} VC</b> untuk memutar mesin slot.", parse_mode=ParseMode.HTML)
                await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
                return
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, user.id)

    dice_msg = await message.reply_dice(emoji="🎰")
    val = dice_msg.dice.value
    await asyncio.sleep(2.2)

    if val == 64:
        payout = bet * 5
        outcome = f"🎉 <b>JACKPOT 777!</b> {mention_user(user.id, user.first_name)} menang besar <b>+{payout} VC</b> (5x)!"
    elif val in (1, 22, 43):
        payout = bet * 3
        outcome = f"✨ <b>TRIPLE MATCH!</b> {mention_user(user.id, user.first_name)} memenangkan <b>+{payout} VC</b> (3x)!"
    elif val in (2, 3, 4, 16, 17, 32, 48, 60, 61, 62, 63):
        payout = int(bet * 1.5)
        outcome = f"🥂 <b>DOUBLE PAIR!</b> {mention_user(user.id, user.first_name)} mendapat <b>+{payout} VC</b>!"
    else:
        payout = 0
        outcome = f"🥀 Belum beruntung kali ini, {mention_user(user.id, user.first_name)} (<b>-{bet} VC</b>)."

    async with db.pool.acquire() as conn:
        if payout > 0:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", payout, user.id)
            await log_tx(conn, user.id, payout - bet, f"Menang Slot Machine (+{payout - bet} VC bersih)")
        else:
            await log_tx(conn, user.id, -bet, "Taruhan Slot Machine")

    await dice_msg.reply(outcome, parse_mode=ParseMode.HTML)


@router.message(Command("dart"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dart_challenge(message: types.Message):
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        err_msg = await message.reply("Format: <code>/dart @username [taruhan 10-100]</code> atau reply pesan lawanmu.", parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    if has_reply:
        bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        target_ident = None
    else:
        bet = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20
        target_ident = parts[1]

    if not (10 <= bet <= 100):
        err_msg = await message.reply("Taruhan dart harus antara <b>10 hingga 100 VC</b>.", parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    challenger = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, challenger, message.message_thread_id)
        target = await resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            err_msg = await message.reply("Lawan dart tidak ditemukan.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id) or 0
        t_coins = target["coins"] or 0
        if c_coins < bet or t_coins < bet:
            err_msg = await message.reply("Saldo salah satu pemain tidak mencukupi.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        styled_btn(f"🎯 Lempar Dart ({bet} VC)", callback_data=f"playdart_{challenger.id}_{target['user_id']}_{bet}", style="success"),
        styled_btn("❌ Tolak", callback_data=f"canceldart_{target['user_id']}", style="danger"),
    ]])
    await message.reply(
        f"🎯 {mention_user(challenger.id, challenger.first_name)} menantang {mention_user(target['user_id'], target['full_name'])} duel dart (<b>{bet} VC</b>).",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("playdart_"))
async def cb_play_dart(call: types.CallbackQuery):
    _, c_str, t_str, bet_str = call.data.split("_")
    c_id, t_id, bet = int(c_str), int(t_str), int(bet_str)

    if call.from_user.id != t_id:
        return await call.answer("Hanya pemain yang ditantang yang bisa memulai lemparan!", show_alert=True)

    await call.answer("Melempar anak panah...")
    await call.message.edit_text("🎯 Pertandingan dart dimulai...", parse_mode=ParseMode.HTML)

    d1_msg = await call.message.answer_dice(emoji="🎯")
    await asyncio.sleep(1.5)
    d2_msg = await call.message.answer_dice(emoji="🎯")
    await asyncio.sleep(2.2)

    s1, s2 = d1_msg.dice.value, d2_msg.dice.value

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", c_id)
            t_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", t_id)

            if (c_user["coins"] or 0) < bet or (t_user["coins"] or 0) < bet:
                return await d2_msg.reply("Pertandingan dibatalkan karena saldo salah satu pemain berubah.")

            if s1 == s2:
                return await d2_msg.reply(
                    f"🎯 Seri! Kedua pemain mencetak skor <b>{s1}/6</b>. Taruhan <b>{bet} VC</b> dikembalikan.",
                    parse_mode=ParseMode.HTML,
                )

            winner = c_user if s1 > s2 else t_user
            loser = t_user if s1 > s2 else c_user

            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, winner["user_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, loser["user_id"])
            await log_tx(conn, winner["user_id"], bet, f"Menang Dart vs {loser['full_name']}")
            await log_tx(conn, loser["user_id"], -bet, f"Kalah Dart vs {winner['full_name']}")

    bullseye_note = " 🔥 <b>BULLSEYE!</b>" if max(s1, s2) == 6 else ""
    await d2_msg.reply(
        f"🎯 <b>Hasil Dart</b>{bullseye_note}\n"
        f"• {mention_user(c_user['user_id'], c_user['full_name'])}: <b>{s1}/6</b>\n"
        f"• {mention_user(t_user['user_id'], t_user['full_name'])}: <b>{s2}/6</b>\n"
        f"🏆 Pemenang: {mention_user(winner['user_id'], winner['full_name'])} (<b>+{bet} VC</b>)",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("canceldart_"))
async def cb_cancel_dart(call: types.CallbackQuery):
    t_id = int(call.data.replace("canceldart_", ""))
    if call.from_user.id != t_id:
        return await call.answer("Bukan tantangan untukmu!", show_alert=True)
    await call.answer("Ditolak.")
    await call.message.edit_text("❌ Tantangan dart ditolak.")


@router.message(Command("dice"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_dice_duel(message: types.Message):
    parts = (message.text or "").split()
    has_reply = bool(message.reply_to_message and message.reply_to_message.from_user)

    if len(parts) < 2 and not has_reply:
        err_msg = await message.reply("Format: <code>/dice @username [taruhan 10-100]</code> atau reply pesan lawanmu.", parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    if has_reply:
        bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        target_ident = None
    else:
        bet = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 20
        target_ident = parts[1]

    if not (10 <= bet <= 100):
        err_msg = await message.reply("Taruhan duel dadu harus antara <b>10 hingga 100 VC</b>.", parse_mode=ParseMode.HTML)
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
        return

    challenger = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, challenger, message.message_thread_id)
        target = await resolve_target_smart(conn, message, target_ident)
        if not target or target["user_id"] == challenger.id:
            err_msg = await message.reply("Lawan duel tidak ditemukan.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        c_coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", challenger.id) or 0
        t_coins = target["coins"] or 0
        if c_coins < bet or t_coins < bet:
            err_msg = await message.reply("Saldo VC salah satu pemain tidak mencukupi.")
            await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=20)
            return

        duel_id = await conn.fetchval("""
            INSERT INTO duel_challenges (challenger_id, target_id, bet_vc)
            VALUES ($1, $2, $3) RETURNING id
        """, challenger.id, target["user_id"], bet)

    await react_msg(message.chat.id, message.message_id, "🎲")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        styled_btn(f"🎲 Lempar Dadu ({bet} VC)", callback_data=f"accept_duel_{duel_id}", style="success"),
        styled_btn("❌ Tolak", callback_data=f"decline_duel_{duel_id}", style="danger"),
    ]])
    await message.reply(
        f"🎲 {mention_user(challenger.id, challenger.first_name)} menantang {mention_user(target['user_id'], target['full_name'])} duel dadu (<b>{bet} VC</b>).",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("accept_duel_"))
async def cb_accept_duel(call: types.CallbackQuery):
    duel_id = int(call.data.replace("accept_duel_", ""))
    async with db.pool.acquire() as conn:
        duel = await conn.fetchrow("SELECT * FROM duel_challenges WHERE id = $1", duel_id)
        if not duel:
            return await call.answer("Tantangan duel sudah selesai.", show_alert=True)
        if call.from_user.id != duel["target_id"]:
            return await call.answer("Bukan tantangan untukmu!", show_alert=True)
        await conn.execute("DELETE FROM duel_challenges WHERE id = $1", duel_id)

    await call.answer("Melempar dadu...")
    await call.message.edit_text("🎲 Duel dadu dimulai...", parse_mode=ParseMode.HTML)

    dice1 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(1.4)
    dice2 = await call.message.answer_dice(emoji="🎲")
    await asyncio.sleep(2.2)

    d1, d2 = dice1.dice.value, dice2.dice.value
    bet = duel["bet_vc"]

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", duel["challenger_id"])
            t_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", duel["target_id"])

            if (c_user["coins"] or 0) < bet or (t_user["coins"] or 0) < bet:
                return await dice2.reply("Duel dibatalkan karena saldo salah satu pemain tidak mencukupi.")

            if d1 == d2:
                return await dice2.reply(
                    f"🎲 Seri! Kedua pemain melempar angka <b>{d1}</b>. Taruhan <b>{bet} VC</b> dikembalikan.",
                    parse_mode=ParseMode.HTML,
                )

            winner = c_user if d1 > d2 else t_user
            loser = t_user if d1 > d2 else c_user

            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, winner["user_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, loser["user_id"])
            await log_tx(conn, winner["user_id"], bet, f"Menang Duel Dadu vs {loser['full_name']}")
            await log_tx(conn, loser["user_id"], -bet, f"Kalah Duel Dadu vs {winner['full_name']}")

    await dice2.reply(
        f"🎲 <b>Hasil Duel Dadu</b>\n"
        f"• {mention_user(c_user['user_id'], c_user['full_name'])}: <b>{d1}</b>\n"
        f"• {mention_user(t_user['user_id'], t_user['full_name'])}: <b>{d2}</b>\n"
        f"🏆 Pemenang: {mention_user(winner['user_id'], winner['full_name'])} (<b>+{bet} VC</b>)",
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data.startswith("decline_duel_"))
async def cb_decline_duel(call: types.CallbackQuery):
    duel_id = int(call.data.replace("decline_duel_", ""))
    async with db.pool.acquire() as conn:
        duel = await conn.fetchrow("SELECT target_id FROM duel_challenges WHERE id = $1", duel_id)
        if not duel:
            return await call.answer("Sudah selesai.", show_alert=True)
        if call.from_user.id != duel["target_id"]:
            return await call.answer("Bukan tantangan untukmu!", show_alert=True)
        await conn.execute("DELETE FROM duel_challenges WHERE id = $1", duel_id)
    await call.answer("Duel ditolak.")
    await call.message.edit_text("❌ Tantangan duel dadu ditolak.")


@router.message(Command("bill"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_check_bill(message: types.Message):
    user = message.from_user
    async with db.pool.acquire() as conn:
        await sync_tg_user(conn, user, message.message_thread_id)
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user.id,
        )

    if not row:
        err_msg = await message.reply("Kirim 1 pesan di grup terlebih dahulu untuk membuka tab tamu.")
        await schedule_delete(message.chat.id, [message.message_id, err_msg.message_id], delay=15)
        return

    is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    status = f"👑 VIP (s/d {row['vip_until'].strftime('%d %b %H:%M UTC')})" if is_vip else "Reguler"
    booth = f"\n• VIP Booth: <b>{html.escape(row['vip_booth_name'])}</b>" if row["vip_booth_name"] else ""
    msg = await message.reply(
        f"🧾 <b>Tab {html.escape(user.first_name)}</b>\n"
        f"• Saldo: <b>{row['coins'] or 0} VC</b>\n"
        f"• Charm: <b>{row['charm_points'] or 0} ✨</b>\n"
        f"• Status: {status}{booth}",
        parse_mode=ParseMode.HTML,
    )
    await schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=45)


@router.message(Command("topcharm"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_top_charm(message: types.Message):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT full_name, charm_points FROM users ORDER BY COALESCE(charm_points, 0) DESC LIMIT 10")
    lines = [
        f"{idx}. {html.escape(r['full_name'])} — <b>{r['charm_points'] or 0} ✨</b>"
        for idx, r in enumerate(rows, start=1)
    ] or ["<i>Belum ada data.</i>"]
    msg = await message.reply("✨ <b>Top 10 Most Charming Guests</b>\n\n" + "\n".join(lines), parse_mode=ParseMode.HTML)
    await schedule_delete(message.chat.id, [message.message_id, msg.message_id], delay=60)
