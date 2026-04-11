"""Concrete memory — SQLite FTS5 facts + MemGPT-inspired Core Memory.

Two systems:
  1. Facts (FTS5)    — open-ended semantic search, for episodic/specific knowledge
  2. Core Memory     — structured blocks with char limits, always in LLM context

Thronglets is the abstract field (traces, signals, pheromones).
This module stores specific facts: "user wants to buy ETH below $2000."
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, NamedTuple

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".oasyce" / "samantha" / "memory.db"


# FTS5 has its own query syntax: ``:`` ``.`` ``-`` ``+`` ``*`` ``^`` ``"`` and
# bareword phrases all have meaning. User input like "0.11.3" or
# "user_id:5" raises ``sqlite3.OperationalError: fts5: syntax error``
# when passed directly to ``MATCH ?``. The safe pattern is to extract
# alphanumeric/unicode word tokens and quote each as a literal phrase.
# An empty result means "nothing to search for" — callers must treat it
# as zero matches rather than as an error.
_FTS_TOKEN = re.compile(r"\w+", re.UNICODE)


def _fts5_query(text: str) -> str:
    """Convert free-form user text into a safe FTS5 MATCH expression.

    Returns ``""`` when no usable tokens remain — callers should treat
    that as "no results" without executing the query.
    """
    tokens = _FTS_TOKEN.findall(text or "")
    if not tokens:
        return ""
    # Quoting each token as a literal phrase neutralises every FTS5
    # operator while preserving token-level matching semantics. Embedded
    # double quotes are escaped per FTS5 spec by doubling them.
    return " ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in tokens)


class Fact(NamedTuple):
    id: int
    content: str
    category: str
    created_at: str
    access_count: int


class Message(NamedTuple):
    id: int
    role: str          # 'user' | 'assistant'
    content: str
    session_id: int
    created_at: str


# Schema is idempotent (IF NOT EXISTS everywhere) so every freshly-opened
# connection can run it safely. That's what makes per-thread connections
# work without coordination: each thread opens its own, runs the same DDL,
# and gets the same view of the DB.
_SCHEMA = """
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

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        session_id INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
        USING fts5(content, content='messages', content_rowid='id');
    CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages(session_id, created_at);

    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, content)
        VALUES (new.id, new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content)
        VALUES ('delete', old.id, old.content);
    END;
"""


class Memory:
    """Persistent fact store backed by SQLite FTS5.

    Two tables:
      facts      — LLM-extracted semantic knowledge (the agent's "beliefs")
      messages   — verbatim turn-by-turn log (the raw conversation)

    Extracted facts are lossy but searchable by concept. Verbatim messages
    preserve nuance and exact phrasing for recall of specific moments.
    Recall from both paths is cheap (FTS5) and complementary.

    Threading model
    ---------------
    One Memory instance is shared across threads; each thread that touches
    it opens its own `sqlite3.Connection` stored in a `threading.local`.
    This matches how the stdlib `sqlite3` module is designed to be used
    from multi-threaded code: share the database, not the connection.

    SQLite's WAL mode lets readers proceed in parallel with a writer and
    serializes writers at the file layer, so no Python-level lock is
    needed — the correctness guarantee comes from SQLite itself.
    """

    def __init__(self, db_path: Path | None = None):
        p = db_path or DEFAULT_DB_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(p)
        self._local = threading.local()
        # Eager open: if the path is unwritable or the schema fails, surface
        # the error at construction time rather than on the first operation.
        self._connect()

    def _connect(self) -> sqlite3.Connection:
        """Return the current thread's connection, opening it on first use."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            self._local.conn = conn
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        """Thread-local connection — lazy-created per thread, never shared."""
        return self._connect()

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
        """Search facts by relevance (FTS5 match + recency).

        Free-form ``query`` is sanitised through ``_fts5_query`` so that
        version strings, punctuation, and bare colons cannot raise an
        ``OperationalError``. An empty sanitised query short-circuits to
        an empty result list — there is nothing meaningful to search for.
        """
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """
            SELECT f.id, f.content, f.category, f.created_at, f.access_count
            FROM facts_fts
            JOIN facts f ON f.id = facts_fts.rowid
            WHERE facts_fts MATCH ?
            ORDER BY facts_fts.rank
            LIMIT ?
            """,
            (safe, limit),
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

    # ── Verbatim messages ─────────────────────────────────────

    def log_message(self, role: str, content: str, session_id: int = 0) -> int:
        """Store a verbatim turn. Returns its id."""
        if not content:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO messages (role, content, session_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (role, content, session_id, now),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def search_messages(self, query: str, limit: int = 5) -> list[Message]:
        """FTS5 search across verbatim messages, ranked by relevance.

        Same sanitisation contract as ``recall``: free-form ``query`` is
        token-extracted through ``_fts5_query`` before being passed to
        FTS5, so user content with version numbers, dotted identifiers,
        or stray punctuation cannot raise ``fts5: syntax error``.
        """
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """
            SELECT m.id, m.role, m.content, m.session_id, m.created_at
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            WHERE messages_fts MATCH ?
            ORDER BY messages_fts.rank
            LIMIT ?
            """,
            (safe, limit),
        ).fetchall()
        return [Message(*r) for r in rows]

    def recent_messages(self, session_id: int = 0, limit: int = 20) -> list[Message]:
        """Latest messages for a session (or all sessions if session_id=0)."""
        if session_id:
            rows = self._conn.execute(
                "SELECT id, role, content, session_id, created_at "
                "FROM messages WHERE session_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, role, content, session_id, created_at "
                "FROM messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Message(*r) for r in rows]

    def message_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0] if row else 0

    def prune(self, max_age_days: int = 90, min_access: int = 0) -> int:
        """Remove stale facts. Returns count of deleted rows.

        Deletes facts that are older than max_age_days AND have been
        accessed at most min_access times. The access_count and last_accessed
        fields (already tracked on every recall) drive this.
        """
        cur = self._conn.execute(
            """
            DELETE FROM facts
            WHERE access_count <= ?
              AND julianday('now') - julianday(created_at) > ?
            """,
            (min_access, max_age_days),
        )
        self._conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.info("Pruned %d stale facts (age>%dd, access<=%d)",
                        deleted, max_age_days, min_access)
        return deleted

    def close(self) -> None:
        """Close the current thread's connection. Best-effort cleanup.

        Connections held by other threads are reclaimed when those threads
        exit or when the garbage collector runs over their thread-locals.
        Under WAL every `commit()` is durable, so this cannot cause data
        loss — it only releases the current thread's file handle.
        """
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


# ── Core Memory (MemGPT-inspired) ──────────────────────────────

@dataclass
class CoreMemory:
    """Structured memory blocks that are always present in LLM context.

    Inspired by MemGPT/Letta: the agent edits its own core memory
    through tools. Each block has a character limit to prevent
    unbounded context growth.

    Blocks:
      human        — who this person is (preferences, facts, life)
      relationship — how Joi relates to this person
    """

    human: str = ""
    relationship: str = ""

    LIMITS: ClassVar[dict[str, int]] = {"human": 2000, "relationship": 1000}

    def update(self, block: str, content: str) -> str:
        """Update a block. Truncates to limit. Returns actual stored content."""
        if block not in self.LIMITS:
            raise ValueError(f"Unknown block: {block}. Available: {list(self.LIMITS)}")
        limit = self.LIMITS[block]
        truncated = content[:limit]
        setattr(self, block, truncated)
        return truncated

    def get(self, block: str) -> str:
        """Read a block's content."""
        if block not in self.LIMITS:
            raise ValueError(f"Unknown block: {block}")
        return getattr(self, block)

    def to_context(self, max_tokens: int = 2000) -> str:
        """Format for inclusion in LLM system prompt."""
        from .context import _truncate_text
        parts = []
        if self.human:
            parts.append(f"[Core memory: about this person]\n{self.human}")
        if self.relationship:
            parts.append(f"[Core memory: your relationship]\n{self.relationship}")
        if not parts:
            return ""
        text = "\n\n".join(parts)
        return _truncate_text(text, max_tokens)

    def to_dict(self) -> dict[str, str]:
        return {"human": self.human, "relationship": self.relationship}

    @classmethod
    def from_dict(cls, d: dict) -> CoreMemory:
        cm = cls()
        for block in cm.LIMITS:
            val = d.get(block, "")
            if val:
                cm.update(block, val)
        return cm

    @classmethod
    def load(cls, workspace: Path) -> CoreMemory:
        """Load from workspace. Migrates from relationship.md if needed."""
        cm_path = workspace / "core_memory.json"
        if cm_path.exists():
            try:
                return cls.from_dict(json.loads(cm_path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("Corrupt core_memory.json, starting fresh")

        # Migrate from legacy relationship.md
        rel_path = workspace / "relationship.md"
        if rel_path.exists():
            content = rel_path.read_text(encoding="utf-8")
            cm = cls()
            cm.update("relationship", content)
            cm.save(workspace)
            logger.info("Migrated relationship.md → core_memory.json")
            return cm

        return cls()

    def save(self, workspace: Path) -> None:
        """Persist to workspace."""
        cm_path = workspace / "core_memory.json"
        cm_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── History Summary (LangChain SummaryBuffer pattern) ──────────

class HistorySummary:
    """Persistent conversation summary per session.

    Inspired by LangChain ConversationSummaryBufferMemory:
    - Recent messages kept verbatim (fetched from API)
    - Older messages compressed into a running summary
    - Summary updated when conversation grows past threshold

    Storage: users/{id}/summaries/{session_id}.txt
    """

    def __init__(self, workspace: Path):
        self._dir = workspace / "summaries"
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, session_id: int) -> str:
        """Load summary for a session. Empty string if none."""
        path = self._dir / f"{session_id}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def save(self, session_id: int, summary: str) -> None:
        """Persist summary for a session."""
        path = self._dir / f"{session_id}.txt"
        path.write_text(summary, encoding="utf-8")

    def needs_update(self, session_id: int, history_len: int,
                     threshold: int = 15) -> bool:
        """Should we generate/update summary?

        Triggers when:
        - No summary exists and history exceeds threshold
        - Summary exists but history has grown significantly since last summary
        """
        if history_len < threshold:
            return False
        existing = self.get(session_id)
        if not existing:
            return True
        # Re-summarize when history has grown 2x since last summary length
        # (rough heuristic: summary ~1/3 of original, so if history >> summary, time to update)
        return history_len > len(existing) // 4
