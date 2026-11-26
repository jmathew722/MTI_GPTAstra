"""Path and input safety for the 3D -> 2D job API: authorized roots, ids, extension / document-type checks, hashing.

Nothing here opens SOLIDWORKS.  The rules come from the architecture spec: validate paths server-side, allow only authorized roots,
refuse traversal and symlink escapes, make collision-safe ids, never execute anything.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import Iterable, Optional

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,79}$")
PART_EXT = ".sldprt"
REFUSED_EXT = {".sldasm": "an assembly (this tool draws single parts)", ".slddrw": "a drawing, not a part", ".step": "a neutral file, not a native part",
               ".stp": "a neutral file, not a native part", ".stl": "a mesh, not a native part", ".prtdot": "a template, not a part"}
MIN_FREE_BYTES = 200 * 1024 * 1024
MAX_PART_BYTES = 2 * 1024 ** 3


class SafetyError(ValueError):
    """A request that must be refused; the message is safe to show the user."""


def new_job_id() -> str:
    return "r3d_" + secrets.token_hex(8)


def safe_id(raw: str, fallback: str = "part") -> str:
    """A filesystem- and URL-safe id from a file stem: unicode and spaces are kept readable but reduced to the safe alphabet."""
    s = re.sub(r"[^A-Za-z0-9_.\-]+", "_", (raw or "").strip()).strip("._-")
    s = s[:80] or fallback
    return s if ID_RE.match(s) else fallback


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def is_within(root: Path, p: Path) -> bool:
    try:
        rp = Path(os.path.realpath(p))
        rr = Path(os.path.realpath(root))
        rp.relative_to(rr)
        return True
    except (ValueError, OSError):
        return False


def has_symlink_component(root: Path, p: Path) -> bool:
    """True when any path component between root and p is a symlink / junction (an escape route)."""
    try:
        rel = Path(p).relative_to(root)
    except ValueError:
        return True
    cur = Path(root)
    for part in rel.parts:
        cur = cur / part
        try:
            if cur.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(cur)):
                return True
        except OSError:
            return True
    return False


def authorize(path: str | Path, roots: Iterable[Path]) -> Path:
    """Return the resolved path if it lies inside one of the authorized roots and crosses no symlink; else raise SafetyError."""
    raw = str(path)
    if "\x00" in raw:
        raise SafetyError("The path contains a NUL character.")
    p = Path(raw)
    if not p.is_absolute():
        raise SafetyError("Paths must be absolute.")
    rs = [Path(r) for r in roots]
    for r in rs:
        if is_within(r, p):
            real = Path(os.path.realpath(p))
            if has_symlink_component(Path(os.path.realpath(r)), real) or (p.exists() and p.is_symlink()):
                raise SafetyError("Symbolic links are not followed.")
            return real
    raise SafetyError("That location is not inside an authorized folder.")


def check_part_file(path: Path) -> dict:
    """Cheap, SOLIDWORKS-free checks. The real document type is confirmed again by the worker when it opens the file."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in REFUSED_EXT:
        raise SafetyError(f"{p.name} is {REFUSED_EXT[ext]}.")
    if ext != PART_EXT:
        raise SafetyError(f"{p.name} is not a SOLIDWORKS part (.SLDPRT).")
    if p.name.startswith("~$"):
        raise SafetyError(f"{p.name} is a SOLIDWORKS lock file, not a part.")
    if not p.is_file():
        raise SafetyError(f"{p.name} was not found.")
    size = p.stat().st_size
    if size == 0:
        raise SafetyError(f"{p.name} is empty.")
    if size > MAX_PART_BYTES:
        raise SafetyError(f"{p.name} is larger than {MAX_PART_BYTES // 1024 ** 3} GB.")
    return {"name": p.name, "size": size}


def dedupe_ids(paths: list[Path]) -> list[tuple[Path, str]]:
    """[(path, part_id)] where two files with the same base name get distinct ids (name, name-2, name-3 ...), in input order."""
    seen: dict[str, int] = {}
    out = []
    for p in paths:
        base = safe_id(p.stem)
        n = seen.get(base.lower(), 0) + 1
        seen[base.lower()] = n
        out.append((p, base if n == 1 else f"{base}-{n}"))
    return out


def discover_parts(folder: Path, recursive: bool = False) -> list[Path]:
    """SLDPRT files in a folder, case-insensitive extension, lock files skipped, deterministic order."""
    folder = Path(folder)
    it = folder.rglob("*") if recursive else folder.glob("*")
    return sorted((p for p in it if p.is_file() and p.suffix.lower() == PART_EXT and not p.name.startswith("~$")), key=lambda p: str(p).lower())


def writable_dir(path: Path) -> Optional[str]:
    """None when ``path`` can be created/written with enough free space; else a user-safe reason."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".w_{secrets.token_hex(4)}"
        probe.write_bytes(b"x")
        probe.unlink()
    except OSError as e:
        return f"The output folder is not writable ({type(e).__name__})."
    try:
        if shutil.disk_usage(p).free < MIN_FREE_BYTES:
            return "The output drive has less than 200 MB free."
    except OSError:
        pass
    return None
