import os
from dotenv import load_dotenv

load_dotenv()

# Token & Identitas
TOKEN_HANS = os.getenv("TOKEN_HANS")       # Bot 1: Gatekeeper & Ekonomi
TOKEN_JULIAN = os.getenv("TOKEN_JULIAN")   # Bot 2: Bartender & Grup RP
TOKEN_KAELEN = os.getenv("TOKEN_KAELEN")   # Bot 3: DJ & Jukebox

# Akun Asisten Voice Chat (Userbot)
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

# Database & Grup
DATABASE_URL = os.getenv("DATABASE_URL")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
GROUP_ID = int(os.getenv("GROUP_ID", 0))

# Aturan Bar (The Velvet Hour)
REQUIRED_CN_SYMBOL = "🥂"
WELCOME_BONUS = 200
DAILY_COIN = 30
VIP_COST_24H = 300
SONG_REQ_COST = 15

# Timer Pasif (dalam menit)
IDLE_WARN_REG = 45
IDLE_KICK_REG = 60
IDLE_WARN_VIP = 90
IDLE_KICK_VIP = 120

# Cooldown Promote (dalam menit)
PROMOTE_CD_REG = 45
PROMOTE_CD_VIP = 30
