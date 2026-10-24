"""bench.config: data root / ODA path from env or .env, never hard-coded."""
import pytest

from bench import config


def test_env_var_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    assert config.data_root() == tmp_path


def test_missing_root_raises_with_instructions(monkeypatch, tmp_path):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path / "nope"))
    with pytest.raises(config.BenchConfigError) as e:
        config.data_root()
    msg = str(e.value)
    assert "MTI_BENCH_DATA" in msg and ".env" in msg


def test_optional_returns_none(monkeypatch):
    monkeypatch.delenv("MTI_BENCH_DATA", raising=False)
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)
    assert config.data_root(required=False) is None


def test_dotenv_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("MTI_BENCH_DATA", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"MTI_BENCH_DATA={tmp_path}\n", encoding="utf-8")
    monkeypatch.setattr(config, "DOTENV", env)
    assert config.data_root() == tmp_path


def test_part_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    assert config.part_dir("A050071E") == tmp_path / "A050071E"


def test_oda_converter(tmp_path, monkeypatch):
    exe = tmp_path / "ODAFileConverter.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("ODA_CONVERTER", str(exe))
    assert config.oda_converter() == exe
    monkeypatch.setenv("ODA_CONVERTER", str(tmp_path / "missing.exe"))
    with pytest.raises(config.BenchConfigError, match="ODA_CONVERTER"):
        config.oda_converter()
