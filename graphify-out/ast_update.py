"""Incremental AST refresh of the graphify knowledge graph (no LLM, no network).

The full graph was built with the /graphify skill (semantic extraction with Claude).
When that skill isn't available, this script keeps the CODE layer current:

* every .py file whose content hash differs from manifest.json (or is new) is
  re-parsed with Python's ``ast``. Its old AST nodes/edges are dropped and rebuilt
  (module, classes, functions, methods; contains / method / imports / calls edges),
  following graphify's own id and label conventions;
* semantic nodes/edges (rationale, concepts, images, documents) are left untouched,
  except dangling links to code that no longer exists are pruned;
* new files get a community chosen by path (see COMMUNITY_RULES);
* graph.json, graph.html (RAW_NODES / RAW_EDGES / LEGEND), manifest.json and
  .graphify_labels.json are rewritten; ``built_at_commit`` gets the current HEAD.

Every node/edge it adds carries ``"_update": "ast-YYYY-MM-DD"``, so a later full
``/graphify . --update`` can tell them apart. Run from the repo root:

    python graphify-out/ast_update.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "graphify-out"
CODE = "2D-3D-CAD-Test-Generation"
SKIP = ("/output/", "/.venv/", "/__pycache__/", "/usage/")
STAMP = f"ast-{date.today().isoformat()}"
PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7",
           "#9C755F", "#BAB0AC"]
# (path regex, community name) for files the semantic build never saw
COMMUNITY_RULES = [
    (r"/pipeline/ir/|/ir_[a-z]+\.py$|/tests/test_ir_|/pipeline/ir_pipeline\.py$", "Feature IR v2 (plans, compilers)"),
    (r"/pipeline/planner\.py$|/tests/test_planner\.py$", "GPT-6 Astra Planner"),
    (r"/pipeline/budget\.py$|/tests/test_budget\.py$", "API Budget Guard ($20 cap)"),
    (r"/pipeline/token_(tracker|report)\.py$|/tests/test_token_", "Token Cost Ledger"),
    (r"/pipeline/openai_adapter\.py$", "Claude Vision Extractor"),
    (r"/pipeline/fasteners\.py$|/tests/test_root_cause_fixes\.py$|/tests/test_placement\.py$|/rebuild_from_json\.py$",
     "Placement & Root-Cause Fixes"),
    (r"/tests/test_model_validator\.py$", "Post-Build Model Validator"),
    (r"/demo/", "Demo Plate (known answer)"),
    (r"/tests/test_bench_manifest\.py$", "Benchmark Split"),
    (r"/graphify-out/", "Graph Tooling"),
]


def slug(rel: str) -> str:
    s = rel[:-3] if rel.endswith(".py") else rel
    s = s.replace("__init__", "init")
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def module_label(rel: str) -> str:
    p = Path(rel)
    return f"{p.parent.name}/__init__.py" if p.name == "__init__.py" else p.name


def resolve_module(mod: str, rel: str) -> str | None:
    """'pipeline.ir.model' -> repo-relative path, if it is a repo module."""
    base = ROOT / CODE
    cand = base / Path(*mod.split("."))
    for p in (cand.with_suffix(".py"), cand / "__init__.py"):
        if p.exists():
            return p.relative_to(ROOT).as_posix()
    return None


def extract(rel: str) -> tuple[list[dict], list[dict]]:
    src = (ROOT / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mid = slug(rel)
    nodes = [{"id": mid, "label": module_label(rel), "_origin": "ast", "file_type": "code",
              "norm_label": module_label(rel).lower(), "source_file": rel, "source_location": "L1"}]
    edges: list[dict] = []
    local: dict[str, str] = {}

    def edge(s, t, rel_, line, ctx=None):
        e = {"source": s, "target": t, "relation": rel_, "_origin": "ast", "confidence": "EXTRACTED",
             "confidence_score": 1.0, "source_file": rel, "source_location": f"L{line}", "weight": 1.0}
        if ctx:
            e["context"] = ctx
        edges.append(e)

    def add_fn(fn, owner_id, method_of=None):
        nid = f"{owner_id}_{fn.name.lower()}"
        label = f".{fn.name}()" if method_of else f"{fn.name}()"
        nodes.append({"id": nid, "label": label, "_callable": True, "_origin": "ast", "file_type": "code",
                      "norm_label": label.lower(), "source_file": rel, "source_location": f"L{fn.lineno}"})
        edge(owner_id, nid, "method" if method_of else "contains", fn.lineno)
        return nid

    bodies: list[tuple[str, ast.AST]] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nid = add_fn(item, mid)
            local[item.name] = nid
            bodies.append((nid, item))
        elif isinstance(item, ast.ClassDef):
            cid = f"{mid}_{item.name.lower()}"
            nodes.append({"id": cid, "label": item.name, "_callable": True, "_callable_class": True,
                          "_origin": "ast", "file_type": "code", "norm_label": item.name.lower(),
                          "source_file": rel, "source_location": f"L{item.lineno}"})
            edge(mid, cid, "contains", item.lineno)
            local[item.name] = cid
            for sub in item.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    bodies.append((add_fn(sub, cid, method_of=cid), sub))
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            target = resolve_module(node.module, rel)
            if target:
                tmid = slug(target)
                for a in node.names:
                    tid = f"{tmid}_{a.name.lower()}"
                    imported[a.asname or a.name] = tid
                    edge(mid, tid, "imports", node.lineno, "import")
    for nid, fn in bodies:
        seen = set()
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name):
                tid = local.get(c.func.id) or imported.get(c.func.id)
                if tid and tid != nid and tid not in seen:
                    seen.add(tid)
                    edge(nid, tid, "calls", c.lineno, "call")
    for n in nodes:
        n["_update"] = STAMP
    for e in edges:
        e["_update"] = STAMP
    return nodes, edges


def main() -> int:
    graph = json.loads((OUT / "graph.json").read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    labels = json.loads((OUT / ".graphify_labels.json").read_text(encoding="utf-8"))
    files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / CODE).rglob("*.py")
                   if not any(s in "/" + p.relative_to(ROOT).as_posix() for s in SKIP))
    files.append("graphify-out/ast_update.py")
    changed = [f for f in files if manifest.get(f, {}).get("ast_hash") != md5(ROOT / f)]
    gone = [f for f in manifest if f.endswith(".py") and f.startswith(CODE) and not (ROOT / f).exists()]

    old_comm: dict[str, Counter] = defaultdict(Counter)
    for n in graph["nodes"]:
        if n.get("source_file") in changed and n.get("community") is not None:
            old_comm[n["source_file"]][(n["community"], n.get("community_name", ""))] += 1
    drop_files = set(changed) | set(gone)
    graph["nodes"] = [n for n in graph["nodes"]
                      if not (n.get("source_file") in drop_files and n.get("_origin") == "ast")]
    graph["links"] = [e for e in graph["links"]
                      if not (e.get("source_file") in drop_files and e.get("_origin") == "ast")]

    name_to_cid = {v: int(k) for k, v in labels.items()}
    next_cid = max(name_to_cid.values(), default=-1) + 1

    def community_for(rel: str) -> tuple[int, str]:
        nonlocal next_cid
        if old_comm.get(rel):
            return old_comm[rel].most_common(1)[0][0]
        for rx, name in COMMUNITY_RULES:
            if re.search(rx, "/" + rel):
                if name not in name_to_cid:
                    name_to_cid[name] = next_cid
                    labels[str(next_cid)] = name
                    next_cid += 1
                return name_to_cid[name], name
        return 13, labels.get("13", "CLI Entry Point")

    have = {n["id"] for n in graph["nodes"]}
    new_edges = []
    for rel in changed:
        ns, es = extract(rel)
        cid, cname = community_for(rel)
        for n in ns:
            n["community"], n["community_name"] = cid, cname
            if n["id"] not in have:
                graph["nodes"].append(n)
                have.add(n["id"])
        new_edges += es
        manifest[rel] = {"mtime": (ROOT / rel).stat().st_mtime, "seen": time.time(),
                         "ast_hash": md5(ROOT / rel), "semantic_hash": manifest.get(rel, {}).get("semantic_hash", "")}
    for f in gone:
        manifest.pop(f, None)
    graph["links"] += [e for e in new_edges if e["source"] in have and e["target"] in have]
    graph["links"] = [e for e in graph["links"] if e["source"] in have and e["target"] in have]
    graph["built_at_commit"] = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                              capture_output=True, text=True).stdout.strip()

    (OUT / "graph.json").write_text(json.dumps(graph, indent=1), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / ".graphify_labels.json").write_text(json.dumps(labels), encoding="utf-8")

    # graph.html: regenerate the three embedded data lines
    deg = Counter()
    for e in graph["links"]:
        deg[e["source"]] += 1
        deg[e["target"]] += 1
    color = {}
    html = (OUT / "graph.html").read_text(encoding="utf-8").split("\n")
    raw_nodes = json.loads(next(l for l in html if l.startswith("const RAW_NODES = "))[len("const RAW_NODES = "):-1])
    for n in raw_nodes:
        color.setdefault(n.get("community"), n["color"]["background"])
    rn = []
    for n in graph["nodes"]:
        c = n.get("community", 0)
        col = color.setdefault(c, PALETTE[c % len(PALETTE)])
        d = deg[n["id"]]
        rn.append({"id": n["id"], "label": n["label"],
                   "color": {"background": col, "border": col, "highlight": {"background": "#ffffff", "border": col}},
                   "size": round(10 + min(d, 60) * 0.5, 1), "font": {"size": 12, "color": "#ffffff"},
                   "title": n["label"], "community": c, "community_name": n.get("community_name", ""),
                   "source_file": n.get("source_file", ""), "file_type": n.get("file_type", ""), "degree": d})
    re_ = [{"from": e["source"], "to": e["target"], "label": e["relation"],
            "title": f"{e['relation']} [{e.get('confidence', 'EXTRACTED')}]",
            "dashes": e.get("confidence") != "EXTRACTED", "width": 2 if e.get("confidence") == "EXTRACTED" else 1,
            "color": {"opacity": 0.7}, "confidence": e.get("confidence", "EXTRACTED")} for e in graph["links"]]
    counts = Counter(n.get("community") for n in graph["nodes"])
    legend = [{"cid": c, "color": color.get(c, PALETTE[c % len(PALETTE)]),
               "label": labels.get(str(c), str(c)).replace("&", "&amp;"), "count": counts[c]}
              for c in sorted(counts, key=lambda c: -counts[c])]
    for i, l in enumerate(html):
        if l.startswith("const RAW_NODES = "):
            html[i] = "const RAW_NODES = " + json.dumps(rn) + ";"
        elif l.startswith("const RAW_EDGES = "):
            html[i] = "const RAW_EDGES = " + json.dumps(re_) + ";"
        elif l.startswith("const LEGEND = "):
            html[i] = "const LEGEND = " + json.dumps(legend) + ";"
    (OUT / "graph.html").write_text("\n".join(html), encoding="utf-8")
    print(json.dumps({"changed_files": len(changed), "removed_files": len(gone), "nodes": len(graph["nodes"]),
                      "links": len(graph["links"]), "communities": len(counts),
                      "new_communities": [labels[str(c)] for c in counts if c >= 45]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
