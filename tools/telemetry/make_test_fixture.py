#!/usr/bin/env python3
"""Generate a deterministic synthetic parking-event archive for testing.

WHY THIS EXISTS
---------------
The real City of Melbourne archives are ~246M rows and the smallest useful one
is a 258 MB download. Nobody should need that to run a test. This produces a
compact, byte-for-byte REPRODUCIBLE fixture that has the same shape, the same
documented defects and the same statistical texture, so the harvester, the
calibrator and the inference engine can all be exercised offline.

IT IS NOT REAL DATA. It is a test input. Anything calibrated on it is
calibrated on a fiction; the point is to prove the pipeline's arithmetic, not to
publish numbers about Melbourne.

WHAT IT REPRODUCES
------------------
Melbourne's real column names: Arrival Time, Departure Time, Parking Restriction,
Overstay, Marker ID, Sign, seconds, Street, Between Street 1, Between Street 2.

The four defects the publisher documents in its own archives:
  * negative `seconds`  - arrival detected after departure (sensor fault)
  * times imputed from midnight when not recorded
  * `OLD` suffix on Sign where the rule changed after the event
  * events truncated at the archive boundary

Statistics are generated from a Poisson arrival process per bay with an hourly
target occupancy, and lognormal stay durations parameterised by MEDIAN and MEAN
separately. That distinction matters: parking durations are strongly
right-skewed, and occupancy follows Little's Law on the MEAN. A generator that
only matched the median would produce a fixture whose implied occupancy is ~31%
too low, and would quietly mis-test every consumer.

    python3 make_test_fixture.py --out /tmp/fixture/events2019.csv
    python3 make_test_fixture.py --out f.csv --bays 800 --days 45 --seed 20190304

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
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# Shape of the fixture. Street multipliers give each street a genuinely
# different demand profile so per-cell estimation has something to recover.
# --------------------------------------------------------------------------- #

STREETS = [
    # name,              bays, demand multiplier, saturday market spike
    ("Bourke St",        160, 1.00, 1.15),
    ("Collins St",       150, 0.88, 1.05),
    ("Flinders Ln",      170, 1.12, 0.95),
    ("Lonsdale St",      160, 0.94, 1.00),
    ("Swanston St",      160, 1.06, 1.30),
]

# Target occupancy rho by hour, weekday. Trough overnight, peak midday, a
# second smaller shoulder in the late afternoon.
RHO_WEEKDAY = [
    0.020, 0.017, 0.016, 0.018, 0.039, 0.082, 0.172, 0.290,
    0.383, 0.449, 0.505, 0.546, 0.556, 0.510, 0.473, 0.416,
    0.364, 0.296, 0.228, 0.176, 0.124, 0.086, 0.053, 0.033,
]
# Weekends run lower and later.
RHO_WEEKEND = [
    0.018, 0.015, 0.014, 0.015, 0.025, 0.050, 0.100, 0.170,
    0.250, 0.330, 0.400, 0.450, 0.470, 0.455, 0.430, 0.400,
    0.355, 0.300, 0.235, 0.175, 0.125, 0.085, 0.050, 0.030,
]

RESTRICTIONS = [
    ("2P", 0.34), ("1P", 0.24), ("4P", 0.16), ("1/2P", 0.08),
    ("No Stopping", 0.06), ("Loading Zone", 0.07), ("Disabled", 0.05),
]

HEADER = ["Arrival Time", "Departure Time", "Parking Restriction", "Overstay",
          "Marker ID", "Sign", "seconds", "Street", "Between Street 1",
          "Between Street 2"]

BETWEEN = {
    "Bourke St":   ("Swanston St", "Russell St"),
    "Collins St":  ("Elizabeth St", "Swanston St"),
    "Flinders Ln": ("Queen St", "Elizabeth St"),
    "Lonsdale St": ("Russell St", "Exhibition St"),
    "Swanston St": ("Flinders Ln", "Collins St"),
}


# --------------------------------------------------------------------------- #

def lognormal_params(median_minutes: float, mean_minutes: float):
    """Solve for (mu, sigma) of a lognormal from its MEDIAN and MEAN.

    median = exp(mu), mean = exp(mu + sigma^2/2), so
    sigma = sqrt(2 * ln(mean / median)).

    Parameterising on both is the whole point. A right-skewed stay distribution
    has mean > median, and Little's Law consumes the mean. Generating on the
    median alone would understate occupancy by a wide margin.
    """
    if mean_minutes <= median_minutes <= 0:
        raise SystemExit("mean stay must exceed median stay for a right-skewed fit")
    mu = math.log(median_minutes)
    sigma = math.sqrt(2.0 * math.log(mean_minutes / median_minutes))
    return mu, sigma


def pick_restriction(rng: random.Random) -> str:
    r = rng.random()
    acc = 0.0
    for name, w in RESTRICTIONS:
        acc += w
        if r <= acc:
            return name
    return RESTRICTIONS[-1][0]


def generate(out_path: str, bays_scale: float, days: int, seed: int,
             start_date: str, median_stay: float, mean_stay: float,
             defect_negative: float, defect_imputed: float,
             defect_sign_old: float, overstay_rate: float,
             max_minutes: int, day_effect_sd: float = 0.20,
             event_day_rate: float = 0.06, event_multiplier: float = 1.8,
             event_hours=(11, 19)) -> dict:
    rng = random.Random(seed)
    mu, sigma = lognormal_params(median_stay, mean_stay)
    start = datetime.strptime(start_date, "%Y-%m-%d")

    # Per-bay identity, fixed for the whole run - a bay is infrastructure.
    bays = []
    marker = 100000
    for name, n_bays, mult, sat in STREETS:
        count = max(1, int(round(n_bays * bays_scale)))
        for i in range(count):
            marker += rng.choice([1, 1, 2, 3])
            bays.append({
                "street": name, "marker": f"M{marker}",
                "bay": f"{name}|{i:04d}", "mult": mult, "sat": sat,
            })

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fh = open(out_path, "w", newline="", encoding="utf-8")
    w = csv.writer(fh)
    w.writerow(HEADER)

    n_rows = 0
    counts = {"negative_duration": 0, "imputed_times": 0,
              "sign_old_suffix": 0, "overstayed": 0, "clipped_boundary": 0}
    stay_sum = 0.0
    stay_n = 0
    end_boundary = start + timedelta(days=days)

    mean_stay_h = mean_stay / 60.0
    start_epoch = start.timestamp()
    end_epoch = end_boundary.timestamp()

    # One bay is a SINGLE SERVER. A second car cannot arrive until the first has
    # left, so arrivals that find the bay busy are lost. That changes the
    # required arrival rate: with blocking, the busy fraction is
    #     rho = lambda*E[S] / (1 + lambda*E[S])
    # which inverts to
    #     lambda = rho / ((1 - rho) * E[S])
    # NOT lambda = rho / E[S]. Drawing Poisson counts per bay-hour independently
    # - the obvious first attempt - produced a fixture in which 31.8% of events
    # overlapped another event on the same bay. Physically impossible, and it
    # silently corrupts every occupancy measure downstream: count-based
    # occupancy reads high, set-based reads low, and the two disagree by ~25%.
    # ---- day-level demand effects ---------------------------------------- #
    # WITHOUT THESE THE FIXTURE CANNOT TEST LIVE FUSION AT ALL.
    #
    # If every weekday follows the identical rho curve, then day-to-day
    # variation is pure Poisson noise, a climatological model is already
    # near-optimal, and live sensors can only inject sampling noise. Measured
    # on such a fixture, fusion looks WORSE than climatology - correctly, but
    # for a reason that has nothing to do with the real world.
    #
    # Real cities have genuine day-level demand shifts: weather, events,
    # holidays, roadworks, school terms. Two effects are modelled:
    #   * a lognormal day multiplier (day_effect_sd) - ordinary variation
    #   * rare event days (event_day_rate) with a large afternoon spike -
    #     exactly the case where a historical average is most wrong and a
    #     live sensor is most valuable
    day_mult = {}
    for day_offset in range(days):
        d = (start + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        m = math.exp(rng.gauss(0.0, day_effect_sd)) if day_effect_sd > 0 else 1.0
        day_mult[d] = (m, rng.random() < event_day_rate)
    n_event_days = sum(1 for _, is_ev in day_mult.values() if is_ev)

    for bay in bays:
        busy_until = start_epoch
        for day_offset in range(days):
            day = start + timedelta(days=day_offset)
            day_start = day.timestamp()
            wd = day.weekday()                  # 0=Mon .. 6=Sun
            base = RHO_WEEKEND if wd >= 5 else RHO_WEEKDAY
            is_saturday = wd == 5
            dmult, is_event_day = day_mult[day.strftime("%Y-%m-%d")]

            for hour in range(24):
                rho = base[hour] * bay["mult"] * dmult
                if is_saturday and 8 <= hour < 15:
                    rho *= bay["sat"]           # market / retail spike
                if is_event_day and event_hours[0] <= hour < event_hours[1]:
                    rho *= event_multiplier
                rho = max(0.0, min(0.95, rho))
                if rho <= 0.001:
                    continue
                lam = rho / ((1.0 - rho) * mean_stay_h)
                h_start = day_start + hour * 3600
                h_end = h_start + 3600
                t = max(h_start, busy_until)
                while t < h_end:
                    # lam is per HOUR; t is epoch SECONDS.
                    t += rng.expovariate(lam) * 3600.0   # idle time is exponential
                    if t >= h_end:
                        break
                    stay_min = min(math.exp(rng.gauss(mu, sigma)), max_minutes)
                    arr = t
                    dep = arr + stay_min * 60.0
                    if dep >= end_epoch:
                        # Publisher truncates events crossing the archive
                        # boundary rather than reporting a partial stay.
                        counts["clipped_boundary"] += 1
                        busy_until = dep
                        break
                    busy_until = dep
                    t = dep                     # bay unavailable until departure

                    arr_dt = datetime.utcfromtimestamp(arr).replace(microsecond=0)
                    dep_dt = datetime.utcfromtimestamp(dep)
                    restriction = pick_restriction(rng)
                    sign = (f"{restriction} {arr_dt.hour:02d}00-"
                            f"{min(arr_dt.hour + 2, 23):02d}00")
                    seconds = int(round((dep - arr) / 1.0))
                    overstayed = "Yes" if rng.random() < overstay_rate else "No"
                    if overstayed == "Yes":
                        counts["overstayed"] += 1
                    a_s = arr_dt.strftime("%Y-%m-%dT%H:%M:%S")
                    d_s = dep_dt.strftime("%Y-%m-%dT%H:%M:%S")

                    # --- injected defects, at the publisher's own rates --- #
                    if rng.random() < defect_sign_old:
                        sign += " OLD"
                        counts["sign_old_suffix"] += 1
                    if rng.random() < defect_imputed:
                        # Times not recorded; the publisher imputes from
                        # midnight, which makes `seconds` meaningless.
                        a_s = arr_dt.strftime("%Y-%m-%dT00:00:00")
                        d_s = arr_dt.strftime("%Y-%m-%dT00:00:00")
                        seconds = 0
                        counts["imputed_times"] += 1
                    elif rng.random() < defect_negative:
                        # Arrival detected AFTER departure: sensor fault. The
                        # row survives into the archive with negative seconds.
                        seconds = -abs(seconds)
                        counts["negative_duration"] += 1

                    b1, b2 = BETWEEN[bay["street"]]
                    w.writerow([a_s, d_s, restriction, overstayed, bay["marker"],
                                sign, seconds, bay["street"], b1, b2])
                    n_rows += 1
                    if seconds > 0:
                        stay_sum += seconds
                        stay_n += 1

    fh.close()

    h = hashlib.sha256()
    with open(out_path, "rb") as rb:
        for chunk in iter(lambda: rb.read(1 << 20), b""):
            h.update(chunk)

    return {
        "rows": n_rows, "bays": len(bays), "days": days,
        "sha256": h.hexdigest(), "bytes": os.path.getsize(out_path),
        "defects": counts,
        "meanStayMinutes": round(stay_sum / stay_n / 60.0, 2) if stay_n else None,
        "targetMeanStayMinutes": mean_stay,
        "targetMedianStayMinutes": median_stay,
        "seed": seed, "startDate": start_date,
        "dayEffectSd": day_effect_sd, "eventDays": n_event_days,
        "eventDayRate": event_day_rate, "eventMultiplier": event_multiplier,
    }


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's algorithm. Retained for reference; the generator now uses a
    continuous-time renewal process per bay because a bay is a single server
    and Poisson counts per hour allow two cars in one bay at once."""
    if lam <= 0:
        return 0
    if lam > 30:                      # avoid exp(-lam) underflow on big rates
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="CSV path to write")
    ap.add_argument("--bays-scale", type=float, default=1.0,
                    help="scale the 800-bay street inventory (default 1.0)")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--start-date", default="2019-03-04")
    ap.add_argument("--seed", type=int, default=20190304)
    ap.add_argument("--median-stay", type=float, default=28.0,
                    help="minutes; the lognormal median")
    ap.add_argument("--mean-stay", type=float, default=40.0,
                    help="minutes; the lognormal MEAN. Little's Law uses this.")
    ap.add_argument("--max-minutes", type=int, default=1440,
                    help="cap on a single stay duration")
    # Publisher-documented defect rates, measured on the real archive.
    ap.add_argument("--defect-negative", type=float, default=0.0244)
    ap.add_argument("--defect-imputed", type=float, default=0.0149)
    ap.add_argument("--defect-sign-old", type=float, default=0.0345)
    ap.add_argument("--overstay-rate", type=float, default=0.1052)
    # Day-level demand variation. Without it, live fusion cannot be tested:
    # a climatological model is already near-optimal on a fixture whose days
    # are all identical, so sensors can only add sampling noise.
    ap.add_argument("--day-effect-sd", type=float, default=0.20,
                    help="lognormal SD of the per-day demand multiplier "
                         "(0 = every day identical, which makes fusion untestable)")
    ap.add_argument("--event-day-rate", type=float, default=0.06,
                    help="fraction of dates that are major-event days")
    ap.add_argument("--event-multiplier", type=float, default=1.8,
                    help="demand multiplier during --event-hours on event days")
    args = ap.parse_args()

    print("=" * 74)
    print("SYNTHETIC PARKING-EVENT FIXTURE  —  TEST INPUT, NOT REAL DATA")
    print("=" * 74)
    stats = generate(args.out, args.bays_scale, args.days, args.seed,
                     args.start_date, args.median_stay, args.mean_stay,
                     args.defect_negative, args.defect_imputed,
                     args.defect_sign_old, args.overstay_rate, args.max_minutes,
                     day_effect_sd=args.day_effect_sd,
                     event_day_rate=args.event_day_rate,
                     event_multiplier=args.event_multiplier)
    print(f"  out              : {args.out}")
    print(f"  rows             : {stats['rows']:,}")
    print(f"  bays / days      : {stats['bays']:,} / {stats['days']}")
    print(f"  bytes            : {stats['bytes']:,}")
    print(f"  sha256           : {stats['sha256']}")
    print(f"  mean stay        : {stats['meanStayMinutes']} min "
          f"(target {stats['targetMeanStayMinutes']})")
    print(f"  defects injected : {stats['defects']}")
    print(f"  day effects      : lognormal SD {stats['dayEffectSd']}, "
          f"{stats['eventDays']} event day(s) at x{stats['eventMultiplier']}")
    print("-" * 74)
    print("  Deterministic: re-running with the same flags reproduces these")
    print("  bytes exactly. NOT real parking data - do not calibrate a")
    print("  production model on it.")
    print("=" * 74)
    sys.exit(0)


if __name__ == "__main__":
    main()
