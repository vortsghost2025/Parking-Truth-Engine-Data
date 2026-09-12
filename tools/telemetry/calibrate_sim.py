#!/usr/bin/env python3
"""
PTE Simulator Calibration — real measured distributions drive the synthetic feed
================================================================================

WHY
---
Synthetic telemetry is only defensible if its statistics are real and cited.
This tool reads the aggregates produced by telemetry_harvester.py over a REAL
parking-event archive and derives a calibration file that sim_feed.py consumes.

That replaces sim_feed.py's hand-written demand curve with measured behaviour
from ~14M-246M real City of Melbourne parking events.

THE ACTUAL METHOD: LITTLE'S LAW
-------------------------------
You cannot measure occupancy directly from an event archive - the archive records
arrivals and departures, not "how many bays were full at 14:00". But occupancy
follows from arrivals and durations without any modelling assumption:

    L = lambda * W

    L      = mean number of bays occupied
    lambda = mean arrival rate
    W      = mean time spent parked

Per hour of day h:

    lambda_h = arrivals_in_hour_h / (distinct_bays * distinct_dates)
    rho_h    = lambda_h * W_h          # expected occupancy FRACTION, 0..1

This is a queueing identity, not a fitted curve. It holds in steady state, so the
tool reports how far from steady state the source period is (a pandemic-distorted
archive like Jan-May 2020 violates it more than a normal year) and clips rho to a
safe maximum rather than letting it exceed 1.

Stay durations are exported as a percentile inverse-CDF so the simulator samples
the MEASURED distribution instead of an invented lognormal.

OUTPUT
------
    calibration.json   consumed by: sim_feed.py --calibration calibration.json

STDLIB ONLY. Python 3.8+.

    # 1. harvest a real archive
    python3 ../telemetry/telemetry_harvester.py archive --year 2020-jan-may \
        --max-emit 250000 --out out/archive

    # 2. derive the calibration
    python3 calibrate_sim.py --stats out/archive/archive-stats.json \
        --out out/calibration.json

    # 3. run the simulator on measured behaviour
    python3 ../realtime-sim/sim_feed.py --calibration out/calibration.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = 1
# Steady-state identity cannot yield rho > 1; clip below it so the simulator
# always leaves some bays free and never asserts a physically impossible state.
RHO_CLIP = 0.985


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def percentile_table(seconds_samples):
    """Explicit inverse-CDF knots for the simulator to sample from."""
    if not seconds_samples:
        return None
    v = sorted(seconds_samples)
    n = len(v)
    knots = [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0]
    table = []
    for q in knots:
        idx = min(n - 1, max(0, int(q * (n - 1))))
        table.append({"q": q, "seconds": round(v[idx], 1)})
    return table


def build_calibration(stats, events=None, min_bays=1, label=None):
    agg = stats.get("aggregate", {}) or {}
    stay = agg.get("stayDurationSeconds") or {}
    by_hour = agg.get("eventsByArrivalHourUtc") or {}
    # Little's Law requires the MEAN stay, not the median. Prefer the mean where
    # the harvester supplied it and say which one was used.
    by_hour_mean = agg.get("meanStayMinutesByArrivalHourUtc") or {}
    by_hour_median = agg.get("medianStayMinutesByArrivalHourUtc") or {}
    stay_stat_used = "mean" if by_hour_mean else ("median" if by_hour_median else None)
    by_hour_stay = by_hour_mean or by_hour_median
    restrictions = agg.get("topRestrictions") or []
    overstay = agg.get("overstayBreakdown") or {}
    defects = agg.get("dataQualityDefects") or {}
    trange = agg.get("timeRangeUtc") or {}

    warnings = []

    distinct_bays = agg.get("distinctBays") or 0
    distinct_dates = agg.get("distinctArrivalDates") or 0
    total_events = stats.get("rowsRead") or 0
    sample_size = stay.get("sampledRows") or 0

    if distinct_bays < min_bays or distinct_bays == 0:
        warnings.append(
            "distinctBays is missing or zero; Little's Law cannot be applied. "
            "Re-run telemetry_harvester.py (current version tracks it).")
    if distinct_dates == 0:
        warnings.append("distinctArrivalDates is zero; arrival rate cannot be "
                        "normalised per day.")
    if sample_size == 0:
        warnings.append("No positive stay durations found; the stay distribution "
                        "will fall back to the simulator's built-in default.")

    # ---- Little's Law ---------------------------------------------------- #
    mean_stay_hours = (stay.get("mean") or 0.0) / 3600.0 if stay else 0.0
    lam_by_hour = {}
    rho_by_hour = {}
    if distinct_bays and distinct_dates:
        bay_days = distinct_bays * distinct_dates
        for h in range(24):
            c = int(by_hour.get(str(h), 0))
            lam = c / bay_days                     # arrivals per bay per hour h
            # per-hour mean stay where measured, else the overall mean
            w_h = None
            if str(h) in by_hour_stay:
                w_h = by_hour_stay[str(h)] / 60.0
            if not w_h or w_h <= 0:
                w_h = mean_stay_hours
            lam_by_hour[h] = lam
            rho = lam * w_h
            if rho > RHO_CLIP:
                warnings.append(
                    f"rho for hour {h} computed as {rho:.3f} > {RHO_CLIP}; "
                    f"clipped. Indicates non-steady-state demand, more arrivals "
                    f"than bays can hold, or an undercounted bay population.")
                rho = RHO_CLIP
            rho_by_hour[h] = round(max(0.0, rho), 4)
    else:
        warnings.append("Occupancy curve NOT derived - insufficient metadata.")

    # ---- stay distribution as inverse-CDF -------------------------------- #
    inv_cdf = None
    if events:
        secs = []
        cap = 200000
        for ev in events:
            d = ev.get("durationSeconds")
            if isinstance(d, (int, float)) and d > 0:
                secs.append(d)
                if len(secs) >= cap:
                    break
        inv_cdf = percentile_table(secs)
        if inv_cdf:
            warnings.append("inverse-CDF built from the emitted JSONL sample, "
                            "which is capped by --max-emit; percentiles in "
                            "aggregate.stayDurationSeconds cover ALL rows and "
                            "are the more trustworthy figure.")
    if not inv_cdf and stay:
        # fall back to the all-rows percentiles already in stats
        inv_cdf = [
            {"q": 0.0,  "seconds": stay.get("min")},
            {"q": 0.25, "seconds": stay.get("p25")},
            {"q": 0.5,  "seconds": stay.get("median")},
            {"q": 0.75, "seconds": stay.get("p75")},
            {"q": 0.95, "seconds": stay.get("p95")},
            {"q": 0.99, "seconds": stay.get("p99")},
            {"q": 1.0,  "seconds": stay.get("max")},
        ]
        inv_cdf = [k for k in inv_cdf if k["seconds"] is not None]

    # ---- restriction mix -------------------------------------------------- #
    restr_total = sum(c for _, c in restrictions) or 0
    restriction_mix = ({k: round(c / restr_total, 4) for k, c in restrictions}
                       if restr_total else {})
    if restr_total:
        covered = sum(c for _, c in restrictions)
        if covered < total_events * 0.99:
            warnings.append(
                "restrictionMix is built from topRestrictions only (the "
                "harvester caps this list at 25); shares are of the top-N total, "
                "not of all rows.")

    # ---- overstay rate ---------------------------------------------------- #
    overstay_rate = None
    ov_true = sum(v for k, v in overstay.items() if k.lower() in {"true", "yes"})
    ov_false = sum(v for k, v in overstay.items() if k.lower() in {"false", "no"})
    if ov_true + ov_false:
        overstay_rate = round(ov_true / (ov_true + ov_false), 4)

    # ---- provenance ------------------------------------------------------- #
    prov = {
        "derivedFromStatsFile": stats.get("_sourceFile"),
        "sourceUrl": stats.get("sourceUrl"),
        "sourceFile": stats.get("sourceFile"),
        "sourceKind": stats.get("sourceKind"),
        "sourceSha256": stats.get("sha256"),
        "sourceBytes": stats.get("bytes"),
        "sourceMode": stats.get("mode"),
        "harvestRetrievedAt": stats.get("retrievedAt"),
        "sourceTimeRange": trange,
        "rowsRead": total_events,
        "stayDurationSampleRows": sample_size,
        "distinctBays": distinct_bays,
        "distinctArrivalDates": distinct_dates,
        "bayDays": distinct_bays * distinct_dates if distinct_bays and distinct_dates else None,
        "skippedRows": stats.get("skipped"),
    }

    cal = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": now_iso(),
        "generator": "tools/telemetry/calibrate_sim.py",
        "label": label or (stats.get("sourceId") or "unlabelled"),
        "method": {
            "occupancyCurve": "Little's Law: rho_h = lambda_h * W_h, where "
                              "lambda_h = arrivals_in_hour_h / (distinct_bays * "
                              "distinct_dates) and W_h is the mean stay in hour h. "
                              "A queueing identity, not a fitted curve.",
            "stayDistribution": "empirical inverse-CDF of measured positive "
                                "durations; the simulator interpolates between knots",
            "stayStatisticUsed": stay_stat_used,
            "stayStatisticNote": ("W is the MEAN stay per hour, as the identity "
                                  "requires." if stay_stat_used == "mean" else
                                  "W fell back to the MEDIAN stay because the "
                                  "harvester did not supply per-hour means. Parking "
                                  "durations are right-skewed, so rho is "
                                  "UNDERESTIMATED - re-run with a current "
                                  "telemetry_harvester.py."
                                  if stay_stat_used == "median" else
                                  "No per-hour stay statistic available; the "
                                  "overall mean was used for every hour."),
            "steadyStateAssumption": "Little's Law holds in steady state. A "
                                     "pandemic-distorted or partial-year archive "
                                     "violates it more than a normal year. rho is "
                                     f"clipped at {RHO_CLIP}.",
            "timezoneCaveat": "Hours are as published by the source. If the "
                              "publisher's timestamps are local and were labelled "
                              "UTC by the harvester, the curve is shifted. Verify "
                              "before trusting hour-of-day behaviour.",
        },
        "provenance": prov,
        "occupancyCurveByHour": [rho_by_hour.get(h, 0.0) for h in range(24)],
        "arrivalRatePerBayHour": [round(lam_by_hour.get(h, 0.0), 6) for h in range(24)],
        "stayDurationSeconds": {
            "percentiles": {k: stay.get(k) for k in
                            ("min", "p25", "median", "p75", "p95", "p99", "max",
                             "mean")} if stay else None,
            "meanMinutes": stay.get("meanMinutes"),
            "medianMinutes": stay.get("medianMinutes"),
            "inverseCdf": inv_cdf,
        },
        "restrictionMix": restriction_mix,
        "overstayRate": overstay_rate,
        "dataQualityDefectRates": {
            k: round(v / total_events, 6) if total_events else None
            for k, v in defects.items()
        },
        "dataQualityDefectCounts": defects,
        "eventsByArrivalHour": {str(h): int(by_hour.get(str(h), 0)) for h in range(24)},
        "eventsByWeekday": agg.get("eventsByWeekday") or {},
        "topStreets": agg.get("topStreets") or [],
        "warnings": warnings,
        "usable": bool(rho_by_hour and inv_cdf),
        "legalityClaimed": False,
        "note": "AVAILABILITY lane only. restrictionMix and overstayRate are "
                "descriptive statistics about past behaviour. They are NOT "
                "legality inputs and must not be used to decide whether a curb "
                "is legal to park on.",
    }
    return cal


def load_events(path, cap=None):
    out = []
    with open(path) as fh:
        for i, line in enumerate(fh):
            if cap and i >= cap:
                break
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", required=True,
                    help="archive-stats.json (or live-harvest-stats.json) from "
                         "telemetry_harvester.py")
    ap.add_argument("--events", default=None,
                    help="optional telemetry-events.jsonl for a finer inverse-CDF")
    ap.add_argument("--events-cap", type=int, default=200000)
    ap.add_argument("--label", default=None)
    ap.add_argument("--out", default="calibration.json")
    args = ap.parse_args()

    if not os.path.exists(args.stats):
        raise SystemExit(f"no stats file at {args.stats}")
    with open(args.stats) as fh:
        stats = json.load(fh)
    stats["_sourceFile"] = os.path.abspath(args.stats)

    events = None
    if args.events:
        if not os.path.exists(args.events):
            raise SystemExit(f"no events file at {args.events}")
        events = load_events(args.events, cap=args.events_cap)

    cal = build_calibration(stats, events=events, label=args.label)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(cal, fh, indent=2)

    curve = cal["occupancyCurveByHour"]
    inv = cal["stayDurationSeconds"]["inverseCdf"] or []
    print("=" * 74)
    print("CALIBRATION DERIVED FROM REAL PARKING-EVENT DATA")
    print("=" * 74)
    print(f"  label            : {cal['label']}")
    print(f"  source sha256    : {cal['provenance']['sourceSha256']}")
    print(f"  rows read        : {cal['provenance']['rowsRead']:,}")
    print(f"  distinct bays    : {cal['provenance']['distinctBays']:,}")
    print(f"  distinct dates   : {cal['provenance']['distinctArrivalDates']}")
    print(f"  bay-days         : {cal['provenance']['bayDays']}")
    if inv:
        med = next((k["seconds"] for k in inv if k["q"] == 0.5), None)
        p95 = next((k["seconds"] for k in inv if k["q"] == 0.95), None)
        if med: print(f"  median stay      : {med/60.0:.1f} min")
        if p95: print(f"  p95 stay         : {p95/60.0:.1f} min")
    print(f"  overstay rate    : {cal['overstayRate']}")
    print(f"  defect rates     : {cal['dataQualityDefectRates']}")
    print("-" * 74)
    print("  occupancy curve by hour (Little's Law, rho = lambda * W):")
    peak_h = max(range(24), key=lambda h: curve[h]) if any(curve) else None
    for row in range(0, 24, 6):
        cells = "  ".join(f"{h:02d}h={curve[h]:.3f}" for h in range(row, min(row + 6, 24)))
        print(f"    {cells}")
    if peak_h is not None and any(curve):
        print(f"    peak hour: {peak_h:02d}:00 at rho={curve[peak_h]:.3f}")
    print("-" * 74)
    if cal["warnings"]:
        print(f"  WARNINGS ({len(cal['warnings'])}):")
        for w in cal["warnings"]:
            print(f"    - {w}")
    else:
        print("  no warnings")
    print(f"  usable           : {cal['usable']}")
    print(f"  written          : {args.out}")
    print("=" * 74)
    if not cal["usable"]:
        print("NOT USABLE - fix the warnings above before feeding this to the "
              "simulator.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
