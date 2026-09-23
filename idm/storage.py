import sqlite3, os, threading, time, json, csv, shutil
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "InternetDownloadManager"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "downloads.db"
DEFAULT_DIR = Path.home() / "Downloads"

class Storage:
    def __init__(self):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("""CREATE TABLE IF NOT EXISTS downloads(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                filename TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER DEFAULT 0,
                downloaded INTEGER DEFAULT 0,
                error TEXT DEFAULT '',
                category TEXT DEFAULT 'Other',
                queue_name TEXT DEFAULT 'Main',
                priority INTEGER DEFAULT 0,
                scheduled_at REAL DEFAULT 0,
                created REAL,
                updated REAL
            )""")
            self.conn.commit()
            # Upgrade databases created by v0.3.x.
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(downloads)")}
            for name, ddl in [
                ("category", "TEXT DEFAULT 'Other'"),
                ("queue_name", "TEXT DEFAULT 'Main'"),
                ("priority", "INTEGER DEFAULT 0"),
                ("scheduled_at", "REAL DEFAULT 0"),
                ("connections", "INTEGER DEFAULT 4"),
                ("expected_hash", "TEXT DEFAULT ''"),
                ("hash_algorithm", "TEXT DEFAULT 'SHA-256'"),
                ("started", "REAL DEFAULT 0"),
                ("completed", "REAL DEFAULT 0"),
                ("retry_count", "INTEGER DEFAULT 0"),
            ]:
                if name not in cols:
                    self.conn.execute(f"ALTER TABLE downloads ADD COLUMN {name} {ddl}")
            self.conn.commit()

    def recover_incomplete(self):
        with self.lock:
            rows=self.conn.execute("SELECT id FROM downloads WHERE status='Downloading'").fetchall()
            if rows:
                self.conn.execute("UPDATE downloads SET status='Paused', error='Recovered after application restart; resume is available.', updated=? WHERE status='Downloading'", (time.time(),))
                self.conn.commit()

    def all(self):
        with self.lock:
            return self.conn.execute("SELECT * FROM downloads ORDER BY priority DESC, id DESC").fetchall()

    def get(self, row_id):
        with self.lock:
            return self.conn.execute("SELECT * FROM downloads WHERE id=?", (row_id,)).fetchone()

    def add(self, url, filename, path, status="Queued", total=0, downloaded=0,
            category="Other", queue_name="Main", priority=0, scheduled_at=0, connections=4, expected_hash="", hash_algorithm="SHA-256"):
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO downloads
                (url,filename,path,status,total,downloaded,category,queue_name,priority,scheduled_at,connections,expected_hash,hash_algorithm,started,completed,retry_count,created,updated)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (url, filename, path, status, total, downloaded, category, queue_name,
                 priority, scheduled_at, connections, expected_hash, hash_algorithm, 0, 0, 0, time.time(), time.time()))
            self.conn.commit()
            return cur.lastrowid

    def update(self, row_id, **kw):
        kw["updated"] = time.time()
        keys = list(kw.keys())
        vals = [kw[k] for k in keys] + [row_id]
        with self.lock:
            self.conn.execute(
                f"UPDATE downloads SET {','.join(k+'=?' for k in keys)} WHERE id=?",
                vals)
            self.conn.commit()

    def backup(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.conn.commit()
            shutil.copy2(DB_PATH, destination)
        return destination

    def export_json(self, destination):
        destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True)
        rows=[dict(r) for r in self.all()]
        destination.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf-8')
        return destination

    def export_csv(self, destination):
        destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True)
        rows=[dict(r) for r in self.all()]
        fields=['id','url','filename','path','status','total','downloaded','error','category','queue_name','priority','scheduled_at','connections','expected_hash','hash_algorithm','started','completed','retry_count','created','updated']
        with destination.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
        return destination

    def import_json(self, source):
        data=json.loads(Path(source).read_text(encoding='utf-8'))
        if not isinstance(data,list): raise ValueError('Import file must contain a JSON list.')
        count=0
        for r in data:
            if not isinstance(r,dict) or not r.get('url') or not r.get('filename') or not r.get('path'): continue
            self.add(r['url'],r['filename'],r['path'],r.get('status','Queued'),int(r.get('total') or 0),int(r.get('downloaded') or 0),r.get('category','Other'),r.get('queue_name','Main'),int(r.get('priority') or 0),float(r.get('scheduled_at') or 0),int(r.get('connections') or 4),r.get('expected_hash',''),r.get('hash_algorithm','SHA-256'))
            count+=1
        return count

    def delete(self, row_id):
        with self.lock:
            self.conn.execute("DELETE FROM downloads WHERE id=?", (row_id,))
            self.conn.commit()
