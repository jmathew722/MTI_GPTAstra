"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def _no_local_mti_standard(monkeypatch, tmp_path):
    """Tests never read the machine's confidential MTI table (config/mti/*.local.json):
    results must not depend on whether this machine has it. MTI-table tests point
    MTI_STANDARD_PATH at a synthetic fixture instead."""
    monkeypatch.setenv("MTI_STANDARD_PATH", str(tmp_path / "no-mti-standard.json"))
