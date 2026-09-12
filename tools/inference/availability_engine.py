#!/usr/bin/env python3
"""
PTE Availability Inference Engine
=================================

The question this answers: given ALL the evidence we can get, what is the
probability that a parking space is free right now - and how much should anyone
trust that number?

WHY THIS IS THE PRODUCT
-----------------------
Relaying a municipal sensor feed is a commodity. Cities that publish one already
have dozens of apps doing exactly that, and cities that don't publish one leave
those apps with nothing to say. Neither position is defensible.

What is defensible is an estimator that:
  * fuses whatever evidence exists - live sensors, historical event archives,
    crowdsourced dwell, static inventory, time-of-day priors
  * returns a PROBABILITY with a credible interval, not a colour
  * degrades to UNKNOWN when evidence is thin instead of inventing certainty
  * can be SCORED against held-out ground truth, so "to the best of our ability"
    is a measured claim rather than a marketing one

METHOD
------
Per (street segment, day type, hour of day) the archive gives k occupied
bay-slots out of n observed bay-slots. Rather than use the raw ratio - which is
wildly unreliable for a street seen a handful of times - each cell is estimated
with an empirical-Bayes Beta posterior whose prior is the city-wide rate for that
hour:

    prior      Beta(a0, b0)   from the city-level aggregate, strength --prior-strength
    posterior  Beta(a0 + k, b0 + n - k)
    pOccupied  posterior mean
    interval   exact Beta quantiles via a continued-fraction incomplete beta

This is hierarchical shrinkage. A street with 5,000 observed slots keeps its own
estimate; a street with 8 slots is pulled almost entirely to the city prior, and
- crucially - its interval stays WIDE. Thin evidence produces honest uncertainty
instead of a confident wrong answer.

The published state uses the LOWER credible bound of pFree, not the point
estimate, so a cell only reports HIGH availability when the data supports it.

MODES
-----
build      read telemetry events -> model file (counts, priors, provenance)
predict    query the model for a street/time -> probability + interval + lineage
validate   hold out real dates, predict them, and SCORE the estimator
           (Brier, log loss, reliability bins, interval coverage)

STDLIB ONLY. Python 3.8+. No scipy.

    python3 availability_engine.py build --events out/archive/telemetry-events.jsonl \
        --out out/model.json
    python3 availability_engine.py predict --model out/model.json \
        --street "Collins St" --at "2026-09-15T12:30"
    python3 availability_engine.py validate --events out/archive/telemetry-events.jsonl \
        --holdout 0.2 --model-out out/model.json --report out/validation.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = 1
SLOT_MINUTES = 15          # occupancy sampling resolution
HIGH_LOWER_BOUND = 0.35    # pFree lower 95% bound needed to claim HIGH
MIN_SLOTS_FOR_STATE = 20

# Publishing HIGH confidence on a pattern seen on two days is exactly the false
# certainty this estimator exists to avoid. Day-to-day dispersion cannot even be
# estimated below ~5 dates, so a floor is required.
MIN_DATES_FOR_LIMITED = 5
MIN_DATES_FOR_HIGH = 12

# Conservative floor for between-day SD when dispersion is NOT measurable (too
# few dates). Never zero: an unmeasurable spread must widen the interval, not
# collapse it. 0.10 is deliberately pessimistic - it means "a given day may sit
# 10 points away from the average" - and is only used when the data cannot say.
DEFAULT_SD_DAY = 0.10   # below this, the answer is UNKNOWN regardless

# --------------------------------------------------------------------------- #
# Exact Beta distribution helpers (stdlib only)
# --------------------------------------------------------------------------- #

def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    MAXIT, EPS, FPMIN = 300, 3.0e-12, 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def betainc(a, b, x):
    """Regularised incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log1p(-x))
    front = math.exp(lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + b * math.log1p(-x) + a * math.log(x)) * _betacf(b, a, 1.0 - x) / b


def beta_quantile(a, b, p, lo=0.0, hi=1.0, iters=80):
    """Inverse of betainc by bisection. Exact enough for credible bounds."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# --------------------------------------------------------------------------- #
# Event loading
# --------------------------------------------------------------------------- #

def day_type(dt):
    return "weekend" if dt.weekday() >= 5 else "weekday"


def load_events(path, max_events=None):
    """Yield normalised events, skipping rows that cannot support inference."""
    kept = skipped = 0
    reasons = defaultdict(int)
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                reasons["unparseable_line"] += 1
                continue
            if max_events and kept >= max_events:
                break
            a = ev.get("arrivalEpoch")
            d = ev.get("departureEpoch")
            dur = ev.get("durationSeconds")
            if a is None and dur is None:
                skipped += 1
                reasons["no_time_information"] += 1
                continue
            if ev.get("timeConfidence") == "IMPUTED":
                # Publisher reconstructed these from midnight. Including them
                # would inject calendar artifacts into hour-of-day estimates.
                skipped += 1
                reasons["excluded_imputed_times"] += 1
                continue
            if isinstance(dur, (int, float)) and dur < 0:
                skipped += 1
                reasons["excluded_negative_duration"] += 1
                continue
            if a is not None and d is None and isinstance(dur, (int, float)):
                d = a + dur
            if a is None and d is not None and isinstance(dur, (int, float)):
                a = d - dur
            if a is None or d is None or d <= a:
                skipped += 1
                reasons["incomplete_interval"] += 1
                continue
            if d - a > 26 * 3600:
                skipped += 1
                reasons["excluded_implausible_stay"] += 1
                continue
            ev["_a"], ev["_d"] = a, d
            kept += 1
            yield ev
    load_events.stats = {"kept": kept, "skipped": skipped,
                         "skipReasons": dict(reasons)}


def slot_keys(a_epoch, d_epoch):
    """Yield (date_str, day_type, hour, slot_in_hour) tuples the event covers."""
    step = SLOT_MINUTES * 60
    start = int(a_epoch // step) * step
    t = start
    while t < d_epoch:
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        yield (dt.strftime("%Y-%m-%d"), day_type(dt), dt.hour,
               dt.minute // SLOT_MINUTES)
        t += step


# --------------------------------------------------------------------------- #
# MODE: build
# --------------------------------------------------------------------------- #

def build_model(events_path, prior_strength=30.0, max_events=None,
                source_meta=None, holdout_dates=None, daily_cell_cap=2_000_000):
    """Estimate P(free) per (street, day type, hour).

    DENOMINATOR - this is the part that is easy to get wrong, and getting it
    wrong is fatal. The numerator is the number of bay-slots a car actually
    occupied. The denominator must be the number of bay-slots that COULD have
    been occupied:

        n = distinct_bays(street) * distinct_dates(street, daytype) * slots_per_hour

    Counting only slots that appear in an event makes occupied == total and pins
    pOccupied at 1.0, i.e. "nowhere is ever free". An event archive records cars
    that were THERE; the empty slots are precisely what is missing from it, and
    they have to be reconstructed from bay inventory x calendar.
    """
    occupied = defaultdict(int)               # (street,daytype,hour) -> occupied slots
    city_occ = defaultdict(int)               # (daytype,hour)        -> occupied slots
    # (daytype,hour,date) -> occupied city slots. Bounded by 2*24*n_dates, so it
    # stays small even for a multi-year archive. Used to MEASURE day-to-day
    # overdispersion rather than assume slots are independent.
    daily_city = defaultdict(int)
    # (street,daytype,hour,date) -> occupied slots, for PER-CELL dispersion.
    # Hard-capped: once the cap is reached no NEW keys are added, though existing
    # keys keep accumulating. On a multi-street multi-year archive this is a
    # bounded approximation and the shortfall is reported, not hidden.
    daily_cell = {}
    daily_cell_capped = [False]
    bays_per_street = defaultdict(set)        # street -> {bayKey}
    city_bays = set()
    dates_per_street = defaultdict(set)       # (street,daytype) -> {date}
    city_dates = defaultdict(set)             # daytype -> {date}
    all_dates = set()
    n_events = 0
    slots_per_hour = 60 // SLOT_MINUTES

    holdout_dates = set(holdout_dates or ())

    for ev in load_events(events_path, max_events=max_events):
        a, d = ev["_a"], ev["_d"]
        street = ev.get("street") or "UNKNOWN_STREET"
        bay = ev.get("bayKey") or "UNKNOWN_BAY"
        n_events += 1
        # Bay inventory is static infrastructure, not an outcome, so it is taken
        # from every event including held-out dates. Excluding a bay that happens
        # to appear only on a held-out day would shrink the denominator and bias
        # occupancy upward. Noted rather than hidden.
        bays_per_street[street].add(bay)
        city_bays.add(bay)
        seen_cells = set()
        for date_s, dt_type, hour, slot in slot_keys(a, d):
            if date_s in holdout_dates:
                continue          # never train on held-out evidence
            key = (street, dt_type, hour)
            if (key, date_s, slot) in seen_cells:
                continue
            seen_cells.add((key, date_s, slot))
            occupied[key] += 1
            city_occ[(dt_type, hour)] += 1
            daily_city[(dt_type, hour, date_s)] += 1
            ck = (street, dt_type, hour, date_s)
            v = daily_cell.get(ck)
            if v is not None:
                daily_cell[ck] = v + 1
            elif len(daily_cell) < daily_cell_cap:
                daily_cell[ck] = 1
            else:
                daily_cell_capped[0] = True
            dates_per_street[(street, dt_type)].add(date_s)
            city_dates[dt_type].add(date_s)
            all_dates.add(date_s)

    stats = getattr(load_events, "stats", {})

    def denom_street(street, dt_type):
        return (len(bays_per_street.get(street, ())) *
                len(dates_per_street.get((street, dt_type), ())) * slots_per_hour)

    def denom_city(dt_type):
        return len(city_bays) * len(city_dates.get(dt_type, ())) * slots_per_hour

    # ---- measure overdispersion ------------------------------------------ #
    # Bay-slots are NOT independent observations. A single parking event covers
    # many consecutive 15-minute slots, and demand varies day to day far more
    # than a binomial allows. Treating n slots as n independent trials makes the
    # credible interval far too narrow - measured at 0.30 coverage of a nominal
    # 95% interval before this correction.
    #
    # phi is measured, not assumed: compare the observed between-date variance of
    # the daily occupancy rate with the variance a binomial would predict.
    overdispersion = {}
    for dt_type in ("weekday", "weekend"):
        n_day_city = len(city_bays) * slots_per_hour
        if n_day_city == 0:
            continue
        for hour in range(24):
            rates = [c / n_day_city for (t, h, _d), c in daily_city.items()
                     if t == dt_type and h == hour]
            # dates with no recorded occupancy are genuine zeros, not absences
            n_dates = len(city_dates.get(dt_type, ()))
            rates += [0.0] * max(0, n_dates - len(rates))
            if len(rates) < 3:
                continue
            p_bar = sum(rates) / len(rates)
            obs_var = sum((r - p_bar) ** 2 for r in rates) / (len(rates) - 1)
            bin_var = p_bar * (1.0 - p_bar) / n_day_city
            phi = max(1.0, obs_var / bin_var) if bin_var > 0 else 1.0
            overdispersion[f"{dt_type}|{hour}"] = {
                "phi": round(phi, 3),
                "datesUsed": len(rates),
                "meanDailyOccupancy": round(p_bar, 6),
                "observedBetweenDateVar": obs_var,
                "binomialVar": bin_var,
                "effectiveSampleFraction": round(1.0 / phi, 6),
            }

    def phi_for(dt_type, hour):
        od = overdispersion.get(f"{dt_type}|{hour}")
        return od["phi"] if od else 1.0

    # ---- per-cell dispersion, measured the same way ---------------------- #
    # City-level phi alone left 95% interval coverage at 0.73, because the
    # residual is street-specific: some streets genuinely vary more day to day
    # than the city average. Measuring phi per cell fixes the width where the
    # data supports it and falls back to the city estimate where it does not.
    cell_phi = {}
    cell_phi_source = {}
    cell_between_var = {}
    grouped = defaultdict(list)
    for (street, dt_type, hour, date_s), c in daily_cell.items():
        grouped[(street, dt_type, hour)].append(c)
    for key, counts in grouped.items():
        street, dt_type, hour = key
        n_day = len(bays_per_street.get(street, ())) * slots_per_hour
        n_dates = len(dates_per_street.get((street, dt_type), ()))
        if n_day == 0 or n_dates < 5 or len(counts) < 5:
            cell_phi[key] = phi_for(dt_type, hour)
            cell_phi_source[key] = "city-fallback(insufficient-dates)"
            continue
        rates = [c / n_day for c in counts]
        rates += [0.0] * max(0, n_dates - len(rates))
        p_bar = sum(rates) / len(rates)
        obs_var = sum((r - p_bar) ** 2 for r in rates) / (len(rates) - 1)
        bin_var = p_bar * (1.0 - p_bar) / n_day
        phi = max(1.0, obs_var / bin_var) if bin_var > 0 else 1.0
        cell_phi[key] = phi
        cell_phi_source[key] = "measured-per-cell"
        cell_between_var[key] = obs_var

    # ---- city-level priors (empirical Bayes) ----------------------------- #
    priors = {}
    for (dt_type, hour), k in city_occ.items():
        n = denom_city(dt_type)
        if n == 0:
            continue
        rate = min(1.0, k / n)
        a0 = max(1e-6, rate * prior_strength)
        b0 = max(1e-6, (1.0 - rate) * prior_strength)
        priors[f"{dt_type}|{hour}"] = {"a0": round(a0, 6), "b0": round(b0, 6),
                                       "cityRate": round(rate, 6),
                                       "cityOccupiedSlots": k, "cityTotalSlots": n}

    # ---- posteriors per cell --------------------------------------------- #
    out_cells = {}
    cells = {}
    for (street, dt_type, hour), k in occupied.items():
        n = denom_street(street, dt_type)
        if n == 0:
            continue
        cells[(street, dt_type, hour)] = (min(k, n), n)
    for (street, dt_type, hour), (k, n) in cells.items():
        pk = priors.get(f"{dt_type}|{hour}")
        a0 = pk["a0"] if pk else prior_strength * 0.5
        b0 = pk["b0"] if pk else prior_strength * 0.5
        # Quasi-binomial: scale BOTH successes and failures by phi. The mean is
        # preserved (so the point estimate is unchanged) while the variance is
        # inflated by phi, which is what makes the interval honest.
        phi = cell_phi.get((street, dt_type, hour)) or phi_for(dt_type, hour)
        k_eff, n_eff = k / phi, n / phi
        a, b = a0 + k_eff, b0 + (n_eff - k_eff)
        mean_occ = a / (a + b)
        p_free = 1.0 - mean_occ

        # TWO DIFFERENT UNCERTAINTIES, and conflating them is what produced
        # 0.30 then 0.67 coverage of a nominal 95% interval:
        #
        #   1. sd_mean  - how well the cell's average rate is known. Shrinks
        #                 with more evidence. This is the Beta posterior width.
        #   2. sd_day   - how much a GIVEN day departs from that average. Does
        #                 NOT shrink with more evidence; it is a property of the
        #                 street and hour.
        #
        # The product predicts a future day, so the interval must carry both.
        # A Beta posterior alone reports only (1), which is why it looked
        # certain while being wrong about individual days.
        ab = a + b
        sd_mean = math.sqrt(a * b / (ab * ab * (ab + 1.0))) if ab > 0 else 0.0
        bv = cell_between_var.get((street, dt_type, hour))
        if bv is None:
            od = overdispersion.get(f"{dt_type}|{hour}") or {}
            bv = od.get("observedBetweenDateVar")
        if bv is None or bv <= 0.0:
            # No measurable day-to-day spread. This happens with too few dates,
            # or when a cell looks artificially stable. Falling back to 0 would
            # publish a razor-thin interval built on almost no evidence.
            bv = DEFAULT_SD_DAY ** 2
            sd_day_source = "default-floor(not-measurable)"
        else:
            sd_day_source = "measured"
        sd_day = math.sqrt(bv)
        sd_pred = math.sqrt(sd_mean * sd_mean + sd_day * sd_day)
        p_free_lo = max(0.0, min(1.0, p_free - 1.96 * sd_pred))
        p_free_hi = max(0.0, min(1.0, p_free + 1.96 * sd_pred))
        shrink = a0 / (a0 + n_eff) if (a0 + n_eff) else 1.0
        out_cells[f"{street}|{dt_type}|{hour}"] = {
            "street": street, "dayType": dt_type, "hour": hour,
            "occupiedSlots": k, "totalSlots": n,
            "effectiveSlots": round(n_eff, 1), "overdispersionPhi": round(phi, 3),
            "sdMeanEstimate": round(sd_mean, 5),
            "sdBetweenDays": round(sd_day, 5), "sdDaySource": sd_day_source,
            "sdPredictive": round(sd_pred, 5),
            "phiSource": cell_phi_source.get((street, dt_type, hour), "city"),
            "pOccupied": round(mean_occ, 6),
            # same predictive interval expressed in occupied space
            "pOccupied95": [round(max(0.0, min(1.0, mean_occ - 1.96 * sd_pred)), 6),
                            round(max(0.0, min(1.0, mean_occ + 1.96 * sd_pred)), 6)],
            "pFree": round(p_free, 6),
            "pFree95": [round(p_free_lo, 6), round(p_free_hi, 6)],
            "shrinkageToPrior": round(shrink, 4),
            "datesUsed": len(dates_per_street.get((street, dt_type), ())),
            "sufficientEvidence": (n_eff >= MIN_SLOTS_FOR_STATE and
                                   len(dates_per_street.get((street, dt_type), ()))
                                   >= MIN_DATES_FOR_LIMITED),
        }

    model = {
        "schemaVersion": SCHEMA_VERSION,
        "builtAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "tools/inference/availability_engine.py",
        "slotMinutes": SLOT_MINUTES,
        "priorStrength": prior_strength,
        "trainingEvents": n_events,
        "eventFiltering": stats,
        "distinctStreets": len(bays_per_street),
        "distinctDates": len(all_dates),
        "dateRange": [min(all_dates), max(all_dates)] if all_dates else None,
        "baysPerStreet": {s: len(v) for s, v in bays_per_street.items()},
        "datesPerStreetDayType": {f"{s}|{t}": len(v)
                                  for (s, t), v in dates_per_street.items()},
        "denominatorRule": "totalSlots = distinct_bays(street) * "
                           "distinct_dates(street, dayType) * slots_per_hour. "
                           "An event archive only records bays that were "
                           "occupied; the empty slots are reconstructed from bay "
                           "inventory x calendar. Getting this wrong pins "
                           "pOccupied at 1.0.",
        "heldOutDates": sorted(holdout_dates),
        "priors": priors,
        "overdispersion": {
            "cityLevel": overdispersion,
            "perCellDatesCapped": daily_cell_capped[0],
            "perCellCap": daily_cell_cap,
            "perCellPhiSources": dict(Counter(cell_phi_source.values())),
            "method": "phi = observed between-date variance of the daily "
                      "occupancy rate / the variance a binomial would predict. "
                      "Measured per (street, dayType, hour) where at least 5 "
                      "dates are available, else the city-level estimate for "
                      "that dayType and hour is used. Applied quasi-binomially: "
                      "successes and failures are both divided by phi, which "
                      "preserves the point estimate and inflates the variance.",
            "why": "Bay-slots are not independent. One parking event covers many "
                   "consecutive slots and demand varies day to day, so treating "
                   "n slots as n trials makes intervals far too narrow. Measured "
                   "coverage of a nominal 95% interval was 0.30 before any "
                   "correction and 0.73 with a city-level phi alone.",
        },
        "cells": {k: dict(v, publishedState=state_from(v))
                  for k, v in out_cells.items()},
        "stateRule": {
            "HIGH": f"pFree lower 95% bound > {HIGH_LOWER_BOUND} AND "
                    f"effectiveSlots >= {MIN_SLOTS_FOR_STATE} AND "
                    f"distinctDates >= {MIN_DATES_FOR_HIGH}",
            "LIMITED": f"distinctDates >= {MIN_DATES_FOR_LIMITED} but the lower "
                       f"bound or the day count does not clear the HIGH bar",
            "UNKNOWN": f"distinctDates < {MIN_DATES_FOR_LIMITED}, or "
                       f"effectiveSlots < {MIN_SLOTS_FOR_STATE}, or no cell for "
                       f"that street/hour",
            "highLowerBound": HIGH_LOWER_BOUND,
            "minSlots": MIN_SLOTS_FOR_STATE,
            "minDatesLimited": MIN_DATES_FOR_LIMITED,
            "minDatesHigh": MIN_DATES_FOR_HIGH,
            "defaultSdDay": DEFAULT_SD_DAY,
            "note": "The published state uses the LOWER bound of the predictive "
                    "interval, not the point estimate, so HIGH is only claimed "
                    "when the evidence supports it. A confident point estimate "
                    "from thin data still yields LIMITED or UNKNOWN. Where "
                    "day-to-day dispersion cannot be measured, the interval uses "
                    f"a conservative floor of {DEFAULT_SD_DAY} rather than "
                    "collapsing to zero - unmeasurable uncertainty must widen "
                    "the interval, never narrow it.",
        },
        "timezoneCaveat": "Hours are UTC as labelled by the harvester. If the "
                          "source timestamps are publisher-local, the hour axis "
                          "is shifted and must be corrected before use.",
        "legalityClaimed": False,
        "note": "AVAILABILITY lane only. This engine estimates the probability "
                "that a space is free. It makes no claim about whether parking "
                "there is legal, and a HIGH availability estimate must never "
                "upgrade a PROHIBITED / CONFLICT / UNKNOWN legality verdict.",
    }
    if source_meta:
        model["provenance"] = source_meta
    return model


def cell_for(model, street, dt):
    key = f"{street}|{day_type(dt)}|{dt.hour}"
    return model["cells"].get(key)


def fallback_for(model, dt):
    """City-level prior for that hour, used when a street has no cell."""
    pk = model["priors"].get(f"{day_type(dt)}|{dt.hour}")
    if not pk:
        return None
    a, b = pk["a0"], pk["b0"]
    mean_occ = a / (a + b)
    return {
        "street": None, "dayType": day_type(dt), "hour": dt.hour,
        "occupiedSlots": None, "totalSlots": 0,
        "pOccupied": round(mean_occ, 6),
        "pOccupied95": [round(beta_quantile(a, b, 0.025), 6),
                        round(beta_quantile(a, b, 0.975), 6)],
        "pFree": round(1.0 - mean_occ, 6),
        "pFree95": [round(1.0 - beta_quantile(a, b, 0.975), 6),
                    round(1.0 - beta_quantile(a, b, 0.025), 6)],
        "shrinkageToPrior": 1.0,
        "sufficientEvidence": False,
        "fallback": "city-prior-for-hour",
    }


def state_from(cell):
    """Map an estimate onto the three-state contract: HIGH / LIMITED / UNKNOWN.

    HIGH is deliberately hard to reach. It requires the LOWER bound of the
    predictive interval to clear the threshold, enough effective bay-slots, AND
    enough distinct days - because a pattern seen on two Tuesdays is a rumour,
    not a model.
    """
    if cell is None or not cell.get("sufficientEvidence"):
        return "UNKNOWN"
    if cell["pFree95"][0] <= HIGH_LOWER_BOUND:
        return "LIMITED"
    if cell.get("datesUsed", 0) < MIN_DATES_FOR_HIGH:
        return "LIMITED"          # confident-looking, but not enough days to trust
    return "HIGH"


# --------------------------------------------------------------------------- #
# MODE: predict
# --------------------------------------------------------------------------- #

def cmd_predict(args):
    with open(args.model) as fh:
        model = json.load(fh)
    dt = datetime.strptime(args.at.replace(" ", "T"), "%Y-%m-%dT%H:%M")
    dt = dt.replace(tzinfo=timezone.utc)

    cell = cell_for(model, args.street, dt)
    used_fallback = False
    if cell is None:
        cell = fallback_for(model, dt)
        used_fallback = cell is not None

    result = {
        "query": {"street": args.street, "at": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "dayType": day_type(dt), "hour": dt.hour},
        "pFree": cell["pFree"] if cell else None,
        "pFree95": cell["pFree95"] if cell else None,
        "pOccupied": cell["pOccupied"] if cell else None,
        "availability": state_from(cell) if cell else "UNKNOWN",
        "evidenceSlots": cell.get("totalSlots") if cell else 0,
        "shrinkageToPrior": cell.get("shrinkageToPrior") if cell else 1.0,
        "usedCityPriorFallback": used_fallback,
        "modelProvenance": model.get("provenance"),
        "modelBuiltAt": model.get("builtAt"),
        "trainingEvents": model.get("trainingEvents"),
        "timezoneCaveat": model.get("timezoneCaveat"),
        "legalityClaimed": False,
        "separationNote": "Availability only. This estimate cannot make an "
                          "illegal, conflicted or unknown curb legal.",
    }
    if cell is None:
        result["reason"] = ("No cell for this street/day-type/hour and no "
                            "city prior for that hour. UNKNOWN, not a guess.")

    print(json.dumps(result, indent=2))
    if not args.json:
        av = result["availability"]
        pf = result["pFree"]
        lo, hi = (result["pFree95"] or [None, None])
        print("-" * 70, file=sys.stderr)
        print(f"  {args.street} @ {result['query']['at']} ({result['query']['dayType']})",
              file=sys.stderr)
        if pf is None:
            print("  availability: UNKNOWN - no evidence", file=sys.stderr)
        else:
            print(f"  availability: {av}", file=sys.stderr)
            print(f"  P(free)     : {pf:.3f}   95% CI [{lo:.3f}, {hi:.3f}]",
                  file=sys.stderr)
            print(f"  evidence    : {result['evidenceSlots']} bay-slots "
                  f"(shrinkage to prior {result['shrinkageToPrior']:.2f})",
                  file=sys.stderr)
            if used_fallback:
                print("  NOTE        : used the CITY PRIOR for this hour; this "
                      "street has no observations of its own.", file=sys.stderr)
        print("-" * 70, file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# MODE: validate  (hold out real dates, then score the estimator)
# --------------------------------------------------------------------------- #

def observed_occupancy(events_path, dates, max_events=None):
    """Ground truth: fraction of bay-slots occupied on the held-out dates."""
    cells = defaultdict(lambda: [0, 0])
    dates = set(dates)
    for ev in load_events(events_path, max_events=max_events):
        a, d = ev["_a"], ev["_d"]
        street = ev.get("street") or "UNKNOWN_STREET"
        seen = set()
        for date_s, dt_type, hour, slot in slot_keys(a, d):
            if date_s not in dates:
                continue
            key = (street, dt_type, hour)
            if (key, date_s, slot) in seen:
                continue
            seen.add((key, date_s, slot))
            cells[key][0] += 1
            cells[key][1] += 1
    return {f"{s}|{t}|{h}": (k, n) for (s, t, h), (k, n) in cells.items()}


def denominator_slots(events_path, dates, max_events=None, bay_inventory=None):
    """Total bay-slots AVAILABLE (occupied or not) on the held-out dates.

    pFree is only meaningful against a denominator that includes slots where no
    car was present. Reconstructed as distinct bays x distinct dates x slots per
    hour.

    bay_inventory must be the SAME inventory the model was trained with. Taking
    it only from held-out events would silently drop bays that were empty on
    every held-out day, shrinking the denominator and overstating observed
    occupancy - which would make the estimator look worse than it is.
    """
    bays = defaultdict(set)
    day_dates = defaultdict(set)
    dates = set(dates)
    for ev in load_events(events_path, max_events=max_events):
        street = ev.get("street") or "UNKNOWN_STREET"
        if bay_inventory is None:
            bays[street].add(ev.get("bayKey") or "UNKNOWN_BAY")
        for date_s, dt_type, hour, slot in slot_keys(ev["_a"], ev["_d"]):
            if date_s in dates:
                day_dates[(street, dt_type)].add(date_s)
    if bay_inventory is not None:
        for street, n in bay_inventory.items():
            bays[street] = set(range(int(n)))   # count is what the denominator needs
    slots_per_hour = 60 // SLOT_MINUTES
    denom = {}
    for street, bs in bays.items():
        for (s, dt_type), ds in day_dates.items():
            if s != street:
                continue
            for hour in range(24):
                denom[f"{street}|{dt_type}|{hour}"] = len(bs) * len(ds) * slots_per_hour
    return denom


def cmd_validate(args):
    rng = random.Random(args.seed)
    all_dates = set()
    for ev in load_events(args.events, max_events=args.scan_only):
        for date_s, _, _, _ in slot_keys(ev["_a"], ev["_d"]):
            all_dates.add(date_s)
            break
    all_dates = sorted(all_dates)
    if len(all_dates) < 5:
        raise SystemExit(f"only {len(all_dates)} distinct dates; need >= 5 to "
                         f"hold any out meaningfully")

    n_hold = max(1, int(round(len(all_dates) * args.holdout)))
    holdout = set(rng.sample(all_dates, n_hold))
    train_dates = [d for d in all_dates if d not in holdout]

    print("=" * 74)
    print("AVAILABILITY ESTIMATOR VALIDATION — scored against held-out reality")
    print("=" * 74)
    print(f"  dates total   : {len(all_dates)}  ({all_dates[0]} .. {all_dates[-1]})")
    print(f"  training      : {len(train_dates)}")
    print(f"  held out      : {len(holdout)}  {sorted(holdout)[:6]}"
          f"{' ...' if len(holdout) > 6 else ''}")
    print("-" * 74, flush=True)

    print("  building model on training dates only ...", flush=True)
    model = build_model(args.events, prior_strength=args.prior_strength,
                        max_events=args.max_events, holdout_dates=holdout,
                        source_meta={"eventsFile": os.path.abspath(args.events)})

    print("  reconstructing held-out ground truth ...", flush=True)
    truth = observed_occupancy(args.events, holdout, max_events=args.max_events)
    denom = denominator_slots(args.events, holdout, max_events=args.max_events,
                              bay_inventory=model.get("baysPerStreet"))

    rows = []
    for key, (k, n_occ_slots) in truth.items():
        n_total = denom.get(key)
        if not n_total:
            continue
        observed_p_occ = min(1.0, n_occ_slots / n_total)
        street, dt_type, hour = key.split("|")
        cell = model["cells"].get(key) or fallback_for(model, _fake_dt(dt_type, int(hour)))
        if cell is None:
            continue
        rows.append({
            "key": key, "street": street, "dayType": dt_type, "hour": int(hour),
            "observedPOccupied": round(observed_p_occ, 6),
            "observedPFree": round(1.0 - observed_p_occ, 6),
            "predictedPOccupied": cell["pOccupied"],
            "predictedPFree": cell["pFree"],
            "predictedPFree95": cell["pFree95"],
            "evidenceSlots": cell.get("totalSlots") or 0,
            "shrinkageToPrior": cell.get("shrinkageToPrior"),
            "state": state_from(cell),
            "heldOutOccupiedSlots": n_occ_slots,
            "heldOutTotalSlots": n_total,
        })

    if not rows:
        raise SystemExit("no comparable cells between prediction and ground truth")

    # ---- scoring ---------------------------------------------------------- #
    brier = sum((r["predictedPFree"] - r["observedPFree"]) ** 2 for r in rows) / len(rows)
    eps = 1e-9
    logloss = -sum(
        r["observedPFree"] * math.log(max(eps, r["predictedPFree"]))
        + (1 - r["observedPFree"]) * math.log(max(eps, 1 - r["predictedPFree"]))
        for r in rows) / len(rows)
    mae = sum(abs(r["predictedPFree"] - r["observedPFree"]) for r in rows) / len(rows)

    # baseline: always predict the training-set mean
    base_p = sum(r["predictedPFree"] for r in rows) / len(rows)
    brier_base = sum((base_p - r["observedPFree"]) ** 2 for r in rows) / len(rows)

    # interval coverage: does the 95% CI actually contain the truth ~95% of the time?
    covered = sum(1 for r in rows
                  if r["predictedPFree95"][0] - 1e-9 <= r["observedPFree"] <= r["predictedPFree95"][1] + 1e-9)
    coverage = covered / len(rows)

    # reliability bins
    bins = [(0.0, 0.1), (0.1, 0.25), (0.25, 0.4), (0.4, 0.55),
            (0.55, 0.7), (0.7, 0.85), (0.85, 1.01)]
    reliability = []
    for lo, hi in bins:
        sel = [r for r in rows if lo <= r["predictedPFree"] < hi]
        if not sel:
            continue
        reliability.append({
            "predictedBin": [lo, round(min(hi, 1.0), 3)],
            "cells": len(sel),
            "meanPredictedPFree": round(sum(r["predictedPFree"] for r in sel) / len(sel), 4),
            "meanObservedPFree": round(sum(r["observedPFree"] for r in sel) / len(sel), 4),
            "calibrationGap": round(sum(r["observedPFree"] - r["predictedPFree"] for r in sel) / len(sel), 4),
        })

    # how do UNKNOWN cells compare to cells with real evidence?
    by_state = defaultdict(list)
    for r in rows:
        by_state[r["state"]].append(r)
    per_state = {}
    for st, rs in by_state.items():
        per_state[st] = {
            "cells": len(rs),
            "mae": round(sum(abs(r["predictedPFree"] - r["observedPFree"]) for r in rs) / len(rs), 4),
            "meanEvidenceSlots": round(sum(r["evidenceSlots"] for r in rs) / len(rs), 1),
        }

    # stratify by evidence volume: does more data actually help?
    evidence_strata = []
    for lo, hi, label in ((0, MIN_SLOTS_FOR_STATE, f"<{MIN_SLOTS_FOR_STATE} slots"),
                          (MIN_SLOTS_FOR_STATE, 200, "20-199 slots"),
                          (200, 2000, "200-1999 slots"),
                          (2000, 10 ** 9, "2000+ slots")):
        sel = [r for r in rows if lo <= r["evidenceSlots"] < hi]
        if not sel:
            continue
        evidence_strata.append({
            "stratum": label, "cells": len(sel),
            "mae": round(sum(abs(r["predictedPFree"] - r["observedPFree"]) for r in sel) / len(sel), 4),
            "brier": round(sum((r["predictedPFree"] - r["observedPFree"]) ** 2 for r in sel) / len(sel), 5),
            "meanShrinkage": round(sum(r["shrinkageToPrior"] for r in sel) / len(sel), 4),
        })

    worst = sorted(rows, key=lambda r: -abs(r["predictedPFree"] - r["observedPFree"]))[:12]

    report = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "hold out whole DATES, train on the rest, score predictions "
                  "against reconstructed occupancy on the held-out dates. "
                  "Holding out dates (not rows) prevents leakage: a stay that "
                  "spans a held-out day would otherwise appear in both sets.",
        "eventsFile": os.path.abspath(args.events),
        "slotMinutes": SLOT_MINUTES,
        "priorStrength": args.prior_strength,
        "totalDates": len(all_dates),
        "trainingDates": len(train_dates),
        "heldOutDates": sorted(holdout),
        "cellsScored": len(rows),
        "scores": {
            "brier": round(brier, 6),
            "brierBaselineSameValueEverywhere": round(brier_base, 6),
            "brierSkillScore": round(1 - brier / brier_base, 4) if brier_base else None,
            "logLoss": round(logloss, 6),
            "meanAbsoluteError": round(mae, 4),
            "ci95Coverage": round(coverage, 4),
            "ci95CoverageNote": "A well-calibrated 95% interval should contain "
                                "the truth ~0.95 of the time. Materially below "
                                "means the intervals are overconfident and the "
                                "engine is claiming more certainty than it has.",
        },
        "reliabilityBins": reliability,
        "byPublishedState": per_state,
        "byEvidenceVolume": evidence_strata,
        "worstCells": worst,
        "eventFiltering": model.get("eventFiltering"),
        "interpretation": [],
        "legalityClaimed": False,
    }

    # plain-language interpretation, generated from the numbers
    interp = report["interpretation"]
    skill = report["scores"]["brierSkillScore"]
    if skill is not None:
        interp.append(
            f"Brier skill score vs a constant predictor: {skill:+.3f}. "
            + ("Positive means the estimator beats 'say the same number "
               "everywhere'." if skill > 0 else
               "NOT positive: the estimator does not yet beat a constant "
               "predictor on held-out data. Do not ship it."))
    interp.append(f"Mean absolute error on P(free): {mae:.3f} "
                  f"({'roughly ±' + format(int(mae*100)) + ' points' if mae else 'n/a'}).")
    if coverage < 0.90:
        interp.append(f"95% interval coverage is only {coverage:.2f} - intervals "
                      f"are OVERCONFIDENT. Widen them or report UNKNOWN more often.")
    elif coverage > 0.99:
        interp.append(f"95% interval coverage is {coverage:.2f} - intervals are "
                      f"conservative; they could be tightened.")
    else:
        interp.append(f"95% interval coverage {coverage:.2f} is in the expected "
                      f"range - the stated uncertainty is honest.")
    if evidence_strata:
        thin = next((s for s in evidence_strata if s["stratum"].startswith("<")), None)
        thick = evidence_strata[-1]
        if thin and thick and thick["cells"]:
            interp.append(
                f"MAE with {thin['stratum']}: {thin['mae']:.3f} vs "
                f"{thick['stratum']}: {thick['mae']:.3f}. "
                + ("More evidence does reduce error, as expected."
                   if thick["mae"] < thin["mae"] else
                   "More evidence did NOT reduce error here - investigate before "
                   "trusting the shrinkage."))
    interp.append("Availability only. None of this says anything about legality.")

    os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
    with open(args.report, "w") as fh:
        json.dump(report, fh, indent=2)
    if args.model_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.model_out)) or ".", exist_ok=True)
        with open(args.model_out, "w") as fh:
            json.dump(model, fh, indent=2)

    print(f"  cells scored  : {len(rows)}")
    print("-" * 74)
    print("  SCORES")
    print(f"    Brier                     : {brier:.5f}")
    print(f"    Brier (constant baseline) : {brier_base:.5f}")
    print(f"    Brier skill score         : {report['scores']['brierSkillScore']:+.4f}")
    print(f"    log loss                  : {logloss:.5f}")
    print(f"    mean absolute error       : {mae:.4f}")
    print(f"    95% CI coverage           : {coverage:.3f}   (target ~0.95)")
    print("-" * 74)
    print("  RELIABILITY (predicted vs observed P(free))")
    for b in reliability:
        bar = "#" * int(b["meanObservedPFree"] * 30)
        print(f"    pred {b['predictedBin'][0]:.2f}-{b['predictedBin'][1]:.2f} "
              f"n={b['cells']:>4}  pred={b['meanPredictedPFree']:.3f} "
              f"obs={b['meanObservedPFree']:.3f} gap={b['calibrationGap']:+.3f} {bar}")
    print("-" * 74)
    print("  BY EVIDENCE VOLUME")
    for s in evidence_strata:
        print(f"    {s['stratum']:<16} cells={s['cells']:>4}  MAE={s['mae']:.3f}  "
              f"Brier={s['brier']:.4f}  shrinkage={s['meanShrinkage']:.2f}")
    print("-" * 74)
    print("  BY PUBLISHED STATE")
    for st, v in sorted(per_state.items()):
        print(f"    {st:<9} cells={v['cells']:>4}  MAE={v['mae']:.3f}  "
              f"meanEvidenceSlots={v['meanEvidenceSlots']}")
    print("-" * 74)
    print("  WORST CELLS")
    for r in worst[:6]:
        print(f"    {r['street'][:22]:<22} {r['dayType'][:3]} {r['hour']:02d}h "
              f"pred={r['predictedPFree']:.3f} obs={r['observedPFree']:.3f} "
              f"slots={r['evidenceSlots']}")
    print("-" * 74)
    print("  INTERPRETATION")
    for line in interp:
        print(f"    - {line}")
    print("-" * 74)
    print(f"  report : {args.report}")
    if args.model_out:
        print(f"  model  : {args.model_out}")
    print("=" * 74)
    return 0


def _fake_dt(dt_type, hour):
    """Construct a datetime with the requested day-type and hour."""
    base = datetime(2026, 9, 15, tzinfo=timezone.utc)      # a Tuesday
    if dt_type == "weekend":
        base = datetime(2026, 9, 19, tzinfo=timezone.utc)  # a Saturday
    return base.replace(hour=hour)


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build a model from telemetry events")
    b.add_argument("--events", required=True)
    b.add_argument("--prior-strength", type=float, default=30.0,
                   help="pseudo-slots of prior. Higher = more shrinkage toward "
                        "the city average for thin streets.")
    b.add_argument("--max-events", type=int, default=None)
    b.add_argument("--out", default="model.json")

    p = sub.add_parser("predict", help="query the model")
    p.add_argument("--model", required=True)
    p.add_argument("--street", required=True)
    p.add_argument("--at", required=True, help="'YYYY-MM-DDTHH:MM'")
    p.add_argument("--json", action="store_true", help="suppress the stderr summary")

    v = sub.add_parser("validate", help="score the estimator on held-out dates")
    v.add_argument("--events", required=True)
    v.add_argument("--holdout", type=float, default=0.2,
                   help="fraction of DATES to hold out (default 0.2)")
    v.add_argument("--prior-strength", type=float, default=30.0)
    v.add_argument("--max-events", type=int, default=None)
    v.add_argument("--scan-only", type=int, default=None,
                   help="cap events when scanning for the date list")
    v.add_argument("--seed", type=int, default=1337)
    v.add_argument("--model-out", default=None)
    v.add_argument("--report", default="validation-report.json")

    args = ap.parse_args()
    if args.cmd == "build":
        model = build_model(args.events, prior_strength=args.prior_strength,
                            max_events=args.max_events,
                            source_meta={"eventsFile": os.path.abspath(args.events)})
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            json.dump(model, fh, indent=2)
        cells = model["cells"]
        suff = sum(1 for c in cells.values() if c["sufficientEvidence"])
        print("=" * 74)
        print("AVAILABILITY MODEL BUILT")
        print("=" * 74)
        print(f"  events used      : {model['trainingEvents']:,}")
        print(f"  skipped          : {model['eventFiltering']}")
        print(f"  cells            : {len(cells):,}  "
              f"({suff:,} with sufficient evidence, "
              f"{len(cells)-suff:,} -> UNKNOWN)")
        print(f"  streets          : {model['distinctStreets']}")
        print(f"  date range       : {model['dateRange']}")
        print(f"  prior strength   : {model['priorStrength']}")
        print(f"  written          : {args.out}")
        print("=" * 74)
        sys.exit(0)
    elif args.cmd == "predict":
        sys.exit(cmd_predict(args))
    elif args.cmd == "validate":
        sys.exit(cmd_validate(args))


if __name__ == "__main__":
    main()
