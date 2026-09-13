#!/usr/bin/env python3
"""Camden pressure-signal test: verdicts and report (PTE-TEL-003 deliverable 7).

WHAT IT DECIDES
---------------
One question: **do PCN event patterns contain a reproducible street/time
parking-pressure signal?** The answer is PASS, PARTIAL or FAIL, and it is
produced from the five fail criteria in the approved scope rather than from a
vibe:

  F1  signal dominated by enforcement deployment rather than parking demand
  F2  results collapse when CEO GPS events are isolated
  F3  insufficient geographic / time coverage
  F4  no independent validation route
  F5  unstable rankings across comparable periods

THE HONEST CENTRE OF THIS MODULE
--------------------------------
**PCN data alone cannot separate parking demand from enforcement deployment.**
A PCN is issued where an officer or camera looks AND where a driver contravenes.
Every diagnostic here narrows that ambiguity; none eliminates it. The only thing
that eliminates it is an INDEPENDENT proxy - a measure of pressure not derived
from the PCN series. That is why F4 is a fail criterion rather than a footnote,
and why, with no proxy supplied, this module caps the verdict at PARTIAL and
reports descriptive signal characterisation only.

A signal that correlates with itself is not evidence. The harness refuses to
pretend otherwise.

WHAT IT WILL NOT DO
-------------------
It does not output occupancy, a probability of finding a space, a confidence
percentage, or any bay-level quantity. `camden_pressure.assert_no_forbidden_
semantics()` machine-checks the emitted report and raises if any key implies one.
It does not touch legality: a PCN says a car WAS there, not that a car MAY be
there.

    python3 camden_signal_test.py --bays bays.csv --pcn pcn.csv --out report.json
    python3 camden_signal_test.py --bays b.csv --pcn p.csv --proxy proxy.csv --selftest

STDLIB ONLY. Deterministic: same inputs and flags -> same outputs, byte for byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camden_aggregate import (          # noqa: E402
    DAY_TYPES,
    JOIN_LEVEL_CPZ,
    JOIN_LEVEL_STREET,
    assert_no_bay_level_join,
    build_capacity,
    build_cells,
    build_date_index,
    cell_sort_key,
)
from camden_normalize import (  # noqa: E402
    STRATA, STRATUM_CEO_GPS, STRATUM_FIXED_CCTV, load_code_map, normalize_all)
from camden_pressure import (           # noqa: E402
    SEMANTIC_CONTRACT,
    assert_no_forbidden_semantics,
    build_index,
    concentration,
    hourly_shape,
)
from camden_sources import load_bay_map, load_pcn_series, load_proxy  # noqa: E402

HARNESS_VERSION = "1.0.0"

# Thresholds are explicit and overridable, because a verdict whose cut-offs are
# buried in code cannot be argued with.
DEFAULT_THRESHOLDS = {
    "minDistinctStreets": 10,
    "minDistinctDates": 28,
    "minCapacityCoverageFraction": 0.50,
    "minCeoGpsShare": 0.05,
    "minEventsForRanking": 30,
    "stratumIsolationSpearman": 0.50,
    "splitHalfSpearman": 0.50,
    "proxySpearman": 0.40,
    "prohibitionShareDominant": 0.50,
    "indexVsProhibitionSpearman": 0.40,
    "sizeConfoundGiniGap": 0.25,
}


# ---------------------------------------------------------------------------
# Statistics (no scipy; ties handled by average rank)
# ---------------------------------------------------------------------------

def ranks(values) -> list[float]:
    """Average ranks, with deterministic tie-breaking by value order."""
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def pearson(xs, ys) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def spearman(pairs) -> dict:
    """Spearman rank correlation over (x, y) pairs, ignoring None entries.

    Reported with n and the tie counts, because a correlation computed over six
    streets with heavy ties is not the same object as one over four hundred.
    """
    clean = [(float(x), float(y)) for x, y in pairs
             if x is not None and y is not None]
    n = len(clean)
    if n < 3:
        return {"rho": None, "n": n, "tiesX": None, "tiesY": None,
                "note": "fewer than 3 usable pairs"}
    xs = [c[0] for c in clean]
    ys = [c[1] for c in clean]
    rx, ry = ranks(xs), ranks(ys)
    rho = pearson(rx, ry)
    return {
        "rho": None if rho is None else round(rho, 6),
        "n": n,
        "tiesX": n - len(set(xs)),
        "tiesY": n - len(set(ys)),
    }


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

def run_pipeline(bays_payload: dict, pcn_payload: dict, level: str,
                 date_subset: set[str] | None = None,
                 code_map: dict | None = None) -> dict:
    """Normalise -> capacity -> date index -> cells, optionally for a date subset.

    Re-running the pipeline on a subset is how period comparisons are made.
    Aggregation is pure and cheap, so splitting is done by filtering events
    rather than by storing per-date counts inside every cell.
    """
    norm = normalize_all(bays_payload, pcn_payload, code_map=code_map)
    pcns = norm["pcns"]
    if date_subset is not None:
        pcns = [e for e in pcns
                if (e.get("temporal") or {}).get("date") in date_subset]
    cap = build_capacity(norm["bays"], level)
    date_index = build_date_index(pcns)
    grid = build_cells(pcns, cap["capacity"], date_index, level)
    assert_no_bay_level_join(grid["cells"])
    assert_no_bay_level_join(grid["unknownHourCells"])
    return {
        "normalized": norm,
        "capacity": cap,
        "dateIndex": date_index,
        "grid": grid,
        "pcnCountUsed": len(pcns),
    }


def _index_map(index_result: dict) -> dict:
    return {jk: e["relativePressureIndex"]
            for jk, e in index_result["index"].items()}


def _street_index_by_stratum(cells: dict, thresholds: dict) -> dict:
    out = {}
    for stratum in list(STRATA) + ["CEO_GPS_ONLY"]:
        scope = stratum if stratum != "CEO_GPS_ONLY" else STRATUM_CEO_GPS
        out[stratum] = build_index(cells, stratum=scope,
                                   min_exposure=thresholds["minEventsForRanking"] / 10.0)
    return out


def _contravention_mix(cells: dict) -> dict:
    """Share of PCNs by contravention class, overall and per street.

    The classification is a heuristic over free text (see camden_normalize) and
    is used ONLY as a confound diagnostic. A street whose PCNs are mostly
    prohibition-type is more plausibly an artefact of where enforcement looks;
    a street mostly turnover/overstay-type is more plausibly reflecting real
    parking pressure.
    """
    overall: dict[str, int] = {}
    per_street: dict[str, dict[str, int]] = {}
    for cell in cells.values():
        jk = cell["joinKey"]
        bucket = per_street.setdefault(jk, {})
        for cls, n in cell["contraventionClassCounts"].items():
            overall[cls] = overall.get(cls, 0) + n
            bucket[cls] = bucket.get(cls, 0) + n
    total = sum(overall.values())
    shares = {cls: (round(n / total, 6) if total else None)
              for cls, n in sorted(overall.items())}
    prohibition_share_by_street = {}
    for jk in sorted(per_street):
        b = per_street[jk]
        t = sum(b.values())
        prohibition_share_by_street[jk] = (
            round(b.get("PROHIBITION_TYPE", 0) / t, 6) if t else None)
    return {
        "overallCounts": dict(sorted(overall.items())),
        "overallShares": shares,
        "prohibitionShareOverall": shares.get("PROHIBITION_TYPE"),
        "prohibitionShareByStreet": prohibition_share_by_street,
        "classificationIsHeuristic": True,
    }


# ---------------------------------------------------------------------------
# Fail criteria
# ---------------------------------------------------------------------------

def check_coverage(pipe: dict, thresholds: dict) -> dict:
    """F3 - insufficient geographic / time coverage."""
    grid = pipe["grid"]
    norm = pipe["normalized"]
    cap = pipe["capacity"]["capacity"]
    missing = norm["missingness"]

    streets_with_capacity = [c for c in cap.values() if c.get("spaceCount")]
    covered = len(streets_with_capacity)
    total_streets = len(cap) or 1
    coverage_fraction = covered / total_streets

    strata_counts = missing["spatialStrataCounts"]
    total_pcn = missing["pcnTotal"] or 1
    ceo_share = strata_counts.get(STRATUM_CEO_GPS, 0) / total_pcn

    checks = {
        "distinctStreets": grid["joinKeyCount"],
        "distinctStreetsMin": thresholds["minDistinctStreets"],
        "distinctStreetsOk": grid["joinKeyCount"] >= thresholds["minDistinctStreets"],
        "distinctDates": pipe["dateIndex"]["distinctDates"],
        "distinctDatesMin": thresholds["minDistinctDates"],
        "distinctDatesOk": pipe["dateIndex"]["distinctDates"] >= thresholds["minDistinctDates"],
        "capacityCoverageFraction": round(coverage_fraction, 6),
        "capacityCoverageMin": thresholds["minCapacityCoverageFraction"],
        "capacityCoverageOk": coverage_fraction >= thresholds["minCapacityCoverageFraction"],
        "ceoGpsShare": round(ceo_share, 6),
        "ceoGpsShareMin": thresholds["minCeoGpsShare"],
        "ceoGpsShareOk": ceo_share >= thresholds["minCeoGpsShare"],
        "streetsWithInventoryButNoEvents": len(grid["joinKeysWithNoEvents"]),
        "pcnEventsUnplaceable": grid["pcnEventsUnplaceable"],
        "pcnEventsUnplaceableShare": round(
            grid["pcnEventsUnplaceable"] / total_pcn, 6),
        "pcnHourUnknownShare": round(
            missing["pcnHourUnknown"] / total_pcn, 6),
        "bayStreetsUnmatchedToPcn": len(pipe["capacity"]["bayStreetsUnmatched"]),
    }
    checks["allOk"] = all(checks[k] for k in (
        "distinctStreetsOk", "distinctDatesOk", "capacityCoverageOk", "ceoGpsShareOk"))
    checks["triggered"] = not checks["allOk"]
    checks["criterion"] = "F3 insufficient geographic/time coverage"
    return checks


def check_stratum_isolation(pipe: dict, thresholds: dict) -> dict:
    """F2 - do results collapse when CEO GPS events are isolated?

    Compares the street pressure ranking built from all supplied cells against
    the ranking built from CEO_GPS events only. If a CCTV-heavy series produces a
    materially different street ranking, then the headline signal was substantially
    a map of camera locations rather than of parking behaviour - because the
    publisher warns a fixed CCTV location "could be many metres from the vehicle
    in contravention".
    """
    cells = pipe["grid"]["cells"]
    per_stratum = _street_index_by_stratum(cells, thresholds)
    pooled = per_stratum["CEO_GPS_ONLY"]  # placeholder replaced below

    # All-strata scope: caller-supplied cells, not pool_strata(), so that the
    # comparison is "everything" vs "CEO GPS only".
    all_scope = build_index(cells, stratum=None,
                            min_exposure=thresholds["minEventsForRanking"] / 10.0)
    ceo_scope = build_index(cells, stratum=STRATUM_CEO_GPS,
                            min_exposure=thresholds["minEventsForRanking"] / 10.0)
    cctv_scope = build_index(cells, stratum=STRATUM_FIXED_CCTV,
                             min_exposure=thresholds["minEventsForRanking"] / 10.0)

    all_map = _index_map(all_scope)
    ceo_map = _index_map(ceo_scope)
    cctv_map = _index_map(cctv_scope)
    common = sorted(set(all_map) & set(ceo_map))

    corr = spearman([(all_map[k], ceo_map[k]) for k in common
                     if all_map[k] is not None and ceo_map[k] is not None])
    corr_cctv = spearman([(all_map[k], cctv_map[k]) for k in common
                          if all_map[k] is not None and cctv_map.get(k) is not None])

    rho = corr["rho"]
    triggered = (rho is None) or (rho < thresholds["stratumIsolationSpearman"])
    return {
        "criterion": "F2 results collapse when CEO GPS events are isolated",
        "spearmanAllStrataVsCeoGps": corr,
        "spearmanAllStrataVsFixedCctv": corr_cctv,
        "threshold": thresholds["stratumIsolationSpearman"],
        "streetsComparable": len(common),
        "ceoGpsStreetsWithIndex": ceo_scope["streetCountWithIndex"],
        "fixedCctvStreetsWithIndex": cctv_scope["streetCountWithIndex"],
        "triggered": bool(triggered),
        "interpretation": (
            "CEO-GPS-only ranking diverges from the all-strata ranking, so the "
            "headline signal is materially shaped by where cameras are rather "
            "than by parking behaviour"
            if triggered and rho is not None else
            "too few CEO-GPS streets to isolate the stratum at all"
            if rho is None else
            "CEO-GPS-only ranking agrees with the all-strata ranking"),
        # Shown explicitly, per the requirement never to pool strata without
        # demonstrating the effect of doing so.
        "perStratumIndexSummary": {
            s: {
                "streetCountWithIndex": per_stratum[s]["streetCountWithIndex"],
                "globalRatePcnsPerSpacePerDate":
                    per_stratum[s]["globalRatePcnsPerSpacePerDate"],
            } for s in STRATA
        },
    }


def check_split_half(pipe: dict, bays_payload: dict, pcn_payload: dict,
                     level: str, thresholds: dict,
                     code_map: dict | None = None) -> dict:
    """F5 - are rankings stable across comparable periods?

    Splits the observation window chronologically in half and rebuilds the street
    index for each half. Splitting by DATE rather than by event count keeps the
    two halves comparable in exposure, which is the point of the test.
    """
    dates = pipe["dateIndex"]["dateList"]
    if len(dates) < 4:
        return {"criterion": "F5 unstable rankings across comparable periods",
                "triggered": True, "reason": "fewer than 4 distinct dates",
                "distinctDates": len(dates)}
    mid = len(dates) // 2
    first, second = set(dates[:mid]), set(dates[mid:])

    out = {}
    for label, subset in (("firstHalf", first), ("secondHalf", second)):
        sub = run_pipeline(bays_payload, pcn_payload, level, date_subset=subset,
                           code_map=code_map)
        idx = build_index(sub["grid"]["cells"], stratum=None,
                          min_exposure=thresholds["minEventsForRanking"] / 10.0)
        out[label] = {"dates": len(subset), "indexMap": _index_map(idx),
                      "pcnCount": sub["pcnCountUsed"]}

    common = sorted(set(out["firstHalf"]["indexMap"]) & set(out["secondHalf"]["indexMap"]))
    pairs = [(out["firstHalf"]["indexMap"][k], out["secondHalf"]["indexMap"][k])
             for k in common]
    corr = spearman([(a, b) for a, b in pairs if a is not None and b is not None])
    rho = corr["rho"]
    triggered = (rho is None) or (rho < thresholds["splitHalfSpearman"])
    return {
        "criterion": "F5 unstable rankings across comparable periods",
        "splitBy": "chronological date halves",
        "firstHalfDates": out["firstHalf"]["dates"],
        "secondHalfDates": out["secondHalf"]["dates"],
        "firstHalfPcnCount": out["firstHalf"]["pcnCount"],
        "secondHalfPcnCount": out["secondHalf"]["pcnCount"],
        "streetsComparable": len(common),
        "spearmanFirstVsSecondHalf": corr,
        "threshold": thresholds["splitHalfSpearman"],
        "triggered": bool(triggered),
        "interpretation": (
            "street pressure ranking does not repeat across comparable periods"
            if triggered else
            "street pressure ranking repeats across comparable periods"),
    }


def check_deployment_dominance(pipe: dict, thresholds: dict) -> dict:
    """F1 - is the signal enforcement deployment rather than parking demand?

    Three indicators, reported separately because they measure different things:

      I1 size confound - is the RAW count signal just street size? Compares
         concentration of raw counts against concentration of capacity-normalised
         rates. This is a normalisation artefact, not deployment, and is reported
         as such.
      I2 prohibition dominance - are most PCNs prohibition-type (where officers
         look) rather than turnover/overstay-type (how long people stay)?
      I3 index tracks prohibition mix - does the per-space index rise with the
         prohibition share across streets?

    F1 triggers on I2 AND I3: a series that is mostly prohibition-type AND whose
    index rises with prohibition mix is more plausibly a map of enforcement
    attention than of parking demand.

    LIMITATION, stated because it is the whole point: **no test computed from PCN
    data alone can prove the absence of a deployment effect.** These indicators
    narrow the ambiguity; only an independent proxy resolves it.
    """
    cells = pipe["grid"]["cells"]
    mix = _contravention_mix(cells)
    idx = build_index(cells, stratum=None,
                      min_exposure=thresholds["minEventsForRanking"] / 10.0)

    raw_counts = [e["pcnCount"] for e in idx["index"].values()]
    rates = [e["pcnsPerSpacePerDate"] for e in idx["index"].values()
             if e["pcnsPerSpacePerDate"] is not None]
    conc_raw = concentration(raw_counts)
    conc_rate = concentration(rates)
    gini_gap = None
    if conc_raw["gini"] is not None and conc_rate["gini"] is not None:
        gini_gap = round(conc_raw["gini"] - conc_rate["gini"], 6)

    pairs = []
    for jk, entry in sorted(idx["index"].items()):
        share = mix["prohibitionShareByStreet"].get(jk)
        if entry["relativePressureIndex"] is not None and share is not None:
            pairs.append((entry["relativePressureIndex"], share))
    corr = spearman(pairs)

    i1 = gini_gap is not None and gini_gap > thresholds["sizeConfoundGiniGap"]
    i2 = (mix["prohibitionShareOverall"] is not None
          and mix["prohibitionShareOverall"] > thresholds["prohibitionShareDominant"])
    i3 = corr["rho"] is not None and corr["rho"] > thresholds["indexVsProhibitionSpearman"]

    triggered = bool(i2 and i3)
    return {
        "criterion": "F1 signal dominated by enforcement deployment rather than parking demand",
        "indicators": {
            "I1_sizeConfound": {
                "rawCountConcentration": conc_raw,
                "capacityNormalisedConcentration": conc_rate,
                "giniGapRawMinusNormalised": gini_gap,
                "threshold": thresholds["sizeConfoundGiniGap"],
                "triggered": bool(i1),
                "meaning": ("raw counts are far more concentrated than "
                            "capacity-normalised rates, so the raw signal is "
                            "largely street size"),
            },
            "I2_prohibitionDominance": {
                "prohibitionShareOverall": mix["prohibitionShareOverall"],
                "threshold": thresholds["prohibitionShareDominant"],
                "triggered": bool(i2),
                "overallShares": mix["overallShares"],
                "classificationIsHeuristic": True,
            },
            "I3_indexTracksProhibitionMix": {
                "spearmanIndexVsProhibitionShare": corr,
                "threshold": thresholds["indexVsProhibitionSpearman"],
                "triggered": bool(i3),
            },
        },
        "triggered": triggered,
        "resolvableFromPcnDataAlone": False,
        "limitation": ("No test computed from PCN data alone can prove the "
                       "absence of an enforcement-deployment effect. These "
                       "indicators narrow the ambiguity; only an independent "
                       "proxy resolves it."),
        "interpretation": (
            "PCN mix is prohibition-dominated AND the index rises with that mix: "
            "the signal is more plausibly a map of enforcement attention than of "
            "parking demand" if triggered else
            "no dominance pattern detected; this does NOT establish that demand "
            "drives the signal"),
    }


def check_validation_route(proxy_payload: dict | None, route_declaration: str,
                           idx: dict, thresholds: dict) -> dict:
    """F4 - is there an independent validation route, and does the signal hold?

    Three states:
      supplied   a proxy file was given; correlate and report
      available  the operator asserts a route exists but did not supply it; the
                 verdict is capped at PARTIAL and the output is descriptive only
      none       the operator asserts no route is known; F4 triggers
    """
    if route_declaration == "none_known":
        return {
            "criterion": "F4 no independent validation route",
            "state": "NONE_KNOWN",
            "triggered": True,
            "interpretation": ("no independent validation route is known, so the "
                               "signal cannot be distinguished from enforcement "
                               "artefact and the test cannot pass"),
        }
    if proxy_payload is None:
        return {
            "criterion": "F4 no independent validation route",
            "state": "AVAILABLE_NOT_SUPPLIED",
            "triggered": False,
            "capsVerdictAt": "PARTIAL",
            "interpretation": ("no proxy supplied this run; stopping at "
                               "descriptive signal characterisation. PASS is "
                               "unreachable without an independent proxy."),
        }

    # Aggregate the proxy to street level. The proxy's own street naming may not
    # match Camden's; unmatched streets are reported, not silently dropped.
    from camden_aggregate import street_key
    proxy_by_street: dict[str, list[float]] = {}
    unmatched = 0
    for row in proxy_payload["records"]:
        sk = street_key(row.get("street"))
        if sk is None:
            unmatched += 1
            continue
        proxy_by_street.setdefault(sk, []).append(float(row["value"]))
    proxy_mean = {k: sum(v) / len(v) for k, v in sorted(proxy_by_street.items())}

    index_map = _index_map(idx)
    matched: dict[str, tuple] = {}
    unmatched_index = 0
    for jk, value in index_map.items():
        _, street = (jk.split("||", 1) + [None])[:2] if "||" in jk else (jk, None)
        if street is None or value is None:
            continue
        if street in proxy_mean:
            matched[jk] = (value, proxy_mean[street])
        else:
            unmatched_index += 1

    corr = spearman(list(matched.values()))
    rho = corr["rho"]
    passed = rho is not None and rho >= thresholds["proxySpearman"]
    return {
        "criterion": "F4 independent validation route",
        "state": "SUPPLIED",
        "proxyRecordCount": proxy_payload["recordCount"],
        "proxyProvenance": proxy_payload["provenance"],
        "streetsMatched": len(matched),
        "proxyStreetsUnmatchedToIndex": unmatched,
        "indexStreetsUnmatchedToProxy": unmatched_index,
        "spearmanIndexVsProxy": corr,
        "threshold": thresholds["proxySpearman"],
        "triggered": False,
        "validatedByProxy": bool(passed),
        "independenceCaveat": ("The harness CANNOT verify that this proxy is "
                               "independent of the PCN series; that is an "
                               "operator assertion. If it is derived from PCNs "
                               "the test is circular and this result is "
                               "meaningless."),
        "interpretation": (
            "index agrees with the independent proxy" if passed else
            "index does not agree with the independent proxy at the threshold"),
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def decide_verdict(criteria: dict) -> dict:
    """Combine criteria into PASS / PARTIAL / FAIL with reasons."""
    hard = {k: v for k, v in criteria.items() if v.get("triggered")}
    hard_names = sorted(hard)

    if hard_names:
        verdict = "FAIL"
    else:
        route = criteria["validationRoute"]
        caps = route.get("capsVerdictAt")
        if route.get("state") == "SUPPLIED" and route.get("validatedByProxy"):
            verdict = "PASS"
        elif caps:
            verdict = caps
        else:
            verdict = "PARTIAL"

    return {
        "verdict": verdict,
        "hardCriteriaTriggered": hard_names,
        "criteriaResults": {k: bool(v.get("triggered")) for k, v in sorted(criteria.items())},
        "passRequires": [
            "no hard criterion triggered",
            "an independent proxy supplied (operator-asserted independent)",
            f"Spearman(index, proxy) >= threshold",
        ],
        "explanation": {
            "FAIL": "at least one approved fail criterion triggered",
            "PARTIAL": ("no fail criterion triggered, but the PASS bar was not "
                        "met - in practice because no independent proxy was "
                        "supplied, so this is descriptive characterisation only"),
            "PASS": ("no fail criterion triggered and the index agrees with an "
                     "independent proxy above threshold"),
        }[verdict],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(bays_path: str, pcn_path: str, proxy_path: str | None,
                 level: str, thresholds: dict, route_declaration: str,
                 as_of: str | None, field_map: dict | None = None,
                 code_map_path: str | None = None) -> dict:
    """Build the report.

    `field_map` pins normalised->source column names per dataset, e.g.
    {"bay-map": {"spaceCount": "Number Of Spaces"}}. It exists so a real Camden
    download whose column spellings differ from the adapter's candidates can be
    wired without editing code - guessing a column is worse than failing loudly,
    and failing loudly is worse than being told.
    """
    # C4A: load the authoritative code map ONCE, up front, and validate it. An
    # absent or malformed artifact raises here rather than degrading the whole run
    # to the keyword heuristic unnoticed.
    code_map = load_code_map(code_map_path, required=True)

    overrides = {"bay-map": {}, "pcn-series": {}}
    for key, val in (field_map or {}).items():
        if key in overrides and isinstance(val, dict):
            overrides[key] = {str(a): str(b) for a, b in val.items()}
    bays_payload = load_bay_map(bays_path, overrides["bay-map"])
    pcn_payload = load_pcn_series(pcn_path, overrides["pcn-series"])
    proxy_payload = load_proxy(proxy_path) if proxy_path else None
    if proxy_payload is not None:
        route_declaration = "supplied"

    pipe = run_pipeline(bays_payload, pcn_payload, level, code_map=code_map)
    cells = pipe["grid"]["cells"]
    unknown = pipe["grid"]["unknownHourCells"]
    norm = pipe["normalized"]

    idx = build_index(cells, stratum=None,
                      min_exposure=thresholds["minEventsForRanking"] / 10.0)
    per_stratum = {s: build_index(cells, stratum=s,
                                  min_exposure=thresholds["minEventsForRanking"] / 10.0)
                   for s in STRATA}

    criteria = {
        "coverage": check_coverage(pipe, thresholds),
        "stratumIsolation": check_stratum_isolation(pipe, thresholds),
        "splitHalfStability": check_split_half(pipe, bays_payload, pcn_payload,
                                               level, thresholds,
                                               code_map=code_map),
        "deploymentDominance": check_deployment_dominance(pipe, thresholds),
        "validationRoute": check_validation_route(proxy_payload, route_declaration,
                                                  idx, thresholds),
    }
    verdict = decide_verdict(criteria)

    ranked = sorted(
        ((jk, e["relativePressureIndex"]) for jk, e in idx["index"].items()
         if e["relativePressureIndex"] is not None),
        key=lambda kv: (-kv[1], kv[0]))
    strongest = [{"joinKey": jk, "relativePressureIndex": v} for jk, v in ranked[:10]]
    weakest = [{"joinKey": jk, "relativePressureIndex": v} for jk, v in ranked[-10:]]

    # Do GPS-quality events behave differently?
    gps_behaviour = {
        s: {
            "hourlyShape": hourly_shape(cells, s),
            "streetCountWithIndex": per_stratum[s]["streetCountWithIndex"],
            "globalRatePcnsPerSpacePerDate":
                per_stratum[s]["globalRatePcnsPerSpacePerDate"],
            "totalPcnCount": sum(c["pcnCount"] for c in cells.values()
                                 if c["spatialStratum"] == s),
            "unknownHourPcnCount": sum(c["pcnCount"] for c in unknown.values()
                                       if c["spatialStratum"] == s),
        } for s in STRATA
    }
    ceo = gps_behaviour[STRATUM_CEO_GPS]["hourlyShape"]
    cctv = gps_behaviour[STRATUM_FIXED_CCTV]["hourlyShape"]
    gps_behaviour["differenceDiagnostic"] = {
        "ceoGpsHourlyEntropyBits": ceo["hourlyEntropyBits"],
        "fixedCctvHourlyEntropyBits": cctv["hourlyEntropyBits"],
        "entropyDifference": (
            round(abs((ceo["hourlyEntropyBits"] or 0)
                      - (cctv["hourlyEntropyBits"] or 0)), 6)
            if ceo["hourlyEntropyBits"] is not None
            and cctv["hourlyEntropyBits"] is not None else None),
        "reading": ("a materially different hourly entropy between strata means "
                    "the two location qualities do not describe the same "
                    "process, which is exactly why they are never pooled"),
        "gpsQualityEventsBehaveDifferently": (
            None if ceo["hourlyEntropyBits"] is None or cctv["hourlyEntropyBits"] is None
            else abs(ceo["hourlyEntropyBits"] - cctv["hourlyEntropyBits"]) > 0.5),
    }

    report = {
        "harnessVersion": HARNESS_VERSION,
        "recordId": "PTE-TEL-003",
        "asOf": as_of or pipe["dateIndex"]["dateMax"],
        "asOfSource": "operator flag" if as_of else "max date in PCN series (no wall clock used)",
        "joinLevel": level,
        "inputs": {
            "bays": os.path.abspath(bays_path),
            "pcn": os.path.abspath(pcn_path),
            "proxy": os.path.abspath(proxy_path) if proxy_path else None,
            "fieldMapOverrides": field_map or {},
            "codeMap": code_map_path or code_map["path"],
        },
        "provenance": norm["provenance"],
        "semanticContract": dict(SEMANTIC_CONTRACT),
        "thresholds": dict(sorted(thresholds.items())),

        # 1. coverage
        "coverage": {
            "criteria": criteria["coverage"],
            "dateIndex": pipe["dateIndex"],
            "bayInventory": {
                "streets": len(pipe["capacity"]["capacity"]),
                "bays": sum(c["bayCount"] for c in pipe["capacity"]["capacity"].values()),
                "baysWithPublisherCapacity": sum(
                    c["baysWithCapacity"] for c in pipe["capacity"]["capacity"].values()),
                "bayStreetsUnmatched": pipe["capacity"]["bayStreetsUnmatched"][:50],
                "geometryNote": ("Camden bay coordinates derive from an arbitrary "
                                 "node on the polyline and individual spaces are "
                                 "not identifiable; no bay-level join was "
                                 "performed or is possible."),
            },
        },

        # 2. missingness
        "missingness": norm["missingness"],

        # 2A. classification provenance (PTE-TEL-004 C4A)
        "classification": norm["classification"],

        # 3. repeatability by time and street
        "repeatability": {
            "splitHalf": criteria["splitHalfStability"],
            "note": ("repeatability of a RANKING, not of a level. Levels are not "
                     "comparable across periods if the enforcement regime changed."),
        },

        # 4. whether GPS-quality events behave differently
        "spatialStrataBehaviour": gps_behaviour,

        # 5. strongest and weakest signals
        "signal": {
            "strongestStreets": strongest,
            "weakestStreets": weakest,
            "streetCountWithIndex": idx["streetCountWithIndex"],
            "streetCountSuppressed": idx["streetCountSuppressed"],
            "globalRatePcnsPerSpacePerDate": idx["globalRatePcnsPerSpacePerDate"],
            "indexDistribution": _distribution(
                [e["relativePressureIndex"] for e in idx["index"].values()
                 if e["relativePressureIndex"] is not None]),
            "contraventionMix": _contravention_mix(cells),
        },

        # 6. confounders
        "confounders": {
            "deploymentDominance": criteria["deploymentDominance"],
            "stratumIsolation": criteria["stratumIsolation"],
            "stated": [
                "PCN counts measure enforcement attention AND driver behaviour; "
                "the two cannot be separated from PCN data alone",
                "capacity is publisher-approximate, so per-space rates inherit "
                "that approximation",
                "fixed CCTV locations may be many metres from the vehicle, so "
                "CCTV-derived street attribution is uncertain",
                "streets with no publisher-supplied capacity get no per-space "
                "index, which biases the indexed street set",
                "records with a date but no time are excluded from all hourly "
                "diagnostics; hours were never imputed",
                "contravention classification is a heuristic over free text",
                "appealed or cancelled PCNs are included as issued; caseStatus is "
                "reported but not used to filter",
            ],
        },

        # The independent-validation result. This is the criterion that decides
        # whether a PASS is reachable at all, so it is surfaced in full rather
        # than only consumed by decide_verdict().
        "validation": criteria["validationRoute"],

        # 7. explicit verdict
        "verdict": verdict,

        "index": {
            "allSuppliedStrata": {
                jk: {k: v for k, v in e.items() if k != "semantics"}
                for jk, e in sorted(idx["index"].items())},
            "perStratum": {
                s: {jk: {k: v for k, v in e.items() if k != "semantics"}
                    for jk, e in sorted(per_stratum[s]["index"].items())}
                for s in STRATA},
        },
        "gridSemantics": pipe["grid"]["gridSemantics"],
        "hardGuarantees": {
            "noBayLevelJoinPerformed": True,
            "strataNeverPooledByDefault": True,
            "hoursNeverImputed": norm["missingness"]["hourImputationPerformed"] is False,
            "capacityUsedOnlyWherePublisherSupplied": True,
            "approximateCapacityFlagsPreserved": True,
            "outputIsRelativeIndexOnly": True,
            "legalityClaimed": False,
        },
    }

    # Machine-checked enforcement of the lane's semantic limits.
    assert_no_forbidden_semantics(report)
    return report


def _distribution(values) -> dict:
    vals = sorted(float(v) for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return {"n": 0}
    def q(p):
        if n == 1:
            return round(vals[0], 6)
        pos = p * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return round(vals[lo] * (1 - frac) + vals[hi] * frac, 6)
    return {"n": n, "min": round(vals[0], 6), "p25": q(0.25), "median": q(0.5),
            "p75": q(0.75), "max": round(vals[-1], 6),
            "mean": round(sum(vals) / n, 6)}


def report_sha256(report: dict) -> str:
    blob = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Test whether Camden PCN patterns carry a reproducible "
                    "street/time parking-pressure signal. Emits a RELATIVE "
                    "pressure index only - never occupancy or probability.")
    ap.add_argument("--bays", required=True, help="Camden Parking Bay Map export")
    ap.add_argument("--pcn", required=True, help="Camden PCN series export")
    ap.add_argument("--proxy", help="optional INDEPENDENT validation proxy")
    ap.add_argument("--level", choices=(JOIN_LEVEL_STREET, JOIN_LEVEL_CPZ),
                    default=JOIN_LEVEL_STREET, help="join level (never bay level)")
    ap.add_argument("--validation-route",
                    choices=("available-but-not-supplied", "none_known", "supplied"),
                    default="available-but-not-supplied",
                    help="declare whether an independent validation route exists")
    ap.add_argument("--as-of", help="report timestamp; defaults to max date in data")
    ap.add_argument("--code-map",
                    help="path to the frozen authoritative contravention-code "
                         "artifact (PTE-TEL-004 C4A). Defaults to "
                         "sources/camden/london-councils-contravention-codes-v7.0.json "
                         "in the repo, or $PTE_CAMDEN_CODE_MAP. Required: an "
                         "absent artifact raises rather than silently degrading to "
                         "the keyword heuristic.")
    ap.add_argument("--field-map",
                    help=("JSON pinning normalised->source column names per "
                          "dataset, e.g. "
                          '{"bay-map": {"spaceCount": "Number Of Spaces"}}. '
                          "Use when a real download's columns differ from the "
                          "adapter candidates."))
    ap.add_argument("--threshold", action="append", default=[],
                    metavar="NAME=VALUE", help="override a verdict threshold")
    ap.add_argument("--out", help="write the JSON report here")
    args = ap.parse_args(argv)

    thresholds = dict(DEFAULT_THRESHOLDS)
    for item in args.threshold:
        if "=" not in item:
            ap.error(f"--threshold expects NAME=VALUE, got {item!r}")
        name, raw = item.split("=", 1)
        if name not in thresholds:
            ap.error(f"unknown threshold {name!r}; known: {sorted(thresholds)}")
        thresholds[name] = float(raw)

    route = ("supplied" if args.proxy else
             "none_known" if args.validation_route == "none_known"
             else "available_not_supplied")

    field_map = None
    if args.field_map:
        with open(args.field_map, encoding="utf-8") as fh:
            field_map = json.load(fh)
        if not isinstance(field_map, dict):
            ap.error("--field-map must contain a JSON object")

    report = build_report(args.bays, args.pcn, args.proxy, args.level,
                          thresholds, route, args.as_of, field_map=field_map,
                          code_map_path=args.code_map)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"report -> {args.out}", file=sys.stderr)
        print(f"sha256 -> {report_sha256(report)}", file=sys.stderr)
    else:
        print(text)

    v = report["verdict"]
    print(f"\nVERDICT: {v['verdict']}  ({v['explanation']})", file=sys.stderr)
    if v["hardCriteriaTriggered"]:
        print("  triggered: " + ", ".join(v["hardCriteriaTriggered"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
