"""SQLite store for facts, STAR stories, interview plans and graded attempts."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

FACT_STATUSES = ("draft", "confirmed", "rejected")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.con:
            self.con.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft', source_verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS stories (
                id TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY, body TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL, question_id TEXT NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    # facts -----------------------------------------------------------------
    def next_fact_id(self) -> str:
        rows = self.con.execute("SELECT id FROM facts").fetchall()
        nums = [int(r["id"][2:]) for r in rows if r["id"].startswith("F-") and r["id"][2:].isdigit()]
        return f"F-{max(nums, default=0) + 1}"

    def add_fact(self, text: str, source: str = "", status: str = "draft", source_verified: bool = False, fact_id=None) -> str:
        if status not in FACT_STATUSES:
            raise ValueError("bad status")
        with self.lock, self.con:
            fid = fact_id or self.next_fact_id()
            self.con.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?)",
                             (fid, text.strip(), source.strip(), status, int(source_verified), now()))
        return fid

    def set_fact(self, fid: str, status: str | None = None, text: str | None = None):
        if status is not None and status not in FACT_STATUSES:
            raise ValueError("bad status")
        with self.lock, self.con:
            if not self.con.execute("SELECT 1 FROM facts WHERE id=?", (fid,)).fetchone():
                raise KeyError(fid)
            if status is not None:
                self.con.execute("UPDATE facts SET status=? WHERE id=?", (status, fid))
            if text is not None:
                # Editing a fact's wording means the person has re-stated it; it stays confirmed only by explicit choice.
                self.con.execute("UPDATE facts SET text=? WHERE id=?", (text.strip(), fid))

    def facts(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM facts ORDER BY CAST(substr(id,3) AS INTEGER)")]

    def confirmed_facts(self) -> dict[str, dict]:
        return {f["id"]: f for f in self.facts() if f["status"] == "confirmed"}

    # stories ---------------------------------------------------------------
    def save_story(self, story: dict) -> str:
        with self.lock, self.con:
            if not story.get("id"):
                n = self.con.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
                story["id"] = f"S-{n + 1}"
                while self.con.execute("SELECT 1 FROM stories WHERE id=?", (story["id"],)).fetchone():
                    n += 1
                    story["id"] = f"S-{n + 1}"
            self.con.execute("INSERT OR REPLACE INTO stories VALUES (?,?,?)", (story["id"], json.dumps(story), now()))
        return story["id"]

    def stories(self) -> list[dict]:
        return [json.loads(r["body"]) for r in self.con.execute("SELECT body FROM stories ORDER BY created_at, id")]

    # plans & attempts ------------------------------------------------------
    def save_plan(self, plan: dict) -> int:
        with self.lock, self.con:
            cur = self.con.execute("INSERT INTO plans (body, created_at) VALUES (?,?)", (json.dumps(plan), now()))
            pid = cur.lastrowid
            plan["id"] = pid
            self.con.execute("UPDATE plans SET body=? WHERE id=?", (json.dumps(plan), pid))
        return pid

    def plan(self, pid: int) -> dict | None:
        row = self.con.execute("SELECT body FROM plans WHERE id=?", (pid,)).fetchone()
        return json.loads(row["body"]) if row else None

    def latest_plan(self) -> dict | None:
        row = self.con.execute("SELECT body FROM plans ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row["body"]) if row else None

    def save_attempt(self, plan_id: int, question_id: str, body: dict) -> int:
        with self.lock, self.con:
            cur = self.con.execute("INSERT INTO attempts (plan_id, question_id, body, created_at) VALUES (?,?,?,?)",
                                   (plan_id, question_id, json.dumps(body), now()))
        return cur.lastrowid

    def update_attempt(self, attempt_id: int, body: dict):
        with self.lock, self.con:
            self.con.execute("UPDATE attempts SET body=? WHERE id=?", (json.dumps(body), attempt_id))

    def attempt(self, attempt_id: int) -> dict | None:
        r = self.con.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "plan_id": r["plan_id"], "question_id": r["question_id"], "created_at": r["created_at"], **json.loads(r["body"])}

    def attempts(self, plan_id: int) -> list[dict]:
        rows = self.con.execute("SELECT * FROM attempts WHERE plan_id=? ORDER BY id", (plan_id,))
        return [{"id": r["id"], "question_id": r["question_id"], "created_at": r["created_at"], **json.loads(r["body"])} for r in rows]

    def reset(self):
        with self.lock, self.con:
            for t in ("facts", "stories", "plans", "attempts"):
                self.con.execute(f"DELETE FROM {t}")
