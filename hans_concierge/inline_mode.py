import html
from datetime import datetime
from aiogram import Router, F, types
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
)

import shared.database as db
from hans_concierge.helpers import (
    bot, REQUIRED_CN_SYMBOL, get_or_create_referral_code, styled_btn
)

router = Router()


@router.inline_query()
async def handle_hans_inline(inline_query: types.InlineQuery):
    user = inline_query.from_user
    q = (inline_query.query or "").strip().lower()
    me = await bot.get_me()
    results = []

    async with db.pool.acquire() as conn:
        u_row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, vip_booth_name FROM users WHERE user_id = $1",
            user.id
        )

    coins = u_row["coins"] if u_row else 0
    charm = u_row["charm_points"] if u_row else 0
    is_vip = bool(u_row and u_row["is_vip"] and u_row["vip_until"] and u_row["vip_until"] > datetime.utcnow())
    tier_label = "👑 VIP RESERVE PASS" if is_vip else "🥂 REGULER MEMBER"
    booth_txt = f"\n• <b>VIP Booth:</b> {html.escape(u_row['vip_booth_name'])}" if (u_row and u_row["vip_booth_name"]) else ""
    ref_code = await get_or_create_referral_code(user.id)

    # 1. KARTU PROFIL / MEMBER PASS INSTAN
    if not q or q.startswith("card") or q.startswith("profil"):
        card_msg = (
            f"💳 <b>MEMBER PASS — THE VELVET HOUR</b>\n\n"
            f"• <b>Tamu:</b> {html.escape(user.full_name)} (@{user.username or 'NoUsername'})\n"
            f"• <b>Status:</b> {tier_label}\n"
            f"• <b>Saldo Dompet:</b> <b>{coins} VC</b>\n"
            f"• <b>Charm Points:</b> <b>{charm} ✨</b>{booth_txt}"
        )
        results.append(
            InlineQueryResultArticle(
                id=f"card_{user.id}",
                title=f"💳 Pamerkan Member Pass ({tier_label})",
                description=f"Saldo: {coins} VC | Charm: {charm} ✨ — Klik untuk kirim ke chat",
                input_message_content=InputTextMessageContent(
                    message_text=card_msg,
                    parse_mode="HTML",
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn("🚪 Masuk ke The Velvet Hour", url=f"https://t.me/{me.username}?start=ref_{ref_code}", style="primary")
                ]]),
            )
        )

    # 2. TANTANGAN DUEL DARI CHAT MANA SAJA (@HansVolkovVH_bot duel 50)
    if not q or q.startswith("duel"):
        parts = q.split()
        bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 25
        bet = max(10, min(100, bet))

        duel_msg = (
            f"🎲 <b>TANTANGAN DUEL MEJA BAR — THE VELVET HOUR</b>\n\n"
            f"<b>{html.escape(user.first_name)}</b> membuka tantangan duel taruhan <b>{bet} VC</b>!\n"
            f"<i>Klik tombol di bawah untuk menerima tantangan (wajib berada di dalam grup bar):</i>"
        )
        results.append(
            InlineQueryResultArticle(
                id=f"duel_{user.id}_{bet}",
                title=f"🎲 Kirim Tantangan Duel ({bet} VC)",
                description="Siapa saja di chat ini bisa menekan tombol Terima Duel",
                input_message_content=InputTextMessageContent(
                    message_text=duel_msg,
                    parse_mode="HTML",
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn(f"🎲 Terima Duel ({bet} VC)", callback_data=f"inlineduel_{user.id}_{bet}", style="success")
                ]]),
            )
        )

    # 3. ETALASE LAPAK PARTNER (@HansVolkovVH_bot lapak)
    if not q or q.startswith("lapak") or q.startswith("toko"):
        async with db.pool.acquire() as conn:
            items = await conn.fetch("""
                SELECT si.id, si.title, si.price_vc, ps.shop_name, ps.owner_username
                FROM shop_items si
                JOIN partner_shops ps ON si.shop_id = ps.id
                WHERE si.is_sold = FALSE
                ORDER BY si.id DESC LIMIT 8
            """)
        for it in items:
            item_msg = (
                f"🏪 <b>POJOK LAPAK PARTNER — {html.escape(it['shop_name'])}</b>\n\n"
                f"• <b>Item:</b> <b>{html.escape(it['title'])}</b>\n"
                f"• <b>Harga:</b> <b>{it['price_vc']} VC</b>\n"
                f"• <b>Penjual:</b> @{it['owner_username'] or 'Partner'}\n\n"
                f"<i>Tekan tombol di bawah untuk melihat detail & membeli via Hans:</i>"
            )
            results.append(
                InlineQueryResultArticle(
                    id=f"shopitem_{it['id']}",
                    title=f"🏪 {it['title']} ({it['price_vc']} VC)",
                    description=f"Lapak: {it['shop_name']} — Klik untuk promosikan di chat",
                    input_message_content=InputTextMessageContent(
                        message_text=item_msg,
                        parse_mode="HTML",
                    ),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        styled_btn("🛍️ Buka Pojok Lapak di Hans", url=f"https://t.me/{me.username}?start=lapak", style="primary")
                    ]]),
                )
            )

    await inline_query.answer(results, cache_time=5, is_personal=True)


# Handler saat orang lain menekan tombol "Terima Duel" dari pesan Inline
@router.callback_query(F.data.startswith("inlineduel_"))
async def cb_accept_inline_duel(call: types.CallbackQuery):
    _, challenger_str, bet_str = call.data.split("_")
    challenger_id = int(challenger_str)
    bet = int(bet_str)
    acceptor = call.from_user

    if acceptor.id == challenger_id:
        return await call.answer("Kamu tidak bisa menerima tantanganmu sendiri!", show_alert=True)

    import random
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            c_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", challenger_id)
            a_user = await conn.fetchrow("SELECT user_id, full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", acceptor.id)

            if not c_user or not a_user:
                return await call.answer("Kedua pemain wajib terdaftar di @HansVolkovVH_bot (/start)!", show_alert=True)
            if (c_user["coins"] or 0) < bet or (a_user["coins"] or 0) < bet:
                return await call.answer(f"Saldo salah satu pemain kurang dari {bet} VC!", show_alert=True)

            d1, d2 = random.randint(1, 6), random.randint(1, 6)
            while d1 == d2:
                d1, d2 = random.randint(1, 6), random.randint(1, 6)

            winner = c_user if d1 > d2 else a_user
            loser = a_user if d1 > d2 else c_user

            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", bet, winner["user_id"])
            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", bet, loser["user_id"])
            await conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
                winner["user_id"], bet, f"Menang Inline Duel vs {loser['full_name']}"
            )
            await conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, $2, $3, NOW())",
                loser["user_id"], -bet, f"Kalah Inline Duel vs {winner['full_name']}"
            )

    await call.answer("Duel selesai!")
    await call.edit_message_text(
        f"🎲 <b>HASIL INLINE DUEL — THE VELVET HOUR</b>\n\n"
        f"• <b>{html.escape(c_user['full_name'])}</b>: <b>{d1}</b>\n"
        f"• <b>{html.escape(a_user['full_name'])}</b>: <b>{d2}</b>\n\n"
        f"🏆 <b>Pemenang:</b> <b>{html.escape(winner['full_name'])}</b> meraih <b>+{bet} VC</b>!",
        parse_mode="HTML",
    )
