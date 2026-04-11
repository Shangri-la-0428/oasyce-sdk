"""Guard: ``oasyce_sdk.__version__`` must match ``pyproject.toml``.

Prevents editable-install metadata drift: when pyproject bumps the
version, importing the package should reflect the new value without
needing a fresh ``pip install -e .``.  See ``_package_version`` in
``oasyce_sdk/__init__.py`` for the source-first resolution path that
this test guards.
"""

import re
from pathlib import Path

import oasyce_sdk


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        pyproject.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match is not None, "pyproject.toml is missing a top-level version ="
    assert oasyce_sdk.__version__ == match.group(1)
