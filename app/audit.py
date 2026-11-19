"""Audit trail: every approved coding decision is stored permanently (append-only).
SQLite = a database in a single file, built into Python. No server to install."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("AUDIT_DB", Path(__file__).resolve().parent.parent / "data" / "audit.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id             TEXT NOT NULL,
    coder               TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    note_text           TEXT NOT NULL,
    ai_suggested        TEXT NOT NULL,   -- JSON list: what the AI proposed
    diagnoses           TEXT NOT NULL,   -- JSON list: final codes with Principal/Secondary
    removed_by_coder    TEXT NOT NULL,   -- JSON list: AI codes the coder rejected
    added_by_coder      TEXT NOT NULL,   -- JSON list: codes the AI missed
    ai_latency_seconds  REAL,
    review_seconds      REAL,            -- time from seeing suggestions to approving
    approved_at         TEXT NOT NULL    -- UTC timestamp
)
"""

JSON_FIELDS = ("ai_suggested", "diagnoses", "removed_by_coder", "added_by_coder")


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def save_review(review):
    """Insert one approved review. Never updates or deletes: re-approvals become new rows."""
    row = dict(review)
    for f in JSON_FIELDS:
        row[f] = json.dumps(row[f])
    row["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with _connect() as conn:
        cur = conn.execute(f"INSERT INTO reviews ({cols}) VALUES ({marks})", list(row.values()))
        return cur.lastrowid


def list_reviews(limit=50):
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for f in JSON_FIELDS:
            d[f] = json.loads(d[f])
        out.append(d)
    return out



def get_review(review_id):
    with _connect() as conn:
        r = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        d[f] = json.loads(d[f])
    return d