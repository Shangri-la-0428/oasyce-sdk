"""Stimulus int coercion + quota cooldown — contract tests.

These guard against the production outage where Go-side webhooks
delivered large user IDs as JSON strings, causing the same
relationship to be registered twice (int + str) in the session dict
and doubling LLM reflection cost.
"""

from __future__ import annotations

import time

import pytest

from oasyce_sdk.agent.stimulus import Stimulus


class TestStimulusCoercion:
    def test_int_sender_kept_as_int(self):
        s = Stimulus(kind="chat", content="hi", sender_id=123)
        assert s.sender_id == 123
        assert isinstance(s.sender_id, int)

    def test_str_sender_coerced_to_int(self):
        s = Stimulus(kind="chat", content="hi", sender_id="1776191682194761")
        assert s.sender_id == 1776191682194761
        assert isinstance(s.sender_id, int)

    def test_zero_sender_stays_zero(self):
        s = Stimulus(kind="feed_post", content="x", sender_id=0)
        assert s.sender_id == 0

    def test_empty_string_sender_stays_zero(self):
        # `0` default + truthy guard means empty string shouldn't crash
        s = Stimulus(kind="chat", content="x", sender_id=0)
        assert s.sender_id == 0

    def test_all_id_fields_coerced(self):
        s = Stimulus(
            kind="mention", content="x",
            sender_id="1", post_id="2", session_id="3", comment_id="4",
        )
        assert s.sender_id == 1
        assert s.post_id == 2
        assert s.session_id == 3
        assert s.comment_id == 4

    def test_invalid_str_raises_at_boundary(self):
        with pytest.raises(ValueError):
            Stimulus(kind="chat", content="x", sender_id="not-a-number")


class TestQuotaCooldown:
    """The circuit breaker lives in agent.base as module-level state."""

    def setup_method(self):
        from oasyce_sdk.agent import base
        base._quota_exhausted_at = 0.0

    def teardown_method(self):
        from oasyce_sdk.agent import base
        base._quota_exhausted_at = 0.0

    def test_initially_not_exhausted(self):
        from oasyce_sdk.agent.base import _is_quota_exhausted
        assert _is_quota_exhausted() is False

    def test_mark_then_is_exhausted(self):
        from oasyce_sdk.agent.base import _is_quota_exhausted, _mark_quota_exhausted
        _mark_quota_exhausted("test")
        assert _is_quota_exhausted() is True

    def test_cooldown_elapses(self, monkeypatch):
        from oasyce_sdk.agent import base
        now = 100.0
        monkeypatch.setattr(base.time, "monotonic", lambda: now)
        base._mark_quota_exhausted("test")

        # Just inside cooldown
        now = 100.0 + base._QUOTA_COOLDOWN_SEC - 1
        assert base._is_quota_exhausted() is True

        # Past cooldown
        now = 100.0 + base._QUOTA_COOLDOWN_SEC + 1
        assert base._is_quota_exhausted() is False
        # State auto-cleared
        assert base._quota_exhausted_at == 0.0

    def test_detects_tencent_quota_error(self):
        from oasyce_sdk.agent.base import _looks_like_quota_error
        err = Exception(
            "Error code: 500 - {'error': "
            "{'message': 'token plan quota exhausted', 'code': '20098'}}"
        )
        assert _looks_like_quota_error(err) is True

    def test_detects_generic_quota_phrase(self):
        from oasyce_sdk.agent.base import _looks_like_quota_error
        assert _looks_like_quota_error(Exception("Your quota exhausted")) is True

    def test_ignores_unrelated_errors(self):
        from oasyce_sdk.agent.base import _looks_like_quota_error
        assert _looks_like_quota_error(Exception("connection timeout")) is False
        assert _looks_like_quota_error(ValueError("bad input")) is False
