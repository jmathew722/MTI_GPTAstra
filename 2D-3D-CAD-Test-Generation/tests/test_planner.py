"""IR v2 Task 7: planner loop (mocked model, no API) + dev-set scorer."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pipeline import budget
from pipeline.ir.model import BuildPlan
from pipeline.planner import TOOL_NAME, OpenAIPlanner, Planner, pinned
from pipeline.schema import DrawingData

GOLD = Path(__file__).parent / "golden" / "ir"
DEMO = Path(__file__).resolve().parent.parent / "demo" / "simple_plate"


def golden(name):
    g = json.loads((GOLD / f"{name}.json").read_text(encoding="utf-8"))
    return g["plan"], {k: float(v) for k, v in g["dims"].items()}


def demo_drawing():
    return DrawingData.model_validate(json.loads((DEMO / "extraction_no_api.json").read_text(encoding="utf-8")))


class Scripted(Planner):
    """A planner whose 'model' replays scripted tool inputs (one per call)."""
    provider = "openai"

    def __init__(self, inputs):
        super().__init__(model="scripted")
        self.inputs, self.seen = list(inputs), []

    def _complete(self, system, messages):
        self.seen.append(messages)
        nxt = self.inputs.pop(0)
        if nxt is None:
            return NS(content=[NS(type="text", text="thinking out loud")], stop_reason="end_turn", usage=None)
        return NS(content=[NS(type="tool_use", id=f"t{len(self.seen)}", name=TOOL_NAME, input=nxt)],
                  stop_reason="tool_use", usage=None)


def test_models_are_pinned_in_config():
    assert pinned("openai")[0] == "gpt-6-astra"


def test_good_plan_first_try():
    plan, dims = golden("demo_plate")
    p = Scripted([plan])
    r = p.plan(demo_drawing(), [("FULL SHEET", "QQ==")], dims)
    assert r.plan is not None and r.attempts == 1 and r.error == ""


def test_gate1_findings_go_back_and_get_fixed():
    plan, dims = golden("demo_plate")
    bad = json.loads(json.dumps(plan))
    bad["features"][0]["depth"] = "D003 + 0.5"           # invented length, no justification
    p = Scripted([bad, plan])
    r = p.plan(demo_drawing(), [("FULL SHEET", "QQ==")], dims)
    assert r.attempts == 2 and r.error == ""
    feedback = p.seen[1][-1]["content"][0]
    assert feedback["type"] == "tool_result" and "ungrounded_literal" in feedback["content"]


def test_no_tool_call_and_schema_errors_are_repaired_then_give_up():
    plan, dims = golden("demo_plate")
    p = Scripted([None, {"part": "x"}, {"part": "x"}])
    r = p.plan(demo_drawing(), [("FULL SHEET", "QQ==")], dims)
    assert r.plan is None and r.attempts == 3 and r.error == "schema"


def test_unresolved_is_accepted_not_repaired():
    plan, dims = golden("A040921E")                       # F003 is unresolved on purpose
    p = Scripted([plan])
    r = p.plan(demo_drawing(), [("FULL SHEET", "QQ==")], dims)
    assert r.attempts == 1 and any(f.code == "unresolved" for f in r.findings)


def test_budget_guard_runs_before_a_real_call(tmp_path, monkeypatch):
    monkeypatch.setenv("API_BUDGET_LEDGER", str(tmp_path / "l.jsonl"))
    monkeypatch.setenv("API_BUDGET_USD", "0.01")
    called = []
    client = NS(messages=NS(create=lambda **k: called.append(k)))
    plan, dims = golden("demo_plate")
    with pytest.raises(budget.BudgetExceeded):
        OpenAIPlanner(client=client).plan(demo_drawing(), [("FULL SHEET", "QQ==")], dims)
    assert called == []


# --- scorer ------------------------------------------------------------------ #
cq = pytest.importorskip("cadquery")


def test_golden_scores_perfect_against_itself():
    from pipeline.ir.score import score
    plan, dims = golden("SB11033")
    p = BuildPlan.model_validate(plan)
    s = score(p, dims, p, dims)
    assert s["iou"] == pytest.approx(1.0, abs=1e-4) and s["holes_missing"] == 0 and s["volume_err"] == 0


def test_flipped_frame_still_aligns():
    from pipeline.ir.score import score
    plan, dims = golden("A040921E")
    flipped = json.loads(json.dumps(plan))
    flipped["features"][1]["on"] = "face(F001,+Z)"        # slot cut from the other end
    s = score(BuildPlan.model_validate(flipped), dims, BuildPlan.model_validate(plan), dims)
    assert s["iou"] == pytest.approx(1.0, abs=1e-3)


def test_misplaced_and_missing_holes_are_penalized():
    from pipeline.ir.score import score
    plan, dims = golden("demo_plate")
    worse = json.loads(json.dumps(plan))
    worse["features"] = [f for f in worse["features"] if f["id"] not in ("F003",)]   # drop the grid
    worse["features"][1]["u"] = "D010"                                              # seed moved to x=50
    s = score(BuildPlan.model_validate(worse), dims, BuildPlan.model_validate(plan), dims)
    assert s["iou"] < 0.999 and s["holes_missing"] == 3
