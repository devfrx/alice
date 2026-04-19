import sqlite3
from pathlib import Path

candidates = list(Path("data").rglob("*.db")) + list(Path(".").rglob("*.db"))
print("DB candidates:", candidates)
db = next((str(p) for p in candidates if "alice" in p.name.lower()), None) or (str(candidates[0]) if candidates else None)
print("Using:", db)
if db:
    con = sqlite3.connect(db)
    cur = con.cursor()
    print("--- tables ---")
    for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        print(" ", r[0])
    try:
        cnt = cur.execute("SELECT COUNT(*) FROM artifacts").fetchone()
        print("artifacts count:", cnt)
        for r in cur.execute("SELECT id, kind, title, pinned, conversation_id, created_at FROM artifacts ORDER BY created_at DESC LIMIT 10"):
            print(" ", r)
    except Exception as e:
        print("artifacts query ERR:", e)
