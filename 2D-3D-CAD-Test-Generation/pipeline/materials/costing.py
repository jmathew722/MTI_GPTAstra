"""Illustrative material cost (Phase 1, section 6).

mass = native mass properties (authoritative when they agree with volume x density within ``TOLERANCE``);
net material cost = mass x price per kg.  Unknown material / unverified density / missing price => *unavailable*, never $0.
No machining, labour, scrap, shipping, tax or purchase minimum is included, and there is no default waste assumption.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

TOLERANCE = 0.01          # native mass vs volume x density: 1 %
ILLUSTRATIVE = "Illustrative material estimate — not a supplier quote"
EXCLUDES = "Material only: excludes machining, labour, scrap/waste (unless a yield is set), shipping, tax and purchase minimums."


def _pos(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def money(x: float) -> str:
    return str(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sig(x: float, n: int = 4) -> str:
    if x == 0 or not math.isfinite(x):
        return "0"
    d = n - int(math.floor(math.log10(abs(x)))) - 1
    return f"{round(x, d):.{max(0, d)}f}"


def estimate(*, volume_m3: Optional[float], density_kg_m3: Optional[float], price_per_kg: Optional[float], currency: str = "USD",
             native_mass_kg: Optional[float] = None, density_verified: bool = False, yield_fraction: Optional[float] = None,
             price_basis: str = "", catalog_version: str = "", demo: bool = False) -> dict:
    out: dict = {"available": False, "reason": None, "currency": currency, "price_basis": price_basis, "catalog_version": catalog_version,
                 "label": ILLUSTRATIVE if demo else "Material estimate from the catalog price", "excludes": EXCLUDES, "warnings": [],
                 "inputs": {"volume_m3": volume_m3, "density_kg_m3": density_kg_m3, "native_mass_kg": native_mass_kg,
                            "price_per_kg": price_per_kg, "yield_fraction": yield_fraction},
                 "mass_kg": None, "net_material_cost": None, "stock_cost": None, "display": {}}
    if density_kg_m3 is None or not _pos(density_kg_m3):
        out["reason"] = "No material density is known, so mass and cost cannot be estimated."
        return out
    if not density_verified:
        out["reason"] = "The material was not verified on the native part (density unverified), so the estimate is unavailable."
        return out
    if not _pos(volume_m3):
        out["reason"] = "The native volume is missing or not positive."
        return out
    calc = volume_m3 * density_kg_m3
    mass = calc
    if native_mass_kg is not None:
        if not _pos(native_mass_kg):
            out["warnings"].append("Native mass was not usable; mass computed from volume x density.")
        else:
            gap = abs(native_mass_kg - calc) / calc
            out["mass_crosscheck"] = {"native_kg": native_mass_kg, "volume_x_density_kg": calc, "relative_gap": gap, "tolerance": TOLERANCE}
            if gap > TOLERANCE:
                out["reason"] = (f"Native mass ({sig(native_mass_kg)} kg) and volume x density ({sig(calc)} kg) disagree by "
                                 f"{gap * 100:.1f} %, more than {TOLERANCE * 100:.0f} %.")
                out["mass_kg"] = native_mass_kg
                return out
            mass = native_mass_kg
    out["mass_kg"] = mass
    out["display"]["mass"] = f"{sig(mass)} kg"
    out["display"]["volume"] = f"{sig(volume_m3 * 1e6)} cm³"
    if price_per_kg is None:
        out["reason"] = "The catalog has no price for this material, so the cost is unavailable (not $0)."
        return out
    if not _pos(price_per_kg) and price_per_kg != 0:
        out["reason"] = "The catalog price is invalid."
        return out
    net = mass * price_per_kg
    out["net_material_cost"] = net
    out["display"]["net_material_cost"] = f"{money(net)} {currency}"
    if yield_fraction is not None:
        if not (0 < yield_fraction <= 1):
            out["warnings"].append("Yield must be above 0 and at most 1; stock cost not computed.")
        else:
            out["stock_cost"] = net / yield_fraction
            out["display"]["stock_cost"] = f"{money(out['stock_cost'])} {currency}"
    out["available"] = True
    return out


def batch_totals(estimates: list[dict]) -> dict:
    """Sum per currency; currencies are never combined. Unpriced parts are counted, not treated as zero."""
    by_cur: dict[str, float] = {}
    priced = unpriced = 0
    for e in estimates:
        if e and e.get("available") and e.get("net_material_cost") is not None:
            priced += 1
            by_cur[e["currency"]] = by_cur.get(e["currency"], 0.0) + e["net_material_cost"]
        else:
            unpriced += 1
    return {"priced_parts": priced, "unpriced_parts": unpriced, "totals": {c: {"value": v, "display": f"{money(v)} {c}"} for c, v in by_cur.items()},
            "partial": unpriced > 0, "note": "Unknown costs are not counted as zero." if unpriced else ""}
