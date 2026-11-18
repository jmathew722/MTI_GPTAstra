"""Server cost summary from the pipeline ledger (Stage 2, task 2.3 data layer)."""
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import costs as C  # noqa: E402


def row(part="P1", run="r1", att=1, cost=1.0, priced=True, inp=1000, out=100, cr=0, model="m", rid=None, ts="2026-11-18T00:00:00+00:00", **kw):
    r = {"ts": ts, "run_id": run, "role": "planner", "provider": "p", "model": model, "part": part, "gate": None,
         "attempt": 1, "input_tokens": inp, "output_tokens": out, "cache_read_tokens": cr, "cache_write_tokens": 0,
         "cache_hit": False, "cost_usd": cost if priced else None, "priced": priced, "ok": True, "note": ""}
    if rid:
        r["row_id"] = rid
    if att is not None:
        r["run_attempt"] = att
    r.update(kw)
    return r


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_finds_the_shared_ledger_next_to_the_part_folder(tmp_path):
    part = tmp_path / "P1"
    part.mkdir()
    write(tmp_path / "usage" / "usage_ledger.jsonl", [row(part="P1", rid="a"), row(part="OTHER", rid="b")])
    paths = C.ledger_paths(part)
    assert [p.name for p in paths] == ["usage_ledger.jsonl"]
    rows = C.read_rows(paths)
    assert len(rows) == 2     # reading is unfiltered; summarize() filters to the part


def test_scopes_reconcile_and_attempts_group_without_losing_part_total():
    rows = [row(run="r1", att=1, cost=1.5, rid="1"), row(run="r1", att=1, cost=0.25, rid="2"),
            row(run="r2", att=2, cost=2.0, rid="3", ts="2026-11-18T01:00:00+00:00"), row(part="OTHER", cost=9, rid="4")]
    s = C.summarize(rows, part="P1")
    assert Decimal(s["scopes"]["run"]["cost_usd"]) == Decimal("2.0") and s["scopes"]["run"]["run_id"] == "r2"
    assert Decimal(s["scopes"]["part"]["cost_usd"]) == Decimal("3.75")
    assert [a["run_attempt"] for a in s["attempts"]] == [1, 2]
    assert sum(Decimal(a["cost_usd"]) for a in s["attempts"]) == Decimal("3.75")
    assert [len(a["rows"]) for a in s["attempts"]] == [2, 1]
    assert s["scopes"]["part"]["api_calls"] == 3


def test_unpriced_is_never_zero_and_partial_is_labeled():
    s = C.summarize([row(priced=False, rid="1")], part="P1")
    assert s["scopes"]["part"]["cost_usd"] is None and s["scopes"]["part"]["pricing_status"] == "unpriced"
    s2 = C.summarize([row(cost=1.0, rid="1"), row(priced=False, rid="2")], part="P1")
    assert s2["scopes"]["part"]["pricing_status"] == "partial" and Decimal(s2["scopes"]["part"]["cost_usd"]) == Decimal("1.0")
    assert s2["scopes"]["part"]["unpriced_calls"] == 1


def test_priced_zero_is_zero_only_when_the_backend_says_so():
    s = C.summarize([row(cost=0.0, rid="1", inp=0, out=0)], part="P1")
    assert s["scopes"]["part"]["cost_usd"] == "0" and s["scopes"]["part"]["pricing_status"] == "priced"


def test_legacy_rows_without_run_attempt_are_labeled_and_duplicates_dropped():
    rows = [row(att=None, rid=None, run="old"), row(att=None, rid=None, run="old", cost=2.0), row(rid="x"), row(rid="x")]
    s = C.summarize(C.dedupe(rows), part="P1")
    assert s["legacy_rows"] == 2 and s["scopes"]["part"]["api_calls"] == 3
    assert any(a["run_attempt"] is None and a["label"] == "legacy" for a in s["attempts"])


def test_cache_tokens_models_and_normalized_row_fields_survive():
    s = C.summarize([row(cr=5000, model="a-very-long-model-name-" + "x" * 80, rid="1")], part="P1")
    r = s["attempts"][0]["rows"][0]
    assert r["cache_read_tokens"] == 5000 and r["calls"] == 1 and r["stage"] == "planner"
    assert s["scopes"]["part"]["cached_input_tokens"] == 5000
    assert set(r) >= {"row_id", "ts", "run_id", "run_attempt", "stage", "role", "provider", "model", "calls", "input_tokens",
                      "cache_read_tokens", "cache_write_tokens", "output_tokens", "cost_usd", "pricing_status", "cache_hit", "ok", "gate", "plan_attempt"}


def test_payload_is_bounded_but_totals_cover_every_row():
    rows = [row(cost=0.01, rid=str(i)) for i in range(2500)]
    s = C.summarize(rows, part="P1", max_rows=2000)
    assert s["truncated"] is True and s["total_rows"] == 2500
    assert sum(len(a["rows"]) for a in s["attempts"]) == 2000
    assert Decimal(s["scopes"]["part"]["cost_usd"]) == Decimal("25.00")      # totals use all rows


def test_empty_ledger():
    s = C.summarize([], part="P1")
    assert s["present"] is False and s["attempts"] == [] and s["scopes"]["part"]["pricing_status"] == "priced"
    assert s["scopes"]["part"]["api_calls"] == 0
