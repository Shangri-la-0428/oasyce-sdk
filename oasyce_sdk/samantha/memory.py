"""Concrete memory — SQLite + FTS5 fact store.

Thronglets is the abstract field (traces, signals, pheromones).
This module stores specific facts: "user wants to buy ETH below $2000."
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

DEFAULT_DB_PATH = Path.home() / ".oasyce" / "samantha" / "memory.db"


class Fact(NamedTuple):
    id: int
    content: str
    category: str
    created_at: str
    access_count: int


class Memory:
    """Persistent fact store backed by SQLite FTS5."""

    def __init__(self, db_path: Path | None = None):
        p = db_path or DEFAULT_DB_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(p))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL,
                last_accessed TEXT,
                access_count INTEGER DEFAULT 0
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
                USING fts5(content, category, content='facts', content_rowid='id');

            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, content, category)
                VALUES (new.id, new.content, new.category);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                INSERT INTO facts_fts(facts_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
            END;
        """)

    def save(self, content: str, category: str = "general") -> int:
        """Store a fact. Returns its id."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO facts (content, category, created_at) VALUES (?, ?, ?)",
            (content, category, now),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def recall(self, query: str, limit: int = 5) -> list[Fact]:
        """Search facts by relevance (FTS5 match + recency)."""
        rows = self._conn.execute(
            """
            SELECT f.id, f.content, f.category, f.created_at, f.access_count
            FROM facts_fts
            JOIN facts f ON f.id = facts_fts.rowid
            WHERE facts_fts MATCH ?
            ORDER BY facts_fts.rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        # Update access counts
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            self._conn.execute(
                "UPDATE facts SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
                (now, row[0]),
            )
        if rows:
            self._conn.commit()
        return [Fact(*r) for r in rows]

    def all_facts(self, limit: int = 50) -> list[Fact]:
        """Return most recent facts."""
        rows = self._conn.execute(
            "SELECT id, content, category, created_at, access_count "
            "FROM facts ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Fact(*r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()
