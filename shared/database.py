import asyncpg
from shared.config import DATABASE_URL

pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        # Tabel Utama Tamu & Ekonomi
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                coins INT DEFAULT 0,
                charm_points INT DEFAULT 0,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP,
                is_admin BOOLEAN DEFAULT FALSE,
                is_in_bar BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT NOW(),
                warned_idle BOOLEAN DEFAULT FALSE,
                last_promote TIMESTAMP,
                last_daily DATE,
                daily_streak INT DEFAULT 0,
                total_active_mins INT DEFAULT 0
            );
        """)
        # Tabel Pengaturan Bar (Password Pintu, Status Buka/Tutup)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bar_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await conn.execute("""
            INSERT INTO bar_settings (key, value) 
            VALUES ('door_password', 'VELVET26'), ('bar_open', 'true')
            ON CONFLICT (key) DO NOTHING;
        """)
        # Tabel Tas Koleksi Gift
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                item_code TEXT,
                item_name TEXT,
                sell_value INT,
                received_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # Tabel Staf Paruh Waktu (Shift)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_shifts (
                role TEXT PRIMARY KEY,
                user_id BIGINT,
                started_at TIMESTAMP,
                actions_count INT DEFAULT 0
            );
        """)
