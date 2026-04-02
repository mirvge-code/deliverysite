import hashlib, hmac, json, base64, time

SECRET_KEY = 'test_secret'
JWT_EXPIRE_MIN = 60

def _make_token(user_id: int, username: str, role: str) -> str:
    payload = {
        'sub': user_id, 'username': username, 'role': role,
        'exp': time.time() + JWT_EXPIRE_MIN * 60, 'iat': time.time(),
    }
    p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    sig = hmac.new(SECRET_KEY.encode(), p.encode(), hashlib.sha256).hexdigest()
    return f"local.{p}.{sig}"

def _decode_token(token: str):
    try:
        parts = token.split('.')
        if len(parts) != 3 or parts[0] != 'local':
            return None
        _, p, sig = parts
        expected = hmac.new(SECRET_KEY.encode(), p.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        pad = 4 - len(p) % 4
        payload = json.loads(base64.urlsafe_b64decode(p + '=' * pad).decode())
        if payload.get('exp', 0) < time.time():
            return None
        return payload
    except Exception as e:
        return f"Error: {str(e)}"

token = _make_token(1, 'admin', 'admin')
print(f"Token: {token}")
decoded = _decode_token(token)
print(f"Decoded: {decoded}")
