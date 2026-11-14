import html
import random
from datetime import datetime
from aiogram import Router, F, types
from aiogram.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
)

import shared.database as db
from hans_concierge.helpers import (
    bot, get_or_create_referral_code, get_bar_setting, styled_btn
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

    # 1. KARTU PROFIL / MEMBER PASS
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
                description=f"Saldo: {coins} VC | Charm: {charm} ✨",
                input_message_content=InputTextMessageContent(message_text=card_msg, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn("🚪 Masuk ke The Velvet Hour", url=f"https://t.me/{me.username}?start=ref_{ref_code}", style="primary")
                ]]),
            )
        )

    # 2. TANTANGAN DUEL DADU (@HansVolkovVH_bot duel 50)
    if not q or q.startswith("duel"):
        parts = q.split()
        bet = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 25
        bet = max(10, min(100, bet))

        duel_msg = (
            f"🎲 <b>TANTANGAN DUEL MEJA BAR — THE VELVET HOUR</b>\n\n"
            f"<b>{html.escape(user.first_name)}</b> membuka tantangan duel taruhan <b>{bet} VC</b>!\n"
            f"<i>Klik tombol di bawah untuk menerima tantangan:</i>"
        )
        results.append(
            InlineQueryResultArticle(
                id=f"duel_{user.id}_{bet}",
                title=f"🎲 Kirim Tantangan Duel ({bet} VC)",
                description="Ketik 'duel 50' untuk ubah nominal taruhan (10-100 VC)",
                input_message_content=InputTextMessageContent(message_text=duel_msg, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn(f"🎲 Terima Duel ({bet} VC)", callback_data=f"inlineduel_{user.id}_{bet}", style="success")
                ]]),
            )
        )

    # 3. KIRIM TRAKTIRAN / VOUCHER MINUMAN KE TEMAN (@HansVolkovVH_bot traktir)
    if not q or q.startswith("traktir") or q.startswith("treat"):
        treat_msg = (
            f"🥂 <b>KUPON TRAKTIRAN — THE VELVET HOUR</b>\n\n"
            f"<b>{html.escape(user.first_name)}</b> mentraktir segelas <i>Velvet Signature Cocktail</i> (+15 VC & +3 Charm) untuk siapa saja yang tercepat mengklaim!"
        )
        results.append(
            InlineQueryResultArticle(
                id=f"giftdrink_{user.id}",
                title="🥂 Bagi-Bagi Kupon Traktiran (15 VC)",
                description="Siapa cepat dia dapat! Penerima langsung dapat +15 VC & +3 Charm",
                input_message_content=InputTextMessageContent(message_text=treat_msg, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn("🍸 Klaim Traktiran Sekarang", callback_data=f"inlineclaim_{user.id}", style="primary")
                ]]),
            )
        )

    # 4. UNDANGAN VIP / LINK REFERRAL (@HansVolkovVH_bot invite)
    if not q or q.startswith("invite") or q.startswith("undang"):
        invite_msg = (
            f"🕯️ <b>UNDANGAN EKSKLUSIF — THE VELVET HOUR</b>\n\n"
            f"Kamu diundang langsung oleh <b>{html.escape(user.first_name)}</b> untuk bergabung ke lounge malam paling elegan.\n"
            f"• <b>Kode Referral:</b> <code>{ref_code}</code>\n"
            f"• <b>Bonus Tamu Baru:</b> <b>+50 Velvet Coins</b> langsung saat registrasi!"
        )
        results.append(
            InlineQueryResultArticle(
                id=f"invite_{user.id}",
                title="🕯️ Kirim Undangan Masuk Bar (+Bonus Referral)",
                description=f"Bagikan kode undangan {ref_code} ke teman atau grup RP",
                input_message_content=InputTextMessageContent(message_text=invite_msg, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn("🥂 Terima Undangan & Masuk Bar", url=f"https://t.me/{me.username}?start=ref_{ref_code}", style="success")
                ]]),
            )
        )

    # 5. TOP 5 CHARMING GUESTS (@HansVolkovVH_bot top)
    if not q or q.startswith("top") or q.startswith("rank"):
        async with db.pool.acquire() as conn:
            top_rows = await conn.fetch("SELECT full_name, charm_points FROM users ORDER BY COALESCE(charm_points, 0) DESC LIMIT 5")
        rank_lines = [
            f"{i}. <b>{html.escape(r['full_name'])}</b> — <b>{r['charm_points'] or 0} ✨</b>"
            for i, r in enumerate(top_rows, start=1)
        ] or ["<i>Belum ada data peringkat.</i>"]

        top_msg = "✨ <b>TOP 5 MOST CHARMING GUESTS — THE VELVET HOUR</b>\n\n" + "\n".join(rank_lines)
        results.append(
            InlineQueryResultArticle(
                id=f"topcharm_{user.id}",
                title="✨ Bagikan Papan Peringkat Top 5 Charm",
                description="Tampilkan 5 tamu paling memesona di The Velvet Hour",
                input_message_content=InputTextMessageContent(message_text=top_msg, parse_mode="HTML"),
            )
        )

    # 6. STATUS PINTU BAR & MENU MINI APP (@HansVolkovVH_bot bar)
    if not q or q.startswith("bar") or q.startswith("menu"):
        cur_pw = await get_bar_setting("door_password")
        gate_state = "🔐 Terkunci (Butuh Password Pintu)" if cur_pw else "🟢 Terbuka untuk Pemilik Simbol CN"
        bar_msg = (
            f"🍸 <b>THE VELVET HOUR — LOUNGE STATUS</b>\n\n"
            f"• <b>Status Pintu:</b> {gate_state}\n"
            f"• <b>Layanan Aktif:</b> Bartender Julian, Resepsionis Hans, Slot, Dart & Jukebox\n"
            f"<i>Klik tombol di bawah untuk membuka buku menu atau lobi masuk:</i>"
        )
        results.append(
            InlineQueryResultArticle(
                id=f"barinfo_{user.id}",
                title="🍸 Info Status Bar & Buku Menu",
                description="Bagikan info status pintu masuk & tombol menuju bar",
                input_message_content=InputTextMessageContent(message_text=bar_msg, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    styled_btn("🍸 Buka Lobi The Velvet Hour", url=f"https://t.me/{me.username}?start=lobby", style="primary")
                ]]),
            )
        )

    # 7. ETALASE LAPAK PARTNER (@HansVolkovVH_bot lapak)
    if not q or q.startswith("lapak") or q.startswith("toko"):
        async with db.pool.acquire() as conn:
            items = await conn.fetch("""
                SELECT si.id, si.title, si.price_vc, ps.shop_name, ps.owner_username
                FROM shop_items si
                JOIN partner_shops ps ON si.shop_id = ps.id
                WHERE si.is_sold = FALSE
                ORDER BY si.id DESC LIMIT 6
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
                    input_message_content=InputTextMessageContent(message_text=item_msg, parse_mode="HTML"),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        styled_btn("🛍️ Buka Pojok Lapak di Hans", url=f"https://t.me/{me.username}?start=lapak", style="primary")
                    ]]),
                )
            )

    await inline_query.answer(results[:50], cache_time=5, is_personal=True)


# --- CALLBACK: TERIMA INLINE DUEL ---
@router.callback_query(F.data.startswith("inlineduel_"))
async def cb_accept_inline_duel(call: types.CallbackQuery):
    _, challenger_str, bet_str = call.data.split("_")
    challenger_id = int(challenger_str)
    bet = int(bet_str)
    acceptor = call.from_user

    if acceptor.id == challenger_id:
        return await call.answer("Kamu tidak bisa menerima tantanganmu sendiri!", show_alert=True)

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


# --- CALLBACK: KLAIM KUPON TRAKTIRAN INLINE ---
@router.callback_query(F.data.startswith("inlineclaim_"))
async def cb_claim_inline_treat(call: types.CallbackQuery):
    sender_id = int(call.data.replace("inlineclaim_", ""))
    claimer = call.from_user

    if claimer.id == sender_id:
        return await call.answer("Kamu tidak bisa mengklaim traktiranmu sendiri!", show_alert=True)

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            s_user = await conn.fetchrow("SELECT full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", sender_id)
            c_user = await conn.fetchrow("SELECT full_name, coins FROM users WHERE user_id = $1 FOR UPDATE", claimer.id)

            if not s_user or (s_user["coins"] or 0) < 15:
                return await call.answer("Saldo pengirim sudah tidak mencukupi (butuh 15 VC).", show_alert=True)
            if not c_user:
                return await call.answer("Silakan /start bot Hans terlebih dahulu untuk mengklaim!", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - 15 WHERE user_id = $1", sender_id)
            await conn.execute(
                "UPDATE users SET coins = coins + 15, charm_points = COALESCE(charm_points, 0) + 3 WHERE user_id = $1",
                claimer.id
            )
            await conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, -15, $2, NOW())",
                sender_id, f"Kupon Traktiran diklaim {c_user['full_name']}"
            )
            await conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount, reason, created_at) VALUES ($1, 15, $2, NOW())",
                claimer.id, f"Klaim Traktiran dari {s_user['full_name']}"
            )

    await call.answer("Traktiran berhasil diklaim!")
    await call.edit_message_text(
        f"🥂 <b>KUPON TRAKTIRAN TELAH DIKLAIM!</b>\n\n"
        f"<b>{html.escape(claimer.full_name)}</b> berhasil mengklaim traktiran dari <b>{html.escape(s_user['full_name'])}</b>!\n"
        f"✨ <i>Hadiah diterima: <b>+15 VC</b> & <b>+3 Charm</b>.</i>",
        parse_mode="HTML",
    )
