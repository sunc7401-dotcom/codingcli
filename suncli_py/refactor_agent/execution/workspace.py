"""Task-level workspace state capture for independent verification."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

IGNORED_WORKSPACE_DIRS = frozenset(
    {
        ".git",
        ".gradle",
        ".mypy_cache",
        ".paicli",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "out",
        "target",
        "venv",
    }
)


def capture_workspace_manifest(root: str | Path) -> dict[str, str]:
    """Hash non-generated workspace files without following directory symlinks."""
    resolved_root = Path(root).resolve()
    manifest: dict[str, str] = {}
    for directory, dirnames, filenames in os.walk(resolved_root, topdown=True, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_WORKSPACE_DIRS)
        directory_path = Path(directory)
        for filename in sorted(filenames):
            path = directory_path / filename
            relative_path = path.relative_to(resolved_root).as_posix()
            if path.is_symlink():
                target = os.readlink(path)
                manifest[relative_path] = hashlib.sha256(
                    f"symlink:{target}".encode("utf-8", errors="surrogatepass")
                ).hexdigest()
            elif path.is_file():
                manifest[relative_path] = file_sha256(path)
    return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
