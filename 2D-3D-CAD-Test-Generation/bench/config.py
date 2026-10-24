"""Where the confidential benchmark data lives. Nothing machine-specific is hard-coded:
the data root comes from MTI_BENCH_DATA (a real environment variable wins over .env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

CODE_ROOT = Path(__file__).resolve().parent.parent
DOTENV = CODE_ROOT / ".env"
DATA_ENV = "MTI_BENCH_DATA"
ODA_ENV = "ODA_CONVERTER"


class BenchConfigError(RuntimeError):
    """A required benchmark setting is missing or points nowhere."""


def _load_dotenv() -> None:
    from dotenv import load_dotenv
    load_dotenv(DOTENV, override=False)


def _setting(name: str, example: str, required: bool, want_dir: bool) -> Optional[Path]:
    _load_dotenv()
    raw = (os.getenv(name) or "").strip().strip('"').strip()
    if not raw:
        if not required:
            return None
        raise BenchConfigError(_message(name, "it is not set", example))
    path = Path(raw)
    if (path.is_dir() if want_dir else path.is_file()):
        return path
    kind = "folder" if want_dir else "file"
    raise BenchConfigError(_message(name, f"'{raw}' is not an existing {kind}", example))


def _message(name: str, problem: str, example: str) -> str:
    return (f"{name}: {problem}. Add a line like\n    {name}={example}\n"
            f"to {DOTENV} (git-ignored) or set it as an environment variable.")


def data_root(required: bool = True) -> Optional[Path]:
    return _setting(DATA_ENV, r"C:\path\to\MTI Example Drawings\bench", required, want_dir=True)


def part_dir(part: str) -> Path:
    return data_root() / part


def oda_converter(required: bool = True) -> Optional[Path]:
    return _setting(ODA_ENV, r"C:\Program Files\ODA\ODAFileConverter 26.x\ODAFileConverter.exe",
                    required, want_dir=False)
