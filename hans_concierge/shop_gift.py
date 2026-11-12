import html
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import shared.database as db
from shared.config import GROUP_ID
from hans_concierge.helpers import bot, log_wallet_tx, main_lobby_kb

router = Router()

GIFT_CATALOG = {
    "rose": ("🌹 Single Velvet Rose", 25, 10),
    "champagne": ("🍾 Vintage Champagne Bottle", 75, 35),
    "diamond": ("💎 Midnight Diamond Brooch", 150, 80),
}

class ShopAddItemState(StatesGroup):
    waiting_media = State()
    waiting_title = State()
    waiting_price = State()

class GiftState(StatesGroup):
    waiting_target = State()

# --- LAPAK PARTNER (LIHAT & BELI ITEM DENGAN VC) ---
async def send_lapak_list(target_obj: types.Message | types.CallbackQuery):
    async with db.pool.acquire() as conn:
        shops = await conn.fetch("""
            SELECT s.id, s.shop_name, s.owner_username, COUNT(i.id) as cnt
            FROM partner_shops s
            LEFT JOIN shop_items i ON s.id = i.shop_id AND i.is_sold = FALSE
            GROUP BY s.id, s.shop_name, s.owner_username
            ORDER BY s.id ASC
        """)

    if not shops:
        txt = "🏪 <i>Belum ada lapak partner yang terdaftar saat ini.</i>"
        if isinstance(target_obj, types.CallbackQuery):
            return await target_obj.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())
        return await target_obj.answer(txt, parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

    buttons = []
    for s in shops:
        buttons.append([
            InlineKeyboardButton(
                text=f"🏪 {s['shop_name']} ({s['cnt']} item)",
                callback_data=f"viewshop_{s['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi Utama", callback_data="back_lobby")])

    txt = "🏪 <b>KATALOG LAPAK PARTNER — THE VELVET HOUR</b>\n\nPilih toko di bawah ini untuk melihat koleksi foto/stiker yang dijual:"
    if isinstance(target_obj, types.CallbackQuery):
        await target_obj.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await target_obj.answer(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "browse_lapak")
async def cb_browse_lapak(call: types.CallbackQuery):
    await call.answer()
    await send_lapak_list(call)

@router.callback_query(F.data.startswith("viewshop_"))
async def cb_view_shop(call: types.CallbackQuery):
    await call.answer()
    shop_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    async with db.pool.acquire() as conn:
        shop = await conn.fetchrow("SELECT * FROM partner_shops WHERE id = $1", shop_id)
        if not shop:
            return await call.message.edit_text("Toko tidak ditemukan.", reply_markup=main_lobby_kb())
        items = await conn.fetch(
            "SELECT id, title, price_vc FROM shop_items WHERE shop_id = $1 AND is_sold = FALSE ORDER BY id ASC",
            shop_id
        )

    buttons = []
    for it in items:
        buttons.append([
            InlineKeyboardButton(
                text=f"🖼️ {it['title']} — {it['price_vc']} VC",
                callback_data=f"previewitem_{it['id']}"
            )
        ])

    if shop["owner_id"] == user_id:
        buttons.append([InlineKeyboardButton(text="➕ Tambah Dagangan Baru", callback_data=f"additem_{shop_id}")])
        buttons.append([InlineKeyboardButton(text="🗑️ Hapus Dagangan", callback_data=f"delitemmenu_{shop_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Daftar Toko", callback_data="browse_lapak")])
    await call.message.edit_text(
        f"🏪 <b>{html.escape(shop['shop_name'])}</b>\n"
        f"• <b>Pemilik:</b> @{html.escape(shop['owner_username'] or 'Partner')}\n\n"
        "<i>Klik item di bawah untuk melihat pratinjau & membeli:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("previewitem_"))
async def cb_preview_item(call: types.CallbackQuery):
    await call.answer()
    item_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        it = await conn.fetchrow("SELECT * FROM shop_items WHERE id = $1 AND is_sold = FALSE", item_id)
    if not it:
        return await call.message.answer("Item sudah terjual atau dihapus.", reply_markup=main_lobby_kb())

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Beli Sekarang ({it['price_vc']} VC)", callback_data=f"buyitem_{it['id']}")],
        [InlineKeyboardButton(text="⬅️ Kembali ke Toko", callback_data=f"viewshop_{it['shop_id']}")]
    ])
    caption = f"🏷️ <b>{html.escape(it['title'])}</b>\n💰 <b>Harga:</b> {it['price_vc']} Velvet Coins"

    if it["file_type"] == "sticker":
        await call.message.answer_sticker(it["file_id"])
        await call.message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await call.message.answer_photo(it["file_id"], caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)

@router.callback_query(F.data.startswith("buyitem_"))
async def cb_buy_item(call: types.CallbackQuery):
    item_id = int(call.data.split("_")[1])
    buyer = call.from_user

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            it = await conn.fetchrow("SELECT * FROM shop_items WHERE id = $1 AND is_sold = FALSE FOR UPDATE", item_id)
            if not it:
                return await call.answer("Maaf, item ini baru saja terjual!", show_alert=True)

            shop = await conn.fetchrow("SELECT * FROM partner_shops WHERE id = $1", it["shop_id"])
            if shop["owner_id"] == buyer.id:
                return await call.answer("Kamu tidak bisa membeli daganganmu sendiri.", show_alert=True)

            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", buyer.id)
            price = it["price_vc"]
            if (coins or 0) < price:
                return await call.answer(f"Saldo tidak cukup! Butuh {price} VC.", show_alert=True)

            await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", price, buyer.id)
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", price, shop["owner_id"])
            await conn.execute("UPDATE shop_items SET is_sold = TRUE WHERE id = $1", item_id)

            await log_wallet_tx(conn, buyer.id, -price, f"Beli '{it['title']}' di {shop['shop_name']}")
            await log_wallet_tx(conn, shop["owner_id"], price, f"Penjualan '{it['title']}' ke {buyer.first_name}")

    await call.answer("Pembelian berhasil!", show_alert=True)
    await call.message.answer(
        f"✅ <b>TRANSAKSI LAPAK BERHASIL!</b>\n\n"
        f"Kamu membeli <b>{html.escape(it['title'])}</b> dari <b>{html.escape(shop['shop_name'])}</b> seharga <b>{price} VC</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_lobby_kb()
    )
    try:
        await bot.send_message(
            shop["owner_id"],
            f"💰 <b>DAGANGAN TERJUAL!</b>\n\n"
            f"Item <b>{html.escape(it['title'])}</b> di lapak <b>{html.escape(shop['shop_name'])}</b> dibeli oleh "
            f"<b>{html.escape(buyer.first_name)}</b>! Saldo <b>+{price} VC</b> telah masuk ke dompetmu.",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

# --- KELOLA DAGANGAN PEMILIK LAPAK ---
@router.callback_query(F.data.startswith("additem_"))
async def cb_add_item_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    shop_id = int(call.data.split("_")[1])
    await state.update_data(shop_id=shop_id)
    await state.set_state(ShopAddItemState.waiting_media)
    await call.message.answer("📤 Kirimkan <b>Foto</b> atau <b>Stiker</b> yang ingin dijual di lapakmu (atau ketik /cancel):")

@router.message(ShopAddItemState.waiting_media, F.chat.type == "private")
async def fsm_item_media(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Dibatalkan.", reply_markup=main_lobby_kb())

    if message.photo:
        await state.update_data(file_id=message.photo[-1].file_id, file_type="photo")
    elif message.sticker:
        await state.update_data(file_id=message.sticker.file_id, file_type="sticker")
    else:
        return await message.answer("Harap kirim berupa <b>Foto</b> atau <b>Stiker</b>.")

    await state.set_state(ShopAddItemState.waiting_title)
    await message.answer("📝 Masukkan <b>Nama / Judul Item</b> (Contoh: <i>Banner Vintage Couple</i>):")

@router.message(ShopAddItemState.waiting_title, F.chat.type == "private")
async def fsm_item_title(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Dibatalkan.", reply_markup=main_lobby_kb())
    await state.update_data(title=message.text.strip()[:50])
    await state.set_state(ShopAddItemState.waiting_price)
    await message.answer("💰 Masukkan <b>Harga dalam Velvet Coins (angka saja)</b> (Contoh: <code>75</code>):")

@router.message(ShopAddItemState.waiting_price, F.chat.type == "private")
async def fsm_item_price(message: types.Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        return await message.answer("Masukkan angka harga VC yang valid (minimal 5).")
    price = int(message.text)
    if price < 5:
        return await message.answer("Harga minimal adalah 5 VC.")

    data = await state.get_data()
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO shop_items (shop_id, title, file_id, file_type, price_vc)
            VALUES ($1, $2, $3, $4, $5)
        """, data["shop_id"], data["title"], data["file_id"], data["file_type"], price)

    await state.clear()
    await message.answer(
        f"✅ Item <b>{html.escape(data['title'])}</b> ({price} VC) berhasil dipajang di lapak!",
        parse_mode=ParseMode.HTML,
        reply_markup=main_lobby_kb()
    )

@router.callback_query(F.data.startswith("delitemmenu_"))
async def cb_del_item_menu(call: types.CallbackQuery):
    await call.answer()
    shop_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        items = await conn.fetch("SELECT id, title, price_vc FROM shop_items WHERE shop_id = $1 AND is_sold = FALSE", shop_id)
    if not items:
        return await call.message.answer("Tidak ada item aktif untuk dihapus.")
    buttons = [[InlineKeyboardButton(text=f"❌ Hapus: {i['title']} ({i['price_vc']} VC)", callback_data=f"rmitem_{i['id']}")] for i in items]
    buttons.append([InlineKeyboardButton(text="⬅️ Kembali", callback_data=f"viewshop_{shop_id}")])
    await call.message.edit_text("Pilih item yang ingin dihapus:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("rmitem_"))
async def cb_rm_item(call: types.CallbackQuery):
    item_id = int(call.data.split("_")[1])
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM shop_items WHERE id = $1", item_id)
    await call.answer("Item dihapus!", show_alert=True)
    await send_lapak_list(call)

# --- KIRIM GIFT KE TAMU LAIN ---
@router.callback_query(F.data == "menu_gift")
async def cb_menu_gift(call: types.CallbackQuery):
    await call.answer()
    buttons = []
    for k, (label, cost, charm) in GIFT_CATALOG.items():
        buttons.append([InlineKeyboardButton(text=f"{label} — {cost} VC (+{charm} Charm)", callback_data=f"pickgift_{k}")])
    buttons.append([InlineKeyboardButton(text="🏠 Kembali ke Lobi", callback_data="back_lobby")])
    await call.message.edit_text(
        "🎁 <b>KATALOG HADIAH MEJA LOUNGE</b>\n\nPilih hadiah yang ingin dikirimkan ke tamu lain di ruang utama:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("pickgift_"))
async def cb_pick_gift(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    gift_key = call.data.replace("pickgift_", "")
    if gift_key not in GIFT_CATALOG:
        return
    await state.update_data(gift_key=gift_key)
    await state.set_state(GiftState.waiting_target)
    await call.message.answer(
        "✍️ Ketik <b>@username</b> tamu penerima hadiah (Contoh: <code>@clara</code>), atau ketik /cancel untuk batal:",
        parse_mode=ParseMode.HTML
    )

@router.message(GiftState.waiting_target, F.chat.type == "private")
async def fsm_send_gift(message: types.Message, state: FSMContext):
    if not message.text or message.text.startswith("/cancel"):
        await state.clear()
        return await message.answer("Pengiriman gift dibatalkan.", reply_markup=main_lobby_kb())

    target_uname = message.text.strip().lstrip("@").lower()
    data = await state.get_data()
    gift_key = data["gift_key"]
    label, cost, charm = GIFT_CATALOG[gift_key]
    sender = message.from_user

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            target = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE LOWER(username) = $1", target_uname)
            if not target:
                return await message.answer(f"Tamu <b>@{html.escape(target_uname)}</b> tidak ditemukan di daftar buku tamu.", parse_mode=ParseMode.HTML)
            if target["user_id"] == sender.id:
                return await message.answer("Kamu tidak bisa mengirim gift ke dirimu sendiri.")

            coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1 FOR UPDATE", sender.id)
            if (coins or 0) < cost:
                await state.clear()
                return await message.answer(f"Saldo tidak cukup (butuh <b>{cost} VC</b>).", parse_mode=ParseMode.HTML, reply_markup=main_lobby_kb())

            await conn.execute("UPDATE users SET coins = coins - $1, gifts_sent_vc = COALESCE(gifts_sent_vc, 0) + $1 WHERE user_id = $2", cost, sender.id)
            await conn.execute("UPDATE users SET charm_points = charm_points + $1 WHERE user_id = $2", charm, target["user_id"])
            await log_wallet_tx(conn, sender.id, -cost, f"Kirim {label} ke {target['full_name']}")

    await state.clear()
    await message.answer(
        f"🎁 <b>HADIAH TERKIRIM!</b>\n\n<b>{label}</b> telah diantarkan ke meja <b>{html.escape(target['full_name'])}</b> (<b>+{charm} Charm Points</b>)!",
        parse_mode=ParseMode.HTML,
        reply_markup=main_lobby_kb()
    )
    try:
        await bot.send_message(
            GROUP_ID,
            f"🎁 <b>KIRIMAN HADIAH MEJA LOUNGE!</b>\n\n"
            f"<i>Concierge Hans melangkah ke ruang utama membawa {label} untuk "
            f"<a href='tg://user?id={target['user_id']}'>{html.escape(target['full_name'])}</a> dari <b>{html.escape(sender.first_name)}</b>!</i>\n\n"
            f"✨ <b>+{charm} Charm Points</b> untuk <b>{html.escape(target['full_name'])}</b>!",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
