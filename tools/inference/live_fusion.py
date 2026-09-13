#!/usr/bin/env python3
"""Live fusion — layer 2 on top of the climatological availability model.

    tools/inference/availability_engine.py  -> what a street USUALLY does
    tools/inference/live_fusion.py          -> what it is doing RIGHT NOW

WHY TWO LAYERS
--------------
The climatological model is strong on the average and blind to the exception. It
knows Bourke St at 15:00 on a weekday is ~65% free; it cannot know that today
there is a match, or roadworks, or that it is raining and nobody has left. Live
sensors are the opposite: exact about now, absent almost everywhere, and silent
about what happens next.

Fusing them is the product. And the fusion has to work in the case that actually
matters commercially - a street where only SOME bays are sensed, or none are.

THE CENTRAL QUESTION
--------------------
Given partial sensing, what can we say about the bays we cannot see?

Answered by Bayesian update, not by a hand-tuned blend:

    prior     Beta(a0, b0)   moment-matched to the climatological cell's
                             predictive distribution for a single day
    likelihd  Binomial(m, rho) over the m bays actually sensed
    posterior Beta(a0 + w*j, b0 + w*(m-j))

The weights fall out of the arithmetic. A street with 5 sensed bays barely moves
the prior; a street with 200 overrides it. Nobody has to decide how much to
trust sensors - the sample size decides.

FRESHNESS IS NOT A HEURISTIC
----------------------------
A sensor reading decays because CARS LEAVE. So the decay constant is the measured
stay duration, not an arbitrary TTL:

    w = 0.5 ** (age_minutes / median_stay_minutes)

A reading as old as the median stay has a ~50% chance of describing a car that
has already gone. This ties staleness to observed behaviour and means a city
with 2-hour stays tolerates older feeds than a city with 20-minute turnover.

WHAT IS MEASURED, NOT ASSUMED
-----------------------------
`validate-fusion` reconstructs the true instantaneous occupancy of every bay on
held-out dates, then HIDES a fraction of the bays and asks the fusion to predict
them. It scores against the UNSERVED bays only - predicting bays you can see is
not a claim worth making. Sweep coverage 0% -> 100% and compare three predictors:
climatology alone, raw sensor proportion, and fusion.

It also splits the score into typical days and ATYPICAL days (where reality
deviates from the climatological pattern), because that split is where the
commercial argument actually lives.

STDLIB ONLY. No network needed for validation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import zlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from availability_engine import (          # noqa: E402
    DEFAULT_SD_DAY, HIGH_LOWER_BOUND, MIN_DATES_FOR_HIGH, MIN_DATES_FOR_LIMITED,
    MIN_SLOTS_FOR_STATE, SLOT_MINUTES, betainc, build_model, cell_for, day_type,
    load_events, state_from,
)

# Sensed bays may not be a random sample of a street - municipalities install
# sensors on the blocks they care about. This SD is added in quadrature when
# predicting bays that were NOT sensed, so the interval admits the possibility
# that the sensed subset is unrepresentative.
DEFAULT_SENSOR_BIAS_SD = 0.05

# How loudly the two SOURCES must disagree before it is reported as a conflict
# rather than silently blended into a posterior.
#
# This is a z-score on the difference between the live-only occupancy estimate
# and the climatological one, NOT the size of the posterior shift. Measuring the
# posterior shift is the wrong quantity and fails silently: a strong prior damps
# the shift, so a genuine disagreement can be averaged away without ever
# tripping the detector. The z-score compares the sources on their own terms and
# is invariant to how much weight the prior carries.
CONFLICT_Z = 3.0
CONFLICT_MIN_LIVE = 10


# --------------------------------------------------------------------------- #
# prior construction
# --------------------------------------------------------------------------- #

def beta_from_moments(mean: float, var: float):
    """Moment-match a Beta distribution to a mean and variance.

    Beta(a,b) has mean a/(a+b) and variance mean*(1-mean)/(a+b+1), so
    nu = a+b+1 = mean*(1-mean)/var. nu is the prior's EFFECTIVE SAMPLE SIZE in
    bay-observations: it says how many sensed bays would be needed to shift the
    prior by half. Deriving it from the measured predictive spread means a
    street the model is unsure about yields to live data quickly, and a street
    it knows well does not.
    """
    mean = min(max(mean, 1e-6), 1.0 - 1e-6)
    if var <= 0:
        var = DEFAULT_SD_DAY ** 2
    max_var = mean * (1.0 - mean)          # variance of a Bernoulli; Beta cap
    var = min(var, max_var * 0.999)
    nu = mean * (1.0 - mean) / var
    nu = max(1e-3, min(nu, 1e7))
    return mean * nu, (1.0 - mean) * nu, nu


def freshness_weight(age_minutes: float, median_stay_minutes: float) -> float:
    """Discount a sensor reading by how many median-stays old it is."""
    if age_minutes <= 0:
        return 1.0
    if median_stay_minutes <= 0:
        return 1.0
    return 0.5 ** (age_minutes / median_stay_minutes)


# --------------------------------------------------------------------------- #
# the fusion itself
# --------------------------------------------------------------------------- #

def fuse(prior_pfree: float, prior_sd: float, n_sensed: int, n_occupied: int,
         weight: float = 1.0, sensor_bias_sd: float = DEFAULT_SENSOR_BIAS_SD,
         dates_used: int = 0, effective_slots: float = 0.0):
    """Combine one climatological cell with one live snapshot of a street.

    Returns the posterior P(free) for the street's bays - including the ones
    nobody can see - with an interval that accounts for estimation uncertainty,
    day-to-day dispersion, sensor staleness and possible sensor bias.
    """
    rho0 = 1.0 - min(max(prior_pfree, 0.0), 1.0)
    a0, b0, nu = beta_from_moments(rho0, prior_sd ** 2 if prior_sd > 0 else None)

    m_eff = max(0.0, n_sensed) * weight
    j_eff = max(0.0, min(n_occupied, n_sensed)) * weight
    f_eff = max(0.0, m_eff - j_eff)

    a, b = a0 + j_eff, b0 + f_eff
    ab = a + b
    rho_post = a / ab if ab > 0 else rho0
    var_beta = (a * b) / (ab * ab * (ab + 1.0)) if ab > 0 else 0.0

    p_free = 1.0 - rho_post
    # Sensed bays get the Beta interval alone. Unsensed bays additionally carry
    # the risk that the sensed subset is not representative of the street.
    sd_sensed = math.sqrt(var_beta)
    sd_unsensed = math.sqrt(var_beta + sensor_bias_sd ** 2)

    live_share = m_eff / (m_eff + nu) if (m_eff + nu) > 0 else 0.0
    shift = rho_post - rho0

    # Disagreement between the two sources, in units of their combined
    # uncertainty. Only meaningful once enough bays are actually sensed.
    z = None
    rho_live = None
    if m_eff >= CONFLICT_MIN_LIVE:
        rho_live = j_eff / m_eff
        var_live = rho_live * (1.0 - rho_live) / m_eff
        denom = math.sqrt(var_live + (prior_sd ** 2 if prior_sd > 0 else 0.0))
        if denom > 0:
            z = (rho_live - rho0) / denom

    return {
        "liveOccupancy": rho_live,
        "liveVsClimatologyZ": (round(z, 3) if z is not None else None),
        "pFree": p_free,
        "pFree95": (max(0.0, min(1.0, p_free - 1.96 * sd_unsensed)),
                    max(0.0, min(1.0, p_free + 1.96 * sd_unsensed))),
        "sdSensed": sd_sensed,
        "sdUnsensed": sd_unsensed,
        "priorOccupancy": rho0,
        "posteriorOccupancy": rho_post,
        "priorEffectiveSampleSize": nu,
        "liveEffectiveSampleSize": m_eff,
        "liveShareOfPosterior": live_share,
        "shiftFromClimatology": shift,
        "conflict": bool(z is not None and abs(z) >= CONFLICT_Z),
        "datesUsed": dates_used,
        "effectiveSlots": effective_slots,
    }


def fused_state(res: dict, has_live: bool):
    """The layer-1 contract, plus a fourth state for contradictory evidence.

    HIGH  - the interval resolves the question, and enough independent evidence
            stands behind it. Two-sided: a street that is confidently FULL is
            HIGH just as much as one that is confidently free.
    LIMITED - there is a real estimate, but the interval straddles the ambiguous
            middle, or the evidence is thin.
    CONFLICT - live sensors and climatology disagree by more than CONFLICT_Z
            combined SDs. The blended number is still returned, because a
            conflict is information rather than a refusal to answer, but it is
            never presented as HIGH confidence.
    UNKNOWN - no climatology and no usable sensors.
    """
    if res.get("conflict"):
        return "CONFLICT"

    has_climatology = bool(res.get("effectiveSlots")) or res.get("datesUsed", 0) > 0
    if not has_live and not has_climatology:
        return "UNKNOWN"
    if not has_live and res.get("datesUsed", 0) < MIN_DATES_FOR_LIMITED:
        return "UNKNOWN"          # history too thin and nothing live to lean on

    lo, hi = res["pFree95"]
    decisive = lo > HIGH_LOWER_BOUND or hi < (1.0 - HIGH_LOWER_BOUND)
    if not decisive:
        return "LIMITED"

    # Enough independent evidence behind a decisive interval?
    total_indep = res["liveEffectiveSampleSize"] + \
        (res["effectiveSlots"] if res["datesUsed"] >= MIN_DATES_FOR_HIGH else 0.0)
    if total_indep < MIN_SLOTS_FOR_STATE:
        return "LIMITED"
    if res["datesUsed"] >= MIN_DATES_FOR_HIGH or res["liveEffectiveSampleSize"] >= 50:
        return "HIGH"
    return "LIMITED"


# --------------------------------------------------------------------------- #
# live snapshot input
# --------------------------------------------------------------------------- #

def _to_epoch(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(v), fmt).replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def load_live(source: str):
    """Read a live bay snapshot.

    Accepts:
      * the realtime-sim feed's /api/bays.geojson (bayId, street, status,
        sensable, sensorOk, observedAt)
      * a plain JSON list/object of {"bayKey","street","state","observedAt"}
      * a JSONL file of the same
      * "-" for stdin

    Returns (observations, now_epoch). Each observation is
    {bayKey, street, state in FREE|OCCUPIED|UNKNOWN, observedAt, usable}.
    """
    if source == "-":
        raw = sys.stdin.read()
    elif source.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(source, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    else:
        with open(source, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()

    obs, now = [], None
    raw_s = raw.lstrip()
    if raw_s.startswith("{") or raw_s.startswith("["):
        data = json.loads(raw)
        items = (data.get("features") if isinstance(data, dict) else data) or []
        for it in items:
            p = it.get("properties", it) if isinstance(it, dict) else {}
            if not isinstance(p, dict):
                continue
            bay = p.get("bayId") or p.get("bayKey") or p.get("marker_id")
            street = p.get("street") or p.get("Street") or "UNKNOWN_STREET"
            state = (p.get("status") or p.get("state") or "").upper()
            if state in ("OCCUPIED", "TAKEN", "IN_USE"):
                state = "OCCUPIED"
            elif state in ("FREE", "AVAILABLE", "VACANT"):
                state = "FREE"
            else:
                state = "UNKNOWN"
            # A bay that is not sensable, or whose sensor has failed, is not
            # evidence. Counting it as FREE would be the single most damaging
            # mistake available here.
            sensable = p.get("sensable", True)
            sensor_ok = p.get("sensorOk", True)
            t = _to_epoch(p.get("observedAt") or p.get("lastUpdated"))
            if t is not None:
                now = t if now is None else max(now, t)
            obs.append({"bayKey": bay or f"{street}|{len(obs)}",
                        "street": street, "state": state, "observedAt": t,
                        "usable": bool(state != "UNKNOWN" and sensable
                                       and sensor_ok and bay)})
    else:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            state = (p.get("state") or p.get("status") or "").upper()
            state = ("OCCUPIED" if state.startswith("OCC") else
                     "FREE" if state.startswith(("FREE", "AVAIL")) else "UNKNOWN")
            t = _to_epoch(p.get("observedAt"))
            if t is not None:
                now = t if now is None else max(now, t)
            obs.append({"bayKey": p.get("bayKey") or p.get("bayId"),
                        "street": p.get("street") or "UNKNOWN_STREET",
                        "state": state, "observedAt": t,
                        "usable": bool(state != "UNKNOWN" and
                                       (p.get("bayKey") or p.get("bayId")))})
    return obs, now


def summarise_live(obs, now, median_stay_minutes, sensor_bias_sd):
    """Collapse per-bay observations into per-street evidence."""
    by_street = defaultdict(lambda: {"sensed": 0, "occupied": 0, "free": 0,
                                     "unknown": 0, "weight_sum": 0.0,
                                     "ages": []})
    for o in obs:
        s = by_street[o["street"]]
        if not o["usable"]:
            s["unknown"] += 1
            continue
        age_min = ((now - o["observedAt"]) / 60.0
                   if (now and o["observedAt"]) else 0.0)
        age_min = max(0.0, age_min)
        w = freshness_weight(age_min, median_stay_minutes)
        s["sensed"] += 1
        s["weight_sum"] += w
        s["ages"].append(age_min)
        if o["state"] == "OCCUPIED":
            s["occupied"] += 1
        else:
            s["free"] += 1
    out = {}
    for street, s in by_street.items():
        avg_w = (s["weight_sum"] / s["sensed"]) if s["sensed"] else 0.0
        out[street] = {
            "sensedBays": s["sensed"], "occupied": s["occupied"],
            "free": s["free"], "unknownBays": s["unknown"],
            "meanFreshnessWeight": avg_w,
            "effectiveSensedBays": s["weight_sum"],
            "meanAgeMinutes": (sum(s["ages"]) / len(s["ages"])) if s["ages"] else 0.0,
        }
    return out


# --------------------------------------------------------------------------- #
# MODE: fuse
# --------------------------------------------------------------------------- #

def cmd_fuse(args):
    with open(args.model) as fh:
        model = json.load(fh)
    obs, now = load_live(args.live)
    if now is None:
        now = datetime.now(timezone.utc).timestamp()

    median_stay = args.median_stay
    if median_stay is None:
        st = model.get("stayStatistics") or {}
        median_stay = st.get("medianMinutes") or 28.0

    dt = (datetime.strptime(args.at.replace(" ", "T"), "%Y-%m-%dT%H:%M")
          .replace(tzinfo=timezone.utc) if args.at
          else datetime.fromtimestamp(now, timezone.utc))
    # Age a reading against the instant being PREDICTED, not against the
    # snapshot's own clock. Asking "what is it like at 12:30?" using a feed that
    # stopped updating at 03:30 means every reading is nine hours stale, and a
    # nine-hour-old reading in a city with a 28-minute median stay carries almost
    # no information. Measuring age against the snapshot time instead would
    # score it as brand new and let it override the climatology outright.
    live = summarise_live(obs, dt.timestamp(), median_stay, args.sensor_bias_sd)

    if args.street:
        streets = [x.strip() for x in args.street.split(",") if x.strip()]
    else:
        # Union, not just the streets that appear in the live feed. A feed with
        # no coverage at all - or one that only instruments part of the city -
        # must still produce climatological answers for every street the model
        # knows. Reporting nothing because the sensors are silent is the worst
        # possible failure mode: it looks like the street does not exist.
        known = set(live)
        for k in model.get("cells", {}):
            known.add(k.split("|")[0])
        streets = sorted(known)
    results = []
    for street in streets:
        street = street.strip()
        dt_type, hour = day_type(dt), dt.hour
        cell = cell_for(model, street, dt)
        used_fallback = False
        if cell is None:
            from availability_engine import fallback_for
            cell = fallback_for(model, dt)
            used_fallback = cell is not None
        lv = live.get(street, {})
        has_live = lv.get("sensedBays", 0) > 0
        if cell is None and not has_live:
            results.append({"street": street, "at": dt.isoformat(),
                            "availability": "UNKNOWN",
                            "reason": "no climatology and no live sensors"})
            continue
        if cell is None:
            # No history at all, but sensors exist. Prior is uninformative.
            prior_pfree, prior_sd = 0.5, 0.25
        else:
            prior_pfree = cell["pFree"]
            prior_sd = cell.get("sdPredictive") or DEFAULT_SD_DAY
        res = fuse(prior_pfree, prior_sd,
                   lv.get("sensedBays", 0), lv.get("occupied", 0),
                   weight=lv.get("meanFreshnessWeight", 1.0),
                   sensor_bias_sd=args.sensor_bias_sd,
                   dates_used=(cell or {}).get("datesUsed", 0),
                   effective_slots=(cell or {}).get("effectiveSlots", 0.0))
        res.update({
            "street": street, "at": dt.isoformat(),
            "dayType": dt_type, "hour": hour,
            "availability": fused_state(res, has_live),
            "live": lv or {"sensedBays": 0},
            "climatologyUsed": not used_fallback,
            "usedCityPriorFallback": used_fallback,
            "medianStayMinutes": median_stay,
            "legalityClaimed": False,
            "separationNote": "Availability only. A HIGH fused estimate cannot "
                              "make an illegal, conflicted or unknown curb legal.",
        })
        results.append(res)

    if args.json:
        json.dump({"generatedAt": datetime.now(timezone.utc).isoformat(),
                   "liveSource": args.live, "observedAt": now,
                   "medianStayMinutes": median_stay, "results": results},
                  sys.stdout, indent=2, default=str)
        print()
        return 0

    print("=" * 78)
    print("FUSED AVAILABILITY  —  climatology + live sensors")
    print("=" * 78)
    print(f"  live source        : {args.live}")
    print(f"  snapshot time      : {datetime.fromtimestamp(now, timezone.utc).isoformat()}")
    print(f"  predicting for     : {dt.isoformat()}")
    age = (dt.timestamp() - now) / 60.0
    if age > 1:
        print(f"  SNAPSHOT AGE       : {age:.0f} min "
              f"= {age / median_stay:.1f} median stays -> readings are being "
              f"discounted accordingly")
    print(f"  median stay        : {median_stay} min (freshness half-life)")
    print(f"  climatology model  : {args.model}")
    print("-" * 78)
    print(f"  {'street':<22}{'state':<9}{'P(free)':>9}{'95% CI':>17}"
          f"{'sensed':>8}{'live wt':>9}{'clim':>7}")
    print("-" * 78)
    for r in results:
        if "pFree" not in r:
            print(f"  {r['street']:<22}{r['availability']:<9}  {r.get('reason','')}")
            continue
        lo, hi = r["pFree95"]
        lv = r["live"]
        print(f"  {r['street'][:22]:<22}{r['availability']:<9}{r['pFree']:>9.3f}"
              f"{'[%.3f,%.3f]' % (lo, hi):>17}"
              f"{lv.get('sensedBays', 0):>8}{lv.get('meanFreshnessWeight', 0):>9.2f}"
              f"{1 - r['liveShareOfPosterior']:>7.2f}")
        z = r.get("liveVsClimatologyZ")
        if r["conflict"]:
            print(f"      CONFLICT (z={z:+.1f}): sensors say occupancy "
                  f"{r['liveOccupancy']:.3f}, climatology says "
                  f"{r['priorOccupancy']:.3f}. That gap is {abs(z):.1f} combined "
                  f"SDs - too large to be noise. The posterior "
                  f"({r['posteriorOccupancy']:.3f}) blends them, but the "
                  f"disagreement is reported rather than averaged away. Likely "
                  f"causes: an event, roadworks, weather, or a stale/faulty feed.")
        elif z is not None and abs(z) >= 2.0:
            print(f"      note: live vs climatology z={z:+.1f} - watch this street.")
        if lv.get("unknownBays"):
            print(f"      {lv['unknownBays']} bay(s) UNKNOWN/stale - excluded, "
                  f"NOT counted as free.")
    print("-" * 78)
    print("  'live wt' = mean freshness weight (1.0 = brand new, 0.5 = one")
    print("              median-stay old). 'clim' = share of the posterior still")
    print("              coming from history rather than sensors.")
    print(f"  Conflicts are flagged at |z| >= {CONFLICT_Z} between the LIVE-ONLY")
    print("  and CLIMATOLOGY-ONLY occupancy estimates. The z-score is used")
    print("  rather than the posterior shift because a strong prior damps the")
    print("  shift and would let a real disagreement pass unreported.")
    print("  AVAILABILITY ONLY. Says nothing about legality.")
    print("=" * 78)
    return 0


# --------------------------------------------------------------------------- #
# MODE: make-snapshot  (offline test input for `fuse`)
# --------------------------------------------------------------------------- #

def cmd_make_snapshot(args):
    """Emit a live-sensor snapshot reconstructed from an event archive.

    WHY. `fuse` needs a live feed, but a real one is only reachable from a
    machine with network access and a municipal endpoint that works. This
    reconstructs what sensors WOULD have reported on a given date and hour from
    the archive, at a chosen coverage, with sensor faults and staleness injected
    at realistic rates - so the fusion path can be exercised, and its failure
    modes provoked, entirely offline.

    The output is shaped like the realtime-sim feed's /api/bays.geojson, which is
    the format `fuse` already understands.
    """
    instant = datetime.strptime(args.at.replace(" ", "T"), "%Y-%m-%dT%H:%M")
    instant = instant.replace(tzinfo=timezone.utc)
    target = instant.timestamp()
    lo, hi = target - 3600, target + 3600

    street_bays = defaultdict(set)
    occupied = set()
    for ev in load_events(args.events, max_events=args.max_events):
        a, d, bay = ev["_a"], ev["_d"], ev.get("bayKey")
        street = ev.get("street") or "UNKNOWN_STREET"
        if not bay:
            continue
        street_bays[street].add(bay)
        if a <= target < d:
            occupied.add(bay)

    rng = random.Random(args.seed)
    cutoff = int(round(args.coverage * 10000))
    features = []
    counts = defaultdict(int)
    for street in sorted(street_bays):
        for bay in sorted(street_bays[street]):
            sensable = _stable_pick(bay, cutoff)
            counts["bays"] += 1
            if not sensable:
                counts["unsensed"] += 1
                continue
            is_occ = bay in occupied
            sensor_ok = rng.random() >= args.fault_rate
            age_min = 0.0
            if rng.random() < args.stale_rate:
                age_min = rng.uniform(5, 180)      # a feed that stopped updating
            counts["sensed"] += 1
            if not sensor_ok:
                counts["faulted"] += 1
                status = "UNKNOWN"
            elif age_min > 0:
                counts["stale"] += 1
                status = "OCCUPIED" if is_occ else "FREE"
            else:
                status = "OCCUPIED" if is_occ else "FREE"
            if status == "OCCUPIED":
                counts["occupied"] += 1
            observed = (instant - timedelta(minutes=age_min)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                "properties": {
                    "bayId": bay, "street": street, "status": status,
                    "sensable": True, "sensorOk": sensor_ok,
                    "observedAt": observed,
                    "synthetic": True,
                    "note": "RECONSTRUCTED FROM AN EVENT ARCHIVE FOR TESTING. "
                            "Not a live municipal feed.",
                },
            })

    doc = {"type": "FeatureCollection",
           "generatedAt": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "simulator": "pte-live-fusion-snapshot",
           "synthetic": True, "features": features}
    if args.out == "-":
        json.dump(doc, sys.stdout, indent=1)
        print()
    else:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            json.dump(doc, fh, indent=1)

    print("=" * 74, file=sys.stderr)
    print("SYNTHETIC LIVE SNAPSHOT  —  TEST INPUT, NOT A REAL FEED", file=sys.stderr)
    print("=" * 74, file=sys.stderr)
    print(f"  instant          : {instant.isoformat()}", file=sys.stderr)
    print(f"  bays / sensed    : {counts['bays']} / {counts['sensed']} "
          f"(coverage {args.coverage:.0%})", file=sys.stderr)
    print(f"  occupied         : {counts['occupied']}", file=sys.stderr)
    print(f"  faulted/stale    : {counts['faulted']} / {counts['stale']}",
          file=sys.stderr)
    print(f"  unsensed         : {counts['unsensed']}  <- these are what "
          f"fusion has to infer", file=sys.stderr)
    print(f"  written          : {args.out}", file=sys.stderr)
    print("=" * 74, file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# MODE: validate-fusion
# --------------------------------------------------------------------------- #

def _stable_pick(bay: str, cutoff: int) -> bool:
    """Deterministic pseudo-random bay selection, stable across runs and dates.

    A real sensor installation is FIXED - the same bays are instrumented every
    day. Selecting per-observation would leak and would not resemble reality.
    """
    return (zlib.crc32(bay.encode("utf-8")) % 10000) < cutoff


def instantaneous_truth(events_path, holdout_dates, max_events=None):
    """Reconstruct which bays were occupied at each (date, hour:30) instant.

    An hourly aggregate would smear a 10-minute stay across the whole hour and
    overstate occupancy. Sampling a single instant per hour gives a true
    snapshot, which is what a live sensor actually reports.
    """
    occupied = defaultdict(set)          # (date_s, hour) -> {bay}
    street_bays = defaultdict(set)       # street -> {bay}
    holdout = set(holdout_dates)
    for ev in load_events(events_path, max_events=max_events):
        a, d, bay = ev["_a"], ev["_d"], ev.get("bayKey")
        street = ev.get("street") or "UNKNOWN_STREET"
        if not bay or d <= a:
            continue
        street_bays[street].add(bay)
        # first :30 instant at or after arrival
        t = (int(a) // 3600) * 3600 + 1800
        if t < a:
            t += 3600
        while t < d:
            dtm = datetime.fromtimestamp(t, timezone.utc)
            date_s = dtm.strftime("%Y-%m-%d")
            if date_s in holdout:
                occupied[(date_s, dtm.hour)].add(bay)
            t += 3600
    return occupied, street_bays


def _scores(pairs):
    """pairs = [(predicted_pfree, true_pfree), ...]"""
    if not pairs:
        return None
    n = len(pairs)
    mae = sum(abs(p - t) for p, t in pairs) / n
    brier = sum((p - t) ** 2 for p, t in pairs) / n
    return {"n": n, "mae": round(mae, 5), "brier": round(brier, 6)}


def noise_floor(pairs_n):
    """Irreducible MAE from sampling a finite subset of bays.

    THE TRAP THIS AVOIDS. The target here is the occupancy of the UNSENSED bays.
    As sensor coverage rises, fewer bays remain unsensed, so the target itself
    gets noisier - and every predictor's MAE rises with it, including one that
    never changes. Without this floor the coverage sweep is unreadable: it looks
    like more sensing makes inference WORSE, when in fact the yardstick is just
    wobbling more.

    For n bays at occupancy p the sample fraction has SD sqrt(p(1-p)/n), and a
    predictor that knows p exactly still incurs E|X - p| = sqrt(2/pi) * SD.
    """
    if not pairs_n:
        return None
    tot = 0.0
    for p_hat, n_unsensed in pairs_n:
        if n_unsensed <= 0:
            continue
        p_hat = min(max(p_hat, 0.0), 1.0)
        tot += math.sqrt(2.0 / math.pi) * math.sqrt(p_hat * (1.0 - p_hat) / n_unsensed)
    return round(tot / len(pairs_n), 5)


def cmd_validate_fusion(args):
    # ---- date split, identical rule to the climatological validation ------- #
    import random as _random
    all_dates = set()
    for ev in load_events(args.events, max_events=args.scan_only):
        all_dates.add(datetime.fromtimestamp(ev["_a"], timezone.utc)
                      .strftime("%Y-%m-%d"))
    all_dates = sorted(all_dates)
    rng = _random.Random(args.seed)
    shuffled = all_dates[:]
    rng.shuffle(shuffled)
    n_hold = max(1, int(round(len(shuffled) * args.holdout)))
    holdout = sorted(shuffled[:n_hold])
    train = sorted(set(all_dates) - set(holdout))

    print("=" * 78)
    print("LIVE-FUSION VALIDATION  —  can partial sensing predict UNSEEN bays?")
    print("=" * 78)
    print(f"  dates       : {len(all_dates)}  ({all_dates[0]} .. {all_dates[-1]})")
    print(f"  training    : {len(train)}   held out : {len(holdout)}")

    model = build_model(args.events, prior_strength=args.prior_strength,
                        max_events=args.max_events, holdout_dates=holdout,
                        source_meta={"eventsFile": os.path.abspath(args.events)})
    print(f"  climatology : {len(model['cells'])} cells built on training dates only")

    occupied, street_bays = instantaneous_truth(args.events, holdout,
                                                max_events=args.max_events)
    median_stay = ((model.get("stayStatistics") or {}).get("medianMinutes")
                   or args.median_stay)
    print(f"  truth       : {len(occupied)} (date,hour) snapshots reconstructed "
          f"at :30 past each hour")
    print(f"  median stay : {median_stay} min  (freshness half-life)")
    print("-" * 78)

    coverages = [float(x) for x in args.coverages.split(",") if x.strip()]
    report = {"datesTotal": len(all_dates), "training": train, "holdout": holdout,
              "medianStayMinutes": median_stay, "coverages": {}}

    # Which (street,date,hour) cells count as ATYPICAL is decided by
    # climatology, before any live data is seen.
    print("  sweeping sensor coverage ...")
    header = (f"  {'cov':>5} {'predictor':<14} {'n':>5} {'MAE':>8} "
              f"{'Brier':>9} | {'typical MAE':>12} {'atypical MAE':>13}")
    for cov in coverages:
        cutoff = int(round(cov * 10000))
        sensed_by_street = {s: {b for b in bs if _stable_pick(b, cutoff)}
                            for s, bs in street_bays.items()}
        fusion_all, clim_all, live_all = [], [], []
        fus_typ, fus_atyp, clim_typ, clim_atyp = [], [], [], []
        floor_all, floor_atyp = [], []
        cov_hits = cov_n = 0
        conflicts = 0

        for (date_s, hour), occ_set in occupied.items():
            dtm = datetime.strptime(date_s, "%Y-%m-%d").replace(
                tzinfo=timezone.utc, hour=hour)
            dt_type = day_type(dtm)
            for street, bays in street_bays.items():
                if not bays:
                    continue
                n_bays = len(bays)
                occ_street = len(occ_set & bays)
                truth_pfree_all = 1.0 - occ_street / n_bays
                unsensed = bays - sensed_by_street[street]
                sensed = sensed_by_street[street]
                j = len(occ_set & sensed)
                m = len(sensed)

                cell = model["cells"].get(f"{street}|{dt_type}|{hour}")
                if cell is None:
                    continue
                clim_pfree = cell["pFree"]
                prior_sd = cell.get("sdPredictive") or DEFAULT_SD_DAY

                # atypical = reality departs from the climatological pattern by
                # more than the model's own day-to-day SD. Decided from truth,
                # not from the prediction, so it cannot favour any predictor.
                atypical = abs(truth_pfree_all - clim_pfree) > 1.96 * prior_sd

                if unsensed:
                    truth_unsensed = 1.0 - len(occ_set & unsensed) / len(unsensed)
                else:
                    truth_unsensed = None     # coverage 1.0: nothing left to infer

                res = fuse(clim_pfree, prior_sd, m, j, weight=1.0,
                           sensor_bias_sd=args.sensor_bias_sd,
                           dates_used=cell.get("datesUsed", 0),
                           effective_slots=cell.get("effectiveSlots", 0.0))
                if res["conflict"]:
                    conflicts += 1

                if truth_unsensed is None:
                    continue
                fusion_all.append((res["pFree"], truth_unsensed))
                clim_all.append((clim_pfree, truth_unsensed))
                (fus_atyp if atypical else fus_typ).append(
                    (res["pFree"], truth_unsensed))
                (clim_atyp if atypical else clim_typ).append(
                    (clim_pfree, truth_unsensed))
                # floor uses the subset size and the best available p estimate
                floor_all.append((clim_pfree, len(unsensed)))
                if atypical:
                    floor_atyp.append((clim_pfree, len(unsensed)))
                if m > 0:
                    live_all.append((1.0 - j / m, truth_unsensed))
                lo, hi = res["pFree95"]
                cov_n += 1
                cov_hits += 1 if lo <= truth_unsensed <= hi else 0

        sf, sc = _scores(fusion_all), _scores(clim_all)
        sl = _scores(live_all)
        styp, satyp = _scores(fus_typ), _scores(fus_atyp)
        ctyp, catyp = _scores(clim_typ), _scores(clim_atyp)
        fl_all, fl_atyp = noise_floor(floor_all), noise_floor(floor_atyp)
        coverage_ci = (cov_hits / cov_n) if cov_n else None

        report["coverages"][str(cov)] = {
            "fusion": sf, "climatology": sc, "liveOnly": sl,
            "fusionTypical": styp, "fusionAtypical": satyp,
            "climatologyTypical": ctyp, "climatologyAtypical": catyp,
            "noiseFloor": fl_all, "noiseFloorAtypical": fl_atyp,
            "fusionExcessOverFloor": (round(sf["mae"] - fl_all, 5)
                                      if (sf and fl_all) else None),
            "climatologyExcessOverFloor": (round(sc["mae"] - fl_all, 5)
                                           if (sc and fl_all) else None),
            "fusionAtypicalExcessOverFloor": (
                round(satyp["mae"] - fl_atyp, 5) if (satyp and fl_atyp) else None),
            "climatologyAtypicalExcessOverFloor": (
                round(catyp["mae"] - fl_atyp, 5) if (catyp and fl_atyp) else None),
            "ci95Coverage": round(coverage_ci, 4) if coverage_ci else None,
            "conflictsFlagged": conflicts,
            "sensedBaysPerStreet": {s: len(v) for s, v in sensed_by_street.items()},
        }

        print()
        print(f"  === coverage {cov:.0%} ===")
        print(header)
        print("  " + "-" * 76)
        for name, sc_ in (("climatology", sc), ("live only", sl), ("FUSION", sf)):
            if not sc_:
                print(f"  {cov:>5.0%} {name:<14} {'-':>5}   (no live bays sensed)")
                continue
            typ = ctyp if name == "climatology" else styp
            atyp = catyp if name == "climatology" else satyp
            extra = ""
            if name == "live only":
                extra = ""
            print(f"  {cov:>5.0%} {name:<14} {sc_['n']:>5} {sc_['mae']:>8.4f} "
                  f"{sc_['brier']:>9.6f} | "
                  f"{(typ['mae'] if typ else float('nan')):>12.4f} "
                  f"{(atyp['mae'] if atyp else float('nan')):>13.4f}{extra}")
        if fl_all is not None:
            print(f"        irreducible noise floor for this subset size: "
                  f"{fl_all:.4f}   (atypical {fl_atyp:.4f})")
            if sf and sc:
                print(f"        excess over floor - climatology "
                      f"{sc['mae'] - fl_all:+.4f}   fusion "
                      f"{sf['mae'] - fl_all:+.4f}")
            if satyp and catyp and fl_atyp:
                print(f"        excess over floor, ATYPICAL days - climatology "
                      f"{catyp['mae'] - fl_atyp:+.4f}   fusion "
                      f"{satyp['mae'] - fl_atyp:+.4f}")
        if coverage_ci is not None:
            print(f"        95% interval coverage of the fused estimate: "
                  f"{coverage_ci:.3f}   conflicts flagged: {conflicts}")

    # ---- the summary that matters ------------------------------------------ #
    print()
    print("=" * 78)
    print("  VERDICT")
    print("=" * 78)
    base = report["coverages"].get(str(coverages[0]), {}).get("climatology")
    for cov in coverages:
        r = report["coverages"][str(cov)]
        if not r.get("fusion"):
            continue
        line = f"  {cov:>5.0%} sensed -> unsensed-bay MAE {r['fusion']['mae']:.4f}"
        if r.get("noiseFloor"):
            line += f"   (floor {r['noiseFloor']:.4f})"
        if r.get("fusionExcessOverFloor") is not None and \
                r.get("climatologyExcessOverFloor") is not None:
            fe, ce = r["fusionExcessOverFloor"], r["climatologyExcessOverFloor"]
            red = (ce - fe) / ce * 100 if ce else 0.0
            line += f"\n          excess over floor: fusion {fe:+.4f} vs " \
                    f"climatology {ce:+.4f}  ({red:+.1f}%)"
        if r.get("fusionAtypical") and r.get("climatologyAtypical"):
            fa, ca = r.get("fusionAtypicalExcessOverFloor"), \
                r.get("climatologyAtypicalExcessOverFloor")
            line += f"\n          ATYPICAL days (reality departs from the pattern):"
            if fa is not None and ca:
                a_red = (ca - fa) / ca * 100
                line += f" excess over floor fusion {fa:+.4f} vs climatology " \
                        f"{ca:+.4f}  ({a_red:+.1f}%)"
            else:
                line += (f" fusion {r['fusionAtypical']['mae']:.4f} vs "
                         f"climatology {r['climatologyAtypical']['mae']:.4f}")
        print(line)
    print("-" * 78)
    print("  Scored against the UNSERVED bays only. Predicting bays you can")
    print("  already see is not a claim worth making.")
    print("  AVAILABILITY ONLY - nothing here speaks to legality.")
    print("=" * 78)

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".",
                    exist_ok=True)
        with open(args.report, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"  report : {args.report}")
    return 0


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fuse", help="fuse a live snapshot with a built model")
    f.add_argument("--model", required=True)
    f.add_argument("--live", required=True,
                   help="bays.geojson / JSON / JSONL snapshot, URL, or '-'")
    f.add_argument("--at", default=None, help="'YYYY-MM-DDTHH:MM' (default: snapshot time)")
    f.add_argument("--street", default=None,
                   help="comma-separated streets (default: every street in the snapshot)")
    f.add_argument("--median-stay", type=float, default=None,
                   help="freshness half-life in minutes (default: from the model)")
    f.add_argument("--sensor-bias-sd", type=float, default=DEFAULT_SENSOR_BIAS_SD,
                   help="extra SD for the risk that sensed bays are unrepresentative")
    f.add_argument("--json", action="store_true")

    v = sub.add_parser("validate-fusion",
                       help="measure whether partial sensing predicts unseen bays")
    v.add_argument("--events", required=True)
    v.add_argument("--holdout", type=float, default=0.2)
    v.add_argument("--prior-strength", type=float, default=30.0)
    v.add_argument("--max-events", type=int, default=None)
    v.add_argument("--scan-only", type=int, default=None)
    v.add_argument("--seed", type=int, default=1337)
    v.add_argument("--coverages", default="0.0,0.05,0.10,0.20,0.40,0.70",
                   help="comma-separated fractions of bays assumed sensed")
    v.add_argument("--median-stay", type=float, default=28.0)
    v.add_argument("--sensor-bias-sd", type=float, default=DEFAULT_SENSOR_BIAS_SD)
    v.add_argument("--report", default="fusion-validation.json")

    m = sub.add_parser("make-snapshot",
                       help="reconstruct a test live-snapshot from an archive")
    m.add_argument("--events", required=True)
    m.add_argument("--at", required=True, help="'YYYY-MM-DDTHH:MM' instant")
    m.add_argument("--coverage", type=float, default=0.2,
                   help="fraction of bays assumed to carry a sensor")
    m.add_argument("--fault-rate", type=float, default=0.05,
                   help="sensors reporting UNKNOWN")
    m.add_argument("--stale-rate", type=float, default=0.10,
                   help="sensors whose feed stopped updating")
    m.add_argument("--seed", type=int, default=7)
    m.add_argument("--max-events", type=int, default=None)
    m.add_argument("--out", default="snapshot.json")

    args = ap.parse_args()
    if args.cmd == "make-snapshot":
        sys.exit(cmd_make_snapshot(args))
    elif args.cmd == "fuse":
        sys.exit(cmd_fuse(args))
    elif args.cmd == "validate-fusion":
        sys.exit(cmd_validate_fusion(args))


if __name__ == "__main__":
    main()
