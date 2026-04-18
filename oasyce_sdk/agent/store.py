"""Observation + Knowledge stores — SQLite FTS5 persistence for v2 cognitive types.

Shares the same connection management pattern as ``memory.Memory``
(threading.local, WAL mode, idempotent schema) and can coexist in
the same database file — each store creates its own tables.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from .cognitive import Annotation, KnowledgeTriple, Observation
from .memory import _fts5_query


def _normalize_bm25(rank: float) -> float:
    """Convert FTS5 rank (negative, lower = better) to a [0, 1] score."""
    return 1.0 / (1.0 + abs(rank))


# ── Return types ─────────────────────────────────────────────────


class ObservationRow(NamedTuple):
    id: int
    source_type: str
    source_id: int
    author_id: int
    content: str
    media_urls: list[str]
    location: str
    observed_at: str
    emotional_weight: float
    psyche_snapshot: dict


class AnnotationRow(NamedTuple):
    id: int
    target_type: str
    target_id: int
    topics: list[str]
    entities: list[str]
    sentiment: str
    summary: str
    confidence: float
    source: str
    created_at: str


class KnowledgeTripleRow(NamedTuple):
    id: int
    subject: str
    predicate: str
    object: str
    valid_from: str
    valid_to: str
    source_type: str
    source_id: int
    confidence: float
    created_at: str


class PsycheSnapshotRow(NamedTuple):
    id: int
    session_id: int
    snapshot: dict
    created_at: str


# ── Base store ───────────────────────────────────────────────────


class _SQLiteStore:
    """Thread-safe SQLite base with WAL mode and idempotent schema.

    Subclasses override ``_SCHEMA`` and call ``super().__init__``.
    Connection management mirrors ``memory.Memory``: one connection
    per thread via ``threading.local``, WAL for concurrent reads,
    schema applied on every new connection (IF NOT EXISTS everywhere).
    """

    _SCHEMA: str = ""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(db_path)
        self._local = threading.local()
        self._connect()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(self._SCHEMA)
            self._local.conn = conn
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._connect()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


# ── Observation store ────────────────────────────────────────────


class ObservationStore(_SQLiteStore):
    """Persists Observations and their Annotations with FTS5 search."""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL DEFAULT '',
            source_id INTEGER NOT NULL DEFAULT 0,
            author_id INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL DEFAULT '',
            media_urls TEXT NOT NULL DEFAULT '[]',
            location TEXT NOT NULL DEFAULT '',
            observed_at TEXT NOT NULL,
            emotional_weight REAL NOT NULL DEFAULT 0.5,
            psyche_snapshot TEXT NOT NULL DEFAULT '{}'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts
            USING fts5(content, location, content='observations', content_rowid='id');

        CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, content, location)
            VALUES (new.id, new.content, new.location);
        END;
        CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, content, location)
            VALUES ('delete', old.id, old.content, old.location);
        END;

        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL DEFAULT '',
            target_id INTEGER NOT NULL DEFAULT 0,
            topics TEXT NOT NULL DEFAULT '[]',
            entities TEXT NOT NULL DEFAULT '[]',
            sentiment TEXT NOT NULL DEFAULT 'neutral',
            summary TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.8,
            source TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS annotations_fts
            USING fts5(summary, content='annotations', content_rowid='id');

        CREATE TRIGGER IF NOT EXISTS annotations_ai AFTER INSERT ON annotations BEGIN
            INSERT INTO annotations_fts(rowid, summary)
            VALUES (new.id, new.summary);
        END;
        CREATE TRIGGER IF NOT EXISTS annotations_ad AFTER DELETE ON annotations BEGIN
            INSERT INTO annotations_fts(annotations_fts, rowid, summary)
            VALUES ('delete', old.id, old.summary);
        END;
    """

    def save_observation(self, obs: Observation) -> int:
        cur = self._conn.execute(
            """INSERT INTO observations
               (source_type, source_id, author_id, content, media_urls,
                location, observed_at, emotional_weight, psyche_snapshot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                obs.source_type,
                obs.source_id,
                obs.author_id,
                obs.content,
                json.dumps(obs.media_urls, ensure_ascii=False),
                obs.location,
                obs.observed_at,
                obs.emotional_weight,
                json.dumps(obs.psyche_snapshot, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_observation(self, obs_id: int) -> ObservationRow | None:
        row = self._conn.execute(
            """SELECT id, source_type, source_id, author_id, content,
                      media_urls, location, observed_at, emotional_weight,
                      psyche_snapshot
               FROM observations WHERE id = ?""",
            (obs_id,),
        ).fetchone()
        if row is None:
            return None
        return ObservationRow(
            id=row[0], source_type=row[1], source_id=row[2],
            author_id=row[3], content=row[4],
            media_urls=json.loads(row[5]), location=row[6],
            observed_at=row[7], emotional_weight=row[8],
            psyche_snapshot=json.loads(row[9]),
        )

    def get_observation_by_source_id(self, source_id: int) -> ObservationRow | None:
        row = self._conn.execute(
            """SELECT id, source_type, source_id, author_id, content,
                      media_urls, location, observed_at, emotional_weight,
                      psyche_snapshot
               FROM observations WHERE source_id = ?""",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        return ObservationRow(
            id=row[0], source_type=row[1], source_id=row[2],
            author_id=row[3], content=row[4],
            media_urls=json.loads(row[5]), location=row[6],
            observed_at=row[7], emotional_weight=row[8],
            psyche_snapshot=json.loads(row[9]),
        )

    def search_observations(self, query: str, limit: int = 10) -> list[ObservationRow]:
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """SELECT o.id, o.source_type, o.source_id, o.author_id, o.content,
                      o.media_urls, o.location, o.observed_at, o.emotional_weight,
                      o.psyche_snapshot
               FROM observations_fts
               JOIN observations o ON o.id = observations_fts.rowid
               WHERE observations_fts MATCH ?
               ORDER BY observations_fts.rank
               LIMIT ?""",
            (safe, limit),
        ).fetchall()
        return [
            ObservationRow(
                id=r[0], source_type=r[1], source_id=r[2],
                author_id=r[3], content=r[4],
                media_urls=json.loads(r[5]), location=r[6],
                observed_at=r[7], emotional_weight=r[8],
                psyche_snapshot=json.loads(r[9]),
            )
            for r in rows
        ]

    def search_observations_scored(
        self, query: str, limit: int = 10,
    ) -> list[tuple[ObservationRow, float]]:
        """Search observations with BM25 relevance scores from FTS5."""
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """SELECT o.id, o.source_type, o.source_id, o.author_id, o.content,
                      o.media_urls, o.location, o.observed_at, o.emotional_weight,
                      o.psyche_snapshot, observations_fts.rank
               FROM observations_fts
               JOIN observations o ON o.id = observations_fts.rowid
               WHERE observations_fts MATCH ?
               ORDER BY observations_fts.rank
               LIMIT ?""",
            (safe, limit),
        ).fetchall()
        return [
            (
                ObservationRow(
                    id=r[0], source_type=r[1], source_id=r[2],
                    author_id=r[3], content=r[4],
                    media_urls=json.loads(r[5]), location=r[6],
                    observed_at=r[7], emotional_weight=r[8],
                    psyche_snapshot=json.loads(r[9]),
                ),
                _normalize_bm25(r[10]),
            )
            for r in rows
        ]

    def save_annotation(self, ann: Annotation) -> int:
        cur = self._conn.execute(
            """INSERT INTO annotations
               (target_type, target_id, topics, entities, sentiment,
                summary, confidence, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ann.target_type,
                ann.target_id,
                json.dumps(ann.topics, ensure_ascii=False),
                json.dumps(ann.entities, ensure_ascii=False),
                ann.sentiment,
                ann.summary,
                ann.confidence,
                ann.source,
                ann.created_at,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_annotations_for(self, target_type: str, target_id: int) -> list[AnnotationRow]:
        rows = self._conn.execute(
            """SELECT id, target_type, target_id, topics, entities,
                      sentiment, summary, confidence, source, created_at
               FROM annotations
               WHERE target_type = ? AND target_id = ?
               ORDER BY created_at DESC""",
            (target_type, target_id),
        ).fetchall()
        return [
            AnnotationRow(
                id=r[0], target_type=r[1], target_id=r[2],
                topics=json.loads(r[3]), entities=json.loads(r[4]),
                sentiment=r[5], summary=r[6], confidence=r[7],
                source=r[8], created_at=r[9],
            )
            for r in rows
        ]

    def search_annotations(self, query: str, limit: int = 10) -> list[AnnotationRow]:
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """SELECT a.id, a.target_type, a.target_id, a.topics, a.entities,
                      a.sentiment, a.summary, a.confidence, a.source, a.created_at
               FROM annotations_fts
               JOIN annotations a ON a.id = annotations_fts.rowid
               WHERE annotations_fts MATCH ?
               ORDER BY annotations_fts.rank
               LIMIT ?""",
            (safe, limit),
        ).fetchall()
        return [
            AnnotationRow(
                id=r[0], target_type=r[1], target_id=r[2],
                topics=json.loads(r[3]), entities=json.loads(r[4]),
                sentiment=r[5], summary=r[6], confidence=r[7],
                source=r[8], created_at=r[9],
            )
            for r in rows
        ]

    def search_annotations_scored(
        self, query: str, limit: int = 10,
    ) -> list[tuple[AnnotationRow, float]]:
        """Search annotations with BM25 relevance scores from FTS5."""
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """SELECT a.id, a.target_type, a.target_id, a.topics, a.entities,
                      a.sentiment, a.summary, a.confidence, a.source, a.created_at,
                      annotations_fts.rank
               FROM annotations_fts
               JOIN annotations a ON a.id = annotations_fts.rowid
               WHERE annotations_fts MATCH ?
               ORDER BY annotations_fts.rank
               LIMIT ?""",
            (safe, limit),
        ).fetchall()
        return [
            (
                AnnotationRow(
                    id=r[0], target_type=r[1], target_id=r[2],
                    topics=json.loads(r[3]), entities=json.loads(r[4]),
                    sentiment=r[5], summary=r[6], confidence=r[7],
                    source=r[8], created_at=r[9],
                ),
                _normalize_bm25(r[10]),
            )
            for r in rows
        ]

    def update_observation_appraisal(
        self,
        obs_id: int,
        emotional_weight: float,
        psyche_snapshot: dict | None = None,
    ) -> None:
        """Enrich a stored observation with Psyche-derived emotional encoding."""
        self._conn.execute(
            """UPDATE observations
               SET emotional_weight = ?, psyche_snapshot = ?
               WHERE id = ?""",
            (
                emotional_weight,
                json.dumps(psyche_snapshot or {}, ensure_ascii=False),
                obs_id,
            ),
        )
        self._conn.commit()


# ── Knowledge store ──────────────────────────────────────────────


class KnowledgeStore(_SQLiteStore):
    """ADD-only knowledge triples and Psyche snapshots with FTS5 search."""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS knowledge_triples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL DEFAULT '',
            predicate TEXT NOT NULL DEFAULT '',
            object TEXT NOT NULL DEFAULT '',
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT '',
            source_id INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0.8,
            created_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
            USING fts5(subject, predicate, object,
                       content='knowledge_triples', content_rowid='id');

        CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge_triples BEGIN
            INSERT INTO knowledge_fts(rowid, subject, predicate, object)
            VALUES (new.id, new.subject, new.predicate, new.object);
        END;
        CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge_triples BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, subject, predicate, object)
            VALUES ('delete', old.id, old.subject, old.predicate, old.object);
        END;

        CREATE TABLE IF NOT EXISTS psyche_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL DEFAULT 0,
            snapshot TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_psyche_session
            ON psyche_snapshots(session_id, created_at);
    """

    def add_triple(self, triple: KnowledgeTriple) -> int:
        cur = self._conn.execute(
            """INSERT INTO knowledge_triples
               (subject, predicate, object, valid_from, valid_to,
                source_type, source_id, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                triple.subject,
                triple.predicate,
                triple.object,
                triple.valid_from,
                triple.valid_to,
                triple.source_type,
                triple.source_id,
                triple.confidence,
                triple.created_at,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def search_triples(self, query: str, limit: int = 10) -> list[KnowledgeTripleRow]:
        safe = _fts5_query(query)
        if not safe:
            return []
        rows = self._conn.execute(
            """SELECT k.id, k.subject, k.predicate, k.object,
                      k.valid_from, k.valid_to, k.source_type,
                      k.source_id, k.confidence, k.created_at
               FROM knowledge_fts
               JOIN knowledge_triples k ON k.id = knowledge_fts.rowid
               WHERE knowledge_fts MATCH ?
               ORDER BY knowledge_fts.rank
               LIMIT ?""",
            (safe, limit),
        ).fetchall()
        return [KnowledgeTripleRow(*r) for r in rows]

    def find_by_entity(self, entity: str, limit: int = 20) -> list[KnowledgeTripleRow]:
        safe = _fts5_query(entity)
        if not safe:
            return []
        rows = self._conn.execute(
            """SELECT k.id, k.subject, k.predicate, k.object,
                      k.valid_from, k.valid_to, k.source_type,
                      k.source_id, k.confidence, k.created_at
               FROM knowledge_fts
               JOIN knowledge_triples k ON k.id = knowledge_fts.rowid
               WHERE knowledge_fts MATCH ?
               ORDER BY k.created_at DESC
               LIMIT ?""",
            (safe, limit),
        ).fetchall()
        return [KnowledgeTripleRow(*r) for r in rows]

    def save_psyche_snapshot(self, session_id: int, snapshot: dict) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO psyche_snapshots (session_id, snapshot, created_at)
               VALUES (?, ?, ?)""",
            (session_id, json.dumps(snapshot, ensure_ascii=False), now),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def latest_psyche_snapshot(self, session_id: int) -> PsycheSnapshotRow | None:
        row = self._conn.execute(
            """SELECT id, session_id, snapshot, created_at
               FROM psyche_snapshots
               WHERE session_id = ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return PsycheSnapshotRow(
            id=row[0], session_id=row[1],
            snapshot=json.loads(row[2]), created_at=row[3],
        )
