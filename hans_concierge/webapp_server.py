import os
import hmac
import json
import html
import asyncio
import hashlib
from urllib.parse import parse_qsl
from datetime import datetime
from aiohttp import web
from aiogram import Bot
from aiogram.enums import ParseMode, ChatAction

import shared.database as db
import shared.config as cfg
from hans_concierge.helpers import log_wallet_tx, add_quest_progress

julian_bot = Bot(token=cfg.TOKEN_JULIAN)
kaelen_bot = Bot(token=cfg.TOKEN_KAELEN) if getattr(cfg, "TOKEN_KAELEN", None) else julian_bot
hans_bot = Bot(token=cfg.TOKEN_HANS)

WEBAPP_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "webapp", "index.html")


def _verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None
        return json.loads(parsed.get("user", "{}"))
    except Exception:
        return None


def _authenticate_user(init_data: str) -> dict | None:
    for tok in [getattr(cfg, "TOKEN_JULIAN", ""), getattr(cfg, "TOKEN_HANS", "")]:
        if tok:
            u = _verify_telegram_init_data(init_data, tok)
            if u and u.get("id"):
                return u
    return None


async def _serve_with_bartender_animation(category: str, mention: str, item_name: str, is_vip: bool):
    """Animasi bartending bertahap di grup utama agar terasa hidup."""
    vip_tag = " 👑 <i>(VIP Reserve)</i>" if is_vip else ""
    try:
        await julian_bot.send_chat_action(cfg.GROUP_ID, ChatAction.TYPING)
    except Exception:
        pass

    if category in ("drink", "custom_mix"):
        msg = await julian_bot.send_message(
            cfg.GROUP_ID,
            f"🧊 <i>Julian mengambil gelas kristal dingin dan menyiapkan bahan untuk {mention}...</i>",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(1.3)
        await msg.edit_text(
            f"🍸 <i>Julian mengocok shaker dengan ritme presisi lalu menuangkannya perlahan...</i>",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(1.3)
        header = "🧪 <b>CUSTOM MIXOLOGY — JULIAN</b>" if category == "custom_mix" else "🍸 <b>JULIAN — BARTENDER SERVICE</b>"
        await msg.edit_text(
            f"{header}\n\n"
            f"<i>Julian menggeser gelas di atas meja bar mahoni menuju {mention}{vip_tag}.</i>\n"
            f"• <b>Pesanan:</b> <b>{item_name}</b>\n"
            f"<i>\"Silakan dinikmati malam ini.\"</i>",
            parse_mode=ParseMode.HTML,
        )
    elif category == "food":
        msg = await julian_bot.send_message(
            cfg.GROUP_ID,
            f"🔥 <i>Pesanan dapur untuk {mention} sedang diproses oleh chef...</i>",
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(1.8)
        await msg.edit_text(
            f"🍽️ <b>JULIAN — MIDNIGHT KITCHEN</b>\n\n"
            f"<i>Hidangan hangat baru saja keluar dari dapur dan disajikan ke meja {mention}{vip_tag}.</i>\n"
            f"• <b>Hidangan:</b> <b>{item_name}</b>",
            parse_mode=ParseMode.HTML,
        )


async def handle_index(request: web.Request) -> web.Response:
    with open(WEBAPP_HTML_PATH, "r", encoding="utf-8") as f:
        return web.Response(text=f.read(), content_type="text/html")


async def handle_api_me(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = _authenticate_user(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "error": "Sesi tidak valid"}, status=401)

    uid = int(tg_user["id"])
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1", uid)
        items = await conn.fetch("""
            SELECT si.id, si.title, si.price_vc, ps.shop_name
            FROM shop_items si
            JOIN partner_shops ps ON si.shop_id = ps.id
            WHERE si.is_sold = FALSE
            ORDER BY si.id DESC LIMIT 20
        """)

    coins = row["coins"] if row else 0
    is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    shop_list = [
        {"id": r["id"], "title": r["title"], "price_vc": r["price_vc"], "shop_name": r["shop_name"]}
        for r in items
    ]
    return web.json_response({"ok": True, "coins": coins, "is_vip": is_vip, "shop_items": shop_list})


async def handle_api_order(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = _authenticate_user(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "error": "Sesi Telegram tidak valid"}, status=401)

    uid = int(tg_user["id"])
    first_name = html.escape(tg_user.get("first_name", "Tamu"))
    mention = f'<a href="tg://user?id={uid}">{first_name}</a>'
    category = body.get("category", "drink")

    # PEMBELIAN ITEM LAPAK PARTNER LANGSUNG DARI MINI APP
    if category == "lapak":
        item_id = int(body.get("item_id", 0))
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                item = await conn.fetchrow("""
                    SELECT si.*, ps.owner_id, ps.shop_name
                    FROM shop_items si
                    JOIN partner_shops ps ON si.shop_id = ps.id
                    WHERE si.id = $1 FOR UPDATE
                """, item_id)
                if not item or item["is_sold"]:
                    return web.json_response({"ok": False, "error": "Item sudah terjual atau tidak tersedia."})
                if item["owner_id"] == uid:
                    return web.json_response({"ok": False, "error": "Tidak bisa membeli item lapak sendiri."})

                buyer = await conn.fetchrow("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", uid)
                price = item["price_vc"]
                if not buyer or (buyer["coins"] or 0) < price:
                    return web.json_response({"ok": False, "error": f"Saldo kurang! Butuh {price} VC."})

                new_coins = buyer["coins"] - price
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, uid)
                await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", price, item["owner_id"])
                await conn.execute("UPDATE shop_items SET is_sold = TRUE, buyer_id = $1 WHERE id = $2", uid, item_id)
                await log_wallet_tx(conn, uid, -price, f"Beli di {item['shop_name']}: {item['title']}")
                await log_wallet_tx(conn, item["owner_id"], price, f"Penjualan {item['title']}")

        try:
            await hans_bot.send_message(
                uid,
                f"🧾 <b>NOTA PEMBELIAN LAPAK — {html.escape(item['shop_name'])}</b>\n\n"
                f"• <b>Item:</b> {html.escape(item['title'])}\n"
                f"• <b>Harga:</b> {price} VC\n"
                f"• <b>Konten / Catatan:</b>\n<blockquote>{html.escape(item['content_text'] or '-')}</blockquote>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return web.json_response({"ok": True, "new_coins": new_coins})

    # PESANAN BAR, CUSTOM MIXOLOGY, & JUKEBOX
    item_name = html.escape(str(body.get("item_name", "Menu"))[:100])
    base_price = int(body.get("price", 0))

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1 FOR UPDATE", uid)
            if not row:
                return web.json_response({"ok": False, "error": "Silakan /start bot Hans terlebih dahulu."})

            is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            final_cost = 0 if is_vip else max(0, base_price)
            coins = row["coins"] or 0

            if coins < final_cost:
                return web.json_response({
                    "ok": False,
                    "error": f"Saldo kurang! Butuh {final_cost} VC (saldo kamu: {coins} VC)."
                })

            new_coins = coins - final_cost
            if final_cost > 0:
                await conn.execute("UPDATE users SET coins = $1 WHERE user_id = $2", new_coins, uid)
                await log_wallet_tx(conn, uid, -final_cost, f"Pesanan Mini App: {item_name}")

    if category in ("drink", "custom_mix", "food"):
        await add_quest_progress(uid, "bar_social", 1)
        asyncio.create_task(_serve_with_bartender_animation(category, mention, item_name, is_vip))
    elif category == "song":
        await add_quest_progress(uid, "music_vibe", 1)
        rp_text = (
            f"🎶 <b>KAELEN — JUKEBOX REQUEST</b>\n\n"
            f"<i>Kaelen menyesuaikan piringan hitam di booth DJ atas permintaan {mention}.</i>\n"
            f"• <b>Lagu Dipilih:</b> <b>{item_name}</b>"
        )
        await kaelen_bot.send_message(cfg.GROUP_ID, rp_text, parse_mode=ParseMode.HTML)

    return web.json_response({"ok": True, "new_coins": new_coins})


async def start_webapp_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/me", handle_api_me)
    app.router.add_post("/api/order", handle_api_order)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
