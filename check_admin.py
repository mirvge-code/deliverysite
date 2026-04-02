import sqlite3, json

DB_PATH = 'C:/Users/Tecno/Downloads/seychasye_v2/project/data/seychasye.db'

try:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT username, role, is_active FROM users WHERE username=?', ('admin',)).fetchone()
        if row:
            print(json.dumps(dict(row)))
        else:
            print(json.dumps({"error": "Admin user not found"}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
