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
import sqlite3
from dataclasses import dataclass
from typing import ClassVar
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

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
        self._conn.close()


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
