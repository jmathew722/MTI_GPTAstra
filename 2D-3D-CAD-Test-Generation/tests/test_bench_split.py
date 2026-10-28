"""bench.split: the format-dev pick reproduces from the recorded seed; manifest agrees."""
from pathlib import Path

import pytest
import yaml

from bench.split import (CLEAN, PARKED, READMITTED, READMITTED_DEV, READMITTED_HELD, SEED, SWAP_SEED,
                         bench_parts, choose_format_dev, format_dev, mti_entries, pair, swap_pick)

M = yaml.safe_load((Path(__file__).resolve().parent.parent / "bench" / "manifest.yaml").read_text(encoding="utf-8"))


def test_seeded_pick():
    assert choose_format_dev() == ["A050291E", "A050381E", "A050511E"]
    assert SEED == 20261023


def test_near_duplicates_never_dev():
    assert not {"A050471E", "A050481E"} & set(format_dev())


def test_seeded_swap_brings_a_round_part_into_dev():
    assert SWAP_SEED == 20261024
    assert swap_pick() == ("A050311E", "A050291E")
    assert format_dev() == ["A050311E", "A050381E", "A050381M", "A050511E"]


def test_12_clean_7_readmitted_2_parked():
    # 2026-10-24: 1801901E (4 solids) and 1807408E (model differs from drawing) parked; the 3 metric
    # twins and 4 OBSOLETE sheets re-admitted under the drawing-is-ground-truth policy
    assert len(CLEAN) == 12 and len(READMITTED) == 7 and len(PARKED) == 2
    groups = [{p.part for p in g} for g in (CLEAN, READMITTED, PARKED)]
    assert not (groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])


def test_twins_share_a_split_with_their_inch_partner():
    pick = set(format_dev())
    for twin, partner in (("A050381M", "A050381E"), ("A050031M", "A050031E"), ("A050081M", "A050081E_OLD")):
        in_dev = twin in {p.part for p in READMITTED_DEV}
        assert in_dev == (partner in pick), twin


def test_manifest_matches_split():
    mti = mti_entries(M)
    dev = {e["part"] for e in mti["dev"]}
    held = {e["part"] for e in mti["held_out"]}
    parked = {e["part"] for e in M["splits"]["parked"]}
    assert dev == set(format_dev())
    every = {p.part for p in CLEAN} | {p.part for p in READMITTED}
    assert held == every - dev
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
    assert complex_held == {"1901001E"}
    assert {e["part"] for e in mti["dev"]} .isdisjoint(complex_held)
    assert not {e["part"] for e in mti["held_out"] + mti["dev"] if e.get("pairing") == "provisional"}


def test_parked_reasons_match_split_py():
    by_part = {e["part"]: e["reason"] for e in M["splits"]["parked"]}
    assert by_part == {p.part: p.reason for p in PARKED}


def test_bench_parts_19_unique():
    parts = bench_parts(M)
    assert len(parts) == 19 and len(set(parts)) == 19


def test_pair_unknown_part_raises_keyerror():
    with pytest.raises(KeyError):
        pair("NOPE")
