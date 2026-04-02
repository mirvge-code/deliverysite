"""
Сейчастье — бэкенд v4.4 (Full Fix: JSON dates, PG Compatibility)
Flask + Multi-DB + JSON Serializer
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
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PG = True
except Exception:
    HAS_PG = False

# ─── Config ──────────────────────────────────────────────────────────
IS_VERCEL = bool(os.environ.get('VERCEL', ''))
BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

DB_URL = os.environ.get('DATABASE_URL', '')
if not DB_URL:
    if IS_VERCEL: DB_PATH = '/tmp/seychasye.db'
    else:
        DB_PATH = os.path.join(BASE_DIR, 'data', 'seychasye.db')
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
else: DB_PATH = None

SECRET_KEY     = os.environ.get('SECRET_KEY', 'default-dev-key-change-me')
JWT_EXPIRE_MIN = int(os.environ.get('JWT_EXPIRE_MIN', 1440))

TG_TOKEN   = os.environ.get('TG_BOT_TOKEN', '')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID', '')

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# ─── DB Abstraction ──────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        if DB_URL:
            conn = psycopg2.connect(DB_URL)
            conn.autocommit = False
            g.db = conn; g.is_pg = True
        else:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            g.db = conn; g.is_pg = False
    return g.db

def q(sql: str, params: tuple = ()):
    db = get_db(); is_pg = getattr(g, 'is_pg', False)
    if is_pg:
        sql = sql.replace('?', '%s')
        sql = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
        sql = sql.replace("DATETIME('now')", "CURRENT_TIMESTAMP")
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params); return cur
    return db.execute(sql, params)

def commit(): get_db().commit()

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()

# Row to serializable dict helper (handles datetime)
def to_dict(row):
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime): d[k] = v.isoformat()
    return d

def init_db():
    db = psycopg2.connect(DB_URL) if DB_URL else sqlite3.connect(DB_PATH)
    is_pg = bool(DB_URL)
    try:
        cur = db.cursor()
        pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        dt = "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP" if is_pg else "TEXT NOT NULL DEFAULT (datetime('now'))"
        stmts = [
            f"CREATE TABLE IF NOT EXISTS users (id {pk}, username TEXT NOT NULL UNIQUE, email TEXT, phone TEXT, full_name TEXT NOT NULL DEFAULT '', pass_hash TEXT NOT NULL, pass_salt TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'client', is_active INTEGER NOT NULL DEFAULT 1, created_at {dt}, last_login TEXT)",
            f"CREATE TABLE IF NOT EXISTS categories (id {pk}, name TEXT NOT NULL UNIQUE, emoji TEXT NOT NULL DEFAULT '🍽', sort INTEGER NOT NULL DEFAULT 0)",
            f"CREATE TABLE IF NOT EXISTS menu (id {pk}, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL, category TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '🍽', photo_url TEXT, badge TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at {dt})",
            f"CREATE TABLE IF NOT EXISTS promos (id {pk}, code TEXT NOT NULL UNIQUE, type TEXT NOT NULL DEFAULT 'percent', value REAL NOT NULL, min_sum REAL NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, used_cnt INTEGER NOT NULL DEFAULT 0)",
            f"CREATE TABLE IF NOT EXISTS orders (id {pk}, order_num TEXT NOT NULL UNIQUE, user_id INTEGER, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT, delivery_type TEXT NOT NULL DEFAULT 'delivery', address TEXT, flat TEXT, floor TEXT, intercom TEXT, delivery_time TEXT, comment TEXT, payment TEXT NOT NULL DEFAULT 'cash', promo_code TEXT, subtotal REAL NOT NULL, discount REAL NOT NULL DEFAULT 0, total REAL NOT NULL, status TEXT NOT NULL DEFAULT 'new', items_json TEXT NOT NULL, created_at {dt}, updated_at {dt})",
            f"CREATE TABLE IF NOT EXISTS reviews (id {pk}, name TEXT NOT NULL, rating INTEGER NOT NULL, text TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0, created_at {dt})",
            f"CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            f"CREATE TABLE IF NOT EXISTS login_attempts (ip TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, locked_until TEXT, updated_at {dt})"
        ]
        for s in stmts: cur.execute(s)
        db.commit()
    finally: db.close()

try: init_db()
except Exception as e: print(f"DB Init Error: {e}")

# ─── Auth Helpers ────────────────────────────────────────────────────
def _make_token(u_id, user, role):
    payload = {'sub': u_id, 'username': user, 'role': role, 'exp': time.time() + JWT_EXPIRE_MIN*60, 'iat': time.time()}
    import base64
    pl = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    sig = hmac.new(SECRET_KEY.encode(), pl.encode(), hashlib.sha256).hexdigest()
    return f"local.{pl}.{sig}"

def _decode_token(t):
    try:
        parts = t.split('.')
        if len(parts) != 3 or parts[0] != 'local': return None
        _, pl, sig = parts
        if not hmac.compare_digest(sig, hmac.new(SECRET_KEY.encode(), pl.encode(), hashlib.sha256).hexdigest()): return None
        import base64
        data = json.loads(base64.urlsafe_b64decode(pl + '=' * (4 - len(pl)%4)).decode())
        if data['exp'] < time.time(): return None
        return data
    except: return None

def role_required(*roles):
    def dec(f):
        @wraps(f)
        def w(*a, **k):
            t = request.cookies.get('sc_token') or (request.headers.get('Authorization','')[7:] if request.headers.get('Authorization','').startswith('Bearer ') else None)
            u = _decode_token(t) if t else None
            if not u or u.get('role') not in roles: return jsonify({'error': 'Forbidden'}), 403
            g.user = u; return f(*a, **k)
        return w
    return dec

# ─── Public API ──────────────────────────────────────────────────────
@app.route('/api/auth/me')
def me():
    t = request.cookies.get('sc_token') or (request.headers.get('Authorization','')[7:] if request.headers.get('Authorization','').startswith('Bearer ') else None)
    u = _decode_token(t) if t else None
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    user = q("SELECT id, username, full_name, email, role FROM users WHERE id=?", (u['sub'],)).fetchone()
    if not user: return jsonify({'error': 'User not found'}), 404
    return jsonify({'ok': True, **to_dict(user)})

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.json or {}; user, pw = d.get('username','').strip(), d.get('password','')
    u = q("SELECT * FROM users WHERE username=? OR email=?", (user, user)).fetchone()
    if not u or _hash_password(pw, u['pass_salt']) != u['pass_hash']: return jsonify({'error': 'Неверный логин'}), 401
    t = _make_token(u['id'], u['username'], u['role'])
    r = make_response(jsonify({'ok': True, 'id': u['id'], 'username': u['username'], 'role': u['role'], 'full_name': u['full_name']}))
    r.set_cookie('sc_token', t, httponly=True, samesite='Lax', max_age=86400*30, path='/')
    return r

@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.json or {}; user, pw, full = d.get('username','').strip(), d.get('password',''), d.get('full_name','').strip()
    if len(pw) < 8: return jsonify({'error': 'Слишком короткий пароль'}), 400
    if q("SELECT id FROM users WHERE username=?", (user,)).fetchone(): return jsonify({'error': 'Логин занят'}), 409
    salt = secrets.token_hex(16); h = _hash_password(pw, salt)
    p = "%s" if getattr(g, 'is_pg', False) else "?"
    if getattr(g, 'is_pg', False): uid = q(f"INSERT INTO users (username, full_name, pass_hash, pass_salt) VALUES ({p},{p},{p},{p}) RETURNING id", (user, full, h, salt)).fetchone()['id']
    else: uid = q(f"INSERT INTO users (username, full_name, pass_hash, pass_salt) VALUES ({p},{p},{p},{p})", (user, full, h, salt)).lastrowid
    commit(); t = _make_token(uid, user, 'client')
    r = make_response(jsonify({'ok': True, 'role': 'client'}))
    r.set_cookie('sc_token', t, httponly=True, samesite='Lax', max_age=86400*30, path='/')
    return r

@app.route('/api/menu', methods=['GET', 'POST'])
def menu_api():
    if request.method == 'POST':
        u = _decode_token(request.cookies.get('sc_token','')) or {}
        if u.get('role') not in ['admin', 'manager']: return jsonify({'error': 'Forbidden'}), 403
        d = request.json or {}; p = "%s" if getattr(g, 'is_pg', False) else "?"
        sql = f"INSERT INTO menu (name, description, price, category, emoji, photo_url, badge) VALUES ({p},{p},{p},{p},{p},{p},{p})"
        if getattr(g, 'is_pg', False): uid = q(sql + " RETURNING id", (d.get('name'), d.get('description'), d.get('price'), d.get('category'), d.get('emoji'), d.get('photo_url'), d.get('badge'))).fetchone()['id']
        else: uid = q(sql, (d.get('name'), d.get('description'), d.get('price'), d.get('category'), d.get('emoji'), d.get('photo_url'), d.get('badge'))).lastrowid
        commit(); return jsonify({'ok': True, 'id': uid})
    return jsonify([to_dict(r) for r in q("SELECT * FROM menu WHERE active=1").fetchall()])

@app.route('/api/menu/<int:id>', methods=['PUT', 'DELETE'])
@role_required('admin', 'manager')
def menu_item_api(id):
    if request.method == 'DELETE': q("DELETE FROM menu WHERE id=?", (id,)); commit()
    else:
        d = request.json or {}; p = "%s" if getattr(g, 'is_pg', False) else "?"
        q(f"UPDATE menu SET name={p}, description={p}, price={p}, category={p}, emoji={p}, photo_url={p}, badge={p} WHERE id={p}",
          (d.get('name'), d.get('description'), d.get('price'), d.get('category'), d.get('emoji'), d.get('photo_url'), d.get('badge'), id))
        commit()
    return jsonify({'ok': True})

@app.route('/api/categories', methods=['GET', 'POST'])
def cats_api():
    if request.method == 'POST':
        u = _decode_token(request.cookies.get('sc_token','')) or {}
        if u.get('role') not in ['admin', 'manager']: return jsonify({'error': 'Forbidden'}), 403
        d = request.json or {}; p = "%s" if getattr(g, 'is_pg', False) else "?"
        if getattr(g, 'is_pg', False): uid = q(f"INSERT INTO categories (name, emoji) VALUES ({p},{p}) RETURNING id", (d.get('name'), d.get('emoji'))).fetchone()['id']
        else: uid = q(f"INSERT INTO categories (name, emoji) VALUES ({p},{p})", (d.get('name'), d.get('emoji'))).lastrowid
        commit(); return jsonify({'ok': True, 'id': uid})
    return jsonify([to_dict(r) for r in q("SELECT * FROM categories ORDER BY sort ASC").fetchall()])

@app.route('/api/categories/<int:id>', methods=['DELETE'])
@role_required('admin', 'manager')
def del_category(id):
    q("DELETE FROM categories WHERE id=?", (id,)); commit(); return jsonify({'ok': True})

@app.route('/api/orders', methods=['GET', 'POST'])
def orders_api():
    if request.method == 'POST':
        d = request.json or {}; items = d.get('items', [])
        if not items: return jsonify({'error': 'Basket is empty'}), 400
        subtotal = 0; final_items = []
        for i in items:
            it = q("SELECT name, price FROM menu WHERE id=?", (i['id'],)).fetchone()
            if it:
                price = it['price']; subtotal += price * i['qty']
                final_items.append({'id': i['id'], 'name': it['name'], 'price': price, 'qty': i['qty']})
        discount = 0; promo_code = d.get('promo_code', '').strip().upper()
        if promo_code:
            p = q("SELECT * FROM promos WHERE code=? AND active=1", (promo_code,)).fetchone()
            if p and subtotal >= p['min_sum']:
                discount = (subtotal * p['value'] / 100) if p['type'] == 'percent' else p['value']
                q("UPDATE promos SET used_cnt = used_cnt + 1 WHERE id=?", (p['id'],))
        total = max(0, subtotal - discount); num = datetime.now().strftime('%m%d-') + secrets.token_hex(3).upper(); p = "%s" if getattr(g, 'is_pg', False) else "?"
        q(f"INSERT INTO orders (order_num, name, phone, email, delivery_type, address, flat, floor, intercom, delivery_time, comment, payment, promo_code, subtotal, discount, total, items_json) VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})",
          (num, d.get('name',''), d.get('phone',''), d.get('email',''), d.get('delivery_type','delivery'), d.get('address',''), d.get('flat',''), d.get('floor',''), d.get('intercom',''), d.get('delivery_time','asap'), d.get('comment',''), d.get('payment','cash'), promo_code, subtotal, discount, total, json.dumps(final_items)))
        commit(); return jsonify({'ok': True, 'order_num': num})

    u = _decode_token(request.cookies.get('sc_token','')) or {}
    if u.get('role') not in ['admin', 'manager']: return jsonify({'error': 'Forbidden'}), 401
    status = request.args.get('status', '')
    if status: rows = q("SELECT * FROM orders WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else: rows = q("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    res = []; [res.append({**to_dict(r), 'items': json.loads(r['items_json'] or '[]')}) for r in rows]; return jsonify(res)

@app.route('/api/orders/<int:id>/status', methods=['PATCH'])
@role_required('admin', 'manager')
def update_order_status(id):
    s = request.json.get('status'); q("UPDATE orders SET status=? WHERE id=?", (s, id)); commit(); return jsonify({'ok': True})

@app.route('/api/promos', methods=['GET', 'POST', 'DELETE'])
@role_required('admin', 'manager')
def admin_promos():
    if request.method == 'POST':
        d = request.json or {}; p = "%s" if getattr(g, 'is_pg', False) else "?"
        if getattr(g, 'is_pg', False): uid = q(f"INSERT INTO promos (code, type, value, min_sum, description) VALUES ({p},{p},{p},{p},{p}) RETURNING id", (d['code'], d['type'], d['value'], d['min_sum'], d['description'])).fetchone()['id']
        else: uid = q(f"INSERT INTO promos (code, type, value, min_sum, description) VALUES ({p},{p},{p},{p},{p})", (d['code'], d['type'], d['value'], d['min_sum'], d['description'])).lastrowid
        commit(); return jsonify({'ok': True, 'id': uid})
    return jsonify([to_dict(r) for r in q("SELECT * FROM promos ORDER BY id DESC").fetchall()])

@app.route('/api/promos/<int:id>', methods=['DELETE'])
@role_required('admin', 'manager')
def del_p(id): q("DELETE FROM promos WHERE id=?", (id,)); commit(); return jsonify({'ok': True})

@app.route('/api/admin/users', methods=['GET'])
@role_required('admin')
def adm_users(): return jsonify([to_dict(r) for r in q("SELECT id, username, email, full_name, role, is_active, created_at FROM users").fetchall()])

@app.route('/api/settings', methods=['GET', 'POST'])
def settings_api():
    if request.method == 'POST':
        u = _decode_token(request.cookies.get('sc_token','')) or {}; if u.get('role') != 'admin': return jsonify({'error': 'Forbidden'}), 403
        d = request.json or {}
        for k, v in d.items():
            if getattr(g,'is_pg',False): q("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (k, str(v)))
            else: q("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=?", (k, str(v), str(v)))
        commit(); return jsonify({'ok': True})
    return jsonify({r['key']: r['value'] for r in q("SELECT key, value FROM settings").fetchall()})

@app.route('/api/reviews', methods=['GET', 'POST'])
def reviews_api():
    if request.method == 'POST':
        d = request.json or {}; p = "%s" if getattr(g, 'is_pg', False) else "?"
        q(f"INSERT INTO reviews (name, rating, text) VALUES ({p},{p},{p})", (d.get('name','Аноним'), d.get('rating',5), d.get('text',''))); commit(); return jsonify({'ok': True})
    return jsonify([to_dict(r) for r in q("SELECT * FROM reviews WHERE approved=1 ORDER BY created_at DESC").fetchall()])

@app.route('/api/reviews/<int:id>/approve', methods=['PATCH'])
@role_required('admin', 'manager')
def approve_rev(id): q("UPDATE reviews SET approved=1 WHERE id=?", (id,)); commit(); return jsonify({'ok': True})

@app.route('/api/reviews/<int:id>', methods=['DELETE'])
@role_required('admin', 'manager')
def del_rev(id): q("DELETE FROM reviews WHERE id=?", (id,)); commit(); return jsonify({'ok': True})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path and os.path.exists(os.path.join(PUBLIC_DIR, path)): return send_from_directory(PUBLIC_DIR, path)
    return send_from_directory(PUBLIC_DIR, 'index.html')

if __name__ == '__main__': app.run(host='0.0.0.0', port=5000)
