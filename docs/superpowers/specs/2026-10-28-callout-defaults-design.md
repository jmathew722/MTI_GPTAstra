# Callout defaults: build vague callouts by documented rules instead of skipping them

**Date:** 2026-10-28 · **Status:** implemented with this spec (review pending on the PR) · **Owner:** ggould + Claude Code

## Problem

The planner marks a feature `unresolved` whenever the drawing doesn't fully settle it, and the
reference and SolidWorks compilers then skip it. On MTI's audit set (31 parts), **36 features are
unresolved**. Most of them are the same handful of vague callouts:

- ".030 R MAX";
- "BREAK ALL SHARP CORNERS";
- "C/R";
- a tap with a thread depth but no drill depth.

Each of these is a question for MTI, and the parts stay incomplete until someone answers. In
production the pipeline gets only the 2D drawing and no one to ask, so it needs a documented,
consistent answer.

## What the unresolved features already contain

Every unresolved feature in the audit plans already carries **full geometry**: a size expression
over dimension IDs, the edge queries, the hole position and spec. Only the status says "don't
build". So defaults can be applied **deterministically after planning**: no prompt change, no
API cost, and saved plans can be re-run.

## Evidence: what MTI's own models do (measured from their SLDPRTs, 2026-10-28)

| Callout | MTI's models |
|---|---|
| ".030 R MAX" (SB12006, SB12010, SB12095), "ALL RADII .047 MAX" (2N2664) | fillet **at the max value** (R.030; R.047 ×9). SB12007/SB12009 omit it. |
| ".005 C/R MAX" (4C1229) | not modelled |
| "#10-32 TAP .38 DEEP" (SB12006/07/09/10) | drill Ø.159 × **.536**, which is .38 + 5 × (1/32) exactly |
| unsized plate corners (A00115E, A00116E) | not modelled |
| ".12 C/R" (2N2664) | both forms occur on the part |
| "ALL CHAMFERS .06 × 45° U.O.S." (2N2664) | .06 × 45° chamfers ×14 |

## Rules (`pipeline/ir/defaults.py`)

They apply only to `unresolved` features whose callout matches; anything else is untouched. Each
applied rule:

- sets the status to `planned` and appends `DEFAULT Dn: <rule>` to the feature's
  justification, so the build report flags it for review;
- or, for the "not modelled" rules, removes the feature and records it.

| Rule | Matches | Action |
|---|---|---|
| **D1** max-only radius | edge op, callout "R MAX" / "RADII … MAX", printed size > .010 | fillet at the max value on the plan's edges |
| **D2** tiny break | edge op, printed size ≤ .010 | not modelled (below modelling resolution) |
| **D3** chamfer-or-radius | edge op, callout "C/R", size > .010 | chamfer 45° at the printed size |
| **D4** unsized break | edge op whose size is 0 or missing ("BREAK ALL SHARP CORNERS", undimensioned corners) | not modelled (manufacturing instruction) |
| **D5** tap depth only | hole with no drill depth; a callout "<thread> TAP/THD <x> DEEP/DP"; x matches a dimension | tapped; drill depth = `D_x + 5 / tpi` (metric: `+ 5 * pitch`) |
| **D6** thread class only | tapped hole fully defined; the only question is the thread class (e.g. 2A on an internal thread) | planned; threads are cosmetic (CLAUDE.md rule 7), so class never blocks geometry. "8-32" becomes "#8-32". |
| **D7** general note / TYP with a printed size | edge op, callout "ALL CHAMFERS … U.O.S." or "… TYP.", size > .010 | planned on the plan's edges |

**Never defaulted** (they stay questions):

- drawing conflicts (30° bevel vs tip diameter);
- "TO SUIT";
- unnamed hardware ("LOW HEAD");
- taps with no printed depth at all;
- unresolved positions (CLAUDE.md rule 6 still holds: a default sets a size, never a position).

## Reporting and switches

- `IRResult.defaults` lists every rule applied (`F006: D1 fillet .030 at max`).
- `plan.json` stays the planner's raw output; the defaults re-apply on every run and on
  `--reuse-plans`, so a rule change re-runs at $0.
- `MTI_CALLOUT_DEFAULTS=0` turns the rules off. That is the pre-2026-10-28 behaviour, where every
  vague callout is a question.

## Test plan

- One unit test per rule, plus "never defaulted" cases.
- Rebuild the 12 affected audit parts from saved plans ($0) and compare against MTI's models.
