"""Small, durable race records; independent of the bounded in-memory caches."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time


class RaceArchive:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self._init_lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=2)) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS records (
                        kind TEXT NOT NULL, date TEXT NOT NULL, jcd TEXT NOT NULL,
                        race INTEGER NOT NULL, payload TEXT NOT NULL, saved_at REAL NOT NULL,
                        PRIMARY KEY(kind, date, jcd, race)
                    );
                    CREATE TABLE IF NOT EXISTS boards (
                        date TEXT NOT NULL, jcd TEXT NOT NULL, payload TEXT,
                        revision INTEGER NOT NULL DEFAULT 0,
                        built_revision INTEGER NOT NULL DEFAULT -1,
                        saved_at REAL NOT NULL DEFAULT 0,
                        PRIMARY KEY(date, jcd)
                    );
                    CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """)
                db.commit()
            self._initialized = True

    def _read(self, query, args=()):
        if not self.path.exists():
            return []
        # Readers do not create a database or wait behind a large batch write.
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=.1)) as db:
            return db.execute(query, args).fetchall()

    def get(self, kind, date, jcd="", race=0):
        rows = self._read("SELECT payload,saved_at FROM records WHERE kind=? AND date=? AND jcd=? AND race=?",
                          (kind, date, jcd, race))
        return {"payload": json.loads(rows[0][0]), "savedAt": rows[0][1]} if rows else None

    def list_records(self, kind, date, jcd=None):
        query = "SELECT jcd,race,payload FROM records WHERE kind=? AND date=?"
        args = (kind, date)
        if jcd is not None:
            query += " AND jcd=?"
            args += (jcd,)
        return [(venue, race, json.loads(payload)) for venue, race, payload in self._read(query, args)]

    def put(self, kind, date, jcd, race, payload, merge=None, saved_at=None):
        self.initialize()
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM records WHERE kind=? AND date=? AND jcd=? AND race=?",
                             (kind, date, jcd, race)).fetchone()
            previous = json.loads(row[0]) if row else None
            if merge:
                payload = merge(previous, payload)
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            changed = not row or row[0] != encoded
            db.execute("INSERT INTO records VALUES(?,?,?,?,?,?) ON CONFLICT(kind,date,jcd,race) "
                       "DO UPDATE SET payload=excluded.payload,saved_at=excluded.saved_at",
                       (kind, date, jcd, race, encoded, time.time() if saved_at is None else saved_at))
            if changed and kind in ("result", "event"):
                db.execute("INSERT INTO boards(date,jcd,revision) VALUES(?,?,1) ON CONFLICT(date,jcd) "
                           "DO UPDATE SET revision=revision+1", (date, jcd))
        return payload

    def get_board(self, date, jcd):
        rows = self._read("SELECT payload,revision,built_revision,saved_at FROM boards WHERE date=? AND jcd=?", (date, jcd))
        if not rows:
            return None
        payload, revision, built_revision, saved_at = rows[0]
        return {"payload": json.loads(payload) if payload else None, "revision": revision,
                "refreshing": revision != built_revision, "savedAt": saved_at}

    def dirty_boards(self, limit=8):
        return self._read("SELECT date,jcd FROM boards WHERE revision!=built_revision ORDER BY saved_at LIMIT ?", (limit,))

    def request_board(self, date, jcd):
        self.initialize()
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.execute("INSERT OR IGNORE INTO boards(date,jcd) VALUES(?,?)", (date, jcd))

    def put_board(self, date, jcd, payload, revision):
        self.initialize()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            cursor = db.execute("UPDATE boards SET payload=?,built_revision=?,saved_at=? "
                                "WHERE date=? AND jcd=? AND revision=?",
                                (encoded, revision, time.time(), date, jcd, revision))
            return cursor.rowcount == 1

    def get_meta(self, key):
        rows = self._read("SELECT value FROM metadata WHERE key=?", (key,))
        return json.loads(rows[0][0]) if rows else None

    def set_meta(self, key, value):
        self.initialize()
        with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
            db.execute("INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value, ensure_ascii=False)))

    def counts(self):
        return dict(self._read("SELECT kind,COUNT(*) FROM records GROUP BY kind"))


class AcquisitionQueue:
    """Bounded, deduplicated jobs consumed by one worker, never by an HTTP thread."""

    def __init__(self, capacity=128, clock=time.monotonic):
        self.capacity = capacity
        self.clock = clock
        self.lock = threading.Lock()
        self.pending = {}
        self.completed = {}
        self.active = None
        self.last_error = None

    def submit(self, key, priority=5, interval=60):
        now = self.clock()
        with self.lock:
            if key == self.active:
                return False
            previous = self.completed.get(key)
            if previous and now - previous[0] < max(interval, 300 if previous[1] else 0):
                return False
            if key in self.pending:
                order, queued = self.pending[key]
                self.pending[key] = (min(order, priority), queued)
                return False
            if len(self.pending) >= self.capacity:
                lowest = max(self.pending, key=lambda key: self.pending[key])
                if self.pending[lowest][0] <= priority:
                    return False
                del self.pending[lowest]
            self.pending[key] = (priority, now)
            return True

    def run_one(self, handler, allow_network=True):
        with self.lock:
            eligible = [key for key in self.pending if allow_network or key[0] in ("board", "learning")]
            if self.active or not eligible:
                return False
            key = min(eligible, key=lambda key: self.pending[key])
            del self.pending[key]
            self.active = key
        failed = False
        try:
            handler(*key)
        except Exception as error:
            failed = True
            with self.lock:
                self.last_error = {"job": key, "error": str(error), "at": time.time()}
            print(f"[acquisition] job={key} failed: {error}", flush=True)
        finally:
            with self.lock:
                self.completed[key] = (self.clock(), failed)
                self.active = None
                for old in sorted(self.completed, key=lambda key: self.completed[key][0])[:-512]:
                    del self.completed[old]
        return True

    def status(self):
        with self.lock:
            return {"active": self.active, "queued": len(self.pending), "lastError": self.last_error}
