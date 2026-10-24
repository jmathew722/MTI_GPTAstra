"""bench.split: the format-dev pick reproduces from the recorded seed; manifest agrees."""
from pathlib import Path

import yaml

from bench.split import CLEAN, PARKED, SEED, choose_format_dev, mti_entries

M = yaml.safe_load((Path(__file__).resolve().parent.parent / "bench" / "manifest.yaml").read_text(encoding="utf-8"))


def test_seeded_pick():
    assert choose_format_dev() == ["A050291E", "A050381E", "A050511E"]
    assert SEED == 20261023


def test_near_duplicates_never_dev():
    assert not {"A050471E", "A050481E"} & set(choose_format_dev())


def test_14_clean_7_parked():
    assert len(CLEAN) == 14 and len(PARKED) == 7
    assert not {p.part for p in CLEAN} & {p.part for p in PARKED}


def test_manifest_matches_split():
    mti = mti_entries(M)
    dev = {e["part"] for e in mti["dev"]}
    held = {e["part"] for e in mti["held_out"]}
    parked = {e["part"] for e in M["splits"]["parked"]}
    assert dev == set(choose_format_dev())
    assert held == {p.part for p in CLEAN} - dev
    assert parked == {p.part for p in PARKED}
    assert all(e["reason"] for e in M["splits"]["parked"])
    assert M["mti_bench"]["seed"] == SEED
