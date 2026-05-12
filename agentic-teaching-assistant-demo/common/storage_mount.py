"""
Storage mount detection helpers.

These heuristics are used to reduce false positives/negatives across
different container runtimes and filesystems (bind mounts, overlayfs, PVCs).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple


TRUTHY_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY_VALUES


def is_running_in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def _has_non_root_mount_ancestor(path: Path) -> bool:
    """
    Check if path or one of its ancestors is a mount point, excluding root.

    Root ("/") is always a mount and would make this check trivially true.
    """
    current = path.resolve()
    while True:
        if current.exists() and current.is_mount() and str(current) != current.anchor:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _has_device_boundary(path: Path) -> bool:
    """
    Detect a mount boundary by comparing device IDs to ancestors.
    """
    current = path.resolve()
    while current.parent != current:
        try:
            current_dev = current.stat().st_dev
            parent_dev = current.parent.stat().st_dev
        except OSError:
            return False
        if current_dev != parent_dev:
            return True
        current = current.parent
    return False


def _read_proc_mount_points() -> set[str]:
    mounts_file = Path("/proc/mounts")
    if not mounts_file.exists():
        return set()

    mount_points: set[str] = set()
    try:
        with mounts_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                # Mount path in /proc/mounts escapes spaces as \040.
                mount_points.add(parts[1].replace("\\040", " "))
    except OSError:
        return set()

    return mount_points


def _has_proc_mount_ancestor(path: Path) -> bool:
    """
    Detect path ancestry against /proc/mounts, excluding root mount.
    """
    mount_points = _read_proc_mount_points()
    if not mount_points:
        return False

    current = path.resolve()
    while True:
        current_str = str(current)
        if current_str != "/" and current_str in mount_points:
            return True
        if current.parent == current:
            return False
        current = current.parent


def _resolve_sentinel_path(storage_dir: Path, sentinel_file: Optional[str]) -> Optional[Path]:
    if not sentinel_file:
        return None

    sentinel = Path(sentinel_file)
    if sentinel.is_absolute():
        return sentinel
    return storage_dir / sentinel


def detect_storage_mount(
    storage_dir: Path,
    sentinel_file: Optional[str] = None,
) -> Tuple[bool, Dict[str, bool], Optional[str]]:
    """
    Detect whether storage_dir appears mounted using multiple heuristics.

    Returns:
      (detected, checks, sentinel_path)
      - detected: aggregate detection result
      - checks: per-heuristic booleans
      - sentinel_path: resolved sentinel path if provided
    """
    storage_dir = storage_dir.resolve()
    sentinel_path = _resolve_sentinel_path(storage_dir, sentinel_file)

    checks = {
        "path_or_ancestor_is_mount": _has_non_root_mount_ancestor(storage_dir),
        "device_boundary_detected": _has_device_boundary(storage_dir),
        "proc_mounts_match": _has_proc_mount_ancestor(storage_dir),
        "sentinel_exists": bool(sentinel_path and sentinel_path.exists()),
    }

    detected = any(checks.values())
    return detected, checks, str(sentinel_path) if sentinel_path else None
