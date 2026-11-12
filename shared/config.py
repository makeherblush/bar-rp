import os

# --- TOKEN KETIGA BOT ---
TOKEN_HANS = os.getenv("TOKEN_HANS", "")
TOKEN_JULIAN = os.getenv("TOKEN_JULIAN", "")
TOKEN_KAELEN = os.getenv("TOKEN_KAELEN", "")

# --- KONFIGURASI OWNER & LOKASI GRUP / CHANNEL ---
OWNER_ID = int(os.getenv("OWNER_ID", 0))
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "").lstrip("@")

GROUP_ID = int(os.getenv("GROUP_ID", 0))
CH_INFO_ID = int(os.getenv("CH_INFO_ID", 0))
CH_PROMOTE_ID = int(os.getenv("CH_PROMOTE_ID", 0))

CH_INFO_LINK = os.getenv("CH_INFO_LINK", "https://t.me/")
CH_PROMOTE_LINK = os.getenv("CH_PROMOTE_LINK", "https://t.me/")

# --- ATURAN ROLEPLAY & EKONOMI VELVET COINS (VC) ---
REQUIRED_CN_SYMBOL = os.getenv("REQUIRED_CN_SYMBOL", "🥂")
WELCOME_BONUS = int(os.getenv("WELCOME_BONUS", 200))
DAILY_COIN = int(os.getenv("DAILY_COIN", 30))
VIP_COST_24H = int(os.getenv("VIP_COST_24H", 300))

PROMOTE_CD_REG = int(os.getenv("PROMOTE_CD_REG", 45))  # Cooldown promote reguler (menit)
PROMOTE_CD_VIP = int(os.getenv("PROMOTE_CD_VIP", 30))  # Cooldown promote VIP (menit)

# --- KATALOG HADIAH BAR BOUTIQUE ---
# Format: "kode": ("Nama Gift", harga_beli, nilai_cair_50%, poin_charm)
GIFTS_CATALOG = {
    "rose": ("🌹 Velvet Rose", 50, 25, 10),
    "negroni": ("🍸 Classic Negroni", 100, 50, 25),
    "cigar": ("🚬 Cuban Reserve Cigar", 200, 100, 55),
    "champagne": ("🍾 Dom Pérignon Vintage", 500, 250, 150),
    "diamond": ("💎 Midnight Diamond Ring", 1000, 500, 350),
}

# --- KONFIGURASI MUSIK & ASISTEN (KAELEN) ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
SONG_REQ_COST = int(os.getenv("SONG_REQ_COST", 15))
