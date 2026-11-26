"""Provenance: software versions, code revision and source fingerprint."""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from simulator import __version__
from simulator.config import PROJECT_ROOT

SOURCE_PACKAGES = ("simulator", "algorithms", "experiments")
DEPENDENCIES = ("numpy", "scipy", "pandas", "statsmodels", "matplotlib", "openpyxl", "pytest")


@lru_cache(maxsize=1)
def source_hash() -> str:
    """SHA-256 over every .py file that can influence a simulation run."""
    h = hashlib.sha256()
    for pkg in SOURCE_PACKAGES:
        for path in sorted((PROJECT_ROOT / pkg).rglob("*.py")):
            h.update(str(path.relative_to(PROJECT_ROOT)).replace("\\", "/").encode())
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


@lru_cache(maxsize=1)
def git_info() -> dict:
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True,
                                 timeout=10)
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    top = run("rev-parse", "--show-toplevel")
    if top is None or Path(top).resolve() != PROJECT_ROOT.resolve():
        return {"git_commit": None, "git_dirty": None}
    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--", *SOURCE_PACKAGES)
    return {"git_commit": commit, "git_dirty": bool(status) if status is not None else None}


@lru_cache(maxsize=1)
def dependency_versions() -> dict:
    versions = {}
    for dep in DEPENDENCIES:
        try:
            versions[dep] = importlib.metadata.version(dep)
        except importlib.metadata.PackageNotFoundError:
            versions[dep] = None
    return versions


def code_version() -> str:
    info = git_info()
    tag = f"{__version__}+src.{source_hash()[:10]}"
    if info["git_commit"]:
        tag += f".git.{info['git_commit'][:8]}" + (".dirty" if info["git_dirty"] else "")
    return tag


def provenance_record() -> dict:
    return {
        "execution_timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "simulator_version": __version__,
        "code_version": code_version(),
        "source_sha256": source_hash(),
        **git_info(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "dependencies": dependency_versions(),
    }
