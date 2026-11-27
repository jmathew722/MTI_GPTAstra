"""v8: cost and runtime additions for the 2D -> 3D workspace (server/app.py, server/estimates.py): a median "expected" next to the low/high band, the model
and rate date of the estimate, and a V8-shaped usage summary of the last run built from the ledger. Pure functions plus the two routes; no model call is made."""
import json
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pythoncom")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[3] / "2D-3D-CAD-Test-Generation"
_TMP = tempfile.mkdtemp(prefix="mcagent_v8w_")
os.environ.setdefault("MCAGENT_REPO", str(REPO))
os.environ.setdefault("MCAGENT_DATA", os.path.join(_TMP, "data"))
os.environ.setdefault("MCAGENT_FINAL_OUTPUTS", os.path.join(_TMP, "final"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
import app as appmod  # noqa: E402
import estimates as est  # noqa: E402

client = TestClient(appmod.app)


def row(role="extractor", model="gpt-6-astra", provider="openai", inp=1000, out=200, cached=0, cost="0.0043", priced=True, hit=False, attempt=0, ts="2026-11-27T10:00:00+00:00", run="r1"):
    return {"role": role, "model": model, "provider": provider, "input_tokens": inp, "output_tokens": out, "cache_read_tokens": cached, "cost_usd": cost, "priced": priced,
            "cache_hit": hit, "attempt": attempt, "ts": ts, "run_id": run, "run_attempt": 1}


def test_estimate_has_a_median_expected_next_to_the_band_and_unknown_stays_unknown():
    e = est.estimate(2, [10.0, 20.0, 30.0], [Decimal("0.10"), Decimal("0.20"), Decimal("0.60")])
    assert e["time"]["expected"] == 40.0 and e["time"]["low"] <= e["time"]["expected"] <= e["time"]["high"]          # median 20 s x 2 parts
    assert Decimal(e["cost"]["expected"]) == Decimal("0.4000") and Decimal(e["cost"]["low"]) <= Decimal(e["cost"]["expected"]) <= Decimal(e["cost"]["high"])
    none = est.estimate(2, [], [])
    assert none["time"]["available"] is False and "expected" not in none["time"] and none["cost"]["available"] is False and "expected" not in none["cost"]


def test_rate_info_comes_from_the_latest_row_and_pricing_file_and_is_none_when_unknown():
    assert appmod._rate_info([]) == {"model": None, "rate_version": None}
    info = appmod._rate_info([row(ts="2026-11-01T00:00:00+00:00", model="old-model"), row(ts="2026-11-27T00:00:00+00:00")])
    assert info["model"] == "gpt-6-astra" and info["rate_version"] == "2026-11-27"
    assert appmod._rate_info([row(model="no-such-model")])["rate_version"] is None                               # a model without a price entry has no rate date


def test_usage_priced_partial_unpriced_cached_and_retries():
    u = appmod._usage_of([row(role="extractor", inp=30000, out=4000, cached=1000, cost="0.003"), row(role="planner", inp=8000, out=900, cost="0.0008"), row(role="planner", attempt=2, cost="0.0005")])
    assert u["calls"] == 3 and u["cost_status"] == "priced" and u["cost_usd"] == pytest.approx(0.0043) and u["cached_tokens"] == 1000 and u["input_tokens"] == 38000 + 1000
    assert u["by_stage"]["planner"]["attempts"] == 3 and u["by_stage"]["extractor"]["cost_usd"] == pytest.approx(0.003) and u["model"] == "gpt-6-astra"
    p = appmod._usage_of([row(cost="0.01"), row(cost=None, priced=False)])
    assert p["cost_status"] == "partial" and p["cost_usd"] == pytest.approx(0.01) and p["unpriced_calls"] == 1
    n = appmod._usage_of([row(cost=None, priced=False), row(cost=None, priced=False)])
    assert n["cost_status"] == "unpriced" and n["cost_usd"] is None                                              # never $0
    c = appmod._usage_of([row(hit=True, cost="0")])
    assert c["calls"] == 0 and c["cache_hits"] == 1 and c["cost_status"] == "none"
    assert appmod._usage_of([])["cost_status"] == "none"


def test_estimate_route_carries_model_and_rate_version_keys():
    r = client.get("/api/estimate")
    assert r.status_code == 200
    j = r.json()
    assert "model" in j and "rate_version" in j and set(j["time"]) >= {"available"}
