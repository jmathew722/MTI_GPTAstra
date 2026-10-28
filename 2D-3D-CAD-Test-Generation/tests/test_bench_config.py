"""bench.config: data root / ODA path from env or .env, never hard-coded."""
import pytest

from bench import config


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Never read the real .env; clean anything load_dotenv writes into os.environ."""
    for name in ("MTI_BENCH_DATA", "ODA_CONVERTER"):
        monkeypatch.setenv(name, "placeholder")  # register for teardown restore
        monkeypatch.delenv(name)
    monkeypatch.setattr(config, "DOTENV", tmp_path / "absent.env")


def test_env_var_beats_dotenv(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    env = tmp_path / ".env"
    env.write_text(f"MTI_BENCH_DATA={other}\n", encoding="utf-8")
    monkeypatch.setattr(config, "DOTENV", env)
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path))
    assert config.data_root() == tmp_path


def test_missing_root_raises_with_instructions(monkeypatch, tmp_path):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path / "nope"))
    with pytest.raises(config.BenchConfigError) as e:
        config.data_root()
    msg = str(e.value)
    assert "MTI_BENCH_DATA" in msg and ".env" in msg


def test_optional_returns_none(monkeypatch):
    assert config.data_root(required=False) is None


def test_dotenv_is_read(tmp_path, monkeypatch):
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


def test_set_but_missing_raises_even_when_optional(tmp_path, monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", str(tmp_path / "typo"))
    with pytest.raises(config.BenchConfigError, match="MTI_BENCH_DATA"):
        config.data_root(required=False)


def test_empty_value_is_unset(monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", "")
    assert config.data_root(required=False) is None


def test_quoted_value_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("MTI_BENCH_DATA", f'  "{tmp_path}"  ')
    assert config.data_root() == tmp_path


def test_oda_optional_returns_none_when_unset():
    assert config.oda_converter(required=False) is None


def test_file_where_dir_expected_raises(tmp_path, monkeypatch):
    f = tmp_path / "afile"
    f.write_text("x")
    monkeypatch.setenv("MTI_BENCH_DATA", str(f))
    with pytest.raises(config.BenchConfigError, match="MTI_BENCH_DATA"):
        config.data_root(required=False)
