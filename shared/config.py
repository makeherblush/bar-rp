import os
from dotenv import load_dotenv

load_dotenv()

# Token Bot
TOKEN_HANS = os.getenv("TOKEN_HANS")
TOKEN_JULIAN = os.getenv("TOKEN_JULIAN")
TOKEN_KAELEN = os.getenv("TOKEN_KAELEN")

# Database & ID Utama
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "OwnerVelvet") # Tanpa @
GROUP_ID = int(os.getenv("GROUP_ID", 0))

# 2 Channel Wajib Sub
CH_INFO_ID = int(os.getenv("CH_INFO_ID", 0))
CH_PROMOTE_ID = int(os.getenv("CH_PROMOTE_ID", 0))
CH_INFO_LINK = os.getenv("CH_INFO_LINK", "https://t.me/VelvetInfo")
CH_PROMOTE_LINK = os.getenv("CH_PROMOTE_LINK", "https://t.me/VelvetBoard")

# Aturan & Ekonomi Bar
REQUIRED_CN_SYMBOL = "🥂"
WELCOME_BONUS = 200
DAILY_COIN = 30
VIP_COST_24H = 300
PROMOTE_CD_REG = 45 # Menit
PROMOTE_CD_VIP = 30 # Menit

# Katalog Gift (kode: (Nama, Harga Beli, Nilai Tukar 50%, Poin Charm))
GIFTS_CATALOG = {
    "espresso": ("☕ Warm Espresso", 40, 20, 5),
    "martini": ("🍸 Classic Martini", 60, 30, 10),
    "rose": ("🌹 Single Red Rose", 80, 40, 15),
    "truffle": ("🍫 Artisan Truffle Box", 150, 75, 25),
    "bear": ("🧸 Velvet Teddy Bear", 200, 100, 35),
    "bouquet": ("💐 Midnight Bouquet", 250, 125, 45),
    "champagne": ("🥂 Vintage Champagne", 400, 200, 70),
    "crown": ("👑 The Velvet Crown", 1500, 750, 250),
}
