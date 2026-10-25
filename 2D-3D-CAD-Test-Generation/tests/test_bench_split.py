"""bench.split: the format-dev pick reproduces from the recorded seed; manifest agrees."""
from pathlib import Path

import pytest
import yaml

from bench.split import CLEAN, PARKED, SEED, bench_parts, choose_format_dev, mti_entries, pair

M = yaml.safe_load((Path(__file__).resolve().parent.parent / "bench" / "manifest.yaml").read_text(encoding="utf-8"))


def test_seeded_pick():
    assert choose_format_dev() == ["A050291E", "A050381E", "A050511E"]
    assert SEED == 20261023


def test_near_duplicates_never_dev():
    assert not {"A050471E", "A050481E"} & set(choose_format_dev())


def test_13_clean_8_parked():
    # 1801901E parked 2026-10-25: its MTI model is 4 solids (cannot be keyed as one part)
    assert len(CLEAN) == 13 and len(PARKED) == 8
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


def test_manifest_entries_agree_with_clean_per_part():
    mti = mti_entries(M)
    for e in mti["dev"] + mti["held_out"]:
        p = pair(e["part"])
        assert e["complexity"] == p.complexity
        assert e["units"] == "inch"
        assert e["family"] == p.family.split("; PROVISIONAL")[0], e["part"]
    complex_held = {e["part"] for e in mti["held_out"] if e["complexity"] == "complex"}
    assert complex_held == {"1807408E", "1901001E"}
    assert {e["part"] for e in mti["dev"]} .isdisjoint(complex_held)
    assert {e["part"] for e in mti["held_out"] + mti["dev"] if e.get("pairing") == "provisional"} == {"1807408E"}


def test_parked_reasons_match_split_py():
    by_part = {e["part"]: e["reason"] for e in M["splits"]["parked"]}
    assert by_part == {p.part: p.reason for p in PARKED}


def test_bench_parts_13_unique():
    parts = bench_parts(M)
    assert len(parts) == 13 and len(set(parts)) == 13


def test_pair_unknown_part_raises_keyerror():
    with pytest.raises(KeyError):
        pair("NOPE")
