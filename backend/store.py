import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path, quota_mb=128, keep_sessions=12):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.quota_mb, self.keep_sessions = path, quota_mb, keep_sessions
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, payload TEXT);
        CREATE TABLE IF NOT EXISTS frames(session TEXT, frame INTEGER, payload TEXT, PRIMARY KEY(session,frame));
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, session TEXT, frame INTEGER, payload TEXT);
        CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, session TEXT, payload TEXT);
        ''')
        for s in self.sessions():
            if s["status"] == "live":
                s["status"] = "interrupted"
                self.session(s)

    def session(self, value):
        self.db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", (value["session_id"], json.dumps(value)))
        self.db.commit()

    def sessions(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM sessions ORDER BY rowid DESC")]

    def frame(self, session, frame):
        r = self.db.execute("SELECT payload FROM frames WHERE session=? AND frame=?", (session, frame)).fetchone()
        return json.loads(r[0]) if r else None

    def frame_index(self, session):
        return [r[0] for r in self.db.execute("SELECT frame FROM frames WHERE session=? ORDER BY frame", (session,))]

    def record(self, value):
        o = value["observation"]
        self.db.execute("INSERT INTO frames VALUES(?,?,?)", (o["session_id"], o["frame_id"], json.dumps(value)))
        self.db.commit()

    def event(self, value):
        self.db.execute("INSERT INTO events VALUES(?,?,?,?)", (value["event_id"], value["session_id"], value["frame_id"], json.dumps(value)))
        self.db.commit()

    def events(self, session, frame=None, at=None):
        sql, args = "SELECT payload FROM events WHERE session=?", [session]
        if frame is not None:
            sql += " AND frame<=?"
            args.append(frame)
        if at is not None:
            sql += " AND json_extract(payload,'$.at')<=?"
            args.append(at)
        return [json.loads(r[0]) for r in self.db.execute(sql + " ORDER BY rowid DESC LIMIT 80", args)]

    def command(self, value):
        self.db.execute("INSERT OR REPLACE INTO commands VALUES(?,?,?)", (value["request_id"], value["session_id"], json.dumps(value)))
        self.db.commit()

    def get_command(self, request_id):
        r = self.db.execute("SELECT payload FROM commands WHERE id=?", (request_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def commands(self, session, at=None):
        sql, args = "SELECT payload FROM commands WHERE session=?", [session]
        if at is not None:
            sql += " AND json_extract(payload,'$.transitions[0].at')<=?"
            args.append(at)
        values = [json.loads(r[0]) for r in self.db.execute(sql + " ORDER BY rowid DESC LIMIT 40", args)]
        if at is not None:
            result = []
            for value in values:
                transitions = [t for t in value["transitions"] if t["at"] <= at]
                if transitions:
                    value.update(transitions=transitions, status=transitions[-1]["status"], result=transitions[-1].get("detail"))
                    result.append(value)
            return result
        return values

    def size(self):
        return sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file())

    def cleanup(self, active):
        removed = 0
        sessions = self.sessions()
        for old in reversed(sessions):
            if old["session_id"] == active:
                continue
            if len(sessions) - removed <= self.keep_sessions and self.size() < self.quota_mb * 1024**2:
                break
            sid = old["session_id"]
            for table, column in (("frames", "session"), ("events", "session"), ("commands", "session"), ("sessions", "id")):
                self.db.execute(f"DELETE FROM {table} WHERE {column}=?", (sid,))
            self.db.commit()
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("VACUUM")
            removed += 1
        return removed

    def close(self):
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()
