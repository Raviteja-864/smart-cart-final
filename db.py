import sqlite3
import os
import bcrypt
import config

def get_sqlite_conn():
    conn = sqlite3.connect(config.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class DictCursorWrapper:
    """Wrapper to make SQLite connection output dict-like objects similar to mysql.connector cursor(dictionary=True)"""
    def __init__(self, cursor, is_sqlite=True):
        self.cursor = cursor
        self.is_sqlite = is_sqlite

    def execute(self, query, params=()):
        if self.is_sqlite:
            # Replace MySQL %s parameter placeholder with SQLite ? placeholder
            query = query.replace('%s', '?')
            # Handle SQLite syntax adjustments if needed
            query = query.replace('AUTO_INCREMENT', 'AUTOINCREMENT')
        return self.cursor.execute(query, params)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        if self.is_sqlite and isinstance(row, sqlite3.Row):
            return dict(row)
        elif isinstance(row, dict):
            return row
        elif hasattr(self.cursor, 'description') and self.cursor.description:
            colnames = [d[0] for d in self.cursor.description]
            return dict(zip(colnames, row))
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        if self.is_sqlite and len(rows) > 0 and isinstance(rows[0], sqlite3.Row):
            return [dict(r) for r in rows]
        elif len(rows) > 0 and isinstance(rows[0], dict):
            return rows
        elif hasattr(self.cursor, 'description') and self.cursor.description:
            colnames = [d[0] for d in self.cursor.description]
            return [dict(zip(colnames, r)) for r in rows]
        return rows

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def close(self):
        self.cursor.close()


class DatabaseConnectionWrapper:
    def __init__(self, conn, is_sqlite=True):
        self.conn = conn
        self.is_sqlite = is_sqlite

    def cursor(self, dictionary=True):
        if self.is_sqlite:
            return DictCursorWrapper(self.conn.cursor(), is_sqlite=True)
        else:
            return DictCursorWrapper(self.conn.cursor(dictionary=dictionary), is_sqlite=False)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db_connection():
    if config.USE_MYSQL:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=config.DB_HOST,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
                database=config.DB_NAME
            )
            return DatabaseConnectionWrapper(conn, is_sqlite=False)
        except Exception as e:
            print(f"MySQL Connection failed ({e}), falling back to SQLite...")
    
    # SQLite Fallback
    conn = get_sqlite_conn()
    return DatabaseConnectionWrapper(conn, is_sqlite=True)


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Create Tables
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin (
        admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        category TEXT NOT NULL,
        price REAL NOT NULL,
        original_price REAL,
        stock_quantity INTEGER DEFAULT 50,
        badge TEXT DEFAULT 'Popular',
        image TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cart (
        cart_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER DEFAULT 1,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        order_number TEXT,
        total_amount REAL NOT NULL,
        address TEXT,
        payment_method TEXT DEFAULT 'COD',
        payment_status TEXT DEFAULT 'Pending',
        razorpay_order_id TEXT,
        razorpay_payment_id TEXT,
        status TEXT DEFAULT 'Placed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL DEFAULT 0.0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS addresses (
        address_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        full_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT NOT NULL,
        city TEXT NOT NULL,
        state TEXT,
        pincode TEXT NOT NULL,
        country TEXT DEFAULT 'India'
    )
    """)

    conn.commit()

    # Create Default Admin User if none exists
    cur.execute("SELECT COUNT(*) as cnt FROM admin")
    admin_count = cur.fetchone()['cnt']
    if admin_count == 0:
        hashed_pwd = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
        cur.execute("INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)", ("Admin Store", "admin@smartcart.com", hashed_pwd))
        conn.commit()

    # Seed Initial Products if empty
    cur.execute("SELECT COUNT(*) as cnt FROM products")
    prod_count = cur.fetchone()['cnt']

    if prod_count == 0:
        seed_products = [
            ("iPhone 15 Pro Max", "Apple flagship smartphone with A17 Pro chip, titanium design, and 48MP camera system.", "Mobiles", 134900, 159900, 25, "Bestseller", "https://images.unsplash.com/photo-1695048133142-1a20484d2569?auto=format&fit=crop&w=800&q=80"),
            ("Samsung Galaxy S24 Ultra", "Galaxy AI powered flagship with 200MP camera, Snapdragon 8 Gen 3, and integrated S-Pen.", "Mobiles", 129999, 144999, 18, "Hot Deal", "https://images.unsplash.com/photo-1610945265064-0e34e5519bbf?auto=format&fit=crop&w=800&q=80"),
            ("MacBook Pro M3 16\"", "Supercharged for pros with M3 Max chip, 36GB unified memory, and Liquid Retina XDR display.", "Laptops", 249900, 279900, 12, "Top Rated", "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?auto=format&fit=crop&w=800&q=80"),
            ("Sony WH-1000XM5 Headphones", "Industry-leading noise canceling wireless headphones with crystal clear sound quality.", "Audio", 29990, 34990, 40, "Trending", "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=800&q=80"),
            ("Apple Watch Ultra 2", "The ultimate sports and adventure watch with 3000 nits display and precision dual-frequency GPS.", "Wearables", 89900, 95900, 15, "New", "https://images.unsplash.com/photo-1546868871-7041f2a55e12?auto=format&fit=crop&w=800&q=80"),
            ("Nike Air Max 270", "Premium sneakers featuring Nike's biggest heel Air unit yet for a super-soft ride.", "Footwear", 12995, 14995, 50, "Popular", "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=800&q=80"),
            ("Dell XPS 15 OLED", "High performance laptop with 13th Gen Intel i9, 3.5K OLED touchscreen, and RTX 4070.", "Laptops", 189990, 215000, 8, "Featured", "https://images.unsplash.com/photo-1593642632823-8f785ba67e45?auto=format&fit=crop&w=800&q=80"),
            ("PlayStation 5 Slim", "Next-gen gaming console with ultra-high speed SSD, haptic feedback, and 3D Audio.", "Gaming", 54990, 59990, 22, "Hot Deal", "https://images.unsplash.com/photo-1606813907291-d86efa9b94db?auto=format&fit=crop&w=800&q=80")
        ]

        for name, desc, cat, price, orig_price, stock, badge, img in seed_products:
            cur.execute("""
            INSERT INTO products (name, description, category, price, original_price, stock_quantity, badge, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, desc, cat, price, orig_price, stock, badge, img))
        
        conn.commit()

    cur.close()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully!")
