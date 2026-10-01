"""Tests for the token/cost report (pipeline.token_report)."""
import csv
import json
import re

import pytest

from pipeline.token_report import (
    aggregate,
    filter_rows,
    load_rows,
    main,
    render_html,
    reprice,
    summary,
    write_csv,
)
from pipeline.token_tracker import Pricing


def _row(**kw):
    base = {
        "ts": "2026-10-01T12:00:00+00:00", "run_id": "r1", "role": "planner",
        "provider": "anthropic", "model": "claude-opus-5-5", "part": "A", "arm": "",
        "gate": None, "attempt": None, "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_write_tokens": 0, "latency_ms": 100.0,
        "cache_hit": False, "cost_usd": 0.0, "priced": True, "ok": True, "note": "", "extra": {},
    }
    base.update(kw)
    return base


@pytest.fixture
def rows():
    return [
        _row(part="A", role="extractor", model="claude-sonnet-4-6", input_tokens=1000, output_tokens=100, cost_usd=0.10),
        _row(part="A", role="planner", input_tokens=2000, output_tokens=500, cost_usd=0.50, gate=1, attempt=0),
        _row(part="A", role="planner", input_tokens=1500, output_tokens=400, cost_usd=0.40, gate=1, attempt=1),
        _row(part="A", role="auditor_reviewer", input_tokens=800, output_tokens=50, cost_usd=0.20, gate=1, attempt=0),
        _row(part="B", role="planner", provider="bedrock", model="gpt-6-astra", input_tokens=3000,
             output_tokens=300, cost_usd=None, priced=False, arm="astra-raw"),
        _row(part="B", role="extractor", model="claude-sonnet-4-6", cache_hit=True, cost_usd=0.0),
    ]


class TestAggregate:
    def test_by_role_sums_cost_tokens_and_counts(self, rows):
        by = {g["role"]: g for g in aggregate(rows, ("role",))}
        assert by["planner"]["completions"] == 3
        assert by["planner"]["cost_usd"] == pytest.approx(0.90)  # unpriced row not summed as 0...
        assert by["planner"]["unpriced"] == 1                    # ...it is counted instead
        assert by["planner"]["input_tokens"] == 6500
        assert by["extractor"]["cache_hits"] == 1

    def test_by_role_and_model(self, rows):
        groups = aggregate(rows, ("role", "model"))
        keys = {(g["role"], g["model"]) for g in groups}
        assert ("planner", "claude-opus-5-5") in keys and ("planner", "gpt-6-astra") in keys

    def test_sorted_by_cost_descending(self, rows):
        groups = aggregate(rows, ("role",))
        costs = [g["cost_usd"] for g in groups]
        assert costs == sorted(costs, reverse=True)

    def test_retry_cost_by_attempt(self, rows):
        planner = [r for r in rows if r["role"] == "planner" and r["attempt"] is not None]
        by = {g["attempt"]: g for g in aggregate(planner, ("attempt",))}
        assert by[1]["cost_usd"] == pytest.approx(0.40)


class TestSummary:
    def test_totals_and_cost_per_part(self, rows):
        s = summary(rows)
        assert s["completions"] == 6
        assert s["parts"] == 2
        assert s["cost_usd"] == pytest.approx(1.20)
        assert s["unpriced"] == 1
        assert s["cost_per_part"] == pytest.approx(0.60)
        assert s["total_tokens"] == 1100 + 2500 + 1900 + 850 + 3300

    def test_empty(self):
        s = summary([])
        assert s["completions"] == 0 and s["cost_per_part"] == 0.0


class TestFilterAndReprice:
    def test_filters(self, rows):
        assert {r["part"] for r in filter_rows(rows, part="B")} == {"B"}
        assert {r["role"] for r in filter_rows(rows, role="planner")} == {"planner"}
        assert len(filter_rows(rows, arm="astra-raw")) == 1
        assert filter_rows(rows, since="2026-10-02") == []

    def test_reprice_fills_newly_known_prices(self, rows):
        p = Pricing({"providers": {"bedrock": {"gpt-6-astra": {
            "input": 10.0, "output": 50.0, "cache_write": None, "cache_read": None}}}})
        out = reprice(rows, p)
        astra = next(r for r in out if r["model"] == "gpt-6-astra")
        assert astra["priced"] is True
        assert astra["cost_usd"] == pytest.approx(3000 / 1e6 * 10 + 300 / 1e6 * 50)
        cache = next(r for r in out if r["cache_hit"])
        assert cache["cost_usd"] == 0.0


class TestIO:
    def test_load_rows_from_output_dir_and_skips_bad_lines(self, tmp_path, rows):
        ledger = tmp_path / "usage" / "usage_ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("\n".join(json.dumps(r) for r in rows[:2]) + "\nnot json\n", encoding="utf-8")
        assert len(load_rows([tmp_path])) == 2
        assert len(load_rows([ledger])) == 2

    def test_csv_roundtrip(self, tmp_path, rows):
        path = write_csv(rows, tmp_path / "u.csv")
        with path.open(encoding="utf-8") as f:
            back = list(csv.DictReader(f))
        assert len(back) == len(rows)
        assert back[0]["role"] == "extractor"


class TestHtml:
    def test_contains_totals_roles_and_no_remote_assets(self, rows):
        html = render_html(rows, title="Test report")
        assert "Test report" in html
        for role in ("planner", "extractor", "auditor_reviewer"):
            assert role in html
        assert "$1.20" in html
        assert not re.search(r'(src|href)\s*=\s*["\']https?://', html)

    def test_escapes_part_names(self):
        html = render_html([_row(part="<script>x</script>", cost_usd=0.01, input_tokens=1)])
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html

    def test_empty_ledger_renders(self):
        assert "No completions recorded" in render_html([])


class TestCli:
    def test_empty_dir_exits_zero_with_message(self, tmp_path, capsys):
        assert main([str(tmp_path)]) == 0
        assert "No completions" in capsys.readouterr().out

    def test_writes_html_and_csv(self, tmp_path, rows):
        ledger = tmp_path / "usage" / "usage_ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        html, csvp = tmp_path / "r.html", tmp_path / "r.csv"
        assert main([str(tmp_path), "--html", str(html), "--csv", str(csvp)]) == 0
        assert html.exists() and csvp.exists()


def test_all_unpriced_group_says_unpriced_not_zero(rows):
    from pipeline.token_report import group_cost
    g = next(g for g in aggregate(rows, ("provider",)) if g["provider"] == "bedrock")
    assert group_cost(g) == "unpriced"
