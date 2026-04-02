"""
Сейчастье — бэкенд v4.0 (Multidb)
Flask + SQLite/PostgreSQL + JWT
Совместим с Vercel и внешними БД (Supabase/Neon)
"""

import os, json, hashlib, hmac, secrets, time, sqlite3, re, sys
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response, g
from flask_cors import CORS

try:
    import urllib.request as urlreq
    HAS_URLLIB = True
except Exception:
    HAS_URLLIB = False

try:
    import jwt as pyjwt
    HAS_JWT = True
except Exception:
    HAS_JWT = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PG = True
except Exception:
    HAS_PG = False

# ─── Config ──────────────────────────────────────────────────────────
IS_VERCEL = bool(os.environ.get('VERCEL', ''))
BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

# Database URL (Postgres) or Local SQLite
DB_URL = os.environ.get('DATABASE_URL', '')
if not DB_URL:
    if IS_VERCEL:
        DB_PATH = '/tmp/seychasye.db'
    else:
        DB_PATH = os.path.join(BASE_DIR, 'data', 'seychasye.db')
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
else:
    DB_PATH = None

SECRET_KEY     = os.environ.get('SECRET_KEY', 'default-dev-key-change-me')
JWT_EXPIRE_MIN = int(os.environ.get('JWT_EXPIRE_MIN', 1440))

TG_TOKEN   = os.environ.get('TG_BOT_TOKEN', '')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID', '')

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# ─── DB Interface ────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        if DB_URL:
            conn = psycopg2.connect(DB_URL)
            conn.autocommit = False
            g.db = conn
            g.is_pg = True
        else:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            g.db = conn
            g.is_pg = False
    return g.db

def q(sql: str, params: tuple = ()):
    db = get_db()
    is_pg = getattr(g, 'is_pg', False)
    if is_pg:
        sql = sql.replace('?', '%s')
        # SQLite functions to PG
        sql = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
        sql = sql.replace("DATETIME('now')", "CURRENT_TIMESTAMP")
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        return cur
    # SQLite
    return db.execute(sql, params)

def commit():
    get_db().commit()

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()

def init_db():
    # Independent connection for init
    if DB_URL:
        db = psycopg2.connect(DB_URL)
        is_pg = True
    else:
        db = sqlite3.connect(DB_PATH)
        is_pg = False
    
    try:
        cur = db.cursor()
        pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        dt = "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP" if is_pg else "TEXT NOT NULL DEFAULT (datetime('now'))"
        
        statements = [
            f"CREATE TABLE IF NOT EXISTS users (id {pk}, username TEXT NOT NULL UNIQUE, email TEXT, phone TEXT, full_name TEXT NOT NULL DEFAULT '', pass_hash TEXT NOT NULL, pass_salt TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'client', is_active INTEGER NOT NULL DEFAULT 1, created_at {dt}, last_login TEXT)",
            f"CREATE TABLE IF NOT EXISTS categories (id {pk}, name TEXT NOT NULL UNIQUE, emoji TEXT NOT NULL DEFAULT '🍽', sort INTEGER NOT NULL DEFAULT 0)",
            f"CREATE TABLE IF NOT EXISTS menu_items (id {pk}, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL, category TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '🍽', photo_url TEXT, badge TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at {dt})",
            f"CREATE TABLE IF NOT EXISTS promos (id {pk}, code TEXT NOT NULL UNIQUE, type TEXT NOT NULL DEFAULT 'percent', value REAL NOT NULL, min_sum REAL NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, used_cnt INTEGER NOT NULL DEFAULT 0)",
            f"CREATE TABLE IF NOT EXISTS orders (id {pk}, order_num TEXT NOT NULL UNIQUE, user_id INTEGER, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT, delivery_type TEXT NOT NULL DEFAULT 'delivery', address TEXT, flat TEXT, floor TEXT, intercom TEXT, delivery_time TEXT, comment TEXT, payment TEXT NOT NULL DEFAULT 'cash', promo_code TEXT, subtotal REAL NOT NULL, discount REAL NOT NULL DEFAULT 0, total REAL NOT NULL, status TEXT NOT NULL DEFAULT 'new', items_json TEXT NOT NULL, created_at {dt}, updated_at {dt})",
            f"CREATE TABLE IF NOT EXISTS reviews (id {pk}, name TEXT NOT NULL, rating INTEGER NOT NULL, text TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, created_at {dt})",
            f"CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            f"CREATE TABLE IF NOT EXISTS login_attempts (ip TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT, updated_at {dt})"
        ]
        
        for s in statements: cur.execute(s)
        db.commit()

        # Admin
        p = "%s" if is_pg else "?"
        cur.execute(f"SELECT id FROM users WHERE username={p}", ('admin',))
        if not cur.fetchone():
            salt = secrets.token_hex(16)
            h = _hash_password('admin123', salt)
            cur.execute(f"INSERT INTO users (username, pass_hash, pass_salt, role, full_name) VALUES ({p},{p},{p},{p},{p})", ('admin', h, salt, 'admin', 'Администратор'))
        
        # Categories
        cur.execute("SELECT id FROM categories LIMIT 1")
        if not cur.fetchone():
            for c in [('Пицца','🍕',1),('Бургеры','🍔',2),('Суши','🍣',3),('Паста','🍝',4),('Салаты','🥗',5),('Десерты','🍰',6)]:
                cur.execute(f"INSERT INTO categories (name,emoji,sort) VALUES ({p},{p},{p})", c)

        # Settings
        cur.execute("SELECT key FROM settings LIMIT 1")
        if not cur.fetchone():
            defs = {
                'hero_title': 'Еда у двери', 'hero_time': '30 мин', 'hero_sub': 'Лучшие рестораны города.',
                'phone': '+7 (900) 123-45-67', 'email': 'hello@seychasye.ru', 'address': 'Москва', 'hours': '10:00–23:00'
            }
            for k, v in defs.items(): cur.execute(f"INSERT INTO settings (key,value) VALUES ({p},{p})", (k, v))
        
        db.commit()
    finally:
        db.close()

# Always init on start
try: init_db()
except Exception as e: print(f"DB Init Error: {e}")

# ─── Auth ────────────────────────────────────────────────────────────
def _make_token(user_id, username, role):
    payload = {'sub': user_id, 'username': username, 'role': role, 'exp': time.time() + JWT_EXPIRE_MIN * 60, 'iat': time.time()}
    p = secrets.token_hex(32) if not SECRET_KEY else SECRET_KEY
    import base64
    pl_b = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    sig = hmac.new(SECRET_KEY.encode(), pl_b.encode(), hashlib.sha256).hexdigest()
    return f"local.{pl_b}.{sig}"

def _decode_token(token):
    try:
        parts = token.split('.')
        if len(parts) != 3 or parts[0] != 'local': return None
        _, p, sig = parts
        exp = hmac.new(SECRET_KEY.encode(), p.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp): return None
        import base64
        payload = json.loads(base64.urlsafe_b64decode(p + '=' * (4 - len(p)%4)).decode())
        if payload['exp'] < time.time(): return None
        return payload
    except: return None

def require_auth(f):
    @wraps(f)
    def w(*a, **k):
        t = request.cookies.get('sc_token') or (request.headers.get('Authorization','')[7:] if request.headers.get('Authorization','').startswith('Bearer ') else None)
        u = _decode_token(t) if t else None
        if not u: return jsonify({'error': 'Unauthorized'}), 401
        g.user = u
        return f(*a, **k)
    return w

def require_role(*roles):
    def dec(f):
        @wraps(f)
        def w(*a, **k):
            t = request.cookies.get('sc_token') or (request.headers.get('Authorization','')[7:] if request.headers.get('Authorization','').startswith('Bearer ') else None)
            u = _decode_token(t) if t else None
            if not u: return jsonify({'error': 'Unauthorized'}), 401
            if u.get('role') not in roles: return jsonify({'error': 'Forbidden'}), 403
            g.user = u
            return f(*a, **k)
        return w
    return dec

def get_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '127.0.0.1').split(',')[0].strip()

# ─── API ─────────────────────────────────────────────────────────────
@app.route('/api/auth/me')
@require_auth
def me(): return jsonify({'ok': True, **g.user})

@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.json or {}
    user, pw, full = d.get('username','').strip(), d.get('password',''), d.get('full_name','').strip()
    if not (user and pw and full): return jsonify({'error': 'Заполните поля'}), 400
    if len(pw) < 8: return jsonify({'error': 'Пароль < 8 символов'}), 400
    db = get_db()
    if q("SELECT id FROM users WHERE username=?", (user,)).fetchone(): return jsonify({'error': 'Логин занят'}), 409
    salt = secrets.token_hex(16)
    h = _hash_password(pw, salt)
    cur = q("INSERT INTO users (username, full_name, pass_hash, pass_salt) VALUES (?,?,?,?)", (user, full, h, salt))
    uid = getattr(cur, 'lastrowid', None) or cur.fetchone().get('id') if getattr(g, 'is_pg', False) else cur.lastrowid
    if getattr(g, 'is_pg', False): # Handle serial return in PG if needed, but lastrowid is enough for simple cases
        db.commit() # pg needs commit
    else: db.commit()
    t = _make_token(uid, user, 'client')
    r = make_response(jsonify({'ok': True, 'username': user, 'role': 'client'}))
    r.set_cookie('sc_token', t, httponly=True, samesite='Lax', max_age=86400*30, path='/')
    return r

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.json or {}
    user, pw = d.get('username','').strip(), d.get('password','')
    db = get_db()
    u = q("SELECT * FROM users WHERE username=? OR email=?", (user, user)).fetchone()
    if not u or _hash_password(pw, u['pass_salt'] if not getattr(g, 'is_pg', False) else u['pass_salt']) != u['pass_hash']:
        return jsonify({'error': 'Неверный логин или пароль'}), 401
    t = _make_token(u['id'], u['username'], u['role'])
    r = make_response(jsonify({'ok': True, 'username': u['username'], 'role': u['role'], 'full_name': u['full_name']}))
    r.set_cookie('sc_token', t, httponly=True, samesite='Lax', max_age=86400*30, path='/')
    return r

@app.route('/api/categories')
def get_cats():
    rows = q("SELECT * FROM categories ORDER BY sort ASC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/menu')
def get_menu():
    rows = q("SELECT * FROM menu_items WHERE active=1").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/reviews')
def get_revs():
    rows = q("SELECT * FROM reviews WHERE approved=1 ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/reviews', methods=['POST'])
def add_rev():
    d = request.json or {}
    q("INSERT INTO reviews (name, rating, text) VALUES (?,?,?)", (d.get('name','Аноним'), d.get('rating',5), d.get('text','')))
    commit()
    return jsonify({'ok': True})

@app.route('/api/orders', methods=['POST'])
def make_order():
    d = request.json or {}
    num = datetime.now().strftime('%m%d-') + secrets.token_hex(3).upper()
    q("INSERT INTO orders (order_num, name, phone, address, total, items_json) VALUES (?,?,?,?,?,?)",
      (num, d.get('name',''), d.get('phone',''), d.get('address',''), d.get('total',0), json.dumps(d.get('items',[]))))
    commit()
    return jsonify({'ok': True, 'order_num': num})

@app.route('/api/settings')
def get_sets():
    rows = q("SELECT key, value FROM settings").fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/admin/users')
@require_role('admin')
def adm_users():
    rows = q("SELECT id, username, email, full_name, role, is_active, created_at FROM users").fetchall()
    return jsonify([dict(r) for r in rows])

# ─── Static ──────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(PUBLIC_DIR, path)): return send_from_directory(PUBLIC_DIR, path)
    return send_from_directory(PUBLIC_DIR, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
