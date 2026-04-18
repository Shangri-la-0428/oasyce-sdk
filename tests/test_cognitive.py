"""Contract tests for v2 cognitive primitives.

Validates type definitions, Protocol conformance, backward compatibility
of edited types, and store CRUD with FTS5 search.
"""

from __future__ import annotations

import threading

import pytest


# ── CognitiveMode ────────────────────────────────────────────────


class TestCognitiveMode:
    def test_enum_values(self):
        from oasyce_sdk.agent.cognitive import CognitiveMode

        assert CognitiveMode.REACTIVE.value == "reactive"
        assert CognitiveMode.PROACTIVE.value == "proactive"
        assert CognitiveMode.OBSERVING.value == "observing"
        assert CognitiveMode.REFLECTING.value == "reflecting"

    def test_round_trip(self):
        from oasyce_sdk.agent.cognitive import CognitiveMode

        for mode in CognitiveMode:
            assert CognitiveMode(mode.value) is mode

    def test_iteration(self):
        from oasyce_sdk.agent.cognitive import CognitiveMode

        assert len(list(CognitiveMode)) == 4


# ── Appraisal ────────────────────────────────────────────────────


class TestAppraisal:
    def test_defaults(self):
        from oasyce_sdk.agent.cognitive import Appraisal

        a = Appraisal()
        assert a.relevance == 0.5
        assert a.intensity == 0.5
        assert a.valence == 0.0
        assert a.emotional_weight == 0.5
        assert a.dominant_affect == ""
        assert a.psyche_delta == {}

    def test_full_construction(self):
        from oasyce_sdk.agent.cognitive import Appraisal

        a = Appraisal(
            relevance=0.9, intensity=0.8, valence=-0.3,
            emotional_weight=0.7, dominant_affect="curiosity",
            psyche_delta={"warmth": 0.1},
        )
        assert a.dominant_affect == "curiosity"
        assert a.psyche_delta == {"warmth": 0.1}

    def test_independent_mutable_defaults(self):
        from oasyce_sdk.agent.cognitive import Appraisal

        a1 = Appraisal()
        a2 = Appraisal()
        a1.psyche_delta["x"] = 1.0
        assert a2.psyche_delta == {}


# ── Observation ──────────────────────────────────────────────────


class TestObservation:
    def test_defaults(self):
        from oasyce_sdk.agent.cognitive import Observation

        o = Observation()
        assert o.source_type == ""
        assert o.content == ""
        assert o.media_urls == []
        assert o.psyche_snapshot == {}
        assert o.observed_at  # auto-filled

    def test_independent_mutable_defaults(self):
        from oasyce_sdk.agent.cognitive import Observation

        o1 = Observation()
        o2 = Observation()
        o1.media_urls.append("a.jpg")
        o1.psyche_snapshot["k"] = 1
        assert o2.media_urls == []
        assert o2.psyche_snapshot == {}


# ── Annotation ───────────────────────────────────────────────────


class TestAnnotation:
    def test_defaults(self):
        from oasyce_sdk.agent.cognitive import Annotation

        a = Annotation()
        assert a.sentiment == "neutral"
        assert a.confidence == 0.8
        assert a.source == "auto"
        assert a.topics == []
        assert a.entities == []
        assert a.created_at  # auto-filled

    def test_independent_mutable_defaults(self):
        from oasyce_sdk.agent.cognitive import Annotation

        a1 = Annotation()
        a2 = Annotation()
        a1.topics.append("travel")
        a1.entities.append("Alps")
        assert a2.topics == []
        assert a2.entities == []


# ── KnowledgeTriple ──────────────────────────────────────────────


class TestKnowledgeTriple:
    def test_defaults(self):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple

        t = KnowledgeTriple()
        assert t.subject == ""
        assert t.predicate == ""
        assert t.object == ""
        assert t.valid_to == ""
        assert t.valid_from  # auto-filled
        assert t.created_at  # auto-filled

    def test_full_construction(self):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple

        t = KnowledgeTriple(
            subject="user", predicate="prefers", object="snow mountains",
            source_type="post", source_id=42, confidence=0.95,
        )
        assert t.subject == "user"
        assert t.object == "snow mountains"
        assert t.confidence == 0.95


# ── Stream Protocol ──────────────────────────────────────────────


class TestStreamProtocol:
    def test_satisfies_protocol(self):
        from oasyce_sdk.agent.cognitive import CognitiveMode
        from oasyce_sdk.agent.stimulus import Stimulus
        from oasyce_sdk.agent.stream import Stream

        class FeedStream:
            def poll(self) -> list[Stimulus]:
                return []

            @property
            def interval(self) -> int:
                return 60

            @property
            def default_mode(self) -> CognitiveMode:
                return CognitiveMode.OBSERVING

        assert isinstance(FeedStream(), Stream)

    def test_rejects_non_conforming(self):
        from oasyce_sdk.agent.stream import Stream

        class NotAStream:
            pass

        assert not isinstance(NotAStream(), Stream)


# ── Backward compatibility: Plan.mode ────────────────────────────


class TestPlanModeField:
    def test_default_none(self):
        from oasyce_sdk.agent.planner import Plan

        p = Plan()
        assert p.mode is None

    def test_existing_fields_unchanged(self):
        from oasyce_sdk.agent.planner import Plan

        p = Plan()
        assert p.intent == "respond"
        assert p.register == "warm"
        assert p.max_sentences == 8
        assert p.require_confirmation is False

    def test_mode_assignable(self):
        from oasyce_sdk.agent.cognitive import CognitiveMode
        from oasyce_sdk.agent.planner import Plan

        p = Plan()
        p.mode = CognitiveMode.OBSERVING
        assert p.mode == CognitiveMode.OBSERVING


# ── Backward compatibility: EnrichContext.observations ────────────


class TestEnrichContextObservations:
    def test_default_empty(self):
        from oasyce_sdk.agent.pipeline import EnrichContext

        ctx = EnrichContext()
        assert ctx.observations == []

    def test_existing_fields_unchanged(self):
        from oasyce_sdk.agent.pipeline import EnrichContext

        ctx = EnrichContext()
        assert ctx.memories == []
        assert ctx.core_memory is None
        assert ctx.hist_summary == ""


# ── ObservationStore ─────────────────────────────────────────────


class TestObservationStore:
    def test_save_and_get(self, tmp_path):
        from oasyce_sdk.agent.cognitive import Observation
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        obs = Observation(
            source_type="post", source_id=1, author_id=10,
            content="Beautiful snow mountain scenery in Sichuan",
            location="Sichuan",
        )
        obs_id = store.save_observation(obs)
        assert obs_id >= 1

        row = store.get_observation(obs_id)
        assert row is not None
        assert row.content == "Beautiful snow mountain scenery in Sichuan"
        assert row.location == "Sichuan"
        assert row.source_type == "post"
        store.close()

    def test_get_nonexistent(self, tmp_path):
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        assert store.get_observation(999) is None
        store.close()

    def test_fts5_search(self, tmp_path):
        from oasyce_sdk.agent.cognitive import Observation
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        store.save_observation(Observation(
            source_type="post", content="Snow mountain hiking trail guide",
        ))
        store.save_observation(Observation(
            source_type="post", content="Best coffee shops in Shanghai",
        ))

        results = store.search_observations("snow mountain")
        assert len(results) >= 1
        assert "snow" in results[0].content.lower()

        results = store.search_observations("coffee")
        assert len(results) >= 1
        assert "coffee" in results[0].content.lower()
        store.close()

    def test_fts5_punctuation_safety(self, tmp_path):
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        results = store.search_observations("version:1.2.3")
        assert results == []
        results = store.search_observations("")
        assert results == []
        store.close()

    def test_annotation_save_and_retrieve(self, tmp_path):
        from oasyce_sdk.agent.cognitive import Annotation, Observation
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        obs_id = store.save_observation(Observation(
            source_type="post", source_id=42,
            content="Visited Gongga Mountain last weekend",
        ))
        ann = Annotation(
            target_type="observation", target_id=obs_id,
            topics=["travel", "mountain"],
            entities=["Gongga Mountain"],
            sentiment="positive",
            summary="User visited Gongga Mountain recently",
        )
        ann_id = store.save_annotation(ann)
        assert ann_id >= 1

        rows = store.get_annotations_for("observation", obs_id)
        assert len(rows) == 1
        assert rows[0].topics == ["travel", "mountain"]
        assert rows[0].entities == ["Gongga Mountain"]
        store.close()

    def test_annotation_fts5_search(self, tmp_path):
        from oasyce_sdk.agent.cognitive import Annotation
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        store.save_annotation(Annotation(
            target_type="observation", target_id=1,
            summary="Great snow scenery recommended for winter travel",
        ))
        store.save_annotation(Annotation(
            target_type="observation", target_id=2,
            summary="Local restaurant with amazing Sichuan cuisine",
        ))

        results = store.search_annotations("snow winter")
        assert len(results) >= 1
        assert "snow" in results[0].summary.lower()
        store.close()

    def test_thread_safety(self, tmp_path):
        from oasyce_sdk.agent.cognitive import Observation
        from oasyce_sdk.agent.store import ObservationStore

        store = ObservationStore(tmp_path / "test.db")
        errors: list[Exception] = []

        def writer(n: int) -> None:
            try:
                for i in range(5):
                    store.save_observation(Observation(
                        source_type="post", source_id=n * 100 + i,
                        content=f"Thread {n} observation {i}",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        store.close()

    def test_shared_db_path(self, tmp_path):
        from oasyce_sdk.agent.cognitive import Observation
        from oasyce_sdk.agent.memory import Memory
        from oasyce_sdk.agent.store import ObservationStore

        db = tmp_path / "shared.db"
        mem = Memory(db_path=db)
        obs_store = ObservationStore(db)

        mem.save("User likes hiking", "preference")
        obs_store.save_observation(Observation(
            source_type="post", content="Mountain trail review",
        ))

        assert mem.count() == 1
        results = obs_store.search_observations("mountain")
        assert len(results) >= 1

        mem.close()
        obs_store.close()


# ── KnowledgeStore ───────────────────────────────────────────────


class TestKnowledgeStore:
    def test_add_and_search(self, tmp_path):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple
        from oasyce_sdk.agent.store import KnowledgeStore

        store = KnowledgeStore(tmp_path / "test.db")
        triple = KnowledgeTriple(
            subject="user", predicate="prefers", object="snow mountains",
            source_type="post", source_id=1,
        )
        tid = store.add_triple(triple)
        assert tid >= 1

        results = store.search_triples("snow mountains")
        assert len(results) >= 1
        assert results[0].subject == "user"
        assert results[0].object == "snow mountains"
        store.close()

    def test_find_by_entity(self, tmp_path):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple
        from oasyce_sdk.agent.store import KnowledgeStore

        store = KnowledgeStore(tmp_path / "test.db")
        store.add_triple(KnowledgeTriple(
            subject="Gongga Mountain", predicate="located_in", object="Sichuan",
        ))
        store.add_triple(KnowledgeTriple(
            subject="user", predicate="visited", object="Gongga Mountain",
        ))

        results = store.find_by_entity("Gongga Mountain")
        assert len(results) >= 2
        store.close()

    def test_add_only_semantics(self, tmp_path):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple
        from oasyce_sdk.agent.store import KnowledgeStore

        store = KnowledgeStore(tmp_path / "test.db")
        t1 = store.add_triple(KnowledgeTriple(
            subject="user", predicate="lives_in", object="Beijing",
        ))
        t2 = store.add_triple(KnowledgeTriple(
            subject="user", predicate="lives_in", object="Shanghai",
        ))
        assert t1 != t2

        results = store.search_triples("lives_in")
        assert len(results) == 2
        store.close()

    def test_psyche_snapshots(self, tmp_path):
        from oasyce_sdk.agent.store import KnowledgeStore

        store = KnowledgeStore(tmp_path / "test.db")
        store.save_psyche_snapshot(1, {"warmth": 0.7, "vitality": 0.8})
        store.save_psyche_snapshot(1, {"warmth": 0.6, "vitality": 0.5})

        latest = store.latest_psyche_snapshot(1)
        assert latest is not None
        assert latest.snapshot["warmth"] == 0.6

        assert store.latest_psyche_snapshot(999) is None
        store.close()

    def test_thread_safety(self, tmp_path):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple
        from oasyce_sdk.agent.store import KnowledgeStore

        store = KnowledgeStore(tmp_path / "test.db")
        errors: list[Exception] = []

        def writer(n: int) -> None:
            try:
                for i in range(5):
                    store.add_triple(KnowledgeTriple(
                        subject=f"entity_{n}", predicate="has",
                        object=f"attr_{i}",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        store.close()

    def test_shared_db_with_memory_and_observations(self, tmp_path):
        from oasyce_sdk.agent.cognitive import KnowledgeTriple, Observation
        from oasyce_sdk.agent.memory import Memory
        from oasyce_sdk.agent.store import KnowledgeStore, ObservationStore

        db = tmp_path / "shared.db"
        mem = Memory(db_path=db)
        obs = ObservationStore(db)
        know = KnowledgeStore(db)

        mem.save("User mentioned snow mountains", "topic")
        obs.save_observation(Observation(
            source_type="post", content="Snow scenery in Sichuan",
        ))
        know.add_triple(KnowledgeTriple(
            subject="user", predicate="interested_in", object="snow mountains",
        ))

        assert mem.count() == 1
        assert len(obs.search_observations("snow")) >= 1
        assert len(know.search_triples("snow mountains")) >= 1

        mem.close()
        obs.close()
        know.close()


# ── Import from package ──────────────────────────────────────────


class TestPackageExports:
    def test_all_types_importable(self):
        from oasyce_sdk.agent import (
            Annotation,
            Appraisal,
            CognitiveMode,
            KnowledgeStore,
            KnowledgeTriple,
            Observation,
            ObservationStore,
            Stream,
        )

        assert CognitiveMode.REACTIVE.value == "reactive"
        assert Appraisal is not None
        assert Observation is not None
        assert Annotation is not None
        assert KnowledgeTriple is not None
        assert ObservationStore is not None
        assert KnowledgeStore is not None
        assert Stream is not None
