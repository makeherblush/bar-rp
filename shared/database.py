import asyncpg
from shared.config import DATABASE_URL

pool: asyncpg.Pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                coins INTEGER DEFAULT 0,
                charm_points INTEGER DEFAULT 0,
                gifts_sent_vc INTEGER DEFAULT 0,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP,
                is_admin BOOLEAN DEFAULT FALSE,
                is_in_bar BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT NOW(),
                warned_idle BOOLEAN DEFAULT FALSE,
                total_active_mins INTEGER DEFAULT 0,
                last_daily DATE,
                last_promote TIMESTAMP
            );
        """)
        # Tambahkan kolom gifts_sent_vc jika tabel lama sudah terlanjur dibuat
        await conn.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS gifts_sent_vc INTEGER DEFAULT 0;
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_shifts (
                role TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                started_at TIMESTAMP DEFAULT NOW(),
                actions_count INTEGER DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS betta_catalog (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                price_vc INTEGER NOT NULL,
                description TEXT NOT NULL,
                media_type TEXT DEFAULT 'none',
                media_file_id TEXT,
                is_sold BOOLEAN DEFAULT FALSE,
                buyer_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
