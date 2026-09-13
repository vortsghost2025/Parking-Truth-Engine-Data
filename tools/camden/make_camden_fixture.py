#!/usr/bin/env python3
"""Synthetic Camden fixture and scenario generator (PTE-TEL-003 deliverable 6).

WHY THIS EXISTS
---------------
The Camden signal test makes claims about what it can detect: that it fails when
the signal is enforcement deployment, when CEO-GPS isolation collapses the
ranking, when coverage is thin, when rankings drift, and when there is no
independent validation route. A harness that asserts those things without
demonstrating them is a hope, not a test.

So this generator builds fixtures from KNOWN latent processes - a demand process
and a separate enforcement-deployment process, mixed in proportions the caller
controls - and the self-test then checks that the harness's verdict matches the
proportions it was given. The harness is tested against truth it did not create.

IT IS NOT REAL DATA
-------------------
Nothing here is Camden. Street names, CPZ codes, capacities and PCN counts are
fabricated. Any number produced from this fixture describes the fixture. Its only
legitimate use is proving the pipeline's arithmetic and its failure detection.

WHAT IT REPRODUCES DELIBERATELY
-------------------------------
The messy parts of a real Camden export, because a fixture that is cleaner than
reality tests the wrong thing:

  * a share of PCNs carrying a DATE but NO TIME  -> exercises the unknown-hour
    path, which must never be imputed to midnight
  * an unrecognised `Spatial Accuracy` value     -> exercises the UNRECOGNISED
    disposition, so schema drift cannot hide inside UNKNOWN_OTHER
  * PCN streets absent from the bay inventory    -> exercises unmatched-street
    coverage reporting
  * bays with no publisher space count           -> exercises the "capacity is
    None, never 0.0" rule
  * approximate bay lengths and space counts     -> exercises the approximate
    flags that must survive into every aggregate

SCENARIOS (see run_selftest.py for the expected verdicts)
---------------------------------------------------------
  demand-dominated      deployment weight ~0, proxy supplied      -> PASS
  deployment-dominated  prohibition-heavy, index tracks cameras   -> FAIL (F1)
  gps-biased            CCTV concentrated on deployment streets   -> FAIL (F2)
  sparse-coverage       few streets and few dates                 -> FAIL (F3)
  no-validation-route   demand-dominated but no route declared    -> FAIL (F4)
  drifting              second half differs from first            -> FAIL (F5)

    python3 make_camden_fixture.py --out-dir /tmp/camden --scenario demand-dominated
    python3 make_camden_fixture.py --out-dir /tmp/camden --seed 7 --streets 60 --days 90

STDLIB ONLY. Deterministic: same flags -> same bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camden_normalize import load_code_map  # noqa: E402

FIXTURE_VERSION = "2.0.0"

# Column spellings chosen to match the PRIMARY candidate for each field in
# camden_sources, so the fixture exercises the default resolution path. A real
# download may differ; that is what --field-map exists for.
BAY_COLUMNS = [
    "CPZ", "Road Name", "Restriction Type", "Times of Operation", "Maximum Stay",
    "Tariff", "Length (m)", "Number of Spaces", "WKT",
]
PCN_COLUMNS = [
    "PCN", "Date of Contravention", "Contravention Code", "Contravention Description",
    "Ticket Type", "Street", "Parking Restriction", "Vehicle Category",
    "Case Status", "Spatial Accuracy", "CPZ",
]
PROXY_COLUMNS = ["Street", "CPZ", "Date", "Value", "Units", "Source"]

# Camden-plausible but entirely fabricated.
STREET_STEMS = [
    "High", "Camden", "Kentish", "Castlehaven", "Chalk Farm", "Haverstock",
    "Buck", "Baynes", "Harmood", "Grafton", "Bartholomew", "Malden", "Falkland",
    "Gloucester", "Hartland", "Fortress", "Jamestown", "Lawn", "Mansfield",
    "Northside", "Oakley", "Pandora", "Queen's", "Rochester", "Southampton",
    "Torriano", "Underhill", "Vaughan", "Wentworth", "York", "Albany", "Bonny",
    "Clarence", "Delancey", "Emerson", "Ferdinand", "Georgiana", "Heytesbury",
    "Ivor", "Jeffrey", "Kelly", "Leighton", "Marlborough", "Nelson", "Orbel",
    "Prince of Wales", "Quantock", "Regis", "St Pancras", "Talacre",
]
STREET_TYPES = ["Street", "Road", "Way", "Lane", "Close", "Terrace", "Mews", "Grove"]
CPZ_CODES = ["CA", "CB", "CC", "CD", "CE"]

RESTRICTIONS = ["Pay and Display", "Resident Permit", "Business Permit",
                "Shared Use", "Disabled Badge", "Loading"]
TIMES = ["Mon-Fri 08:30-18:30", "Mon-Sat 08:30-18:30", "Daily 24 Hours",
         "Mon-Fri 10:00-16:30"]
MAX_STAYS = ["2 Hours", "3 Hours", "No Max Stay", "4 Hours", "1 Hour"]
TARIFFS = ["Tariff A", "Tariff B", "Tariff C", "Zone 2"]

# ---------------------------------------------------------------------------
# Fixture contravention codes are DERIVED FROM THE FROZEN AUTHORITATIVE ARTIFACT
# (PTE-TEL-004 C4A). They used to be hand-written, and that was worse than
# merely circular.
#
# The PTE-TEL-003 fixture invented both the codes and their descriptions. Checked
# against the London Councils codebook, five of its nine codes carried the WRONG
# authoritative class and one did not exist at all:
#
#   fixture ("01", "Parked without payment")            -> authoritative 01 is
#       "Parked in a restricted street during prescribed hours" = PROHIBITION
#   fixture ("02", "Parked longer than maximum stay")   -> authoritative 02 is a
#       restricted-street waiting/loading offence = PROHIBITION
#   fixture ("03", "Parked exceeding paid time")        -> CODE 03 DOES NOT EXIST
#   fixture ("12", "Parked in restricted zone")         -> authoritative 12 is the
#       residents'/shared-use permit code = MIXED
#   fixture ("30", "Parked without a permit in a CPZ")  -> authoritative 30 is
#       "Parked for longer than permitted" = TURNOVER, the cleanest duration-demand
#       code in the entire list, sitting in the fixture's PROHIBITION bucket
#   fixture ("31", "Parked in a permit bay")            -> authoritative 31 is
#       "Entering and stopping in a box junction" = NOT_PARKING, a moving-traffic
#       offence used as if it were a parking prohibition
#
# So the deployment-dominated scenario's "prohibition-heavy" series was built on a
# fabricated codebook, and the self-test that passed 14/14 was validating the
# classifier against invented ground truth. Deriving the fixture from the frozen
# artifact is what makes the self-test able to disagree with the implementation,
# which is the only reason to have one.
# ---------------------------------------------------------------------------

_CODE_MAP = load_code_map(required=True)


def _codes_by_declared_class(declared: str) -> list[tuple[str, str]]:
    """(base code, OFFICIAL description) for every code we declared `declared`.

    Sorted by code so selection is deterministic and independent of dict order.
    """
    return [(c, e["officialDescription"])
            for c, e in sorted(_CODE_MAP["codes"].items())
            if e["declaredPressureClass"] == declared]


TURNOVER_CODES = _codes_by_declared_class("TURNOVER_PAYMENT")
PROHIBITION_CODES = _codes_by_declared_class("PROHIBITION_ENTITLEMENT")
MIXED_CODES = _codes_by_declared_class("MIXED")
NOT_PARKING_CODES = _codes_by_declared_class("NOT_PARKING")

# Deliberately outside the authoritative artifact, to exercise the counted
# fallback path. "999" parses structurally as base 99 with suffix 9 - a suffix the
# source does not permit on code 99 - so it also exercises invalid-suffix
# reporting. "1234" and "ZZ9" are unparseable. None of these is ever guessed at.
UNMAPPED_CODES = [
    ("999", ""),
    ("1234", ""),
    ("ZZ9", ""),
]
VEHICLES = ["Private Car", "Light Goods Vehicle", "Motorcycle", "Private Hire"]
CASE_STATUSES = ["Issued", "Paid", "Challenged", "Cancelled", "Outstanding"]
TICKET_TYPES = ["CEO On Street", "CEO Via CCTV"]

# Latent shapes. Weekday demand is bimodal (arrival and evening); Saturday is a
# broad retail peak; Sunday is weaker. Deployment is a weekday shift and is
# absent at weekends, which is the single most useful way to tell the two apart
# if the data are good enough.
def _demand_shape(hour: int, day_type: str) -> float:
    if day_type == "WEEKDAY":
        return (0.55 * math.exp(-((hour - 9.5) ** 2) / 3.2)
                + 0.30 * math.exp(-((hour - 13.0) ** 2) / 4.0)
                + 0.70 * math.exp(-((hour - 17.5) ** 2) / 3.0)
                + 0.03)
    if day_type == "SATURDAY":
        return (0.95 * math.exp(-((hour - 13.0) ** 2) / 9.0) + 0.04)
    return (0.45 * math.exp(-((hour - 13.5) ** 2) / 10.0) + 0.03)


def _deployment_shape(hour: int, day_type: str) -> float:
    if day_type != "WEEKDAY":
        return 0.02                      # skeleton weekend cover only
    if 8 <= hour <= 18:
        return 0.85 + 0.15 * math.sin((hour - 8) / 10.0 * math.pi)
    return 0.05


SCENARIOS: dict[str, dict] = {
    # A clean demand signal with a usable independent proxy. Expected: PASS.
    "demand-dominated": dict(
        streets=48, days=84, demand_weight=1.0, deployment_weight=0.05,
        cctv_share=0.25, gps_bias=0.0, drift=0.0, with_proxy=True,
        deployment_concentration=1.0, seed=20260913),
    # Deployment dominates and prohibition codes rise with it. Expected: FAIL F1.
    "deployment-dominated": dict(
        streets=48, days=84, demand_weight=0.10, deployment_weight=1.0,
        cctv_share=0.30, gps_bias=0.6, drift=0.0, with_proxy=True,
        deployment_concentration=3.5, seed=20260913),
    # CCTV sits on the deployment streets AND demand is anti-correlated with
    # deployment, so isolating CEO GPS REORDERS the streets rather than merely
    # rescaling them. Expected: FAIL F2.
    #
    # Note why the earlier version of this scenario did not work: with demand and
    # deployment multipliers drawn independently, the same streets topped both the
    # all-strata and the CEO-GPS-only rankings, so Spearman stayed high even
    # though the magnitudes diverged. F2 tests ORDER collapse. Rescaling is not
    # collapse.
    "gps-biased": dict(
        streets=48, days=84, demand_weight=0.60, deployment_weight=0.90,
        cctv_share=0.40, gps_bias=1.0, drift=0.0, with_proxy=True,
        deployment_concentration=3.0, anticorrelate=True,
        cctv_attribution_prob=0.97, seed=20260913),
    # Too few streets and too few dates. Expected: FAIL F3.
    "sparse-coverage": dict(
        streets=6, days=12, demand_weight=1.0, deployment_weight=0.05,
        cctv_share=0.25, gps_bias=0.0, drift=0.0, with_proxy=True,
        deployment_concentration=1.0, seed=20260913),
    # Good signal, but no independent validation route at all. Expected: FAIL F4.
    "no-validation-route": dict(
        streets=48, days=84, demand_weight=1.0, deployment_weight=0.05,
        cctv_share=0.25, gps_bias=0.0, drift=0.0, with_proxy=False,
        deployment_concentration=1.0, seed=20260913),
    # The second half of the window behaves differently. Expected: FAIL F5.
    "drifting": dict(
        streets=48, days=84, demand_weight=1.0, deployment_weight=0.05,
        cctv_share=0.25, gps_bias=0.0, drift=1.0, with_proxy=True,
        deployment_concentration=1.0, seed=20260913),
    # Demand-dominated like the PASS scenario, but contaminated the way the real
    # Camden series is: moving-traffic and bus-lane codes that C3 should have
    # removed, MIXED codes, and codes absent from the authoritative artifact.
    #
    # The purpose of this scenario is NOT to assert a verdict. It exists to prove
    # that contamination is SURFACED AND COUNTED rather than absorbed: the report
    # must show a non-zero c3PolicyRowsStillPresent, a non-zero fallbackRows with
    # the offending codes named, and a non-zero invalidSuffixRows. A harness that
    # quietly folded any of those into the F1 denominator would pass every other
    # check and still be lying about what it measured.
    "code-map-contaminated": dict(
        streets=48, days=84, demand_weight=1.0, deployment_weight=0.05,
        cctv_share=0.25, gps_bias=0.0, drift=0.0, with_proxy=True,
        deployment_concentration=1.0, seed=20260913,
        non_parking_share=0.18, unmapped_share=0.03),
}


def _poisson(rng: random.Random, lam: float) -> int:
    """Deterministic Poisson draw. Knuth for small lambda, normal for large."""
    if lam <= 0:
        return 0
    if lam < 30:
        threshold = math.exp(-lam)
        k, p = 0, 1.0
        while True:
            p *= rng.random()
            if p <= threshold:
                return k
            k += 1
            if k > 10000:
                return k
    return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))


def _day_type(d: date) -> str:
    if d.weekday() == 5:
        return "SATURDAY"
    if d.weekday() == 6:
        return "SUNDAY"
    return "WEEKDAY"


def anticorrelate_multipliers(streets: list[dict]) -> None:
    """Pair the lowest demand multipliers with the highest deployment ones.

    In place. This is what makes the gps-biased scenario produce a genuine RANKING
    collapse rather than a rescaling: the streets that dominate the all-strata
    index (deployment-heavy, CCTV-attributed) are then systematically different
    from the streets that dominate the CEO-GPS-only index (demand-heavy).
    """
    order = sorted(range(len(streets)), key=lambda i: streets[i]["demandMultiplier"])
    dep_values = sorted((s["deploymentMultiplier"] for s in streets), reverse=True)
    for rank, idx in enumerate(order):
        streets[idx]["deploymentMultiplier"] = dep_values[rank]


def build_street_table(n_streets: int, rng: random.Random) -> list[dict]:
    """Fabricate the street universe with capacity and latent multipliers."""
    used: set[str] = set()
    streets: list[dict] = []
    i = 0
    while len(streets) < n_streets:
        stem = STREET_STEMS[i % len(STREET_STEMS)]
        stype = STREET_TYPES[(i // len(STREET_STEMS)) % len(STREET_TYPES)]
        name = f"{stem} {stype}"
        i += 1
        if name in used:
            name = f"{name} {len(used)}"
        used.add(name)
        cpz = CPZ_CODES[len(streets) % len(CPZ_CODES)]
        # Lognormal capacity: real street inventories are heavily right-skewed.
        spaces = max(2, int(round(rng.lognormvariate(math.log(9.0), 0.75))))
        streets.append({
            "name": name,
            "cpz": cpz,
            "spaces": spaces,
            "demandMultiplier": rng.lognormvariate(0.0, 0.55),
            # Deployment is skewed far harder than demand: officers concentrate.
            "deploymentMultiplier": rng.lognormvariate(0.0, 1.15),
            "restriction": rng.choice(RESTRICTIONS),
            "times": rng.choice(TIMES),
            "maxStay": rng.choice(MAX_STAYS),
            "tariff": rng.choice(TARIFFS),
            "lengthM": round(spaces * rng.uniform(5.2, 6.4), 1),
        })
    return streets


def generate(out_dir: str, scenario: str | None, params: dict,
             seed: int | None = None) -> dict:
    """Write bays.csv, pcn.csv and (optionally) proxy.csv. Returns paths + truth."""
    p = dict(params)
    if seed is not None:
        p["seed"] = seed
    rng = random.Random(int(p["seed"]))
    os.makedirs(out_dir, exist_ok=True)

    streets = build_street_table(int(p["streets"]), rng)
    if p.get("anticorrelate"):
        anticorrelate_multipliers(streets)
    n_streets = len(streets)

    # Which streets carry fixed CCTV. With gps_bias>0 the camera streets align
    # with the deployment-heavy streets, so a pooled signal inherits the
    # deployment pattern while a CEO-GPS-only signal does not.
    camera_count = max(1, int(round(n_streets * float(p["cctv_share"]))))
    if float(p["gps_bias"]) > 0:
        ranked = sorted(range(n_streets),
                        key=lambda i: (-streets[i]["deploymentMultiplier"], i))
        bias_n = int(round(camera_count * float(p["gps_bias"])))
        camera_idx = set(ranked[:bias_n])
        rest = [i for i in range(n_streets) if i not in camera_idx]
        rng.shuffle(rest)
        camera_idx.update(rest[:max(0, camera_count - bias_n)])
    else:
        camera_idx = set(rng.sample(range(n_streets), camera_count))

    cctv_prob = float(p.get("cctv_attribution_prob", 0.78))
    start = date(2025, 1, 6)                       # a Monday
    dates = [start + timedelta(days=i) for i in range(int(p["days"]))]
    midpoint = start + timedelta(days=int(p["days"]) // 2)

    bays_rows: list[list] = []
    for i, st in enumerate(streets):
        # Split each street into 1-4 bays; ~12% of bays have NO publisher space
        # count, to exercise the capacity-is-None path.
        n_bays = rng.randint(1, 4)
        remaining = st["spaces"]
        for b in range(n_bays):
            share = remaining if b == n_bays - 1 else max(1, int(round(remaining / (n_bays - b))))
            remaining -= share
            supply = rng.random() > 0.12
            x0 = 529000 + i * 37 + b
            y0 = 183000 + i * 11 + b
            wkt = (f"LINESTRING ({x0} {y0}, {x0 + 12} {y0 + 3}, "
                   f"{x0 + 26} {y0 + 5})")
            bays_rows.append([
                st["cpz"], st["name"], st["restriction"], st["times"],
                st["maxStay"], st["tariff"],
                round(st["lengthM"] / n_bays, 1),
                str(share) if supply else "",
                wkt,
            ])

    pcn_rows: list[list] = []
    truth_daily: dict[tuple, dict] = {}
    pcn_seq = 0
    drift_factor = float(p["drift"])

    for d in dates:
        day_type = _day_type(d)
        in_second_half = d >= midpoint
        for i, st in enumerate(streets):
            # Drift: in the second half, swap the demand ranking. This is a
            # genuine regime change, not noise, so split-half must detect it.
            dm = st["demandMultiplier"]
            if drift_factor > 0 and in_second_half:
                dm = (2.0 - dm) * drift_factor + dm * (1.0 - drift_factor)
            for hour in range(24):
                dem = _demand_shape(hour, day_type) * dm
                dep = _deployment_shape(hour, day_type) * st["deploymentMultiplier"]
                if float(p["gps_bias"]) > 0 and i in camera_idx:
                    dep *= 1.0 + 0.8 * float(p["gps_bias"])
                lam_demand = st["spaces"] * float(p["demand_weight"]) * dem * 0.055
                lam_deploy = st["spaces"] * float(p["deployment_weight"]) * dep * 0.045
                n_dem = _poisson(rng, lam_demand)
                n_dep = _poisson(rng, lam_deploy)

                slot = truth_daily.setdefault((st["name"], d.isoformat()),
                                              {"demandEvents": 0, "deploymentEvents": 0})
                slot["demandEvents"] += n_dem
                slot["deploymentEvents"] += n_dep

                for _ in range(n_dem):
                    pcn_rows.append(_make_pcn(
                        pcn_seq, rng, d, hour, st, i in camera_idx,
                        origin="DEMAND", time_supplied=rng.random() > 0.08,
                        cctv_prob=cctv_prob))
                    pcn_seq += 1
                for _ in range(n_dep):
                    pcn_rows.append(_make_pcn(
                        pcn_seq, rng, d, hour, st, i in camera_idx,
                        origin="DEPLOYMENT", time_supplied=rng.random() > 0.08,
                        cctv_prob=cctv_prob))
                    pcn_seq += 1
                # Non-parking and unmapped contamination. Shares default to zero so
                # the six original scenarios keep their expected verdicts exactly.
                lam_nonpark = (n_dem + n_dep) * float(p.get("non_parking_share", 0.0))
                for _ in range(_poisson(rng, lam_nonpark)):
                    pcn_rows.append(_make_pcn(
                        pcn_seq, rng, d, hour, st, i in camera_idx,
                        origin=rng.choice(("NON_PARKING", "MIXED")),
                        time_supplied=rng.random() > 0.08, cctv_prob=cctv_prob))
                    pcn_seq += 1
                lam_unmapped = (n_dem + n_dep) * float(p.get("unmapped_share", 0.0))
                for _ in range(_poisson(rng, lam_unmapped)):
                    pcn_rows.append(_make_pcn(
                        pcn_seq, rng, d, hour, st, i in camera_idx,
                        origin="UNMAPPED", time_supplied=rng.random() > 0.08,
                        cctv_prob=cctv_prob))
                    pcn_seq += 1

    # A few PCNs on streets that are NOT in the bay inventory, so unmatched-street
    # coverage reporting is exercised.
    for k in range(max(1, n_streets // 8)):
        st = dict(streets[k % n_streets])
        st["name"] = f"Uninventoried {k} Street"
        st["spaces"] = 6
        for _ in range(rng.randint(2, 9)):
            d = rng.choice(dates)
            pcn_rows.append(_make_pcn(pcn_seq, rng, d, rng.randint(8, 18), st,
                                      False, origin="DEMAND", time_supplied=True))
            pcn_seq += 1

    bays_path = os.path.join(out_dir, "bays.csv")
    pcn_path = os.path.join(out_dir, "pcn.csv")
    _write_csv(bays_path, BAY_COLUMNS, bays_rows)
    _write_csv(pcn_path, PCN_COLUMNS, pcn_rows)

    proxy_path = None
    if p.get("with_proxy"):
        # The proxy is derived from the DEMAND process ONLY - never from PCN
        # counts - which is what makes it independent for the purposes of the
        # test. In a real run this file would come from a different publisher.
        proxy_rows = []
        for (name, iso), slot in sorted(truth_daily.items()):
            st = next(s for s in streets if s["name"] == name)
            value = round(slot["demandEvents"] / max(1.0, st["spaces"]), 6)
            proxy_rows.append([name, st["cpz"], iso, f"{value:.6f}",
                               "synthetic demand events per space",
                               "fixture:latent-demand-process"])
        proxy_path = os.path.join(out_dir, "proxy.csv")
        _write_csv(proxy_path, PROXY_COLUMNS, proxy_rows)

    return {
        "scenario": scenario,
        "fixtureVersion": FIXTURE_VERSION,
        "params": {k: p[k] for k in sorted(p)},
        "outDir": os.path.abspath(out_dir),
        "baysPath": bays_path,
        "pcnPath": pcn_path,
        "proxyPath": proxy_path,
        "streetCount": n_streets,
        "bayRowCount": len(bays_rows),
        "pcnRowCount": len(pcn_rows),
        "cameraStreetCount": len(camera_idx),
        "dateMin": dates[0].isoformat(),
        "dateMax": dates[-1].isoformat(),
        "distinctDates": len(dates),
        "sha256": {
            "bays.csv": _sha256(bays_path),
            "pcn.csv": _sha256(pcn_path),
            **({"proxy.csv": _sha256(proxy_path)} if proxy_path else {}),
        },
        "codeMap": {
            "path": _CODE_MAP["path"],
            "sha256": _CODE_MAP["sha256"],
            "codeListVersion": _CODE_MAP["codeListVersion"],
            "artifactVersion": _CODE_MAP["artifactVersion"],
        },
        "fixtureCodesDerivedFromAuthoritativeArtifact": True,
        "authoritativeCodePool": {
            "TURNOVER_PAYMENT": len(TURNOVER_CODES),
            "PROHIBITION_ENTITLEMENT": len(PROHIBITION_CODES),
            "MIXED": len(MIXED_CODES),
            "NOT_PARKING": len(NOT_PARKING_CODES),
            "UNMAPPED": len(UNMAPPED_CODES),
        },
        "isRealData": False,
    }


def _make_pcn(seq: int, rng: random.Random, d: date, hour: int, st: dict,
              is_camera_street: bool, origin: str, time_supplied: bool,
              cctv_prob: float = 0.78) -> list:
    """Fabricate one PCN row.

    `origin` drives the contravention class: events arising from the DEMAND
    process get turnover/overstay codes, events arising from DEPLOYMENT get
    prohibition codes. That is what lets the harness's mix diagnostics mean
    anything, and it is why the deployment-dominated scenario produces a
    prohibition-heavy series.
    """
    if origin == "DEMAND":
        code, desc = rng.choice(TURNOVER_CODES)
    elif origin == "DEPLOYMENT":
        code, desc = rng.choice(PROHIBITION_CODES)
    elif origin == "MIXED":
        code, desc = rng.choice(MIXED_CODES)
    elif origin == "NON_PARKING":
        # A moving-traffic or bus-lane contravention. Under the C3 policy these are
        # removed at the input layer; emitting them here proves the harness
        # SURFACES any that survive rather than absorbing them into the F1
        # denominator.
        code, desc = rng.choice(NOT_PARKING_CODES)
    elif origin == "UNMAPPED":
        # A code absent from the authoritative artifact. Must increment the
        # reported fallback count.
        code, desc = rng.choice(UNMAPPED_CODES)
    else:
        raise ValueError(f"unknown fixture origin {origin!r}")

    if is_camera_street and rng.random() < cctv_prob:
        accuracy = "Fixed CCTV Camera"
        ticket = "CEO Via CCTV"
    elif rng.random() < 0.90:
        accuracy = "Civil Enforcement Officer GPS Location"
        ticket = "CEO On Street"
    elif rng.random() < 0.5:
        accuracy = "Unknown"
        ticket = "CEO On Street"
    else:
        # A value the adapter has never seen. Must surface as UNRECOGNISED, not
        # be absorbed silently into UNKNOWN_OTHER.
        accuracy = "Surveyor Manual Entry"
        ticket = "CEO On Street"

    when = (f"{d.isoformat()}T{hour:02d}:{rng.randint(0, 59):02d}:00"
            if time_supplied else d.isoformat())
    return [
        f"FX{seq:08d}", when, code, desc, ticket, st["name"],
        st["restriction"], rng.choice(VEHICLES), rng.choice(CASE_STATUSES),
        accuracy, st["cpz"],
    ]


def _write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a deterministic synthetic Camden fixture. NOT REAL "
                    "DATA - it exists to test the harness's arithmetic and its "
                    "failure detection.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--scenario", choices=sorted(SCENARIOS),
                    help="named scenario with pre-set latent process weights")
    ap.add_argument("--seed", type=int, help="override the RNG seed")
    ap.add_argument("--streets", type=int, help="override street count")
    ap.add_argument("--days", type=int, help="override day count")
    ap.add_argument("--demand-weight", type=float, help="latent demand weight")
    ap.add_argument("--deployment-weight", type=float, help="latent deployment weight")
    ap.add_argument("--cctv-share", type=float, help="share of streets carrying fixed CCTV")
    ap.add_argument("--gps-bias", type=float,
                    help="0-1: align CCTV streets with deployment streets")
    ap.add_argument("--drift", type=float, help="0-1: regime change in the second half")
    ap.add_argument("--with-proxy", action="store_true", help="emit an independent proxy")
    ap.add_argument("--no-proxy", action="store_true", help="suppress the proxy")
    ap.add_argument("--manifest", help="write the fixture manifest here")
    args = ap.parse_args(argv)

    params = dict(SCENARIOS[args.scenario]) if args.scenario else dict(
        streets=40, days=60, demand_weight=1.0, deployment_weight=0.15,
        cctv_share=0.25, gps_bias=0.0, drift=0.0, with_proxy=False,
        deployment_concentration=1.0, seed=20260913)

    for flag, key in (("--streets", "streets"), ("--days", "days"),
                      ("--demand-weight", "demand_weight"),
                      ("--deployment-weight", "deployment_weight"),
                      ("--cctv-share", "cctv_share"), ("--gps-bias", "gps_bias"),
                      ("--drift", "drift")):
        val = getattr(args, key.replace("-", "_"), None)
        if val is not None:
            params[key] = val
    if args.with_proxy:
        params["with_proxy"] = True
    if args.no_proxy:
        params["with_proxy"] = False

    manifest = generate(args.out_dir, args.scenario, params, seed=args.seed)
    text = _dumps(manifest)
    if args.manifest:
        os.makedirs(os.path.dirname(os.path.abspath(args.manifest)) or ".", exist_ok=True)
        with open(args.manifest, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"fixture -> {manifest['outDir']}", file=__import__("sys").stderr)
        print(f"manifest -> {args.manifest}", file=__import__("sys").stderr)
    else:
        print(text)
    return 0


def _dumps(obj) -> str:
    import json
    return json.dumps(obj, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
