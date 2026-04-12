import sqlite3
import os

DB_PATH = "data/autoradar.db"


def ensure_schema():

    os.makedirs("data", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("[DB INIT] Garantindo schema do banco...")

    # =====================================================
    # LISTINGS
    # =====================================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS listings (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        url TEXT UNIQUE,
        source TEXT,

        title TEXT,
        brand TEXT,
        model TEXT,
        year INTEGER,

        price INTEGER,
        price_display TEXT,
        currency TEXT,

        km INTEGER,

        city TEXT,
        state TEXT,

        description TEXT,

        main_photo_url TEXT,
        main_photo_path TEXT,

        cambio TEXT,
        cor_externa TEXT,
        cor_interna TEXT,
        combustivel TEXT,

        published_at TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # OPPORTUNITIES
    # =====================================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS opportunities (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        url TEXT UNIQUE,
        source TEXT,

        title TEXT,
        brand TEXT,
        model TEXT,
        year INTEGER,

        price INTEGER,
        price_display TEXT,
        currency TEXT,

        km INTEGER,

        city TEXT,
        state TEXT,

        description TEXT,

        main_photo_url TEXT,
        main_photo_path TEXT,

        cambio TEXT,
        cor_externa TEXT,
        cor_interna TEXT,
        combustivel TEXT,

        published_at TEXT,

        fipe_price INTEGER,
        fipe_model TEXT,

        margin_value INTEGER,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # LINK QUEUE
    # =====================================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS link_queue (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        url TEXT UNIQUE,
        source TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # FIPE CACHE
    # =====================================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fipe_cache (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        brand TEXT,
        model TEXT,
        year INTEGER,

        fipe_price INTEGER,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(brand, model, year)
    )
    """)

    # =====================================================
    # IPHONE OPPORTUNITIES
    # =====================================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS iphone_opportunities (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        url TEXT UNIQUE,
        source TEXT,

        title TEXT,
        price INTEGER,
        price_display TEXT,

        ref_price INTEGER,
        model_key TEXT,
        storage_label TEXT,
        margin INTEGER,

        photo_url TEXT,
        description TEXT,
        condition TEXT,
        location TEXT,
        published_at TEXT,

        telegram_sent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # MIGRAÇÃO: colunas storage_label / description / condition / location / published_at
    # =====================================================
    cursor.execute("PRAGMA table_info(iphone_opportunities)")
    iph_cols = [row[1] for row in cursor.fetchall()]
    _iph_migrations = [
        ("storage_label",  "TEXT"),
        ("description",    "TEXT"),
        ("condition",      "TEXT"),
        ("location",       "TEXT"),
        ("published_at",   "TEXT"),
        ("send_attempts",  "INTEGER DEFAULT 0"),
    ]
    for col, col_type in _iph_migrations:
        if col not in iph_cols:
            print(f"[DB MIGRATION] Adicionando coluna {col} em iphone_opportunities")
            cursor.execute(f"ALTER TABLE iphone_opportunities ADD COLUMN {col} {col_type}")

    # =====================================================
    # PS5 OPPORTUNITIES
    # =====================================================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ps5_opportunities (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        url TEXT UNIQUE,
        source TEXT,

        title TEXT,
        price INTEGER,
        price_display TEXT,

        ref_price INTEGER,
        model TEXT,
        margin INTEGER,

        photo_url TEXT,
        description TEXT,
        condition TEXT,
        location TEXT,
        published_at TEXT,

        telegram_sent INTEGER DEFAULT 0,
        send_attempts INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # MIGRAÇÃO: colunas adicionais em ps5_opportunities
    # =====================================================
    cursor.execute("PRAGMA table_info(ps5_opportunities)")
    ps5_cols = [row[1] for row in cursor.fetchall()]
    _ps5_migrations = [
        ("description",   "TEXT"),
        ("condition",     "TEXT"),
        ("location",      "TEXT"),
        ("published_at",  "TEXT"),
        ("send_attempts", "INTEGER DEFAULT 0"),
    ]
    for col, col_type in _ps5_migrations:
        if col not in ps5_cols:
            print(f"[DB MIGRATION] Adicionando coluna {col} em ps5_opportunities")
            cursor.execute(f"ALTER TABLE ps5_opportunities ADD COLUMN {col} {col_type}")

    # =====================================================
    # MIGRAÇÃO: coluna module e region em link_queue
    # =====================================================

    cursor.execute("PRAGMA table_info(link_queue)")
    lq_cols = [row[1] for row in cursor.fetchall()]
    if "module" not in lq_cols:
        print("[DB MIGRATION] Adicionando coluna module em link_queue")
        cursor.execute("ALTER TABLE link_queue ADD COLUMN module TEXT DEFAULT 'car'")
    if "region" not in lq_cols:
        print("[DB MIGRATION] Adicionando coluna region em link_queue")
        cursor.execute("ALTER TABLE link_queue ADD COLUMN region TEXT DEFAULT ''")

    # =====================================================
    # MIGRAÇÃO: coluna region em opportunities
    # =====================================================
    cursor.execute("PRAGMA table_info(opportunities)")
    opp_cols = [row[1] for row in cursor.fetchall()]
    if "region" not in opp_cols:
        print("[DB MIGRATION] Adicionando coluna region em opportunities")
        cursor.execute("ALTER TABLE opportunities ADD COLUMN region TEXT DEFAULT ''")
    if "send_attempts" not in opp_cols:
        print("[DB MIGRATION] Adicionando coluna send_attempts em opportunities")
        cursor.execute("ALTER TABLE opportunities ADD COLUMN send_attempts INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

    print("[DB INIT] Schema garantido com sucesso.")