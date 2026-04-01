"""File scanner — walk directories, hash files, classify by type."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import List, Optional, Set

# Extension → category mapping
_CATEGORIES = {
    # Documents
    ".pdf": "document", ".doc": "document", ".docx": "document",
    ".txt": "document", ".md": "document", ".rtf": "document",
    ".odt": "document", ".tex": "document",
    # Data
    ".csv": "dataset", ".json": "dataset", ".xlsx": "dataset",
    ".xls": "dataset", ".tsv": "dataset", ".parquet": "dataset",
    ".xml": "dataset", ".yaml": "dataset", ".yml": "dataset",
    ".sqlite": "dataset", ".db": "dataset",
    # Code
    ".py": "code", ".js": "code", ".ts": "code", ".go": "code",
    ".rs": "code", ".java": "code", ".cpp": "code", ".c": "code",
    ".h": "code", ".sol": "code", ".rb": "code", ".php": "code",
    ".swift": "code", ".kt": "code", ".sh": "code",
    # Images
    ".jpg": "image", ".jpeg": "image", ".png": "image",
    ".gif": "image", ".bmp": "image", ".svg": "image",
    ".webp": "image", ".tiff": "image",
    # Audio
    ".mp3": "audio", ".wav": "audio", ".flac": "audio",
    ".aac": "audio", ".ogg": "audio",
    # Video
    ".mp4": "video", ".mov": "video", ".avi": "video",
    ".mkv": "video", ".webm": "video",
    # 3D / Design
    ".blend": "design", ".psd": "design", ".ai": "design",
    ".fig": "design", ".sketch": "design",
}

# Default extensions to scan (common data-bearing files)
DEFAULT_EXTENSIONS = set(_CATEGORIES.keys())

# Default directories to scan
DEFAULT_SCAN_PATHS = [
    os.path.join(os.path.expanduser("~"), d)
    for d in ("Documents", "Desktop", "Downloads", "Pictures")
]

# Skip these directory names
_SKIP_DIRS = {
    ".git", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".Trash", "$RECYCLE.BIN", "System Volume Information",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@dataclass
class FileInfo:
    """Scanned file metadata."""
    path: str
    name: str
    sha256: str
    size: int
    category: str
    tags: List[str]
    privacy_risk: str = "safe"  # safe/low/medium/high/critical


def classify(ext: str) -> str:
    """Return category for a file extension."""
    return _CATEGORIES.get(ext.lower(), "other")


def sha256_file(path: str) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def scan(
    paths: Optional[List[str]] = None,
    extensions: Optional[Set[str]] = None,
    max_size: int = MAX_FILE_SIZE,
    known_hashes: Optional[Set[str]] = None,
    check_privacy: bool = True,
) -> List[FileInfo]:
    """Scan directories for new files with privacy risk assessment.

    Args:
        paths: Directories to scan. Defaults to ~/Documents, ~/Desktop, etc.
        extensions: File extensions to include. Defaults to all known categories.
        max_size: Skip files larger than this (bytes).
        known_hashes: SHA256 hashes already registered — skip these.
        check_privacy: Run PII detection on text files. Default True.

    Returns:
        List of FileInfo for newly discovered files (with privacy_risk field).
    """
    from . import privacy

    paths = paths or DEFAULT_SCAN_PATHS
    extensions = extensions or DEFAULT_EXTENSIONS
    known = known_hashes or set()
    results = []

    for base_path in paths:
        base_path = os.path.expanduser(base_path)
        if not os.path.isdir(base_path):
            continue

        for dirpath, dirnames, filenames in os.walk(base_path):
            # Prune skippable directories in-place
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]

            for fname in filenames:
                if fname.startswith("."):
                    continue

                ext = os.path.splitext(fname)[1].lower()
                if ext not in extensions:
                    continue

                fpath = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(fpath)
                except OSError:
                    continue

                if size == 0 or size > max_size:
                    continue

                try:
                    content_hash = sha256_file(fpath)
                except (OSError, PermissionError):
                    continue

                if content_hash in known:
                    continue

                category = classify(ext)
                tags = [category]
                if ext:
                    tags.append(ext.lstrip("."))

                # Privacy check
                risk = "safe"
                if check_privacy:
                    risk = privacy.check_file(fpath)

                results.append(FileInfo(
                    path=fpath,
                    name=fname,
                    sha256=content_hash,
                    size=size,
                    category=category,
                    tags=tags,
                    privacy_risk=risk,
                ))

    return results
