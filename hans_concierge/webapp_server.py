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

EMBEDDED_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover" />
  <title>The Velvet Hour — iOS Glass Concierge</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg-base: #080609;
      --glass-bg: rgba(28, 22, 28, 0.56);
      --glass-strong: rgba(36, 28, 36, 0.74);
      --glass-border: rgba(255, 255, 255, 0.14);
      --glass-highlight: rgba(255, 255, 255, 0.22);
      --gold: #e5c171;
      --gold-soft: rgba(229, 193, 113, 0.18);
      --text-primary: #f7f3ee;
      --text-secondary: rgba(247, 243, 238, 0.62);
      --blur: blur(26px) saturate(185%);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    }

    html, body {
      background-color: var(--bg-base) !important;
      color: var(--text-primary) !important;
      min-height: 100vh;
      overflow-x: hidden;
      overscroll-behavior-y: none;
    }

    /* Ambient iOS Wallpaper Orbs (agar efek blur kaca terlihat nyata) */
    .ambient-bg {
      position: fixed;
      inset: 0;
      z-index: 0;
      pointer-events: none;
      overflow: hidden;
      background: radial-gradient(circle at 50% 0%, #1d0e16 0%, #080609 72%);
    }
    .orb {
      position: absolute;
      border-radius: 50%;
      filter: blur(75px);
      opacity: 0.55;
    }
    .orb-1 {
      width: 280px; height: 280px;
      top: -60px; right: -50px;
      background: #6b1d35;
    }
    .orb-2 {
      width: 260px; height: 260px;
      top: 240px; left: -80px;
      background: #593d16;
    }
    .orb-3 {
      width: 300px; height: 300px;
      bottom: 40px; right: -70px;
      background: #3b1328;
    }

    .app-shell {
      position: relative;
      z-index: 1;
      padding: 14px 16px 112px;
      max-width: 480px;
      margin: 0 auto;
    }

    /* Top Minimal Header */
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
      padding: 4px 2px;
    }
    .brand-title {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 2.2px;
      color: var(--gold);
      text-transform: uppercase;
    }
    .brand-sub {
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -0.4px;
      color: var(--text-primary);
      margin-top: 1px;
    }
    .pill-balance {
      background: var(--glass-bg);
      backdrop-filter: var(--blur);
      -webkit-backdrop-filter: var(--blur);
      border: 0.5px solid var(--glass-highlight);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.12), 0 6px 18px rgba(0,0,0,0.35);
      padding: 7px 13px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      color: var(--gold);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* Pages / Views */
    .view {
      display: none;
      animation: iosFade 0.28s cubic-bezier(0.22, 1, 0.36, 1);
    }
    .view.active {
      display: block;
    }
    @keyframes iosFade {
      from { opacity: 0; transform: translateY(6px) scale(0.99); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }

    /* =========================================
       3D FLIPPABLE MEMBER PASS CARD (APPLE WALLET STYLE)
       ========================================= */
    .flip-stage {
      perspective: 1300px;
      margin: 4px 0 14px;
    }
    .flip-card {
      width: 100%;
      height: 224px;
      position: relative;
      transform-style: preserve-3d;
      transition: transform 0.72s cubic-bezier(0.22, 1, 0.36, 1);
      cursor: pointer;
    }
    .flip-card.is-flipped {
      transform: rotateY(180deg);
    }
    .card-face {
      position: absolute;
      inset: 0;
      border-radius: 24px;
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
      background: linear-gradient(145deg, rgba(46, 33, 42, 0.78) 0%, rgba(19, 15, 20, 0.85) 100%);
      backdrop-filter: blur(30px) saturate(200%);
      -webkit-backdrop-filter: blur(30px) saturate(200%);
      border: 0.5px solid rgba(255, 255, 255, 0.22);
      box-shadow:
        inset 0 1px 1px rgba(255, 255, 255, 0.24),
        0 20px 40px rgba(0, 0, 0, 0.55);
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      overflow: hidden;
    }
    .card-face::before {
      content: "";
      position: absolute;
      top: -40%; left: -30%;
      width: 160%; height: 160%;
      background: radial-gradient(circle at 25% 20%, rgba(229, 193, 113, 0.16), transparent 55%);
      pointer-events: none;
    }
    .card-back {
      transform: rotateY(180deg);
      background: linear-gradient(145deg, rgba(24, 19, 25, 0.9) 0%, rgba(38, 25, 33, 0.86) 100%);
      padding: 0;
    }

    /* Card Front Elements */
    .cf-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 1;
    }
    .cf-user {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .avatar-ring {
      width: 50px;
      height: 50px;
      border-radius: 50%;
      padding: 2px;
      background: linear-gradient(135deg, #f3d68f, #8e6725);
      box-shadow: 0 4px 14px rgba(0,0,0,0.4);
      flex-shrink: 0;
    }
    .avatar-img {
      width: 100%;
      height: 100%;
      border-radius: 50%;
      object-fit: cover;
      background: #1b141a;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 18px;
      color: var(--gold);
    }
    .cf-name {
      font-size: 17px;
      font-weight: 700;
      letter-spacing: -0.2px;
      color: #fff;
    }
    .cf-usn {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 1px;
    }
    .tier-chip {
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 1px;
      padding: 5px 10px;
      border-radius: 999px;
      background: rgba(229, 193, 113, 0.16);
      border: 0.5px solid rgba(229, 193, 113, 0.55);
      color: var(--gold);
    }

    .cf-mid {
      z-index: 1;
      margin-top: 4px;
    }
    .cf-bal-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 1.4px;
      color: var(--text-secondary);
    }
    .cf-bal-val {
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.6px;
      color: #fff;
      margin-top: 2px;
    }
    .cf-bal-val span {
      font-size: 14px;
      font-weight: 700;
      color: var(--gold);
    }

    .cf-bot {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      z-index: 1;
      border-top: 0.5px solid rgba(255,255,255,0.1);
      padding-top: 10px;
    }
    .cf-stat {
      font-size: 11px;
      color: var(--text-secondary);
    }
    .cf-stat b {
      color: var(--text-primary);
      font-weight: 700;
    }
    .flip-hint {
      font-size: 11px;
      color: var(--gold);
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 4px;
    }

    /* Card Back Elements */
    .mag-strip {
      width: 100%;
      height: 36px;
      background: linear-gradient(90deg, #0b090c, #241c22, #0b090c);
      margin-top: 16px;
      border-top: 0.5px solid rgba(255,255,255,0.08);
      border-bottom: 0.5px solid rgba(255,255,255,0.08);
    }
    .cb-body {
      padding: 12px 20px 16px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      flex: 1;
    }
    .ref-box {
      background: rgba(255, 255, 255, 0.06);
      border: 0.5px solid rgba(255, 255, 255, 0.14);
      border-radius: 14px;
      padding: 10px 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .ref-label {
      font-size: 10px;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 1px;
    }
    .ref-code {
      font-size: 15px;
      font-weight: 800;
      color: var(--gold);
      letter-spacing: 1px;
      margin-top: 2px;
    }
    .btn-copy {
      background: rgba(229, 193, 113, 0.2);
      border: 0.5px solid var(--gold);
      color: var(--gold);
      border-radius: 10px;
      padding: 7px 12px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
    }
    .btn-copy:active {
      transform: scale(0.95);
    }
    .cb-meta-row {
      display: flex;
      justify-content: space-between;
      font-size: 11px;
      color: var(--text-secondary);
      margin-top: 8px;
    }

    /* Glass Panels & Lists */
    .glass-card {
      background: var(--glass-bg);
      backdrop-filter: var(--blur);
      -webkit-backdrop-filter: var(--blur);
      border: 0.5px solid var(--glass-border);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 10px 28px rgba(0,0,0,0.35);
      border-radius: 20px;
      padding: 16px;
      margin-bottom: 12px;
    }

    .section-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.4px;
      text-transform: uppercase;
      color: var(--gold);
      margin: 14px 4px 10px;
    }

    /* iOS Segmented Control */
    .ios-segment {
      display: flex;
      background: rgba(255, 255, 255, 0.06);
      backdrop-filter: var(--blur);
      -webkit-backdrop-filter: var(--blur);
      border: 0.5px solid var(--glass-border);
      border-radius: 14px;
      padding: 3px;
      margin-bottom: 14px;
    }
    .seg-btn {
      flex: 1;
      text-align: center;
      padding: 8px 10px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      border-radius: 11px;
      cursor: pointer;
      transition: all 0.22s ease;
    }
    .seg-btn.active {
      background: rgba(229, 193, 113, 0.2);
      color: var(--gold);
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    }

    /* Menu Grid */
    .menu-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 11px;
    }
    .menu-item {
      background: var(--glass-bg);
      backdrop-filter: var(--blur);
      -webkit-backdrop-filter: var(--blur);
      border: 0.5px solid var(--glass-border);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.09);
      border-radius: 18px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.16s ease;
    }
    .menu-item:active {
      transform: scale(0.97);
    }
    .menu-item.vip-glow {
      border-color: rgba(229, 193, 113, 0.45);
      background: linear-gradient(160deg, rgba(46, 33, 24, 0.65), rgba(24, 18, 24, 0.62));
    }
    .mi-emoji { font-size: 26px; margin-bottom: 8px; }
    .mi-title { font-size: 13.5px; font-weight: 700; color: #fff; margin-bottom: 4px; }
    .mi-desc { font-size: 11px; color: var(--text-secondary); line-height:
