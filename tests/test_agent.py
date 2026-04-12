"""Tests for oasyce_sdk.agent — scanner, privacy, daemon, core."""

import hashlib
import json
import os
import tempfile
import time
import threading

import pytest

from oasyce_sdk.agent import scanner, daemon, privacy


# ---------------------------------------------------------------------------
# Privacy tests
# ---------------------------------------------------------------------------

class TestPrivacy:
    def test_safe_text(self):
        result = privacy.scan_text("Hello world, nothing sensitive here")
        assert result["has_sensitive"] is False
        assert privacy.risk_level(result) == "safe"

    def test_email_detection(self):
        result = privacy.scan_text("Contact me at user@example.com")
        assert result["has_sensitive"] is True
        assert result["findings"][0]["type"] == "email"
        assert result["findings"][0]["count"] == 1

    def test_phone_cn(self):
        result = privacy.scan_text("Call me: 13812345678")
        assert result["has_sensitive"] is True
        types = {f["type"] for f in result["findings"]}
        assert "phone_cn" in types

    def test_id_card_cn(self):
        result = privacy.scan_text("ID: 110101199003071234")
        assert result["has_sensitive"] is True
        types = {f["type"] for f in result["findings"]}
        assert "id_card_cn" in types

    def test_credit_card(self):
        result = privacy.scan_text("Card: 4111-1111-1111-1111")
        assert result["has_sensitive"] is True
        types = {f["type"] for f in result["findings"]}
        assert "credit_card" in types

    def test_ip_address(self):
        result = privacy.scan_text("Server at 192.168.1.100")
        assert result["has_sensitive"] is True
        types = {f["type"] for f in result["findings"]}
        assert "ip_address" in types

    def test_api_key(self):
        fake_key = "x" * 32  # long enough to trigger pattern
        result = privacy.scan_text(f'api_key: "{fake_key}"')
        assert result["has_sensitive"] is True
        types = {f["type"] for f in result["findings"]}
        assert "api_key" in types

    def test_risk_level_safe(self):
        assert privacy.risk_level({"has_sensitive": False, "findings": []}) == "safe"

    def test_risk_level_low(self):
        findings = {"has_sensitive": True, "findings": [{"type": "email", "count": 1}]}
        assert privacy.risk_level(findings) == "low"

    def test_risk_level_medium(self):
        findings = {"has_sensitive": True, "findings": [{"type": "phone_cn", "count": 2}]}
        assert privacy.risk_level(findings) == "medium"

    def test_risk_level_high(self):
        findings = {"has_sensitive": True, "findings": [{"type": "credit_card", "count": 3}]}
        assert privacy.risk_level(findings) == "high"

    def test_risk_level_critical(self):
        findings = {"has_sensitive": True, "findings": [{"type": "credit_card", "count": 5}]}
        assert privacy.risk_level(findings) == "critical"

    def test_scan_file_safe(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Just normal text, no PII here")
            path = f.name
        try:
            result = privacy.scan_file(path)
            assert result["has_sensitive"] is False
            assert privacy.check_file(path) == "safe"
        finally:
            os.unlink(path)

    def test_scan_file_with_email(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Contact: admin@secret.com and root@server.org")
            path = f.name
        try:
            assert privacy.check_file(path) != "safe"
        finally:
            os.unlink(path)

    def test_scan_file_binary_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"user@email.com")
            path = f.name
        try:
            result = privacy.scan_file(path)
            assert result["has_sensitive"] is False  # binary skipped
        finally:
            os.unlink(path)

    def test_scan_file_structured_sqlite_is_not_auto_safe(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            f.write(b"SQLite format 3\x00user@example.com\x0013812345678")
            path = f.name
        try:
            result = privacy.scan_file(path)
            assert result["has_sensitive"] is True
            types = {finding["type"] for finding in result["findings"]}
            assert "email" in types or "phone_cn" in types
            assert privacy.check_file(path) != "safe"
        finally:
            os.unlink(path)

    def test_scan_file_unreadable_structured_data_blocks_auto_safe(self, monkeypatch):
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            f.write(b"PAR1")
            path = f.name
        try:
            original_open = open

            def fake_open(*args, **kwargs):
                if args and args[0] == path and "b" in args[1]:
                    raise OSError("permission denied")
                return original_open(*args, **kwargs)

            monkeypatch.setattr("builtins.open", fake_open)
            result = privacy.scan_file(path)
            assert result["has_sensitive"] is True
            assert result["findings"][0]["type"] == "structured_unscanned"
            assert privacy.check_file(path) == "medium"
        finally:
            os.unlink(path)

    def test_check_file_shortcut(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            fake_key = "a" * 32
            f.write(f'api_key: "{fake_key}"')
            path = f.name
        try:
            risk = privacy.check_file(path)
            assert risk != "safe"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Scanner tests (with privacy integration)
# ---------------------------------------------------------------------------

class TestScanner:
    def test_classify_known(self):
        assert scanner.classify(".pdf") == "document"
        assert scanner.classify(".csv") == "dataset"
        assert scanner.classify(".py") == "code"
        assert scanner.classify(".jpg") == "image"
        assert scanner.classify(".mp4") == "video"
        assert scanner.classify(".mp3") == "audio"

    def test_classify_unknown(self):
        assert scanner.classify(".xyz") == "other"

    def test_classify_case_insensitive(self):
        assert scanner.classify(".PDF") == "document"
        assert scanner.classify(".Py") == "code"

    def test_sha256_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello world")
            f.flush()
            path = f.name
        try:
            got = scanner.sha256_file(path)
            expected = hashlib.sha256(b"hello world").hexdigest()
            assert got == expected
        finally:
            os.unlink(path)

    def test_scan_finds_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("a.txt", "b.pdf", "c.py"):
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write(f"content of {name}")
            with open(os.path.join(tmpdir, "d.exe"), "w") as f:
                f.write("binary")

            results = scanner.scan(paths=[tmpdir])
            names = {r.name for r in results}
            assert "a.txt" in names
            assert "b.pdf" in names
            assert "c.py" in names
            assert "d.exe" not in names

    def test_scan_skips_known_hashes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            content = "test content"
            with open(os.path.join(tmpdir, "test.txt"), "w") as f:
                f.write(content)
            h = hashlib.sha256(content.encode()).hexdigest()
            results = scanner.scan(paths=[tmpdir], known_hashes={h})
            assert len(results) == 0

    def test_scan_skips_large_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "big.txt"), "wb") as f:
                f.write(b"x" * 1000)
            results = scanner.scan(paths=[tmpdir], max_size=500)
            assert len(results) == 0

    def test_scan_skips_empty_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "empty.txt"), "w").close()
            results = scanner.scan(paths=[tmpdir])
            assert len(results) == 0

    def test_scan_skips_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".hidden.txt"), "w") as f:
                f.write("secret")
            results = scanner.scan(paths=[tmpdir])
            assert len(results) == 0

    def test_scan_skips_git_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gitdir = os.path.join(tmpdir, ".git")
            os.makedirs(gitdir)
            with open(os.path.join(gitdir, "config.txt"), "w") as f:
                f.write("git stuff")
            results = scanner.scan(paths=[tmpdir])
            assert len(results) == 0

    def test_fileinfo_has_privacy_risk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "safe.txt"), "w") as f:
                f.write("totally normal content")
            results = scanner.scan(paths=[tmpdir])
            assert len(results) == 1
            assert results[0].privacy_risk == "safe"

    def test_scan_detects_pii_in_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "contacts.csv"), "w") as f:
                f.write("name,email,phone\n")
                f.write("Alice,alice@secret.com,13912345678\n")
                f.write("Bob,bob@secret.com,13812345678\n")
            results = scanner.scan(paths=[tmpdir])
            assert len(results) == 1
            assert results[0].privacy_risk != "safe"

    def test_scan_no_privacy_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "secrets.txt"), "w") as f:
                fake_key = "z" * 32
                f.write(f'api_key: "{fake_key}"')
            results = scanner.scan(paths=[tmpdir], check_privacy=False)
            assert len(results) == 1
            assert results[0].privacy_risk == "safe"  # skipped check

    def test_fileinfo_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "data.csv"), "w") as f:
                f.write("a,b,c\n1,2,3")
            results = scanner.scan(paths=[tmpdir])
            assert len(results) == 1
            fi = results[0]
            assert fi.name == "data.csv"
            assert fi.category == "dataset"
            assert "dataset" in fi.tags
            assert "csv" in fi.tags
            assert fi.size > 0
            assert len(fi.sha256) == 64
            assert fi.privacy_risk in ("safe", "low", "medium", "high", "critical")

    def test_scan_batches_and_honors_cancel_event(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(501):
                with open(os.path.join(tmpdir, f"file-{i}.txt"), "w") as f:
                    f.write(f"content-{i}")

            cancel_event = threading.Event()
            calls = 0

            def fake_sha256_file(path):
                nonlocal calls
                calls += 1
                if calls == 500:
                    cancel_event.set()
                return hashlib.sha256(path.encode()).hexdigest()

            monkeypatch.setattr(scanner, "sha256_file", fake_sha256_file)

            results = scanner.scan(
                paths=[tmpdir],
                check_privacy=False,
                cancel_event=cancel_event,
            )

            assert len(results) == 500
            assert calls == 500


# ---------------------------------------------------------------------------
# Daemon tests
# ---------------------------------------------------------------------------

class TestDaemon:
    @pytest.fixture(autouse=True)
    def _daemon_paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(daemon, "OASYCE_DIR", str(tmp_path))
        monkeypatch.setattr(daemon, "PID_FILE", str(tmp_path / "agent.pid"))
        monkeypatch.setattr(daemon, "LOG_FILE", str(tmp_path / "agent.log"))

    def test_is_alive_nonexistent_pid(self):
        assert daemon._is_alive(999999999) is False

    def test_is_alive_current_process(self):
        assert daemon._is_alive(os.getpid()) is True

    def test_read_pid_missing(self):
        if os.path.exists(daemon.PID_FILE):
            os.remove(daemon.PID_FILE)
        assert daemon._read_pid() is None

    def test_status_not_running(self):
        if os.path.exists(daemon.PID_FILE):
            os.remove(daemon.PID_FILE)
        running, msg = daemon.status()
        assert running is False
        assert "not running" in msg.lower()

    def test_stop_not_running(self):
        if os.path.exists(daemon.PID_FILE):
            os.remove(daemon.PID_FILE)
        ok, msg = daemon.stop()
        assert ok is False

    def test_read_pid_cleans_up_foreign_process_pidfile(self, monkeypatch):
        with open(daemon.PID_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "state": daemon.RUNNING_STATE}, f)

        monkeypatch.setattr(daemon, "_pid_looks_like_agent", lambda pid: False)

        assert daemon._read_pid() is None
        assert not os.path.exists(daemon.PID_FILE)

    def test_start_refuses_duplicate_pending_start(self):
        os.makedirs(daemon.OASYCE_DIR, exist_ok=True)
        with open(daemon.PID_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"pid": 0, "state": daemon.STARTING_STATE, "written_at": time.time()},
                f,
            )

        ok, msg = daemon.start()

        assert ok is False
        assert "already starting" in msg.lower()

    def test_stop_keeps_pidfile_when_process_does_not_exit(self, monkeypatch):
        with open(daemon.PID_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": 4242, "state": daemon.RUNNING_STATE}, f)

        monkeypatch.setattr(daemon, "_pid_looks_like_agent", lambda pid: True)
        monkeypatch.setattr(daemon, "_is_alive", lambda pid: True)
        monkeypatch.setattr(daemon.time, "sleep", lambda _: None)
        timestamps = iter([1000.0, 1000.0, 1006.0])
        monkeypatch.setattr(daemon.time, "time", lambda: next(timestamps))
        signals = []
        monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: signals.append((pid, sig)))

        ok, msg = daemon.stop()

        assert ok is False
        assert "did not stop" in msg.lower()
        assert os.path.exists(daemon.PID_FILE)
        assert signals == [(4242, daemon.signal.SIGTERM)]


# ---------------------------------------------------------------------------
# Core config/DB tests
# ---------------------------------------------------------------------------

class TestCore:
    def test_init_db(self):
        from oasyce_sdk.agent.core import _get_known_hashes, _get_state, _set_state
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS registered_assets (
                    content_hash TEXT PRIMARY KEY,
                    file_path TEXT,
                    file_name TEXT,
                    category TEXT,
                    privacy_risk TEXT DEFAULT 'safe',
                    tx_hash TEXT,
                    registered_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

            hashes = _get_known_hashes(conn)
            assert len(hashes) == 0

            assert _get_state(conn, "foo") is None
            _set_state(conn, "foo", "bar")
            assert _get_state(conn, "foo") == "bar"

            conn.close()

    def test_init_db_has_trades_table(self):
        from oasyce_sdk.agent.core import _init_db
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            original_db = os.path.join(tmpdir, "test.db")
            import oasyce_sdk.agent.core as core_mod
            old_path = core_mod.DB_PATH
            core_mod.DB_PATH = original_db
            try:
                conn = _init_db()
                # capability_trades table should exist
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='capability_trades'"
                )
                assert cur.fetchone() is not None
                conn.close()
            finally:
                core_mod.DB_PATH = old_path

    def test_discover_no_trade_when_disabled(self):
        from oasyce_sdk.agent.core import discover_and_trade, _init_db
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            import oasyce_sdk.agent.core as core_mod
            old_path = core_mod.DB_PATH
            core_mod.DB_PATH = db_path
            try:
                conn = _init_db()
                config = {"auto_trade": False}
                result = discover_and_trade(None, None, conn, config)
                assert result == 0
                conn.close()
            finally:
                core_mod.DB_PATH = old_path

    def test_discover_no_trade_when_no_tags(self):
        from oasyce_sdk.agent.core import discover_and_trade, _init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            import oasyce_sdk.agent.core as core_mod
            old_path = core_mod.DB_PATH
            core_mod.DB_PATH = db_path
            try:
                conn = _init_db()
                config = {"auto_trade": True, "trade_tags": []}
                result = discover_and_trade(None, None, conn, config)
                assert result == 0
                conn.close()
            finally:
                core_mod.DB_PATH = old_path

    def test_get_traded_ids(self):
        from oasyce_sdk.agent.core import _get_traded_ids, _init_db

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            import oasyce_sdk.agent.core as core_mod
            old_path = core_mod.DB_PATH
            core_mod.DB_PATH = db_path
            try:
                conn = _init_db()
                assert len(_get_traded_ids(conn)) == 0
                conn.execute(
                    "INSERT INTO capability_trades VALUES (?, ?, ?, ?, ?)",
                    ("cap-001", "tx123", 500000, "nlp", "2026-01-01T00:00:00Z"),
                )
                conn.commit()
                assert "cap-001" in _get_traded_ids(conn)
                conn.close()
            finally:
                core_mod.DB_PATH = old_path
