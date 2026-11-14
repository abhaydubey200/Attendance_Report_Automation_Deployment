"""Project path resolution."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def resolve_path(value: str | Path, base: Path = PROJECT_ROOT) -> Path:
    """Resolve a configured path: absolute paths are kept, relative ones are anchored at `base`."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()
