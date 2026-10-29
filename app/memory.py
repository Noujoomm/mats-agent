"""
Learning memory: question -> SQL pairs that worked.

* Seeded with 9 bilingual examples (18 questions).
* Every successful query is stored automatically (unverified).
* "Right" re-runs the SQL through the guard and marks the pair verified.
* "Wrong" forgets the pair.
* Retrieval: character-trigram cosine over normalized text (works for Arabic
  dialect, misspellings and English alike); verified pairs get a small boost.
* Lessons: when a query fails and is then fixed (or the user says "Wrong"), the
  mistake is stored and shown to the SQL model for similar questions.
* User facts: lasting facts a user states ("I supervise group 7") are kept per
  browser (client_id) and used to resolve "my group" in later questions.
"""
import math
import sqlite3
import threading
from collections import Counter

from . import guard
from .arabic import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    qkey TEXT NOT NULL,
    sql TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'auto',     -- seed | auto | user
    uses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (qkey, sql)
);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    bad_sql TEXT NOT NULL,
    error TEXT NOT NULL,
    fixed_sql TEXT,
    source TEXT NOT NULL,                    -- repair | wrong
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (question, bad_sql)
);
CREATE TABLE IF NOT EXISTS user_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL,
    fact TEXT NOT NULL,
    fkey TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (client_id, fkey)
);
"""

NOT_BOARDED_SQL = """SELECT g.group_no, p.pilgrim_no, p.name_ar, p.name_en, p.phone
FROM pilgrims p
JOIN groups g ON g.id = p.group_id
WHERE p.group_id IN (SELECT t.group_id FROM trips t JOIN routes r ON r.id = t.route_id
                     WHERE r.code = 'MNA-ARF' AND t.status IN ('departed', 'arrived'))
  AND p.id NOT IN (SELECT s.pilgrim_id FROM boarding_scans s
                   JOIN trips t ON t.id = s.trip_id JOIN routes r ON r.id = t.route_id
                   WHERE r.code = 'MNA-ARF')
ORDER BY g.group_no"""

SEEDS = [
    (["مين ما ركب باص منى لعرفات؟",
      "Who has not boarded the Mina to Arafat bus?"], NOT_BOARDED_SQL),
    (["وش وضع باصات فوج 5 لعرفات؟",
      "What is the status of group 5 buses to Arafat?"],
     """SELECT b.bus_no, b.plate, s.label_ar, s.label_en, t.scheduled_departure,
       t.actual_departure, t.eta, t.arrived_at, t.delay_minutes
FROM trips t
JOIN groups g ON g.id = t.group_id
JOIN buses b ON b.id = t.bus_id
JOIN routes r ON r.id = t.route_id
JOIN trip_statuses s ON s.code = t.status
WHERE g.group_no = 5 AND r.code = 'MNA-ARF'"""),
    (["كم حاج ضايع الحين؟", "How many pilgrims are missing right now?"],
     "SELECT COUNT(*) AS missing_pilgrims FROM pilgrims WHERE status = 'missing'"),
    (["أي باصات متأخرة وكم التأخير؟", "Which buses are delayed and by how much?"],
     """SELECT g.group_no, b.bus_no, r.route_ar, r.route_en, t.delay_minutes, t.eta
FROM trips t
JOIN groups g ON g.id = t.group_id
JOIN buses b ON b.id = t.bus_id
JOIN routes r ON r.id = t.route_id
WHERE t.status = 'delayed'
ORDER BY t.delay_minutes DESC"""),
    (["كم عدد الحجاج لكل جنسية؟", "How many pilgrims per nationality?"],
     """SELECT n.name_ar, n.name_en, COUNT(*) AS pilgrims
FROM pilgrims p JOIN nationalities n ON n.id = p.nationality_id
GROUP BY n.id ORDER BY pilgrims DESC"""),
    (["وش البلاغات المفتوحة؟", "What are the open incidents by type?"],
     """SELECT it.label_ar, it.label_en, COUNT(*) AS open_incidents
FROM incidents i JOIN incident_types it ON it.code = i.type
WHERE i.status = 'open'
GROUP BY it.code ORDER BY open_incidents DESC"""),
    (["مين مشرف فوج 12 ورقمه؟", "Who is the supervisor of group 12 and what is their phone?"],
     """SELECT g.group_no, s.name_ar, s.name_en, s.phone
FROM groups g JOIN supervisors s ON s.id = g.supervisor_id
WHERE g.group_no = 12"""),
    (["أي أفواج للحين في منى؟", "Which groups are still in Mina?"],
     """SELECT g.group_no, g.name_ar, g.name_en, s.label_ar, s.label_en
FROM groups g
JOIN trips t ON t.group_id = g.id
JOIN routes r ON r.id = t.route_id
JOIN trip_statuses s ON s.code = t.status
WHERE r.code = 'MNA-ARF' AND t.status NOT IN ('departed', 'arrived')
GROUP BY g.id ORDER BY g.group_no"""),
    (["كم حاج يحتاج كرسي متحرك في كل مخيم بمنى؟",
      "How many pilgrims need a wheelchair in each Mina camp?"],
     """SELECT c.name_ar, c.name_en, COUNT(*) AS wheelchair_pilgrims
FROM pilgrims p
JOIN groups g ON g.id = p.group_id
JOIN camps c ON c.id = g.mina_camp_id
WHERE p.needs_wheelchair = 1
GROUP BY c.id ORDER BY c.id"""),
]


def _vec(text):
    t = f"  {normalize(text)}  "
    grams = Counter(t[i:i + 3] for i in range(len(t) - 2))
    grams.update(normalize(text).split())          # whole words weigh extra
    return grams


def _cos(a, b):
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class Memory:
    def __init__(self, path, data_db):
        self.path = str(path)
        self.data_db = data_db
        self.lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            for questions, sql in SEEDS:
                for q in questions:
                    c.execute("INSERT OR IGNORE INTO examples (question, qkey, sql, verified, source)"
                              " VALUES (?, ?, ?, 1, 'seed')", (q, normalize(q), sql))

    def _conn(self):
        return sqlite3.connect(self.path, check_same_thread=False)

    def similar(self, question, k=3, min_score=0.12):
        """Top-k similar pairs (verified first) for few-shot prompting."""
        qv = _vec(question)
        with self._conn() as c:
            rows = c.execute("SELECT id, question, sql, verified FROM examples").fetchall()
        scored = []
        for id_, q, sql, ver in rows:
            # Verified pairs (seeds, or marked Right) clearly outrank auto-saved ones, so one
            # bad auto-saved query cannot keep teaching the model its own mistake.
            s = _cos(qv, _vec(q)) + (0.25 if ver else 0.0)
            if s >= min_score:
                scored.append({"id": id_, "question": q, "sql": sql,
                               "verified": bool(ver), "score": round(s, 3)})
        scored.sort(key=lambda e: e["score"], reverse=True)
        out, seen = [], set()
        for e in scored:                       # don't show the same SQL twice
            if e["sql"] in seen:
                continue
            seen.add(e["sql"])
            out.append(e)
            if len(out) == k:
                break
        return out

    def remember(self, question, sql, verified=False, source="auto"):
        with self.lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO examples (question, qkey, sql, verified, source)"
                      " VALUES (?, ?, ?, ?, ?)",
                      (question, normalize(question), sql, int(verified), source))
            if verified:
                c.execute("UPDATE examples SET verified = 1 WHERE qkey = ? AND sql = ?",
                          (normalize(question), sql))

    def mark_right(self, question, sql):
        """Verify by re-running through the guard, then store as verified."""
        conn = guard.connect(self.data_db)
        try:
            res = guard.run(conn, sql)
        finally:
            conn.close()
        self.remember(question, sql, verified=True, source="user")
        return {"ok": True, "rows": len(res["rows"])}

    def forget(self, question, sql=None):
        with self.lock, self._conn() as c:
            if sql:
                n = c.execute("DELETE FROM examples WHERE qkey = ? AND sql = ? AND source != 'seed'",
                              (normalize(question), sql)).rowcount
                n += c.execute("DELETE FROM examples WHERE sql = ? AND verified = 0",
                               (sql,)).rowcount
            else:
                n = c.execute("DELETE FROM examples WHERE qkey = ? AND source != 'seed'",
                              (normalize(question),)).rowcount
        return n

    # ── lessons from mistakes ──
    def add_lesson(self, question, bad_sql, error, fixed_sql=None, source="repair"):
        with self.lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO lessons (question, bad_sql, error, fixed_sql, source)"
                      " VALUES (?, ?, ?, ?, ?)", (question, bad_sql, str(error)[:300], fixed_sql, source))

    def lessons(self, question, k=2, min_score=0.35):
        qv = _vec(question)
        with self._conn() as c:
            rows = c.execute("SELECT question, bad_sql, error, fixed_sql FROM lessons"
                             " ORDER BY id DESC LIMIT 300").fetchall()
        scored = [(_cos(qv, _vec(q)), {"question": q, "bad_sql": b, "error": e, "fixed_sql": f})
                  for q, b, e, f in rows]
        scored = [x for x in scored if x[0] >= min_score]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [x[1] for x in scored[:k]]

    # ── per-user facts ──
    def add_fact(self, client_id, fact):
        with self.lock, self._conn() as c:
            c.execute("INSERT OR IGNORE INTO user_facts (client_id, fact, fkey) VALUES (?, ?, ?)",
                      (client_id, fact, normalize(fact)))

    def facts(self, client_id, limit=10):
        with self._conn() as c:
            rows = c.execute("SELECT fact FROM user_facts WHERE client_id = ? ORDER BY id DESC LIMIT ?",
                             (client_id, limit)).fetchall()
        return [r[0] for r in reversed(rows)]       # oldest first, newest last

    def clear_facts(self, client_id):
        with self.lock, self._conn() as c:
            return c.execute("DELETE FROM user_facts WHERE client_id = ?", (client_id,)).rowcount

    def stats(self, client_id=None):
        with self._conn() as c:
            total, verified = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(verified), 0) FROM examples").fetchone()
            lessons = c.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        out = {"examples": total, "verified": verified, "lessons": lessons}
        if client_id:
            out["facts"] = self.facts(client_id)
        return out
