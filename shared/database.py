import asyncpg
from shared.config import DATABASE_URL

pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
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
                is_patron BOOLEAN DEFAULT FALSE,
                is_in_bar BOOLEAN DEFAULT FALSE,
                got_welcome BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT NOW(),
                warned_idle BOOLEAN DEFAULT FALSE,
                last_promote TIMESTAMP,
                last_daily DATE,
                daily_streak INT DEFAULT 0,
                total_active_mins INT DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bar_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await conn.execute("""
            INSERT INTO bar_settings (key, value) 
            VALUES ('door_password', 'VELVET26'), ('bar_open', 'true'), ('current_pin_id', '0')
            ON CONFLICT (key) DO NOTHING;
        """)
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_shifts (
                role TEXT PRIMARY KEY,
                user_id BIGINT,
                started_at TIMESTAMP,
                actions_count INT DEFAULT 0
            );
        """)
