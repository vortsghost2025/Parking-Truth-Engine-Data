#!/usr/bin/env python3
"""Relative parking-pressure index (PTE-TEL-003 deliverable 5).

WHAT THIS PRODUCES
------------------
A RELATIVE PRESSURE INDEX: PCNs issued per parking space per date, rescaled so
the exposure-weighted mean across streets is 1.0. A value of 2.0 means "twice
the study-average PCN rate per space". It means nothing else.

WHAT THIS IS NOT
----------------
Not occupancy. Not a probability of finding a space. Not a percentage. Not a
confidence figure. Not comparable across cities or across time periods with
different enforcement regimes. The requirement list for this lane is explicit, so
rather than relying on a reader to remember it, the module MACHINE-CHECKS its own
output: `assert_no_forbidden_semantics()` walks the emitted structure and raises
if any key implies occupancy, probability, vacancy, availability or confidence.

WHY A RATE PER SPACE AND NOT A RAW COUNT
----------------------------------------
`PCN rate ~ occupancy x violation rate x enforcement intensity`. A raw count
conflates a busy street with a big street, and rewards enforcement for patrolling
where there are more spaces. Dividing by publisher-supplied capacity removes the
size term - and only that term. The violation rate and enforcement intensity
terms are NOT removed by this arithmetic and cannot be from PCN data alone. They
are reported as confounders by the signal test, never silently assumed away.

WHERE CAPACITY IS MISSING
-------------------------
Camden supplies an approximate space count per bay, but not necessarily for every
street. Where it is absent, `spaceCount` is None - never 0.0 - and the street
gets no per-space rate. It still contributes to count-based diagnostics and is
listed in the coverage report. Inventing a capacity would manufacture a rate out
of nothing.

STDLIB ONLY. Deterministic: same inputs -> same outputs.
"""

from __future__ import annotations

from collections import defaultdict

from camden_normalize import STRATA

# Every output object carries this, so a number can never be read out of context.
# Negations are expressed as a VALUE list rather than as boolean keys, because
# the guard below forbids any KEY containing the forbidden vocabulary - including
# a key whose purpose is to deny it. `isOccupancy: False` would trip the very
# check meant to stop `occupancy: 0.62`. Stating what the index does not claim in
# prose keeps the denial and keeps the namespace clean.
SEMANTIC_CONTRACT = {
    "quantity": "RELATIVE_PARKING_PRESSURE_INDEX",
    "units": ("PCNs per parking space per date, rescaled so the exposure-weighted "
              "mean across indexed streets is 1.0"),
    "doesNotClaim": [
        "occupancy",
        "probability of finding a space",
        "vacancy",
        "availability",
        "a percentage",
        "a confidence figure",
        "cross-city comparability",
        "legality",
    ],
    "comparableAcrossCities": False,
    "comparableAcrossPeriods": (
        "only with caution - a change of enforcement regime invalidates it"),
    "legalityClaimed": False,
    "reading": ("2.0 means twice the study-average PCN rate per space. It does "
                "NOT mean 200% full, NOT a 2.0 probability, and NOT twice the "
                "occupancy."),
}

# Key substrings that must never appear in emitted output. Enforced by
# assert_no_forbidden_semantics(). `availability` is included because it is the
# other lane's vocabulary (see docs/FRONTEND_INTEGRATION_CONTRACT.md) and a
# pressure index wearing that name would be read as an occupancy claim.
FORBIDDEN_KEY_SUBSTRINGS = (
    "occupanc", "occupied", "vacanc", "vacant", "probabilit", "pfree", "pocc",
    "percentfree", "percentfull", "percentoccup", "chanceof", "likelihood",
    "confidence", "availability", "isfree", "isoccupied",
)

# Fields allowed to carry explanatory prose rather than numbers.
_PROSE_FIELDS = {"semantics", "reading", "units", "warning", "warnings", "notes",
                 "gridSemantics", "classReason", "contraventionClass"}


class ForbiddenSemanticsError(AssertionError):
    """Raised when output would imply a claim this lane is not allowed to make."""


def assert_no_forbidden_semantics(obj, path: str = "$") -> None:
    """Walk an emitted structure and refuse keys that imply forbidden claims."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            low = str(key).lower()
            for forbidden in FORBIDDEN_KEY_SUBSTRINGS:
                if forbidden in low:
                    raise ForbiddenSemanticsError(
                        f"{path}.{key}: key implies a forbidden claim "
                        f"(matched {forbidden!r}). This lane emits a relative "
                        "pressure index only - no occupancy, no probability, no "
                        "vacancy, no availability, no confidence percentage.")
            assert_no_forbidden_semantics(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            assert_no_forbidden_semantics(item, f"{path}[{i}]")


def _round(value, ndigits: int = 6):
    return None if value is None else round(float(value), ndigits)


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------

def street_rate(cells: dict, stratum: str | None = None) -> dict:
    """Reduce cells to a per-street rate, optionally within one stratum.

    `stratum=None` is NOT pooling. It computes a rate per street from the
    supplied cells only, so the caller decides which strata are in scope.
    `pool_strata()` in the aggregation module is the only sanctioned way to
    combine strata, and it stamps its output so a report can show the effect.
    """
    counts: dict[str, float] = defaultdict(float)
    exposure: dict[str, float] = defaultdict(float)
    raw_counts: dict[str, int] = defaultdict(int)
    cap_known: dict[str, bool] = defaultdict(bool)
    meta: dict[str, dict] = {}

    for key, cell in cells.items():
        if stratum is not None and cell.get("spatialStratum") != stratum:
            continue
        jk = cell["joinKey"]
        raw_counts[jk] += int(cell["pcnCount"])
        if cell.get("exposureBayDates"):
            exposure[jk] += float(cell["exposureBayDates"])
            counts[jk] += float(cell["pcnCount"])
            cap_known[jk] = True
        slot = meta.setdefault(jk, {
            "joinKey": jk, "cpz": cell.get("cpz"), "street": cell.get("street"),
            "spaceCount": cell.get("spaceCount"),
            "capacityIsApproximate": cell.get("capacityIsApproximate"),
            "capacitySuppliedByPublisher": cell.get("capacitySuppliedByPublisher"),
            "exposureDatesByDayType": {},
        })
        dt = cell.get("dayType")
        if dt is not None:
            slot["exposureDatesByDayType"][dt] = max(
                slot["exposureDatesByDayType"].get(dt, 0),
                int(cell.get("exposureDates") or 0))

    out = {}
    for jk in sorted(meta):
        slot = dict(meta[jk])
        slot["pcnCount"] = int(raw_counts[jk])
        slot["capacityKnown"] = bool(cap_known.get(jk))
        slot["exposureBayDates"] = _round(exposure.get(jk))
        slot["pcnsPerSpacePerDate"] = (
            _round(counts[jk] / exposure[jk], 9)
            if cap_known.get(jk) and exposure.get(jk) else None)
        slot["exposureDatesByDayType"] = dict(sorted(slot["exposureDatesByDayType"].items()))
        out[jk] = slot
    return out


def build_index(cells: dict, stratum: str | None = None,
                min_exposure: float = 1.0) -> dict:
    """Build the relative pressure index for one stratum scope.

    `min_exposure` suppresses the per-space rate for streets whose exposure is so
    small that a single PCN would swing the index wildly. Those streets are
    RETAINED with a null rate and a reason, rather than dropped, because dropping
    them would silently bias the street set toward large, well-inventoried roads.
    """
    rates = street_rate(cells, stratum=stratum)

    eligible = {
        jk: r for jk, r in rates.items()
        if r["pcnsPerSpacePerDate"] is not None
        and (r["exposureBayDates"] or 0) >= min_exposure
    }

    total_count = sum(r["pcnCount"] for r in eligible.values())
    total_exposure = sum(r["exposureBayDates"] for r in eligible.values())
    global_rate = (total_count / total_exposure) if total_exposure else None

    index = {}
    for jk in sorted(rates):
        r = rates[jk]
        entry = dict(r)
        if jk not in eligible:
            entry["relativePressureIndex"] = None
            entry["indexSuppressedReason"] = (
                "no publisher-supplied capacity"
                if r["pcnsPerSpacePerDate"] is None
                else f"exposure {r['exposureBayDates']} below min_exposure {min_exposure}")
        else:
            entry["relativePressureIndex"] = (
                _round(r["pcnsPerSpacePerDate"] / global_rate, 6)
                if global_rate else None)
            entry["indexSuppressedReason"] = None
        entry["semantics"] = SEMANTIC_CONTRACT["reading"]
        index[jk] = entry

    return {
        "scope": {"stratum": stratum or "AS_SUPPLIED_BY_CALLER",
                  "strataIncluded": sorted({r.get("spatialStratum") for r in
                                            (cells.values() if stratum is None else [])
                                            if r.get("spatialStratum")}) or
                  ([stratum] if stratum else []),
                  "minExposure": min_exposure},
        "semanticContract": dict(SEMANTIC_CONTRACT),
        "globalRatePcnsPerSpacePerDate": _round(global_rate, 9),
        "streetCount": len(rates),
        "streetCountWithIndex": sum(
            1 for e in index.values() if e["relativePressureIndex"] is not None),
        "streetCountSuppressed": sum(
            1 for e in index.values() if e["relativePressureIndex"] is None),
        "totalPcnCount": total_count,
        "totalExposureBayDates": _round(total_exposure),
        "index": index,
    }


def hourly_shape(cells: dict, stratum: str) -> dict:
    """Hourly distribution of PCNs for one stratum, summed across streets.

    Reported per stratum because the whole point of the stratification is that a
    CCTV-derived hourly shape reflects camera operating patterns, while a CEO GPS
    shape reflects where officers walked. Averaging them together produces a
    curve that describes neither.
    """
    by_hour: dict[int, int] = defaultdict(int)
    by_daytype_hour: dict[tuple, int] = defaultdict(int)
    total = 0
    for cell in cells.values():
        if cell.get("spatialStratum") != stratum or not cell.get("hourKnown"):
            continue
        by_hour[int(cell["hour"])] += int(cell["pcnCount"])
        by_daytype_hour[(cell["dayType"], int(cell["hour"]))] += int(cell["pcnCount"])
        total += int(cell["pcnCount"])

    return {
        "stratum": stratum,
        "totalPcnWithKnownHour": total,
        "byHour": {h: by_hour.get(h, 0) for h in range(24)},
        "byDayTypeHour": {
            f"{dt}|{h:02d}": v for (dt, h), v in sorted(by_daytype_hour.items())},
        # A flat distribution has entropy log2(24); a shift-shaped one is much
        # lower. Reported as a diagnostic, never as a verdict.
        "hourlyEntropyBits": _round(_entropy([by_hour.get(h, 0) for h in range(24)]), 6),
        "maxPossibleEntropyBits": _round(_entropy([1] * 24), 6),
    }


def _entropy(counts) -> float:
    import math
    total = sum(counts)
    if total <= 0:
        return 0.0
    h = 0.0
    for c in sorted(counts, reverse=True):
        if c <= 0:
            continue
        p = c / total
        h -= p * math.log2(p)
    return h


def concentration(values) -> dict:
    """Concentration diagnostics for a list of non-negative magnitudes.

    Used to test whether the signal is dominated by a handful of streets - which
    is what enforcement targeting looks like - rather than spread in proportion
    to capacity, which is what demand looks like.
    """
    import math
    vals = sorted(float(v) for v in values if v is not None and v > 0)
    n = len(vals)
    total = sum(vals)
    if n == 0 or total <= 0:
        return {"n": n, "gini": None, "hhi": None, "top1Share": None,
                "top5Share": None, "top10Share": None}
    # Gini via the sorted-sum formula; deterministic ordering matters here.
    cum = 0.0
    weighted = 0.0
    for i, v in enumerate(vals, start=1):
        weighted += i * v
    gini = (2.0 * weighted) / (n * total) - (n + 1.0) / n
    shares = [v / total for v in vals]
    hhi = sum(s * s for s in shares)
    desc = sorted(shares, reverse=True)
    return {
        "n": n,
        "gini": _round(max(0.0, gini), 6),
        "hhi": _round(hhi, 6),
        "top1Share": _round(desc[0], 6),
        "top5Share": _round(sum(desc[:5]), 6),
        "top10Share": _round(sum(desc[:10]), 6),
        "entropyNormalised": _round(_entropy(vals) / math.log2(n), 6) if n > 1 else None,
    }
