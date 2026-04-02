"""
Сейчастье — бэкенд v3.0
Flask + SQLite + JWT + Полная система авторизации
Роли: client, manager, admin
"""

import os, json, hashlib, hmac, secrets, time, sqlite3, re, sys
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response, g

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

# ─── Config ──────────────────────────────────────────────────────────
IS_VERCEL = bool(os.environ.get('VERCEL', ''))
BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

# Use /tmp for SQLite on Vercel
if IS_VERCEL:
    DB_PATH = '/tmp/seychasye.db'
else:
    DB_PATH = os.path.join(BASE_DIR, 'data', 'seychasye.db')

SECRET_KEY     = os.environ.get('SECRET_KEY', 'default-dev-key-change-me')
JWT_EXPIRE_MIN = int(os.environ.get('JWT_EXPIRE_MIN', 1440)) # Default 1 day

TG_TOKEN   = os.environ.get('TG_BOT_TOKEN', '')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID', '')

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__, static_folder=None) # Disable default static serving for Vercel
app.config['SECRET_KEY'] = SECRET_KEY

# ─── DB ──────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    NOT NULL UNIQUE,
            email       TEXT,
            phone       TEXT,
            full_name   TEXT    NOT NULL DEFAULT '',
            pass_hash   TEXT    NOT NULL,
            pass_salt   TEXT    NOT NULL,
            role        TEXT    NOT NULL DEFAULT 'client',
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            last_login  TEXT
        );

        CREATE TABLE IF NOT EXISTS categories (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL UNIQUE,
            emoji TEXT NOT NULL DEFAULT '🍽',
            sort  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS menu_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            price       INTEGER NOT NULL,
            category    TEXT    NOT NULL,
            emoji       TEXT    NOT NULL DEFAULT '🍽',
            photo_url   TEXT,
            badge       TEXT    DEFAULT '',
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS promos (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            code     TEXT    NOT NULL UNIQUE,
            type     TEXT    NOT NULL DEFAULT 'percent',
            value    REAL    NOT NULL,
            min_sum  REAL    NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            active   INTEGER NOT NULL DEFAULT 1,
            used_cnt INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS orders (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            order_num    TEXT    NOT NULL UNIQUE,
            user_id      INTEGER,
            name         TEXT    NOT NULL,
            phone        TEXT    NOT NULL,
            email        TEXT,
            delivery_type TEXT   NOT NULL DEFAULT 'delivery',
            address      TEXT,
            flat         TEXT,
            floor        TEXT,
            intercom     TEXT,
            delivery_time TEXT,
            comment      TEXT,
            payment      TEXT    NOT NULL DEFAULT 'cash',
            promo_code   TEXT,
            subtotal     REAL    NOT NULL,
            discount     REAL    NOT NULL DEFAULT 0,
            total        REAL    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'new',
            items_json   TEXT    NOT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            rating     INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            text       TEXT NOT NULL,
            approved   INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            ip         TEXT NOT NULL,
            attempts   INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ip)
        );
        ''')

        # --- Migration for existing databases ---
        cols = {c[1] for c in db.execute("PRAGMA table_info(users)").fetchall()}
        for col, ddl in [('email','email TEXT'),('phone','phone TEXT'),
                         ('full_name',"full_name TEXT NOT NULL DEFAULT ''"),
                         ('is_active',"is_active INTEGER NOT NULL DEFAULT 1")]:
            if col not in cols:
                db.execute(f"ALTER TABLE users ADD COLUMN {ddl}")

        cols_o = {c[1] for c in db.execute("PRAGMA table_info(orders)").fetchall()}
        if 'user_id' not in cols_o:
            db.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")

        # Seed default admin
        existing = db.execute('SELECT id FROM users WHERE username=?', ('admin',)).fetchone()
        if not existing:
            salt = secrets.token_hex(16)
            pw_hash = _hash_password('admin123', salt)
            db.execute(
                'INSERT INTO users (username, pass_hash, pass_salt, role, full_name) VALUES (?,?,?,?,?)',
                ('admin', pw_hash, salt, 'admin', 'Администратор')
            )

        # Seed categories
        if not db.execute('SELECT id FROM categories LIMIT 1').fetchone():
            cats = [('Пицца','🍕',1),('Бургеры','🍔',2),('Суши','🍣',3),
                    ('Паста','🍝',4),('Салаты','🥗',5),('Десерты','🍰',6)]
            db.executemany('INSERT OR IGNORE INTO categories (name,emoji,sort) VALUES (?,?,?)', cats)

        # Seed menu
        if not db.execute('SELECT id FROM menu_items LIMIT 1').fetchone():
            items = [
                ('Пицца Маргарита','Томатный соус, моцарелла, свежий базилик',450,'Пицца','🍕','https://images.unsplash.com/photo-1604382354936-07c5d9983bd3?w=600&q=80','хит'),
                ('Пицца Пепперони','Острая пепперони, томатный соус, сыр',520,'Пицца','🍕','https://images.unsplash.com/photo-1628840042765-356cda07504e?w=600&q=80',''),
                ('Пицца 4 сыра','Моцарелла, пармезан, горгонзола, чеддер',590,'Пицца','🍕','https://images.unsplash.com/photo-1513104890138-7c749659a591?w=600&q=80','новинка'),
                ('Чизбургер','Говяжья котлета, чеддер, маринованный огурец',380,'Бургеры','🍔','https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=600&q=80','хит'),
                ('Смоки Бургер','Копчёная котлета, бекон, лук, BBQ соус',430,'Бургеры','🍔','https://images.unsplash.com/photo-1553979459-d2229ba7433b?w=600&q=80',''),
                ('Гриль Бургер','Говядина на гриле, авокадо, руккола',480,'Бургеры','🍔','https://images.unsplash.com/photo-1586816001966-79b736744398?w=600&q=80','новинка'),
                ('Сет Калифорния','Краб, авокадо, огурец, икра тобико',680,'Суши','🍣','https://images.unsplash.com/photo-1562802378-063ec186a863?w=600&q=80','хит'),
                ('Лосось Ролл','Нежный лосось, сливочный сыр, огурец',620,'Суши','🍣','https://images.unsplash.com/photo-1553621042-f6e147245754?w=600&q=80',''),
                ('Карбонара','Паста, бекон, яйцо, пармезан, сливки',490,'Паста','🍝','https://images.unsplash.com/photo-1612874742237-6526221588e3?w=600&q=80',''),
                ('Болоньезе','Мясной соус, томаты, пармезан, базилик',460,'Паста','🍝','https://images.unsplash.com/photo-1555949258-eb67b1ef0ceb?w=600&q=80','хит'),
                ('Греческий салат','Фета, оливки, огурец, томаты, перец',320,'Салаты','🥗','https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?w=600&q=80',''),
                ('Тирамису','Маскарпоне, савоярди, кофе, какао',290,'Десерты','🍰','https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?w=600&q=80','новинка'),
            ]
            db.executemany('INSERT INTO menu_items (name,description,price,category,emoji,photo_url,badge) VALUES (?,?,?,?,?,?,?)', items)

        # Seed promos
        if not db.execute('SELECT id FROM promos LIMIT 1').fetchone():
            db.executemany('INSERT OR IGNORE INTO promos (code,type,value,min_sum,description) VALUES (?,?,?,?,?)', [
                ('СЕЙЧАСТЬЕ','percent',10,0,'Скидка 10% на весь заказ'),
                ('НОВЫЙ','fixed',150,500,'150 ₽ при заказе от 500 ₽'),
            ])

        # Seed reviews
        if not db.execute('SELECT id FROM reviews LIMIT 1').fetchone():
            db.executemany('INSERT INTO reviews (name,rating,text,approved,created_at) VALUES (?,?,?,?,?)', [
                ('Анна К.',5,'Всё пришло горячим, упаковка отличная. Буду заказывать снова!',1,'2025-05-12 12:00:00'),
                ('Дмитрий',5,'Пицца Маргарита — лучшая в городе. Доставили за 22 минуты!',1,'2025-05-08 18:30:00'),
                ('Мария С.',4,'Отличное меню, большой выбор. Немного задержали, но курьер извинился.',1,'2025-05-02 20:10:00'),
            ])

        # Seed settings
        defaults = {
            'hero_title': 'Еда у двери', 'hero_time': '30 мин',
            'hero_sub': 'Лучшие рестораны города — одно нажатие от вас. Свежо, вкусно, вовремя.',
            'stat_orders': '12 000+', 'stat_partners': '80+', 'stat_rating': '4.9',
            'phone': '+7 (900) 123-45-67', 'email': 'hello@seychasye.ru',
            'address': 'Москва, ул. Вкусная, 1', 'hours': 'Пн–Вс: 10:00–23:00',
            'footer': '© 2025 Сейчастье — Доставка еды. Все права защищены.',
            'about_title': 'Мы доставляем с душой',
            'about_text': 'С 2019 года мы помогаем людям наслаждаться едой из лучших ресторанов города, не выходя из дома.',
            'promo_title': 'Первый заказ — скидка 10%',
            'promo_desc': 'Введите промокод СЕЙЧАСТЬЕ при оформлении',
            'promo_banner_code': 'СЕЙЧАСТЬЕ',
            'accent_color': '#F5C518', 'dark_color': '#1E1E1E',
        }
        for k, v in defaults.items():
            db.execute('INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)', (k, v))
        db.commit()

# Ensure DB is initialized
try:
    init_db()
except Exception as e:
    print(f"CRITICAL: DB init failed: {e}")

# ─── Auth helpers ─────────────────────────────────────────────────────
def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()

def _make_token(user_id: int, username: str, role: str) -> str:
    payload = {
        'sub': user_id, 'username': username, 'role': role,
        'exp': time.time() + JWT_EXPIRE_MIN * 60, 'iat': time.time(),
    }
    if False: # HAS_JWT:
        return pyjwt.encode(payload, SECRET_KEY, algorithm='HS256')
    import base64
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    sig = hmac.new(SECRET_KEY.encode(), p.encode(), hashlib.sha256).hexdigest()
    return f"local.{p}.{sig}"

def _decode_token(token: str):
    try:
        if HAS_JWT and not token.startswith('local.'):
            # PyJWT
            return pyjwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        
        import base64
        parts = token.split('.')
        if len(parts) != 3 or parts[0] != 'local':
            print(f"DEBUG: Token bad format or missing 'local.': {token[:20] if token else 'None'}")
            return None
        _, p, sig = parts
        expected = hmac.new(SECRET_KEY.encode(), p.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            print("DEBUG: Token signature mismatch")
            return None
        pad = (4 - len(p) % 4) % 4
        payload = json.loads(base64.urlsafe_b64decode(p + '=' * pad).decode())
        if payload.get('exp', 0) < time.time():
            print("DEBUG: Token expired")
            return None
        return payload
    except Exception as e:
        print(f"DEBUG: Token error: {str(e)}")
        return None

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.cookies.get('sc_token')
        if not token:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
        
        payload = _decode_token(token) if token else None
        if not payload:
            return jsonify({'error': 'Unauthorized'}), 401
        g.user = payload
        return f(*args, **kwargs)
    return wrapper

def require_role(*roles):
    """Require authentication AND one of the specified roles."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = request.cookies.get('sc_token')
            if not token:
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header[7:]
            
            payload = _decode_token(token) if token else None
            if not payload:
                return jsonify({'error': 'Unauthorized'}), 401
            if payload.get('role') not in roles:
                return jsonify({'error': 'Forbidden'}), 403
            g.user = payload
            return f(*args, **kwargs)
        return wrapper
    return decorator

def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'

# ─── Telegram ─────────────────────────────────────────────────────────
def send_telegram(text: str):
    if not TG_TOKEN or not TG_CHAT_ID or not HAS_URLLIB:
        return
    try:
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        data = json.dumps({'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode()
        req = urlreq.Request(url, data=data, headers={'Content-Type': 'application/json'})
        urlreq.urlopen(req, timeout=5)
    except Exception:
        pass

def order_to_tg(order: dict) -> str:
    items = json.loads(order.get('items_json', '[]'))
    items_str = '\n'.join(f"  • {i['name']} × {i['qty']} = {i['price']*i['qty']} ₽" for i in items)
    delivery = '🚴 Доставка' if order['delivery_type'] == 'delivery' else '🏪 Самовывоз'
    addr = f"\n📍 {order['address']}" if order.get('address') else ''
    promo = f"\n🎟 Промокод: {order['promo_code']} (−{order['discount']} ₽)" if order.get('promo_code') else ''
    return (
        f"🛎 <b>Новый заказ #{order['order_num']}</b>\n\n"
        f"👤 {order['name']}\n📞 {order['phone']}\n{delivery}{addr}\n💳 {order['payment']}\n{promo}\n\n"
        f"<b>Состав:</b>\n{items_str}\n\n💰 Итого: <b>{order['total']} ₽</b>\n🕐 {order['created_at']}"
    )

# ─── API: Auth ────────────────────────────────────────────────────────
MAX_ATTEMPTS = 5
LOCKOUT_SEC  = 5 * 60

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username  = str(data.get('username', '')).strip()
    password  = str(data.get('password', ''))
    confirm   = str(data.get('confirm', ''))
    full_name = str(data.get('full_name', '')).strip()
    email     = str(data.get('email', '')).strip() or None
    phone     = str(data.get('phone', '')).strip() or None

    if not username or len(username) < 3:
        return jsonify({'error': 'Логин — минимум 3 символа'}), 400
    if not re.match(r'^[a-zA-Z0-9_а-яА-ЯёЁ]+$', username):
        return jsonify({'error': 'Логин: только буквы, цифры, _'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Пароль — минимум 8 символов'}), 400
    if password != confirm:
        return jsonify({'error': 'Пароли не совпадают'}), 400
    if not full_name:
        return jsonify({'error': 'Введите ваше имя'}), 400
    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Некорректный email'}), 400

    db = get_db()
    if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
        return jsonify({'error': 'Логин уже занят'}), 409
    if email and db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
        return jsonify({'error': 'Email уже зарегистрирован'}), 409

    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    cur = db.execute(
        'INSERT INTO users (username,email,phone,full_name,pass_hash,pass_salt,role) VALUES (?,?,?,?,?,?,?)',
        (username, email, phone, full_name, pw_hash, salt, 'client')
    )
    db.commit()
    token = _make_token(cur.lastrowid, username, 'client')
    resp = make_response(jsonify({
        'ok': True, 'id': cur.lastrowid, 'username': username,
        'role': 'client', 'full_name': full_name, 'email': email
    }), 201)
    resp.set_cookie('sc_token', token, httponly=True, samesite='None', secure=False,
                    max_age=JWT_EXPIRE_MIN * 60, path='/')
    return resp

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))
    ip = get_client_ip()
    db = get_db()

    row = db.execute('SELECT attempts, locked_until FROM login_attempts WHERE ip=?', (ip,)).fetchone()
    if row and row['locked_until']:
        locked = datetime.fromisoformat(row['locked_until'])
        if datetime.utcnow() < locked:
            secs = int((locked - datetime.utcnow()).total_seconds())
            return jsonify({'error': f'Заблокировано. Подождите {secs} сек.', 'locked': True}), 429

    if not username or not password:
        return jsonify({'error': 'Введите логин и пароль'}), 400

    # Allow login by username or email
    user = db.execute('SELECT * FROM users WHERE username=? OR email=?', (username, username)).fetchone()
    if not user or _hash_password(password, user['pass_salt']) != user['pass_hash']:
        attempts = (row['attempts'] if row else 0) + 1
        locked_until = None
        if attempts >= MAX_ATTEMPTS:
            locked_until = (datetime.utcnow() + timedelta(seconds=LOCKOUT_SEC)).isoformat()
            attempts = 0
        db.execute(
            'INSERT INTO login_attempts (ip,attempts,locked_until,updated_at) VALUES (?,?,?,datetime("now")) '
            'ON CONFLICT(ip) DO UPDATE SET attempts=?,locked_until=?,updated_at=datetime("now")',
            (ip, attempts, locked_until, attempts, locked_until)
        )
        db.commit()
        left = MAX_ATTEMPTS - attempts if not locked_until else 0
        msg = f'Неверный логин или пароль. Осталось попыток: {left}' if left > 0 else 'Слишком много попыток. Заблокировано на 5 минут.'
        return jsonify({'error': msg, 'attempts_left': left}), 401

    if not user['is_active']:
        return jsonify({'error': 'Аккаунт заблокирован. Обратитесь к администратору.'}), 403

    db.execute('DELETE FROM login_attempts WHERE ip=?', (ip,))
    db.execute('UPDATE users SET last_login=datetime("now") WHERE id=?', (user['id'],))
    db.commit()

    token = _make_token(user['id'], user['username'], user['role'])
    resp = make_response(jsonify({
        'ok': True, 'id': user['id'], 'username': user['username'],
        'role': user['role'], 'full_name': user['full_name'] or '',
        'email': user['email'] or '', 'phone': user['phone'] or ''
    }))
    resp.set_cookie('sc_token', token, httponly=True, samesite='None', secure=False,
                    max_age=JWT_EXPIRE_MIN * 60, path='/')
    return resp

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'ok': True}))
    resp.delete_cookie('sc_token', path='/')
    return resp

@app.route('/api/auth/me', methods=['GET'])
@require_auth
def me():
    db = get_db()
    user = db.execute(
        'SELECT id,username,email,phone,full_name,role,is_active,created_at,last_login FROM users WHERE id=?',
        (g.user['sub'],)
    ).fetchone()
    if not user:
        return jsonify({'error': 'Not found'}), 404
    if not user['is_active']:
        resp = make_response(jsonify({'error': 'Account blocked'}), 403)
        resp.delete_cookie('sc_token', path='/')
        return resp
    return jsonify(dict(user))

@app.route('/api/auth/profile', methods=['PUT'])
@require_auth
def update_profile():
    data = request.get_json(silent=True) or {}
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (g.user['sub'],)).fetchone()
    if not user:
        return jsonify({'error': 'Not found'}), 404

    full_name = str(data.get('full_name', user['full_name'])).strip()
    email = str(data.get('email', '')).strip() or user['email']
    phone = str(data.get('phone', '')).strip() or user['phone']

    if not full_name:
        return jsonify({'error': 'Введите имя'}), 400
    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Некорректный email'}), 400
    if email and email != user['email']:
        conflict = db.execute('SELECT id FROM users WHERE email=? AND id!=?', (email, user['id'])).fetchone()
        if conflict:
            return jsonify({'error': 'Email уже используется'}), 409

    db.execute('UPDATE users SET full_name=?, email=?, phone=? WHERE id=?',
               (full_name, email, phone, user['id']))
    db.commit()
    return jsonify({'ok': True, 'full_name': full_name, 'email': email, 'phone': phone})

@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    data = request.get_json(silent=True) or {}
    old_pass  = str(data.get('old_pass', ''))
    new_pass  = str(data.get('new_pass', ''))
    confirm   = str(data.get('confirm', ''))

    if len(new_pass) < 8:
        return jsonify({'error': 'Пароль — минимум 8 символов'}), 400
    if new_pass != confirm:
        return jsonify({'error': 'Пароли не совпадают'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (g.user['sub'],)).fetchone()
    if not user:
        return jsonify({'error': 'Not found'}), 404

    if _hash_password(old_pass, user['pass_salt']) != user['pass_hash']:
        return jsonify({'error': 'Неверный текущий пароль'}), 403

    salt = secrets.token_hex(16)
    pw_hash = _hash_password(new_pass, salt)
    db.execute('UPDATE users SET pass_hash=?, pass_salt=? WHERE id=?', (pw_hash, salt, user['id']))
    db.commit()

    token = _make_token(user['id'], user['username'], user['role'])
    resp = make_response(jsonify({'ok': True}))
    resp.set_cookie('sc_token', token, httponly=True, samesite='None', secure=False,
                    max_age=JWT_EXPIRE_MIN * 60, path='/')
    return resp

# ─── API: Admin Users ─────────────────────────────────────────────────
@app.route('/api/admin/users', methods=['GET'])
@require_role('admin')
def admin_list_users():
    db = get_db()
    role = request.args.get('role', '')
    q = f'%{request.args.get("q", "")}%'
    sql = 'SELECT id,username,email,phone,full_name,role,is_active,created_at,last_login FROM users WHERE (username LIKE ? OR full_name LIKE ? OR email LIKE ?)'
    params = [q, q, q]
    if role:
        sql += ' AND role=?'
        params.append(role)
    sql += ' ORDER BY created_at DESC'
    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/users', methods=['POST'])
@require_role('admin')
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username  = str(data.get('username', '')).strip()
    password  = str(data.get('password', ''))
    full_name = str(data.get('full_name', '')).strip()
    role      = str(data.get('role', 'manager'))
    email     = str(data.get('email', '')).strip() or None

    if not username or len(username) < 3:
        return jsonify({'error': 'Логин — минимум 3 символа'}), 400
    if len(password) < 8:
        return jsonify({'error': 'Пароль — минимум 8 символов'}), 400
    if role not in ('client', 'manager', 'admin'):
        return jsonify({'error': 'Недопустимая роль'}), 400

    db = get_db()
    if db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
        return jsonify({'error': 'Логин уже занят'}), 409

    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    cur = db.execute(
        'INSERT INTO users (username,email,full_name,pass_hash,pass_salt,role) VALUES (?,?,?,?,?,?)',
        (username, email, full_name or username, pw_hash, salt, role)
    )
    db.commit()
    return jsonify({'ok': True, 'id': cur.lastrowid}), 201

@app.route('/api/admin/users/<int:user_id>/role', methods=['PATCH'])
@require_role('admin')
def admin_change_role(user_id):
    data = request.get_json(silent=True) or {}
    role = str(data.get('role', ''))
    if role not in ('client', 'manager', 'admin'):
        return jsonify({'error': 'Недопустимая роль'}), 400
    if user_id == g.user['sub']:
        return jsonify({'error': 'Нельзя изменить свою роль'}), 400
    db = get_db()
    db.execute('UPDATE users SET role=? WHERE id=?', (role, user_id))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/admin/users/<int:user_id>/status', methods=['PATCH'])
@require_role('admin')
def admin_toggle_status(user_id):
    if user_id == g.user['sub']:
        return jsonify({'error': 'Нельзя заблокировать себя'}), 400
    db = get_db()
    user = db.execute('SELECT is_active FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        return jsonify({'error': 'Не найден'}), 404
    new_status = 0 if user['is_active'] else 1
    db.execute('UPDATE users SET is_active=? WHERE id=?', (new_status, user_id))
    db.commit()
    return jsonify({'ok': True, 'is_active': new_status})

@app.route('/api/admin/users/<int:user_id>/reset-password', methods=['PATCH'])
@require_role('admin')
def admin_reset_password(user_id):
    data = request.get_json(silent=True) or {}
    new_pass = str(data.get('new_password', ''))
    if len(new_pass) < 8:
        return jsonify({'error': 'Пароль — минимум 8 символов'}), 400
    db = get_db()
    user = db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        return jsonify({'error': 'Не найден'}), 404
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(new_pass, salt)
    db.execute('UPDATE users SET pass_hash=?, pass_salt=? WHERE id=?', (pw_hash, salt, user_id))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@require_role('admin')
def admin_delete_user(user_id):
    if user_id == g.user['sub']:
        return jsonify({'error': 'Нельзя удалить свой аккаунт'}), 400
    db = get_db()
    db.execute('UPDATE orders SET user_id=NULL WHERE user_id=?', (user_id,))
    db.execute('DELETE FROM users WHERE id=?', (user_id,))
    db.commit()
    return jsonify({'ok': True})

# ─── API: Client Orders ───────────────────────────────────────────────
@app.route('/api/client/orders', methods=['GET'])
@require_auth
def client_orders():
    db = get_db()
    rows = db.execute(
        'SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 50',
        (g.user['sub'],)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['items'] = json.loads(d['items_json'])
        result.append(d)
    return jsonify(result)

# ─── API: Categories ───────────────────────────────────────────────────
@app.route('/api/categories', methods=['GET'])
def get_categories():
    db = get_db()
    rows = db.execute('SELECT * FROM categories ORDER BY sort, name').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/categories', methods=['POST'])
@require_role('manager', 'admin')
def add_category():
    data = request.get_json(silent=True) or {}
    name  = str(data.get('name', '')).strip()
    emoji = str(data.get('emoji', '🍽')).strip() or '🍽'
    if not name:
        return jsonify({'error': 'Название обязательно'}), 400
    db = get_db()
    try:
        cur = db.execute('INSERT INTO categories (name,emoji) VALUES (?,?)', (name, emoji))
        db.commit()
        return jsonify({'id': cur.lastrowid, 'name': name, 'emoji': emoji})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Категория уже существует'}), 409

@app.route('/api/categories/<int:cat_id>', methods=['DELETE'])
@require_role('manager', 'admin')
def delete_category(cat_id):
    db = get_db()
    cat = db.execute('SELECT * FROM categories WHERE id=?', (cat_id,)).fetchone()
    if not cat:
        return jsonify({'error': 'Не найдено'}), 404
    db.execute('UPDATE menu_items SET active=0 WHERE category=?', (cat['name'],))
    db.execute('DELETE FROM categories WHERE id=?', (cat_id,))
    db.commit()
    return jsonify({'ok': True})

# ─── API: Menu ─────────────────────────────────────────────────────────
@app.route('/api/menu', methods=['GET'])
def get_menu():
    db = get_db()
    rows = db.execute('SELECT * FROM menu_items WHERE active=1 ORDER BY id').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/menu', methods=['POST'])
@require_role('manager', 'admin')
def add_menu_item():
    data = request.get_json(silent=True) or {}
    name  = str(data.get('name', '')).strip()
    price = data.get('price')
    cat   = str(data.get('category', '')).strip()
    if not name or not price or not cat:
        return jsonify({'error': 'Название, цена и категория обязательны'}), 400
    try:
        price = int(price)
        assert price > 0
    except Exception:
        return jsonify({'error': 'Некорректная цена'}), 400
    db = get_db()
    db.execute('INSERT OR IGNORE INTO categories (name,emoji) VALUES (?,?)',
               (cat, str(data.get('emoji','🍽'))))
    cur = db.execute(
        'INSERT INTO menu_items (name,description,price,category,emoji,photo_url,badge) VALUES (?,?,?,?,?,?,?)',
        (name, str(data.get('description','')), price, cat,
         str(data.get('emoji','🍽')), data.get('photo_url'), str(data.get('badge','')))
    )
    db.commit()
    row = db.execute('SELECT * FROM menu_items WHERE id=?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.route('/api/menu/<int:item_id>', methods=['PUT'])
@require_role('manager', 'admin')
def update_menu_item(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    item = db.execute('SELECT * FROM menu_items WHERE id=?', (item_id,)).fetchone()
    if not item:
        return jsonify({'error': 'Не найдено'}), 404
    name  = str(data.get('name', item['name'])).strip()
    price = int(data.get('price', item['price']))
    cat   = str(data.get('category', item['category'])).strip()
    db.execute('INSERT OR IGNORE INTO categories (name,emoji) VALUES (?,?)', (cat, data.get('emoji','🍽')))
    db.execute(
        'UPDATE menu_items SET name=?,description=?,price=?,category=?,emoji=?,photo_url=?,badge=? WHERE id=?',
        (name, str(data.get('description', item['description'])), price, cat,
         str(data.get('emoji', item['emoji'])), data.get('photo_url', item['photo_url']),
         str(data.get('badge', item['badge'])), item_id)
    )
    db.commit()
    row = db.execute('SELECT * FROM menu_items WHERE id=?', (item_id,)).fetchone()
    return jsonify(dict(row))

@app.route('/api/menu/<int:item_id>', methods=['DELETE'])
@require_role('manager', 'admin')
def delete_menu_item(item_id):
    db = get_db()
    db.execute('UPDATE menu_items SET active=0 WHERE id=?', (item_id,))
    db.commit()
    return jsonify({'ok': True})

# ─── API: Promos ────────────────────────────────────────────────────────
@app.route('/api/promos', methods=['GET'])
@require_role('manager', 'admin')
def get_promos():
    db = get_db()
    rows = db.execute('SELECT * FROM promos ORDER BY id').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/promos/validate', methods=['POST'])
def validate_promo():
    data   = request.get_json(silent=True) or {}
    code   = str(data.get('code', '')).strip().upper()
    amount = float(data.get('amount', 0))
    db = get_db()
    promo = db.execute('SELECT * FROM promos WHERE UPPER(code)=? AND active=1', (code,)).fetchone()
    if not promo:
        return jsonify({'error': 'Промокод не найден'}), 404
    if amount < promo['min_sum']:
        return jsonify({'error': f'Минимальная сумма: {int(promo["min_sum"])} ₽', 'min_sum': promo['min_sum']}), 400
    discount = round(amount * promo['value'] / 100) if promo['type'] == 'percent' else min(promo['value'], amount)
    return jsonify({'ok': True, 'discount': discount, 'description': promo['description'],
                    'type': promo['type'], 'value': promo['value']})

@app.route('/api/promos', methods=['POST'])
@require_role('manager', 'admin')
def add_promo():
    data  = request.get_json(silent=True) or {}
    code  = str(data.get('code', '')).strip().upper()
    value = float(data.get('value', 0))
    if not code or value <= 0:
        return jsonify({'error': 'Код и значение обязательны'}), 400
    db = get_db()
    try:
        cur = db.execute('INSERT INTO promos (code,type,value,min_sum,description) VALUES (?,?,?,?,?)',
                         (code, data.get('type','percent'), value,
                          float(data.get('min_sum', 0)), str(data.get('description', code))))
        db.commit()
        return jsonify({'id': cur.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Промокод уже существует'}), 409

@app.route('/api/promos/<int:promo_id>', methods=['DELETE'])
@require_role('manager', 'admin')
def delete_promo(promo_id):
    db = get_db()
    db.execute('DELETE FROM promos WHERE id=?', (promo_id,))
    db.commit()
    return jsonify({'ok': True})

# ─── API: Orders ────────────────────────────────────────────────────────
def _generate_order_num():
    return f"{datetime.now().strftime('%y%m%d')}-{secrets.token_hex(3).upper()}"

@app.route('/api/orders', methods=['POST'])
def place_order():
    data = request.get_json(silent=True) or {}
    name  = str(data.get('name', '')).strip()
    phone = str(data.get('phone', '')).strip()
    if not name or not phone:
        return jsonify({'error': 'Имя и телефон обязательны'}), 400
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'Корзина пуста'}), 400

    db = get_db()
    # Determine user_id from auth token if present
    user_id = None
    token = request.cookies.get('sc_token') or request.headers.get('Authorization', '').removeprefix('Bearer ')
    payload = _decode_token(token)
    if payload:
        user_id = payload.get('sub')

    subtotal = 0
    enriched = []
    for it in items:
        row = db.execute('SELECT * FROM menu_items WHERE id=? AND active=1', (int(it['id']),)).fetchone()
        if not row:
            return jsonify({'error': f'Товар #{it["id"]} не найден'}), 400
        qty = int(it.get('qty', 1))
        subtotal += row['price'] * qty
        enriched.append({'id': row['id'], 'name': row['name'], 'price': row['price'], 'qty': qty})

    discount = 0
    promo_code = str(data.get('promo_code', '')).strip().upper() or None
    if promo_code:
        promo = db.execute('SELECT * FROM promos WHERE UPPER(code)=? AND active=1', (promo_code,)).fetchone()
        if promo and subtotal >= promo['min_sum']:
            discount = round(subtotal * promo['value'] / 100) if promo['type'] == 'percent' else min(promo['value'], subtotal)
            db.execute('UPDATE promos SET used_cnt=used_cnt+1 WHERE id=?', (promo['id'],))

    total = subtotal - discount
    order_num = _generate_order_num()

    cur = db.execute('''
        INSERT INTO orders
        (order_num,user_id,name,phone,email,delivery_type,address,flat,floor,intercom,
         delivery_time,comment,payment,promo_code,subtotal,discount,total,status,items_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        order_num, user_id, name, phone,
        data.get('email',''), data.get('delivery_type','delivery'),
        data.get('address',''), data.get('flat',''), data.get('floor',''), data.get('intercom',''),
        data.get('delivery_time','asap'), data.get('comment',''),
        data.get('payment','cash'), promo_code,
        subtotal, discount, total, 'new',
        json.dumps(enriched, ensure_ascii=False)
    ))
    db.commit()

    order = dict(db.execute('SELECT * FROM orders WHERE id=?', (cur.lastrowid,)).fetchone())
    send_telegram(order_to_tg(order))
    return jsonify({'ok': True, 'order_num': order_num, 'total': total}), 201

@app.route('/api/orders', methods=['GET'])
@require_role('manager', 'admin')
def get_orders():
    db = get_db()
    status = request.args.get('status', '')
    q = f'%{request.args.get("q", "")}%'
    sql = 'SELECT * FROM orders WHERE (name LIKE ? OR phone LIKE ? OR order_num LIKE ?)'
    params = [q, q, q]
    if status:
        sql += ' AND status=?'
        params.append(status)
    sql += ' ORDER BY created_at DESC LIMIT 200'
    rows = db.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['items'] = json.loads(d['items_json'])
        result.append(d)
    return jsonify(result)

@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
@require_role('manager', 'admin')
def update_order_status(order_id):
    data   = request.get_json(silent=True) or {}
    status = str(data.get('status', '')).strip()
    valid  = ('new','confirmed','preparing','delivering','done','cancelled')
    if status not in valid:
        return jsonify({'error': 'Некорректный статус'}), 400
    db = get_db()
    db.execute('UPDATE orders SET status=?, updated_at=datetime("now") WHERE id=?', (status, order_id))
    db.commit()
    return jsonify({'ok': True})

# ─── API: Reviews ───────────────────────────────────────────────────────
@app.route('/api/reviews', methods=['GET'])
def get_reviews():
    db = get_db()
    token = request.cookies.get('sc_token', '')
    payload = _decode_token(token)
    is_staff = payload and payload.get('role') in ('manager', 'admin')
    if is_staff:
        rows = db.execute('SELECT * FROM reviews ORDER BY created_at DESC').fetchall()
    else:
        rows = db.execute('SELECT * FROM reviews WHERE approved=1 ORDER BY created_at DESC').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/reviews', methods=['POST'])
def add_review():
    data   = request.get_json(silent=True) or {}
    name   = str(data.get('name', '')).strip()
    rating = int(data.get('rating', 0))
    text   = str(data.get('text', '')).strip()
    if not name or not text or rating not in range(1, 6):
        return jsonify({'error': 'Заполните все поля'}), 400
    db = get_db()
    cur = db.execute('INSERT INTO reviews (name,rating,text) VALUES (?,?,?)', (name, rating, text))
    db.commit()
    return jsonify({'id': cur.lastrowid, 'ok': True}), 201

@app.route('/api/reviews/<int:rev_id>/approve', methods=['PATCH'])
@require_role('manager', 'admin')
def approve_review(rev_id):
    db = get_db()
    db.execute('UPDATE reviews SET approved=1 WHERE id=?', (rev_id,))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/reviews/<int:rev_id>', methods=['DELETE'])
@require_role('manager', 'admin')
def delete_review(rev_id):
    db = get_db()
    db.execute('DELETE FROM reviews WHERE id=?', (rev_id,))
    db.commit()
    return jsonify({'ok': True})

# ─── API: Settings ──────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    db = get_db()
    rows = db.execute('SELECT key, value FROM settings').fetchall()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['POST'])
@require_role('admin')
def save_settings():
    data = request.get_json(silent=True) or {}
    db = get_db()
    for k, v in data.items():
        if re.match(r'^[a-z_]+$', k):
            db.execute('INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=?',
                       (k, str(v), str(v)))
    db.commit()
    return jsonify({'ok': True})

# ─── Static / SPA ──────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path and os.path.exists(os.path.join(PUBLIC_DIR, path)):
        return send_from_directory(PUBLIC_DIR, path)
    return send_from_directory(PUBLIC_DIR, 'index.html')

# ─── Run ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print(f'🚀 Сейчастье запущен: http://localhost:{port}')
    print(f'🔑 Вход по умолчанию: admin / admin123')
    if TG_TOKEN:
        print(f'📱 Telegram бот подключён')
    app.run(host='0.0.0.0', port=port, debug=False)
