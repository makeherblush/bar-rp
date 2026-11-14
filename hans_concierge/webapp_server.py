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
  <title>The Velvet Hour — Member Pass & Lounge</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg-base: #0a0608;
      --glass-bg: rgba(28, 17, 23, 0.56);
      --glass-strong: rgba(36, 21, 29, 0.74);
      --glass-border: rgba(226, 188, 108, 0.28);
      --glass-highlight: rgba(255, 255, 255, 0.08);
      --gold: #e2bc6c;
      --gold-soft: rgba(226, 188, 108, 0.16);
      --cream: #f7f1e8;
      --muted: #b0a39c;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
      -webkit-tap-highlight-color: transparent;
    }

    html, body {
      min-height: 100vh;
      background-color: var(--bg-base) !important;
      background-image:
        radial-gradient(circle at 15% 10%, rgba(122, 24, 52, 0.42) 0%, transparent 48%),
        radial-gradient(circle at 88% 28%, rgba(196, 148, 62, 0.22) 0%, transparent 45%),
        radial-gradient(circle at 50% 90%, rgba(84, 18, 38, 0.35) 0%, transparent 55%);
      background-attachment: fixed;
      color: var(--cream) !important;
      padding: 14px 14px 104px;
      overflow-x: hidden;
    }

    /* === 3D FLIP ENGINE === */
    .flip-scene {
      perspective: 1200px;
      width: 100%;
    }
    .flip-card {
      position: relative;
      width: 100%;
      transform-style: preserve-3d;
      -webkit-transform-style: preserve-3d;
      transition: transform 0.65s cubic-bezier(0.22, 1, 0.36, 1);
      cursor: pointer;
    }
    .flip-card.is-flipped {
      transform: rotateY(180deg);
    }
    .flip-face {
      position: relative;
      width: 100%;
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
      background: var(--glass-bg);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid var(--glass-border);
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.55), inset 0 1px 0 var(--glass-highlight);
    }
    .flip-back {
      position: absolute;
      inset: 0;
      transform: rotateY(180deg);
      background: var(--glass-strong);
    }
    .flip-card:not(.is-flipped) .flip-back { pointer-events: none; }
    .flip-card.is-flipped .flip-front { pointer-events: none; }

    /* === MEMBER PASS HEADER CARD === */
    .member-scene {
      margin-bottom: 16px;
    }
    .member-face {
      border-radius: 22px;
      padding: 16px 18px;
      min-height: 168px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      overflow: hidden;
    }
    .member-face::before {
      content: "";
      position: absolute;
      top: -40%;
      right: -20%;
      width: 180px;
      height: 180px;
      background: radial-gradient(circle, rgba(226, 188, 108, 0.22), transparent 70%);
      pointer-events: none;
    }

    .card-top-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 10px;
      letter-spacing: 1.8px;
      color: var(--gold);
      font-weight: 700;
    }
    .flip-hint {
      font-size: 10px;
      letter-spacing: 0.4px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.06);
      padding: 3px 8px;
      border-radius: 20px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }

    .profile-row {
      display: flex;
      align-items: center;
      gap: 13px;
      margin: 12px 0;
    }
    .avatar-wrap {
      width: 52px;
      height: 52px;
      border-radius: 50%;
      padding: 2px;
      background: linear-gradient(135deg, #f3d58d, #9c7228);
      flex-shrink: 0;
      box-shadow: 0 4px 14px rgba(226, 188, 108, 0.25);
    }
    .avatar-img, .avatar-fallback {
      width: 100%;
      height: 100%;
      border-radius: 50%;
      object-fit: cover;
      display: block;
    }
    .avatar-fallback {
      background: #1f1218;
      color: var(--gold);
      font-weight: 800;
      font-size: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .profile-info {
      min-width: 0;
      flex: 1;
    }
    .profile-name {
      font-size: 17px;
      font-weight: 700;
      color: var(--cream);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .profile-usn {
      font-size: 12px;
      color: var(--muted);
      margin-top: 2px;
    }

    .stats-strip {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .stat-pill {
      flex: 1;
      background: rgba(12, 7, 10, 0.55);
      border: 1px solid rgba(226, 188, 108, 0.2);
      border-radius: 12px;
      padding: 7px 10px;
      display: flex;
      flex-direction: column;
    }
    .stat-label {
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: var(--muted);
    }
    .stat-val {
      font-size: 13px;
      font-weight: 700;
      color: var(--gold);
      margin-top: 1px;
    }

    /* === MEMBER PASS BACK (REFERRAL) === */
    .ref-box {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(10, 6, 8, 0.65);
      border: 1px dashed var(--gold);
      border-radius: 12px;
      padding: 8px 12px;
      margin: 8px 0;
    }
    .ref-code-text {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 15px;
      font-weight: 800;
      letter-spacing: 1.5px;
      color: var(--gold);
    }
    .btn-copy-ref {
      background: var(--gold);
      color: #140d09;
      border: none;
      border-radius: 8px;
      padding: 6px 10px;
      font-size: 11px;
      font-weight: 800;
      cursor: pointer;
    }
    .ref-claim-row {
      display: flex;
      gap: 6px;
      margin-top: 4px;
    }
    .ref-input {
      flex: 1;
      background: rgba(10, 6, 8, 0.65);
      border: 1px solid var(--glass-border);
      color: var(--cream);
      border-radius: 8px;
      padding: 6px 10px;
      font-size: 11px;
      outline: none;
      text-transform: uppercase;
    }
    .btn-claim-ref {
      background: rgba(226, 188, 108, 0.2);
      border: 1px solid var(--gold);
      color: var(--gold);
      border-radius: 8px;
      padding: 6px 10px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
    }

    /* === SECTIONS & GRID === */
    .section { display: none; }
    .section.active { display: block; animation: fadeIn 0.25s ease; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

    .sec-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin: 12px 2px 10px;
    }
    .sec-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 1.6px;
      color: var(--gold);
      font-weight: 700;
    }
    .sec-sub {
      font-size: 10px;
      color: var(--muted);
    }

    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 11px;
    }

    /* === FLIP MENU / LAPAK CARDS === */
    .item-card-inner {
      height: 146px;
    }
    .item-face {
      height: 100%;
      border-radius: 18px;
      padding: 13px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .item-face.vip-glow {
      border-color: rgba(226, 188, 108, 0.62);
      background: linear-gradient(155deg, rgba(52, 32, 22, 0.68), rgba(24, 14, 19, 0.64));
    }
    .item-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }
    .item-emoji {
      font-size: 28px;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,0.4));
    }
    .price-pill {
      font-size: 10px;
      font-weight: 700;
      color: var(--gold);
      background: var(--gold-soft);
      border: 1px solid rgba(226, 188, 108, 0.35);
      padding: 3px 8px;
      border-radius: 20px;
    }
    .item-name {
      font-size: 13.5px;
      font-weight: 700;
      color: var(--cream);
      line-height: 1.25;
    }
    .item-tap-label {
      font-size: 10px;
      color: var(--muted);
      margin-top: 3px;
    }

    .item-desc-back {
      font-size: 11.5px;
      color: var(--cream);
      line-height: 1.4;
      opacity: 0.92;
    }
    .btn-order-glass {
      width: 100%;
      background: linear-gradient(135deg, #e6c375, #b88a35);
      color: #140d09;
      border: none;
      border-radius: 10px;
      padding: 8px;
      font-size: 11.5px;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(226, 188, 108, 0.25);
    }

    /* === GLASS PANEL (MIXOLOGY & JUKEBOX) === */
    .glass-panel {
      background: var(--glass-bg);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid var(--glass-border);
      border-radius: 20px;
      padding: 16px;
      box-shadow: 0 12px 30px rgba(0, 0, 0, 0.45);
    }
    .panel-title {
      font-size: 15px;
      font-weight: 700;
      color: var(--gold);
    }
    .panel-desc {
      font-size: 12px;
      color: var(--muted);
      margin-top: 4px;
      line-height: 1.4;
    }
    label {
      display: block;
      font-size: 11px;
      color: var(--gold);
      font-weight: 600;
      margin: 12px 0 5px;
      letter-spacing: 0.5px;
    }
    select, .glass-input {
      width: 100%;
      background: rgba(12, 7, 10, 0.65);
      border: 1px solid var(--glass-border);
      color: var(--cream);
      padding: 11px 12px;
      border-radius: 12px;
      font-size: 13px;
      outline: none;
    }
    .btn-primary-full {
      width: 100%;
      background: linear-gradient(135deg, #e6c375, #b88a35);
      color: #140d09;
      border: none;
      padding: 13px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
      margin-top: 15px;
      box-shadow: 0 6px 18px rgba(226, 188, 108, 0.25);
    }

    /* === FLOATING GLASS DOCK === */
    .glass-dock {
      position: fixed;
      bottom: 14px;
      left: 14px;
      right: 14px;
      background: rgba(24, 14, 19, 0.78);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--glass-border);
      border-radius: 24px;
      padding: 6px;
      display: flex;
      justify-content: space-between;
      gap: 4px;
      z-index: 50;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.75), inset 0 1px 0 var(--glass-highlight);
    }
    .dock-item {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 7px 4px;
      border-radius: 18px;
      color: var(--muted);
      font-size: 10px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }
    .dock-icon {
      font-size: 17px;
      margin-bottom: 2px;
    }
    .dock-item.active {
      background: linear-gradient(135deg, rgba(226, 188, 108, 0.24), rgba(122, 24, 52, 0.38));
      color: var(--gold);
      border: 1px solid rgba(226, 188, 108, 0.35);
    }

    /* === GLASS TOAST === */
    .toast {
      position: fixed;
      top: 16px;
      left: 16px;
      right: 16px;
      background: rgba(28, 17, 23, 0.9);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      border: 1px solid var(--gold);
      color: var(--cream);
      padding: 12px 16px;
      border-radius: 14px;
      font-size: 12.5px;
      font-weight: 600;
      text-align: center;
      display: none;
      z-index: 99;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.65);
    }
  </style>
</head>
<body>

  <!-- === 3D FLIP MEMBER PASS CARD === -->
  <div class="flip-scene member-scene">
    <div class="flip-card" id="member-flip-card" onclick="toggleMemberCard(event)">
      <!-- SISI DEPAN: PP, NAMA, USERNAME, SALDO, CHARM, STATUS -->
      <div class="flip-face member-face flip-front">
        <div class="card-top-meta">
          <span>THE VELVET HOUR  •  PASS</span>
          <span class="flip-hint">Referral ↻</span>
        </div>

        <div class="profile-row">
          <div class="avatar-wrap" id="avatar-container">
            <div class="avatar-fallback" id="avatar-initial">V</div>
          </div>
          <div class="profile-info">
            <div class="profile-name" id="guest-name">Tamu Lounge</div>
            <div class="profile-usn" id="guest-usn">@velvetguest</div>
          </div>
        </div>

        <div class="stats-strip">
          <div class="stat-pill">
            <span class="stat-label">Saldo</span>
            <span class="stat-val" id="guest-balance">50 VC</span>
          </div>
          <div class="stat-pill">
            <span class="stat-label">Charm</span>
            <span class="stat-val" id="guest-charm">0 ✨</span>
          </div>
          <div class="stat-pill">
            <span class="stat-label">Tier</span>
            <span class="stat-val" id="guest-tier">GUEST</span>
          </div>
        </div>
      </div>

      <!-- SISI BELAKANG: KODE REFERRAL & KLAIM -->
      <div class="flip-face member-face flip-back">
        <div class="card-top-meta">
          <span>INVITE & REWARDS (+25 VC)</span>
          <span class="flip-hint">Profil ↻</span>
        </div>

        <div class="ref-box" onclick="event.stopPropagation()">
          <div>
            <div style="font-size: 9px; color: var(--muted); letter-spacing: 0.8px;">KODE REFERRAL KAMU (<span id="ref-count">0</span> Teman)</div>
            <div class="ref-code-text" id="my-ref-code">VH-00000</div>
          </div>
          <button class="btn-copy-ref" onclick="copyReferral(event)">Salin</button>
        </div>

        <div id="claim-area" class="ref-claim-row" onclick="event.stopPropagation()">
          <input type="text" id="input-ref-code" class="ref-input" placeholder="Punya kode teman? Masukkan..." maxlength="20" />
          <button class="btn-claim-ref" onclick="claimReferral(event)">Klaim</button>
        </div>
      </div>
    </div>
  </div>

  <!-- === TAB 1: MINUMAN === -->
  <div id="tab-drinks" class="section active">
    <div class="sec-header">
      <span class="sec-title">Signature Drinks</span>
      <span class="sec-sub">Tap kartu untuk detail</span>
    </div>
    <div class="grid" id="grid-drinks-reg"></div>

    <div class="sec-header" style="margin-top: 18px;">
      <span class="sec-title">👑 VIP Reserve Cellar</span>
      <span class="sec-sub">Gratis VIP / 15 VC</span>
    </div>
    <div class="grid" id="grid-drinks-vip"></div>
  </div>

  <!-- === TAB 2: MIXOLOGY === -->
  <div id="tab-mixology" class="section">
    <div class="glass-panel">
      <div class="panel-title">🧪 Custom Mixology Bar</div>
      <div class="panel-desc">
        Racik komposisi minumanmu sendiri. Julian akan mengocoknya langsung di meja bar grup (<b>10 VC</b>, Gratis VIP).
      </div>

      <label>1. Dasar Minuman (Base)</label>
      <select id="mix-base">
        <option value="Aged Bourbon Whisky">🥃 Aged Bourbon Whisky</option>
        <option value="Botanical London Gin">🍸 Botanical London Gin</option>
        <option value="Silver Agave Tequila">🌵 Silver Agave Tequila</option>
        <option value="Dark Spiced Rum">🏴‍☠️ Dark Spiced Rum</option>
        <option value="Sparkling Non-Alcoholic Tonic">🫧 Sparkling Tonic (Non-Alkohol)</option>
      </select>

      <label>2. Campuran Rasa (Syrup & Bitters)</label>
      <select id="mix-syrup">
        <option value="Blood Orange & Bitters">🍊 Blood Orange & Aromatic Bitters</option>
        <option value="Velvet Rose & Lychee">🌹 Velvet Rose & Lychee Nectar</option>
        <option value="Smoked Honey & Espresso">☕ Smoked Honey & Cold Espresso</option>
        <option value="Crushed Mint & Yuzu Lime">🌿 Crushed Mint & Yuzu Lime</option>
      </select>

      <label>3. Hiasan Gelas (Garnish)</label>
      <select id="mix-garnish">
        <option value="Kulit Jeruk Bakar">🔥 Kulit Jeruk Bakar</option>
        <option value="Batang Kayu Manis Asap">🪵 Batang Kayu Manis Asap</option>
        <option value="Kelopak Mawar Merah">🥀 Kelopak Mawar Merah</option>
        <option value="Ceri Hitam Maraschino">🍒 Ceri Hitam Maraschino</option>
      </select>

      <label>4. Nama Koktail (Opsional)</label>
      <input type="text" id="mix-name" class="glass-input" placeholder="Contoh: Midnight Crimson" maxlength="32" />

      <button class="btn-primary-full" onclick="submitCustomMix()">🍸 Minta Julian Racik Sekarang</button>
    </div>
  </div>

  <!-- === TAB 3: HIDANGAN === -->
  <div id="tab-food" class="section">
    <div class="sec-header">
      <span class="sec-title">Midnight Kitchen</span>
      <span class="sec-sub">Tap kartu untuk detail</span>
    </div>
    <div class="grid" id="grid-food-reg"></div>

    <div class="sec-header" style="margin-top: 18px;">
      <span class="sec-title">👑 Chef's VIP Gastronomy</span>
      <span class="sec-sub">Gratis VIP / 15 VC</span>
    </div>
    <div class="grid" id="grid-food-vip"></div>
  </div>

  <!-- === TAB 4: LAPAK === -->
  <div id="tab-lapak" class="section">
    <div class="sec-header">
      <span class="sec-title">🏪 Lapak Partner</span>
      <span class="sec-sub">Tap kartu untuk beli</span>
    </div>
    <div class="grid" id="grid-lapak">
      <div style="color: var(--muted); font-size: 12px;">Memuat katalog lapak...</div>
    </div>
  </div>

  <!-- === TAB 5: JUKEBOX === -->
  <div id="tab-music" class="section">
    <div class="glass-panel">
      <div class="panel-title">🎶 Jukebox Booth — Kaelen DJ</div>
      <div class="panel-desc">
        Pilih lagu untuk diputar di ruang utama grup & Voice Chat (<b>10 VC</b>, Gratis VIP).
      </div>
      <input type="text" id="song-input" class="glass-input" style="margin-top: 14px;" placeholder="Contoh: Apocalypse - Cigarettes After Sex" />
      <button class="btn-primary-full" onclick="submitSong()">🎧 Putar di Ruangan</button>
    </div>
  </div>

  <!-- === FLOATING GLASS DOCK === -->
  <nav class="glass-dock">
    <div class="dock-item active" onclick="switchTab('drinks', this)">
      <span class="dock-icon">🍸</span>
      <span>Minuman</span>
    </div>
    <div class="dock-item" onclick="switchTab('mixology', this)">
      <span class="dock-icon">🧪</span>
      <span>Mixology</span>
    </div>
    <div class="dock-item" onclick="switchTab('food', this)">
      <span class="dock-icon">🍽️</span>
      <span>Hidangan</span>
    </div>
    <div class="dock-item" onclick="switchTab('lapak', this)">
      <span class="dock-icon">🏪</span>
      <span>Lapak</span>
    </div>
    <div class="dock-item" onclick="switchTab('music', this)">
      <span class="dock-icon">🎶</span>
      <span>Jukebox</span>
    </div>
  </nav>

  <div id="toast" class="toast"></div>

  <script>
    const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
    if (tg) {
      tg.ready();
      tg.expand();
      if (tg.setHeaderColor) tg.setHeaderColor('#0a0608');
      if (tg.setBackgroundColor) tg.setBackgroundColor('#0a0608');
    }

    const MENUS = {
      drinksReg: [
        { code: "negroni", emoji: "🥃", name: "Classic Negroni", desc: "Perpaduan Gin, Campari & sweet vermouth dengan kulit jeruk.", price: 0 },
        { code: "whisky", emoji: "🧊", name: "Smoked Whisky", desc: "Aged Bourbon disajikan di atas es batu kristal bening.", price: 0 },
        { code: "mojito", emoji: "🌿", name: "Velvet Mojito", desc: "Daun mint segar, perasan lime & soda dingin menyegarkan.", price: 0 },
        { code: "espresso", emoji: "☕", name: "Double Espresso", desc: "Ekstrak biji kopi panggang gelap beraroma pekat.", price: 0 },
        { code: "latte", emoji: "🥛", name: "Caramel Latte", desc: "Espresso lembut berpadu susu steamed & sirup karamel.", price: 0 },
        { code: "mocktail", emoji: "🍹", name: "Crimson Sunset", desc: "Jus delima, cranberry & tonic segar tanpa alkohol.", price: 0 },
      ],
      drinksVip: [
        { code: "vip_dom", emoji: "🍾", name: "Dom Pérignon Vintage", desc: "Sampanye Prancis klasik dengan gelembung halus.", price: 15, vip: true },
        { code: "vip_blue", emoji: "💎", name: "Blue Label Reserve", desc: "Scotch whisky langka dengan sentuhan kayu ek.", price: 15, vip: true },
        { code: "vip_absinthe", emoji: "🧪", name: "Emerald Absinthe", desc: "Racikan herbal hijau dengan gula karamel terbakar.", price: 15, vip: true },
        { code: "vip_royal", emoji: "👑", name: "Velvet Royal Martini", desc: "Dry vodka martini dengan taburan edible gold leaf.", price: 15, vip: true },
      ],
      foodReg: [
        { code: "steak", emoji: "🥩", name: "Ribeye Steak", desc: "Daging panggang medium-rare dengan saus lada hitam.", price: 0 },
        { code: "pasta", emoji: "🍝", name: "Truffle Carbonara", desc: "Spaghetti al dente dengan krim jamur truffle & parmesan.", price: 0 },
        { code: "fries", emoji: "🍟", name: "Truffle Fries", desc: "Kentang goreng renyah beraroma minyak truffle.", price: 0 },
        { code: "platter", emoji: "🧀", name: "Charcuterie Board", desc: "Pilihan keju artisan, buah beri & crackers.", price: 0 },
        { code: "tiramisu", emoji: "🍰", name: "Espresso Tiramisu", desc: "Lapisan krim mascarpone lembut khas Italia.", price: 0 },
        { code: "croissant", emoji: "🥐", name: "Butter Croissant", desc: "Pastry berlapis mentega Prancis yang dipanggang hangat.", price: 0 },
      ],
      foodVip: [
        { code: "vip_a5", emoji: "🥩", name: "Miyazaki Wagyu A5", desc: "Potongan wagyu Jepang marbling sempurna yang lumer.", price: 15, vip: true },
        { code: "vip_caviar", emoji: "🥄", name: "Beluga Caviar", desc: "Kaviar hitam premium disajikan bersama blinis & krim.", price: 15, vip: true },
        { code: "vip_lobster", emoji: "🦞", name: "Poached Lobster", desc: "Daging lobster segar dimasak dengan mentega herbal.", price: 15, vip: true },
        { code: "vip_gold", emoji: "🍫", name: "24K Gold Truffle", desc: "Cokelat ganache gelap berlapis lembaran emas 24 karat.", price: 15, vip: true },
      ]
    };

    let isVipUser = false;
    let currentRefCode = "VH-00000";

    function haptic(style = "light") {
      if (tg && tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred(style);
      }
    }

    function showToast(msg) {
      const t = document.getElementById("toast");
      t.innerText = msg;
      t.style.display = "block";
      clearTimeout(window._toastTimer);
      window._toastTimer = setTimeout(() => { t.style.display = "none"; }, 3200);
    }

    function toggleMemberCard(e) {
      haptic("light");
      document.getElementById("member-flip-card").classList.toggle("is-flipped");
    }

    function flipItemCard(cardEl) {
      haptic("light");
      cardEl.classList.toggle("is-flipped");
    }

    function renderFlipGrid(list, containerId, category) {
      const box = document.getElementById(containerId);
      box.innerHTML = list.map(item => {
        const priceLabel = item.price === 0 ? "Gratis" : (isVipUser ? "Gratis VIP" : `${item.price} VC`);
        const safeName = item.name.replace(/'/g, "\\'");
        return `
          <div class="flip-scene">
            <div class="flip-card item-card-inner" onclick="flipItemCard(this)">
              <div class="flip-face item-face flip-front ${item.vip ? 'vip-glow' : ''}">
                <div class="item-top">
                  <span class="item-emoji">${item.emoji}</span>
                  <span class="price-pill">${priceLabel}</span>
                </div>
                <div>
                  <div class="item-name">${item.name}</div>
                  <div class="item-tap-label">Tap untuk detail ↻</div>
                </div>
              </div>
              <div class="flip-face item-face flip-back ${item.vip ? 'vip-glow' : ''}">
                <div class="item-desc-back">${item.desc}</div>
                <button class="btn-order-glass" onclick="event.stopPropagation(); placeOrder('${category}', '${item.code}', '${safeName}', ${item.price})">
                  Pesan • ${priceLabel}
                </button>
              </div>
            </div>
          </div>
        `;
      }).join("");
    }

    function renderAllMenus() {
      renderFlipGrid(MENUS.drinksReg, "grid-drinks-reg", "drink");
      renderFlipGrid(MENUS.drinksVip, "grid-drinks-vip", "drink");
      renderFlipGrid(MENUS.foodReg, "grid-food-reg", "food");
      renderFlipGrid(MENUS.foodVip, "grid-food-vip", "food");
    }

    function renderLapak(items) {
      const box = document.getElementById("grid-lapak");
      if (!items.length) {
        box.innerHTML = `<div style="color: var(--muted); font-size: 12px; grid-column: 1 / -1;">Belum ada item di lapak partner saat ini.</div>`;
        return;
      }
      box.innerHTML = items.map(it => {
        const safeTitle = it.title.replace(/'/g, "\\'");
        const safeDesc = (it.content_text || `Item eksklusif dari toko ${it.shop_name}`).replace(/</g, "<").slice(0, 75);
        return `
          <div class="flip-scene">
            <div class="flip-card item-card-inner" onclick="flipItemCard(this)">
              <div class="flip-face item-face flip-front">
                <div class="item-top">
                  <span class="item-emoji">🛍️</span>
                  <span class="price-pill">${it.price_vc} VC</span>
                </div>
                <div>
                  <div class="item-name">${it.title}</div>
                  <div class="item-tap-label">🏪 ${it.shop_name} • ↻</div>
                </div>
              </div>
              <div class="flip-face item-face flip-back">
                <div class="item-desc-back">${safeDesc}</div>
                <button class="btn-order-glass" onclick="event.stopPropagation(); buyLapakItem(${it.id}, '${safeTitle}', ${it.price_vc})">
                  Beli • ${it.price_vc} VC
                </button>
              </div>
            </div>
          </div>
        `;
      }).join("");
    }

    function switchTab(tabName, el) {
      haptic("light");
      document.querySelectorAll(".dock-item").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".section").forEach(s => s.classList.remove("active"));
      el.classList.add("active");
      document.getElementById("tab-" + tabName).classList.add("active");
    }

    function syncTelegramHeaderUI() {
      if (!tg || !tg.initDataUnsafe || !tg.initDataUnsafe.user) return;
      const u = tg.initDataUnsafe.user;
      const fullName = [u.first_name, u.last_name].filter(Boolean).join(" ") || "Tamu Lounge";
      document.getElementById("guest-name").innerText = fullName;
      document.getElementById("guest-usn").innerText = u.username ? `@${u.username}` : `ID ${u.id}`;

      const initial = (u.first_name || "V").charAt(0).toUpperCase();
      const avatarBox = document.getElementById("avatar-container");
      if (u.photo_url) {
        avatarBox.innerHTML = `<img src="${u.photo_url}" class="avatar-img" alt="PP" onerror="this.outerHTML='<div class=\\'avatar-fallback\\'>${initial}</div>'" />`;
      } else {
        document.getElementById("avatar-initial").innerText = initial;
      }
    }

    async function loadUserProfile() {
      syncTelegramHeaderUI();
      try {
        const res = await fetch("/api/me", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ initData: tg ? tg.initData : "" })
        });
        const data = await res.json();
        if (data.ok) {
          isVipUser = data.is_vip;
          currentRefCode = data.referral_code || "VH-00000";

          document.getElementById("guest-balance").innerText = `${data.coins} VC`;
          document.getElementById("guest-charm").innerText = `${data.charm_points || 0} ✨`;
          document.getElementById("guest-tier").innerText = data.is_vip ? "👑 VIP" : "GUEST";
          document.getElementById("my-ref-code").innerText = currentRefCode;
          document.getElementById("ref-count").innerText = data.referral_count || 0;

          if (data.has_referred) {
            document.getElementById("claim-area").innerHTML =
              `<div style="font-size: 11px; color: var(--gold); text-align: center; width: 100%; padding: 4px 0;">✅ Bonus undangan sudah diklaim</div>`;
          }

          renderAllMenus();
          renderLapak(data.shop_items || []);
        }
      } catch (e) {
        renderAllMenus();
      }
    }

    function copyReferral(e) {
      e.stopPropagation();
      haptic("medium");
      if (navigator.clipboard) {
        navigator.clipboard.writeText(currentRefCode);
      }
      showToast(`✅ Kode ${currentRefCode} disalin!`);
    }

    async function claimReferral(e) {
      e.stopPropagation();
      const code = document.getElementById("input-ref-code").value.trim().toUpperCase();
      if (code.length < 4) return showToast("⚠️ Masukkan kode referral yang valid.");
      haptic("medium");
      const res = await fetch("/api/referral", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg ? tg.initData : "", code })
      });
      const data = await res.json();
      if (data.ok) {
        document.getElementById("guest-balance").innerText = `${data.new_coins} VC`;
        document.getElementById("claim-area").innerHTML =
          `<div style="font-size: 11px; color: var(--gold); text-align: center; width: 100%; padding: 4px 0;">✅ Bonus +25 VC berhasil diklaim!</div>`;
        showToast("🎉 Kode referral valid! Kamu & temanmu dapat +25 VC.");
      } else {
        showToast("⚠️ " + (data.error || "Kode tidak valid."));
      }
    }

    async function buyLapakItem(itemId, title, price) {
      haptic("medium");
      showToast(`Membeli ${title}...`);
      const res = await fetch("/api/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg ? tg.initData : "", category: "lapak", item_id: itemId, item_name: title, price: price })
      });
      const data = await res.json();
      if (data.ok) {
        document.getElementById("guest-balance").innerText = `${data.new_coins} VC`;
        showToast("✅ Berhasil dibeli! Nota dikirim ke PM Hans.");
        if (tg) setTimeout(() => tg.close(), 1000);
      } else {
        showToast("⚠️ " + (data.error || "Gagal membeli item."));
      }
    }

    async function placeOrder(category, code, itemName, price) {
      haptic("medium");
      showToast(`Menyiapkan ${itemName}...`);
      const res = await fetch("/api/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg ? tg.initData : "", category, code, item_name: itemName, price })
      });
      const data = await res.json();
      if (data.ok) {
        document.getElementById("guest-balance").innerText = `${data.new_coins} VC`;
        showToast("✅ Pesanan dikirim ke ruangan!");
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


def _make_ref_code(uid: int) -> str:
    digest = hashlib.sha1(f"velvet:{uid}".encode()).hexdigest()[:5].upper()
    return f"VH-{digest}"


async def _ensure_webapp_schema_and_user(conn, tg_user: dict):
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS charm_points INTEGER DEFAULT 0;")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code TEXT;")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;")
    await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_thread_id BIGINT;")

    await conn.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'shop_items') THEN
                ALTER TABLE shop_items ADD COLUMN IF NOT EXISTS content_text TEXT;
            END IF;
        END $$;
    """)

    uid = int(tg_user["id"])
    username = tg_user.get("username")
    full_name = f"{tg_user.get('first_name', '')} {tg_user.get('last_name', '')}".strip() or "Tamu"
    default_ref_code = _make_ref_code(uid)

    await conn.execute("""
        INSERT INTO users (user_id, username, full_name, coins, charm_points, referral_code, referral_count)
        VALUES ($1, $2, $3, 50, 0, $4, 0)
        ON CONFLICT (user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, users.username),
            full_name = EXCLUDED.full_name,
            referral_code = COALESCE(NULLIF(users.referral_code, ''), EXCLUDED.referral_code);
    """, uid, username, full_name, default_ref_code)


async def _enqueue_kaelen_song(conn, uid: int, requester_name: str, song_query: str, thread_id: int | None):
    """Masukkan request lagu ke tabel antrean database Kaelen DJ (deteksi tabel & kolom otomatis)."""
    candidate_tables = ["song_requests", "music_queue", "jukebox_queue", "jukebox_requests", "song_queue"]
    target_table = None
    cols = set()

    for tbl in candidate_tables:
        rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
            tbl,
        )
        if rows:
            target_table = tbl
            cols = {r["column_name"] for r in rows}
            break

    if not target_table:
        target_table = "song_requests"
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS song_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                requester_name TEXT,
                song_title TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                thread_id BIGINT,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
            );
        """)
        cols = {"id", "user_id", "requester_name", "song_title", "status", "thread_id", "created_at"}

    insert_cols = []
    insert_vals = []

    if "user_id" in cols:
        insert_cols.append("user_id")
        insert_vals.append(uid)
    if "requester_name" in cols:
        insert_cols.append("requester_name")
        insert_vals.append(requester_name)
    elif "username" in cols:
        insert_cols.append("username")
        insert_vals.append(requester_name)

    for song_col in ("song_title", "title", "query", "song_name", "song"):
        if song_col in cols:
            insert_cols.append(song_col)
            insert_vals.append(song_query)
            break

    if "status" in cols:
        insert_cols.append("status")
        insert_vals.append("pending")
    if "thread_id" in cols and thread_id:
        insert_cols.append("thread_id")
        insert_vals.append(thread_id)
    if "created_at" in cols:
        insert_cols.append("created_at")
        insert_vals.append(datetime.utcnow())

    if insert_cols:
        placeholders = ", ".join(f"${i}" for i in range(1, len(insert_vals) + 1))
        col_sql = ", ".join(insert_cols)
        await conn.execute(
            f"INSERT INTO {target_table} ({col_sql}) VALUES ({placeholders})",
            *insert_vals,
        )


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


async def _send_group_media_or_text(
    bot_client: Bot,
    caption: str,
    media_src: str | None = None,
    mtype: str = "animation",
    thread_id: int | None = None,
    uid_to_clear_thread: int | None = None,
):
    """Kirim ke topik aktif user; jika topik sudah dihapus/tidak valid, otomatis fallback ke General."""
    attempts = [thread_id, None] if thread_id else [None]
    for tid in attempts:
        kwargs = {"message_thread_id": tid} if tid else {}
        try:
            if media_src and mtype == "photo":
                return await bot_client.send_photo(cfg.GROUP_ID, photo=media_src, caption=caption, parse_mode=ParseMode.HTML, **kwargs)
            elif media_src:
                return await bot_client.send_animation(cfg.GROUP_ID, animation=media_src, caption=caption, parse_mode=ParseMode.HTML, **kwargs)
            else:
                return await bot_client.send_message(cfg.GROUP_ID, text=caption, parse_mode=ParseMode.HTML, **kwargs)
        except Exception as e:
            err_lower = str(e).lower()
            if tid and "thread not found" in err_lower:
                if uid_to_clear_thread:
                    try:
                        async with db.pool.acquire() as conn:
                            await conn.execute("UPDATE users SET last_thread_id = NULL WHERE user_id = $1", uid_to_clear_thread)
                    except Exception:
                        pass
                continue
            if media_src:
                try:
                    return await bot_client.send_message(cfg.GROUP_ID, text=caption, parse_mode=ParseMode.HTML, **kwargs)
                except Exception as e2:
                    if tid and "thread not found" in str(e2).lower():
                        continue
            raise


async def _serve_with_bartender_animation(
    category: str,
    mention: str,
    item_name: str,
    is_vip: bool,
    thread_id: int | None = None,
    uid: int | None = None,
):
    vip_tag = " 👑" if is_vip else ""

    if category in ("drink", "custom_mix"):
        try:
            prep_msg = await _send_group_media_or_text(
                julian_bot,
                f"🧊 <i>Julian menyiapkan gelas kristal dingin dan mengocok shaker untuk {mention}...</i>",
                media_src=None,
                thread_id=thread_id,
                uid_to_clear_thread=uid,
            )
            await asyncio.sleep(1.5)
            if prep_msg:
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
        await _send_group_media_or_text(julian_bot, caption, media_src, mtype, thread_id, uid)

    elif category == "food":
        try:
            prep_msg = await _send_group_media_or_text(
                julian_bot,
                f"🔥 <i>Chef di dapur sedang menata hidangan hangat untuk {mention}...</i>",
                media_src=None,
                thread_id=thread_id,
                uid_to_clear_thread=uid,
            )
            await asyncio.sleep(1.7)
            if prep_msg:
                await julian_bot.delete_message(cfg.GROUP_ID, prep_msg.message_id)
        except Exception:
            pass

        caption = (
            f"🍽️ Hidangan hangat <b>{item_name}</b> baru saja keluar dari dapur dan disajikan ke meja {mention}{vip_tag}.\n\n"
            f"<i>\"Selamat menikmati santapan malam Anda.\"</i>"
        )
        media_src, mtype = await _get_custom_service_media("food")
        await _send_group_media_or_text(julian_bot, caption, media_src, mtype, thread_id, uid)


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
        await _ensure_webapp_schema_and_user(conn, tg_user)
        row = await conn.fetchrow(
            "SELECT coins, charm_points, is_vip, vip_until, referral_code, referred_by, referral_count FROM users WHERE user_id = $1",
            uid,
        )
        try:
            items = await conn.fetch("""
                SELECT si.id, si.title, si.price_vc,
                       COALESCE(si.content_text, '') AS content_text,
                       ps.shop_name
                FROM shop_items si
                JOIN partner_shops ps ON si.shop_id = ps.id
                WHERE si.is_sold = FALSE
                ORDER BY si.id DESC LIMIT 20
            """)
        except Exception:
            items = []

    coins = row["coins"] if row else 50
    charm_points = (row["charm_points"] or 0) if row else 0
    is_vip = bool(row and row["is_vip"] and row["vip_until"] and row["vip_until"] > datetime.utcnow())
    shop_list = [
        {
            "id": r["id"],
            "title": r["title"],
            "price_vc": r["price_vc"],
            "content_text": r["content_text"] or "",
            "shop_name": r["shop_name"],
        }
        for r in items
    ]
    return web.json_response({
        "ok": True,
        "coins": coins,
        "charm_points": charm_points,
        "is_vip": is_vip,
        "referral_code": row["referral_code"] if (row and row["referral_code"]) else _make_ref_code(uid),
        "referral_count": (row["referral_count"] or 0) if row else 0,
        "has_referred": bool(row and row["referred_by"]),
        "shop_items": shop_list,
    })


async def handle_api_referral(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = _authenticate_user(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "error": "Sesi tidak valid"}, status=401)

    uid = int(tg_user["id"])
    raw_code = str(body.get("code", "")).strip().upper()
    if not raw_code:
        return web.json_response({"ok": False, "error": "Kode referral kosong."})

    clean_num = raw_code.replace("REF_", "").replace("REF-", "")

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_webapp_schema_and_user(conn, tg_user)
            me = await conn.fetchrow("SELECT coins, referred_by, referral_code FROM users WHERE user_id = $1 FOR UPDATE", uid)
            if me["referred_by"]:
                return web.json_response({"ok": False, "error": "Kamu sudah pernah mengklaim kode referral."})
            if me["referral_code"] == raw_code or (clean_num.isdigit() and int(clean_num) == uid):
                return web.json_response({"ok": False, "error": "Tidak bisa memakai kode referral sendiri."})

            inviter = await conn.fetchrow(
                "SELECT user_id, full_name FROM users WHERE UPPER(referral_code) = $1 FOR UPDATE",
                raw_code,
            )
            if not inviter and clean_num.isdigit():
                inviter = await conn.fetchrow(
                    "SELECT user_id, full_name FROM users WHERE user_id = $1 FOR UPDATE",
                    int(clean_num),
                )
            if not inviter:
                return web.json_response({"ok": False, "error": "Kode referral tidak ditemukan."})

            new_coins = (me["coins"] or 0) + 25
            await conn.execute("UPDATE users SET coins = $1, referred_by = $2 WHERE user_id = $3", new_coins, inviter["user_id"], uid)
            await conn.execute(
                "UPDATE users SET coins = coins + 25, referral_count = COALESCE(referral_count, 0) + 1 WHERE user_id = $1",
                inviter["user_id"],
            )
            await log_wallet_tx(conn, uid, 25, f"Bonus klaim referral {raw_code}")
            await log_wallet_tx(conn, inviter["user_id"], 25, f"Bonus undang teman ({tg_user.get('first_name', 'Tamu')})")

    return web.json_response({"ok": True, "new_coins": new_coins})


async def handle_api_order(request: web.Request) -> web.Response:
    body = await request.json()
    tg_user = _authenticate_user(body.get("initData", ""))
    if not tg_user:
        return web.json_response({"ok": False, "error": "Sesi Telegram tidak valid"}, status=401)

    uid = int(tg_user["id"])
    raw_first = tg_user.get("first_name", "Tamu")
    first_name = html.escape(raw_first)
    mention = f'<a href="tg://user?id={uid}">{first_name}</a>'
    category = body.get("category", "drink")

    if category == "lapak":
        item_id = int(body.get("item_id", 0))
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                await _ensure_webapp_schema_and_user(conn, tg_user)
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
            note_val = item.get("content_text") or item.get("description") or "-"
            await hans_bot.send_message(
                uid,
                f"🧾 <b>Nota Pembelian — {html.escape(item['shop_name'])}</b>\n"
                f"• Item: <b>{html.escape(item['title'])}</b> ({price} VC)\n"
                f"• Catatan: {html.escape(str(note_val))}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return web.json_response({"ok": True, "new_coins": new_coins})

    raw_item_name = str(body.get("item_name", "Menu")).strip()[:100]
    item_name = html.escape(raw_item_name)
    base_price = int(body.get("price", 0))

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_webapp_schema_and_user(conn, tg_user)
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

            if category == "song":
                await _enqueue_kaelen_song(conn, uid, raw_first, raw_item_name, thread_id)

    if category in ("drink", "custom_mix", "food"):
        await add_quest_progress(uid, "bar_social", 1)
        asyncio.create_task(_serve_with_bartender_animation(category, mention, item_name, is_vip, thread_id, uid))
    elif category == "song":
        await add_quest_progress(uid, "music_vibe", 1)
        rp_text = (
            f"🎶 Kaelen memutar piringan hitam di booth DJ — <b>{item_name}</b> mengalun di seluruh ruangan atas permintaan {mention}."
        )
        media_src, mtype = await _get_custom_service_media("song")
        await _send_group_media_or_text(kaelen_bot, rp_text, media_src, mtype, thread_id, uid)

    return web.json_response({"ok": True, "new_coins": new_coins})


async def start_webapp_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/me", handle_api_me)
    app.router.add_post("/api/referral", handle_api_referral)
    app.router.add_post("/api/order", handle_api_order)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
