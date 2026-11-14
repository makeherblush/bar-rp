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

DEFAULT_SERVICE_GIFS = {
    "drink": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbGZ4eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l41lJ8ywG1ncm9FXW/giphy.gif",
    "custom_mix": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbGZ4eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l41lJ8ywG1ncm9FXW/giphy.gif",
    "food": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExd2J4cW12bG14Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7TKP9ln2Dr6ze6f6/giphy.gif",
    "song": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExaG12bG14Y2Y1bTZ2Y2F2eG9yNnR5bW5wZ3J6b2R4Y2Y1bTZ2Y2F2eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/tJU72w9lPzUPe/giphy.gif",
}

EMBEDDED_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>The Velvet Hour — Menu, Mixology & Lounge</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #100b0f;
      --card: #1b1319;
      --gold: #dfb866;
      --gold-dim: rgba(223, 184, 102, 0.28);
      --cream: #f5efe6;
      --muted: #a69c95;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    html, body { background-color: #100b0f !important; color: #f5efe6 !important; padding-bottom: 90px; min-height: 100vh; }

    header {
      background: linear-gradient(180deg, #2b121b 0%, #100b0f 100%);
      padding: 16px 16px 10px;
      border-bottom: 1px solid var(--gold-dim);
      position: sticky; top: 0; z-index: 10;
    }
    .brand { font-size: 10px; letter-spacing: 2px; color: var(--gold); font-weight: 700; }
    .title-row { display: flex; justify-content: space-between; align-items: center; margin-top: 4px; }
    h1 { font-size: 19px; font-weight: 700; color: #f5efe6; }
    .badge-vc {
      background: rgba(223, 184, 102, 0.16);
      border: 1px solid var(--gold);
      color: var(--gold);
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
    }

    .tabs {
      display: flex; gap: 6px; padding: 10px 12px; overflow-x: auto;
      background: #100b0f; position: sticky; top: 64px; z-index: 9;
    }
    .tabs::-webkit-scrollbar { display: none; }
    .tab {
      flex: 0 0 auto; padding: 8px 12px; border-radius: 10px; border: 1px solid var(--gold-dim);
      background: var(--card); color: var(--muted); font-size: 12px; font-weight: 600;
      cursor: pointer;
    }
    .tab.active {
      background: linear-gradient(135deg, #4b1725, #29141d);
      border-color: var(--gold); color: var(--gold);
    }

    .section { display: none; padding: 4px 16px; }
    .section.active { display: block; }
    .sub-title {
      font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px;
      color: var(--gold); margin: 14px 0 8px; font-weight: 700;
    }

    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .item-card {
      background: var(--card); border: 1px solid var(--gold-dim);
      border-radius: 14px; padding: 12px; display: flex; flex-direction: column;
      justify-content: space-between;
    }
    .item-card.vip { border-color: rgba(223, 184, 102, 0.65); background: linear-gradient(160deg, #241914, #181116); }
    .item-emoji { font-size: 24px; margin-bottom: 6px; }
    .item-name { font-size: 13px; font-weight: 700; margin-bottom: 3px; color: #f5efe6; }
    .item-desc { font-size: 11px; color: var(--muted); line-height: 1.35; margin-bottom: 10px; }
    .item-footer { display: flex; justify-content: space-between; align-items: center; }
    .price { font-size: 11px; font-weight: 700; color: var(--gold); }

    .btn-order {
      background: var(--gold); color: #140f0b; border: none; border-radius: 8px;
      padding: 6px 11px; font-size: 11px; font-weight: 700; cursor: pointer;
    }

    .box-panel {
      background: var(--card); border: 1px solid var(--gold-dim);
      border-radius: 14px; padding: 14px; margin-top: 10px;
    }
    label { display: block; font-size: 12px; color: var(--gold); font-weight: 600; margin: 10px 0 6px; }
    select, .input-field {
      width: 100%; background: #100b0f; border: 1px solid var(--gold-dim);
      color: #f5efe6; padding: 11px; border-radius: 10px; font-size: 13px;
      outline: none;
    }
    .btn-full {
      width: 100%; background: linear-gradient(135deg, #dfb866, #b88c38);
      color: #140f0b; border: none; padding: 12px; border-radius: 10px;
      font-size: 13px; font-weight: 800; cursor: pointer; margin-top: 14px;
    }

    .toast {
      position: fixed; bottom: 20px; left: 16px; right: 16px;
      background: #23181e; border: 1px solid var(--gold); color: #f5efe6;
      padding: 12px 14px; border-radius: 12px; font-size: 13px; text-align: center;
      display: none; z-index: 99; box-shadow: 0 8px 24px rgba(0,0,0,0.6);
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">THE VELVET HOUR  •  LOUNGE CONCIERGE</div>
    <div class="title-row">
      <h1 id="guest-name">Selamat Malam</h1>
      <div class="badge-vc" id="guest-balance">50 VC</div>
    </div>
  </header>

  <div class="tabs">
    <div class="tab active" onclick="switchTab('drinks', this)">🍸 Minuman</div>
    <div class="tab" onclick="switchTab('mixology', this)">🧪 Racik Koktail</div>
    <div class="tab" onclick="switchTab('food', this)">🍽️ Hidangan</div>
    <div class="tab" onclick="switchTab('lapak', this)">🏪 Lapak</div>
    <div class="tab" onclick="switchTab('music', this)">🎶 Jukebox</div>
  </div>

  <div id="tab-drinks" class="section active">
    <div class="sub-title">Signature & Classic Drinks (Gratis)</div>
    <div class="grid" id="grid-drinks-reg"></div>
    <div class="sub-title">✨ VIP Reserve Cellar (Gratis VIP / 15 VC)</div>
    <div class="grid" id="grid-drinks-vip"></div>
  </div>

  <div id="tab-mixology" class="section">
    <div class="box-panel">
      <div style="font-size: 15px; font-weight: 700; color: var(--gold);">🧪 Custom Mixology Bar</div>
      <div style="font-size: 12px; color: var(--muted); margin-top: 4px;">
        Pilih bahan racikanmu sendiri—Julian akan mengocoknya langsung di meja bar grup (Biaya: <b>10 VC</b>, Gratis VIP).
      </div>

      <label>1. Dasar Minuman (Base)</label>
      <select id="mix-base">
        <option value="Aged Bourbon Whisky">🥃 Aged Bourbon Whisky</option>
        <option value="Botanical London Gin">🍸 Botanical London Gin</option>
        <option value="Silver Agave Tequila">🌵 Silver Agave Tequila</option>
        <option value="Dark Spiced Rum">🏴‍☠️ Dark Spiced Rum</option>
        <option value="Sparkling Non-Alcoholic Tonic">🫧 Sparkling Tonic (Non-Alkohol)</option>
      </select>

      <label>2. Campuran Rasa (Mixer & Syrup)</label>
      <select id="mix-syrup">
        <option value="Blood Orange & Bitters">🍊 Blood Orange & Aromatic Bitters</option>
        <option value="Velvet Rose & Lychee">🌹 Velvet Rose & Lychee Nectar</option>
        <option value="Smoked Honey & Espresso">☕ Smoked Honey & Cold Espresso</option>
        <option value="Crushed Mint & Yuzu Lime">🌿 Crushed Mint & Yuzu Lime</option>
      </select>

      <label>3. Hiasan Gelas (Garnish)</label>
      <select id="mix-garnish">
        <option value="Kulit Jeruk Bakar">🔥 Kulit Jeruk Bakar (Torched Peel)</option>
        <option value="Batang Kayu Manis Asap">🪵 Batang Kayu Manis Asap</option>
        <option value="Kelopak Mawar Merah">🥀 Kelopak Mawar Merah</option>
        <option value="Ceri Hitam Maraschino">🍒 Ceri Hitam Maraschino</option>
      </select>

      <label>4. Beri Nama Koktailmu (Opsional)</label>
      <input type="text" id="mix-name" class="input-field" placeholder="Contoh: Midnight Crimson" maxlength="32" />

      <button class="btn-full" onclick="submitCustomMix()">🍸 Minta Julian Racik Sekarang</button>
    </div>
  </div>

  <div id="tab-food" class="section">
    <div class="sub-title">Midnight Kitchen (Gratis)</div>
    <div class="grid" id="grid-food-reg"></div>
    <div class="sub-title">✨ Chef's VIP Gastronomy (Gratis VIP / 15 VC)</div>
    <div class="grid" id="grid-food-vip"></div>
  </div>

  <div id="tab-lapak" class="section">
    <div class="sub-title">🏪 Etalase Item Lapak Partner Aktif</div>
    <div class="grid" id="grid-lapak">
      <div style="color: var(--muted); font-size: 12px;">Memuat katalog lapak...</div>
    </div>
  </div>

  <div id="tab-music" class="section">
    <div class="box-panel">
      <div style="font-size: 15px; font-weight: 700; color: var(--gold);">🎧 Request Lagu ke Kaelen DJ</div>
      <div style="font-size: 12px; color: var(--muted); margin-top: 4px;">
        Lagu langsung masuk antrean & diumumkan Kaelen di grup (Biaya: <b>10 VC</b>, Gratis VIP).
      </div>
      <input type="text" id="song-input" class="input-field" style="margin-top: 12px;" placeholder="Contoh: Apocalypse - Cigarettes After Sex" />
      <button class="btn-full" onclick="submitSong()">🎶 Putar di Ruang Utama</button>
    </div>
  </div>

  <div id="toast" class="toast"></div>

  <script>
    const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
    if (tg) {
      tg.ready();
      tg.expand();
      if (tg.setHeaderColor) tg.setHeaderColor('#100b0f');
      if (tg.setBackgroundColor) tg.setBackgroundColor('#100b0f');
    }

    const MENUS = {
      drinksReg: [
        { code: "negroni", emoji: "🥃", name: "Classic Negroni", desc: "Gin, Campari & sweet vermouth.", price: 0 },
        { code: "whisky", emoji: "🧊", name: "Smoked Whisky", desc: "Bourbon dengan es batu kristal.", price: 0 },
        { code: "mojito", emoji: "🌿", name: "Velvet Mojito", desc: "Daun mint, lime & soda dingin.", price: 0 },
        { code: "espresso", emoji: "☕", name: "Double Espresso", desc: "Kopi panggang gelap pekat.", price: 0 },
        { code: "latte", emoji: "🥛", name: "Caramel Latte", desc: "Espresso lembut & karamel.", price: 0 },
        { code: "mocktail", emoji: "🍹", name: "Crimson Sunset", desc: "Delima, cranberry & tonic segar.", price: 0 },
      ],
      drinksVip: [
        { code: "vip_dom", emoji: "🍾", name: "Dom Pérignon Vintage", desc: "Sampanye Prancis eksklusif.", price: 15, vip: true },
        { code: "vip_blue", emoji: "💎", name: "Blue Label Reserve", desc: "Scotch langka aroma kayu ek.", price: 15, vip: true },
        { code: "vip_absinthe", emoji: "🧪", name: "Emerald Absinthe", desc: "Gula karamel terbakar.", price: 15, vip: true },
        { code: "vip_royal", emoji: "👑", name: "Velvet Royal Martini", desc: "Vodka dengan edible gold leaf.", price: 15, vip: true },
      ],
      foodReg: [
        { code: "steak", emoji: "🥩", name: "Ribeye Steak", desc: "Medium-rare saus lada hitam.", price: 0 },
        { code: "pasta", emoji: "🍝", name: "Truffle Carbonara", desc: "Spaghetti jamur truffle & keju.", price: 0 },
        { code: "fries", emoji: "🍟", name: "Truffle Fries", desc: "Kentang renyah tabur parmesan.", price: 0 },
        { code: "platter", emoji: "🧀", name: "Charcuterie Board", desc: "Keju artisan, buah & crackers.", price: 0 },
        { code: "tiramisu", emoji: "🍰", name: "Espresso Tiramisu", desc: "Krim mascarpone klasik Italia.", price: 0 },
        { code: "croissant", emoji: "🥐", name: "Butter Croissant", desc: "Pastry hangat mentega Prancis.", price: 0 },
      ],
      foodVip: [
        { code: "vip_a5", emoji: "🥩", name: "Miyazaki Wagyu A5", desc: "Wagyu Jepang lumer di mulut.", price: 15, vip: true },
        { code: "vip_caviar", emoji: "🥄", name: "Beluga Caviar", desc: "Kaviar hitam & krim asam.", price: 15, vip: true },
        { code: "vip_lobster", emoji: "🦞", name: "Poached Lobster", desc: "Lobster panggang mentega.", price: 15, vip: true },
        { code: "vip_gold", emoji: "🍫", name: "24K Gold Truffle", desc: "Ganache hitam lapis emas.", price: 15, vip: true },
      ]
    };

    let isVipUser = false;

    function showToast(msg) {
      const t = document.getElementById("toast");
      t.innerText = msg;
      t.style.display = "block";
      setTimeout(() => { t.style.display = "none"; }, 3500);
    }

    function renderGrid(list, containerId, category) {
      const box = document.getElementById(containerId);
      box.innerHTML = list.map(item => {
        const priceLabel = item.price === 0 ? "Gratis" : (isVipUser ? "Gratis (VIP)" : `${item.price} VC`);
        return `
          <div class="item-card ${item.vip ? 'vip' : ''}">
            <div>
              <div class="item-emoji">${item.emoji}</div>
              <div class="item-name">${item.name}</div>
              <div class="item-desc">${item.desc}</div>
            </div>
            <div class="item-footer">
              <span class="price">${priceLabel}</span>
              <button class="btn-order" onclick="placeOrder('${category}', '${item.code}', '${item.name}', ${item.price})">Pesan</button>
            </div>
          </div>
        `;
      }).join("");
    }

    function renderAllMenus() {
      renderGrid(MENUS.drinksReg, "grid-drinks-reg", "drink");
      renderGrid(MENUS.drinksVip, "grid-drinks-vip", "drink");
      renderGrid(MENUS.foodReg, "grid-food-reg", "food");
      renderGrid(MENUS.foodVip, "grid-food-vip", "food");
    }

    function switchTab(tabName, el) {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
      el.classList.add("active");
      document.getElementById("tab-" + tabName).classList.add("active");
    }

    async function loadUserProfile() {
      if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) {
        document.getElementById("guest-name").innerText = tg.initDataUnsafe.user.first_name;
      }
      try {
        const res = await fetch("/api/me", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ initData: tg ? tg.initData : "" })
        });
        const data = await res.json();
        if (data.ok) {
          isVipUser = data.is_vip;
          document.getElementById("guest-balance").innerText = `${data.coins} VC ${data.is_vip ? '• VIP' : ''}`;
          renderAllMenus();
          renderLapak(data.shop_items || []);
        }
      } catch (e) {
        renderAllMenus();
      }
    }

    function renderLapak(items) {
      const box = document.getElementById("grid-lapak");
      if (!items.length) {
        box.innerHTML = `<div style="color: var(--muted); font-size: 12px; grid-column: 1 / -1;">Belum ada item dijual di lapak partner saat ini.</div>`;
        return;
      }
      box.innerHTML = items.map(it => `
        <div class="item-card">
          <div>
            <div class="item-emoji">🛍️</div>
            <div class="item-name">${it.title}</div>
            <div class="item-desc">Toko: ${it.shop_name}</div>
          </div>
          <div class="item-footer">
            <span class="price">${it.price_vc} VC</span>
            <button class="btn-order" onclick="buyLapakItem(${it.id}, '${it.title.replace(/'/g, "\\'")}', ${it.price_vc})">Beli</button>
          </div>
        </div>
      `).join("");
    }

    async function buyLapakItem(itemId, title, price) {
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
      showToast(`Membeli ${title}...`);
      const res = await fetch("/api/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg ? tg.initData : "", category: "lapak", item_id: itemId, item_name: title, price: price })
      });
      const data = await res.json();
      if (data.ok) {
        showToast("✅ Berhasil dibeli! Cek nota pembelian di PC Hans.");
        if (tg) setTimeout(() => tg.close(), 1000);
      } else {
        showToast("⚠️ " + (data.error || "Gagal membeli item."));
      }
    }

    async function placeOrder(category, code, itemName, price) {
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("medium");
      showToast(`Julian sedang meracik ${itemName}...`);
      const res = await fetch("/api/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg ? tg.initData : "", category, code, item_name: itemName, price })
      });
      const data = await res.json();
      if (data.ok) {
        document.getElementById("guest-balance").innerText = `${data.new_coins} VC ${isVipUser ? '• VIP' : ''}`;
        showToast("✅ Pesanan dikirim ke meja bar grup!");
        if (tg) setTimeout(() => tg.close(), 800);
      } else {
        showToast("⚠️ " + (data.error || "Gagal memesan."));
      }
    }

    async function submitCustomMix() {
      const base = document.getElementById("mix-base").value;
      const syrup = document.getElementById("mix-syrup").value;
      const garnish = document.getElementById("mix-garnish").value;
      const customName = document.getElementById("mix-name").value.trim() || "Velvet Custom Signature";
      const fullLabel = `${customName} (${base} + ${syrup}, garnish ${garnish})`;
      await placeOrder("custom_mix", "mix", fullLabel, 10);
    }

    async function submitSong() {
      const song = document.getElementById("song-input").value.trim();
      if (song.length < 3) return showToast("⚠️ Ketik judul lagu terlebih dahulu.");
      await placeOrder("song", "reqsong", song, 10);
    }

    renderAllMenus();
    loadUserProfile();
  </script>
</body>
</html>"""


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


async def _ensure_webapp_user(conn, tg_user: dict):
    uid = int(tg_user["id"])
    username = tg_user.get("username")
    full_name = f"{tg_user.get('first_name', '')} {tg_user.get('last_name', '')}".strip() or "Tamu"
    await conn.execute("""
        INSERT INTO users (user_id, username, full_name, coins, charm_points)
        VALUES ($1, $2, $3, 50, 0)
        ON CONFLICT (user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            full_name = EXCLUDED.full_name;
    """, uid, username, full_name)


async def _get_custom_service_media(category: str) -> tuple[str, str]:
    key = f"menu_{category}"
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT file_id, media_type FROM gift_custom_media WHERE gift_code = $1", key)
            if row:
                return row["file_id"], row["media_type"]
    except Exception:
        pass
    return DEFAULT_SERVICE_GIFS.get(category, DEFAULT_SERVICE_GIFS["drink"]), "animation"


async def _serve_with_bartender_animation(
    category: str,
    mention: str,
    item_name: str,
    is_vip: bool,
    thread_id: int | None = None,
):
    vip_tag = " 👑" if is_vip else ""
    send_kwargs = {"message_thread_id": thread_id} if thread_id else {}

    try:
        await julian_bot.send_chat_action(cfg.GROUP_ID, ChatAction.TYPING, **send_kwargs)
    except Exception:
        pass

    if category in ("drink", "custom_mix"):
        prep_msg = await julian_bot.send_message(
            cfg.GROUP_ID,
            f"🧊 <i>Julian menyiapkan gelas kristal dingin dan mengocok shaker untuk {mention}...</i>",
            parse_mode=ParseMode.HTML,
            **send_kwargs,
        )
        await asyncio.sleep(1.5)
        try:
            await julian_bot.delete_message(cfg.GROUP_ID, prep_msg.message_id)
        except Exception:
            pass

        action_line = (
            f"🧪 Julian meracik koktail kustom <b>{item_name}</b> dan menggesernya di atas meja bar untuk {mention}{vip_tag}."
            if category == "custom_mix"
            else f"🍸 Julian menggeser segelas <b>{item_name}</b> di atas meja bar mahoni menuju {mention}{vip_tag}."
        )
        caption = f"{action_line}\n\n<i>\"Silakan dinikmati malam ini.\"</i>"

        media_src, mtype = await _get_custom_service_media(category)
        try:
            if mtype == "photo":
                await julian_bot.send_photo(cfg.GROUP_ID, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
            else:
                await julian_bot.send_animation(cfg.GROUP_ID, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        except Exception:
            await julian_bot.send_message(cfg.GROUP_ID, caption, parse_mode=ParseMode.HTML, **send_kwargs)

    elif category == "food":
        prep_msg = await julian_bot.send_message(
            cfg.GROUP_ID,
            f"🔥 <i>Chef di dapur sedang menata hidangan hangat untuk {mention}...</i>",
            parse_mode=ParseMode.HTML,
            **send_kwargs,
        )
        await asyncio.sleep(1.7)
        try:
            await julian_bot.delete_message(cfg.GROUP_ID, prep_msg.message_id)
        except Exception:
            pass

        caption = (
            f"🍽️ Hidangan hangat <b>{item_name}</b> baru saja keluar dari dapur dan disajikan ke meja {mention}{vip_tag}.\n\n"
            f"<i>\"Selamat menikmati santapan malam Anda.\"</i>"
        )
        media_src, mtype = await _get_custom_service_media("food")
        try:
            if mtype == "photo":
                await julian_bot.send_photo(cfg.GROUP_ID, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
            else:
                await julian_bot.send_animation(cfg.GROUP_ID, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **send_kwargs)
        except Exception:
            await julian_bot.send_message(cfg.GROUP_ID, caption, parse_mode=ParseMode.HTML, **send_kwargs)


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(
        text=EMBEDDED_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


async def handle_api_me(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = _authenticate_user(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "error": "Sesi tidak valid"}, status=401)

    uid = int(tg_user["id"])
    async with db.pool.acquire() as conn:
        await _ensure_webapp_user(conn, tg_user)
        row = await conn.fetchrow("SELECT coins, is_vip, vip_until FROM users WHERE user_id = $1", uid)
        items = await conn.fetch("""
            SELECT si.id, si.title, si.price_vc, ps.shop_name
            FROM shop_items si
            JOIN partner_shops ps ON si.shop_id = ps.id
            WHERE si.is_sold = FALSE
            ORDER BY si.id DESC LIMIT 20
        """)

    coins = row["coins"] if row else 50
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

    if category == "lapak":
        item_id = int(body.get("item_id", 0))
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                await _ensure_webapp_user(conn, tg_user)
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
                f"🧾 <b>Nota Pembelian — {html.escape(item['shop_name'])}</b>\n"
                f"• Item: <b>{html.escape(item['title'])}</b> ({price} VC)\n"
                f"• Catatan: {html.escape(item['content_text'] or '-')}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return web.json_response({"ok": True, "new_coins": new_coins})

    item_name = html.escape(str(body.get("item_name", "Menu"))[:100])
    base_price = int(body.get("price", 0))

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_webapp_user(conn, tg_user)
            row = await conn.fetchrow(
                "SELECT coins, is_vip, vip_until, last_thread_id FROM users WHERE user_id = $1 FOR UPDATE",
                uid,
            )

            is_vip = bool(row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
            final_cost = 0 if is_vip else max(0, base_price)
            coins = row["coins"] or 0
            thread_id = row["last_thread_id"] or getattr(cfg, "DEFAULT_THREAD_ID", None)

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
        asyncio.create_task(_serve_with_bartender_animation(category, mention, item_name, is_vip, thread_id))
    elif category == "song":
        await add_quest_progress(uid, "music_vibe", 1)
        send_kwargs = {"message_thread_id": thread_id} if thread_id else {}
        rp_text = (
            f"🎶 Kaelen memutar piringan hitam di booth DJ — <b>{item_name}</b> mengalun di seluruh ruangan atas permintaan {mention}."
        )
        media_src, mtype = await _get_custom_service_media("song")
        try:
            if mtype == "photo":
                await kaelen_bot.send_photo(cfg.GROUP_ID, photo=media_src, caption=rp_text, parse_mode=ParseMode.HTML, **send_kwargs)
            else:
                await kaelen_bot.send_animation(cfg.GROUP_ID, animation=media_src, caption=rp_text, parse_mode=ParseMode.HTML, **send_kwargs)
        except Exception:
            await kaelen_bot.send_message(cfg.GROUP_ID, rp_text, parse_mode=ParseMode.HTML, **send_kwargs)

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
