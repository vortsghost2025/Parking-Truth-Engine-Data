#!/usr/bin/env python3
"""Street/CPZ aggregation and Spatial Accuracy stratification
(PTE-TEL-003 deliverables 3 and 4).

WHY THIS EXISTS
---------------
PCN events have to become comparable counts before they can mean anything. This
module turns normalised events and bays into a complete grid of cells, keyed at
STREET / CPZ level and stratified by Spatial Accuracy.

THE FOUR DECISIONS THAT MATTER
------------------------------
1. THE JOIN IS STREET/CPZ LEVEL, NEVER BAY LEVEL. Camden states that individual
   parking spaces cannot be identified and that bay coordinates come from an
   ARBITRARY NODE along the polyline geometry. Any bay-level join would be
   spurious precision, so no bay identifier and no coordinate ever enters a cell
   key. `assert_no_bay_level_join()` enforces that structurally.

2. THE GRID IS COMPLETE, INCLUDING ZEROES. A cell exists for every
   street x stratum x dayType x hour combination, with a count of zero where no
   PCN was issued. Without this, "no PCNs" is invisible - and no PCNs could mean
   low pressure OR no enforcement, which is the entire confound this harness
   exists to examine.

3. EXPOSURE IS DATE-BASED, NOT EVENT-BASED. The denominator for a per-bay rate is
   capacity x the number of distinct dates of that dayType in the series, not the
   number of dates on which something happened. Otherwise quiet streets look
   artificially intense.

4. STRATA ARE SEPARATE DIMENSIONS. CEO_GPS, FIXED_CCTV and UNKNOWN_OTHER never
   share a cell. Pooling is possible only through `pool_strata()`, which stamps
   the result with `pooledFrom` so a report can show the effect of pooling
   instead of hiding it.

UNKNOWN HOURS ARE NOT FORCED INTO THE GRID. Records whose source carried a date
but no time are aggregated separately in `unknownHourCells` and reported. They
contribute to street/dayType totals and to nothing hourly.

STDLIB ONLY. Deterministic: same inputs -> same outputs.
"""

from __future__ import annotations

import re
from collections import defaultdict

from camden_normalize import (
    DAYTYPE_SATURDAY,
    DAYTYPE_SUNDAY,
    DAYTYPE_WEEKDAY,
    STRATA,
)

DAY_TYPES = (DAYTYPE_WEEKDAY, DAYTYPE_SATURDAY, DAYTYPE_SUNDAY)
HOURS = tuple(range(24))

JOIN_LEVEL_STREET = "STREET"
JOIN_LEVEL_CPZ = "CPZ"


# ---------------------------------------------------------------------------
# Street matching
# ---------------------------------------------------------------------------

_TOKEN_DROP = {"st", "street", "road", "rd", "lane", "ln", "row", "square",
               "sq", "terrace", "terr", "avenue", "ave", "close", "cl",
               "place", "pl", "way", "mews", "walk", "grove", "hill"}


def street_key(value: str | None) -> str | None:
    """Reduce a street name to a comparable token.

    Case-folds, strips punctuation and collapses whitespace. Deliberately
    conservative: it does NOT remove type words, because in Camden "High Street"
    and "High Road" are different places. The token is a matching aid, not a
    claim that two strings are the same street.
    """
    if value is None:
        return None
    s = re.sub(r"[^a-z0-9]+", " ", str(value).strip().lower())
    s = " ".join(s.split())
    return s or None


def join_key(record: dict, level: str) -> str | None:
    """Build the aggregation key at the requested level.

    STREET level -> "<cpz>||<street>" (CPZ retained because street names repeat
    across zones and the CPZ is the enforcement regime boundary).
    CPZ level -> "<cpz>".
    Returns None when the record cannot be placed, which is counted as
    missingness rather than silently bucketed.
    """
    cpz = (record.get("cpz") or "").strip()
    if level == JOIN_LEVEL_CPZ:
        return cpz or None
    street = street_key(record.get("street"))
    if not street:
        return None
    return f"{cpz}||{street}"


def join_key_parts(key: str | None) -> tuple[str | None, str | None]:
    if key is None:
        return None, None
    if "||" not in key:
        return key, None
    cpz, street = key.split("||", 1)
    return (cpz or None), (street or None)


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

def build_capacity(bays: list[dict], level: str) -> dict:
    """Aggregate publisher-supplied bay capacity to the join level.

    Capacity is used ONLY where the publisher supplies it. Where it does not,
    `spaceCount` stays None rather than defaulting to zero, because zero spaces
    and unknown spaces mean completely different things to a per-bay rate.

    The approximate-capacity flag propagates: a street's capacity is approximate
    if ANY contributing bay is flagged approximate. For Camden that is always,
    because the publisher describes the figure as approximate.
    """
    per_key: dict[str, dict] = {}
    unmatched_streets: set[str] = set()

    for bay in bays:
        key = join_key(bay, level)
        if key is None:
            unmatched_streets.add(str(bay.get("street") or "<missing>"))
            continue
        slot = per_key.setdefault(key, {
            "joinKey": key,
            "joinLevel": level,
            "cpz": join_key_parts(key)[0],
            "street": join_key_parts(key)[1],
            "bayCount": 0,
            "baysWithCapacity": 0,
            "spaceCount": None,
            "bayLengthMTotal": None,
            "capacitySuppliedByPublisher": False,
            "capacityIsApproximate": False,
            "centroidIsArbitraryNode": True,
            "individualSpacesIdentifiable": False,
            "restrictionTypes": set(),
            "tariffs": set(),
            "maximumStays": set(),
            "timesOfOperation": set(),
            "geometryPresent": 0,
        })
        slot["bayCount"] += 1
        if bay.get("capacitySuppliedByPublisher") and bay.get("spaceCount") is not None:
            slot["baysWithCapacity"] += 1
            slot["spaceCount"] = (slot["spaceCount"] or 0.0) + float(bay["spaceCount"])
            slot["capacitySuppliedByPublisher"] = True
            if bay.get("spaceCountIsApproximate"):
                slot["capacityIsApproximate"] = True
        if bay.get("bayLengthM") is not None:
            slot["bayLengthMTotal"] = (slot["bayLengthMTotal"] or 0.0) + float(bay["bayLengthM"])
        if bay.get("restrictionType"):
            slot["restrictionTypes"].add(str(bay["restrictionType"]))
        if bay.get("tariff"):
            slot["tariffs"].add(str(bay["tariff"]))
        if bay.get("maximumStay"):
            slot["maximumStays"].add(str(bay["maximumStay"]))
        if bay.get("timesOfOperation"):
            slot["timesOfOperation"].add(str(bay["timesOfOperation"]))
        summary = bay.get("geometrySummary") or {}
        if summary.get("present"):
            slot["geometryPresent"] += 1

    # Freeze sets into sorted lists so the output is deterministic and JSON-safe.
    for slot in per_key.values():
        for field in ("restrictionTypes", "tariffs", "maximumStays", "timesOfOperation"):
            slot[field] = sorted(slot[field])
        if slot["bayCount"]:
            slot["capacityCoverageFraction"] = round(
                slot["baysWithCapacity"] / slot["bayCount"], 6)
        else:
            slot["capacityCoverageFraction"] = 0.0

    return {"capacity": per_key, "bayStreetsUnmatched": sorted(unmatched_streets)}


# ---------------------------------------------------------------------------
# Exposure (date index)
# ---------------------------------------------------------------------------

def build_date_index(pcns: list[dict]) -> dict:
    """Index the distinct dates present in the PCN series, by dayType.

    This is the exposure denominator. It comes from the event series because
    that is the only place the observation window is documented; if the bay
    inventory covers a period the PCN series does not, that mismatch is a
    coverage finding and is reported, not smoothed over.
    """
    dates_by_daytype: dict[str, set[str]] = {dt: set() for dt in DAY_TYPES}
    date_to_daytype: dict[str, str] = {}
    all_dates: set[str] = set()

    for e in pcns:
        t = e.get("temporal") or {}
        d = t.get("date")
        if not d:
            continue
        all_dates.add(d)
        dt = t.get("dayType")
        if dt in DAY_TYPES:
            dates_by_daytype[dt].add(d)
            # dayType is a pure function of the date, so setdefault cannot
            # disagree with itself; it only makes the choice deterministic.
            date_to_daytype.setdefault(d, dt)

    return {
        "distinctDates": len(all_dates),
        "dateMin": min(all_dates) if all_dates else None,
        "dateMax": max(all_dates) if all_dates else None,
        "datesByDayType": {dt: len(dates_by_daytype[dt]) for dt in DAY_TYPES},
        "dateList": sorted(all_dates),
        "dateDayTypeMap": {d: date_to_daytype[d] for d in sorted(date_to_daytype)},
    }


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------

def _new_cell(join: str, cpz, street, stratum: str, day_type: str, hour) -> dict:
    """A fresh cell.

    Cells are stored SPARSELY: only combinations that actually contain at least
    one PCN are materialised. A missing cell means ZERO events, and because
    exposure is computed analytically from capacity x dates-of-that-dayType the
    zero is still counted in every rate. That preserves complete-grid semantics
    without allocating hundreds of thousands of empty dicts on a real Camden
    download.
    """
    return {
        "joinKey": join,
        "cpz": cpz,
        "street": street,
        "spatialStratum": stratum,
        "dayType": day_type,
        "hour": hour,               # None => hour unknown, never midnight
        "hourKnown": hour is not None,
        "pcnCount": 0,
        "dateCount": 0,
        "distinctDates": [],
        "contraventionClassCounts": {},
        "ticketTypes": {},
        "caseStatuses": {},
        "vehicleCategories": {},
        "legalityClaimed": False,
    }


def _get_cell(store: dict, key: tuple, join: str, cpz, street, stratum: str,
              day_type: str, hour) -> dict:
    cell = store.get(key)
    if cell is None:
        cell = _new_cell(join, cpz, street, stratum, day_type, hour)
        store[key] = cell
    return cell


def build_cells(pcns: list[dict], capacity: dict[str, dict], date_index: dict,
                level: str) -> dict:
    """Build the sparse stratified grid plus the unknown-hour bucket.

    Every cell carries its own exposure, so a consumer never has to reconstruct
    the denominator - and never has an excuse for dividing by an event count
    instead of by capacity x dates.
    """
    cells: dict[tuple, dict] = {}
    unknown_hour: dict[tuple, dict] = {}

    # Universe of join keys: streets in the bay inventory plus streets appearing
    # in the PCN series. A street with PCNs but no inventory still matters (it
    # simply cannot support a per-bay rate); a street with inventory but no PCNs
    # is the interesting zero and is enumerated in joinKeysWithNoEvents.
    keys: set[str] = set(capacity.keys())
    unplaced = 0
    keys_with_events: set[str] = set()

    for e in pcns:
        key = join_key(e, level)
        if key is None:
            unplaced += 1
            continue
        keys.add(key)
        stratum = e.get("spatialStratum")
        t = e.get("temporal") or {}
        day_type = t.get("dayType")
        if stratum not in STRATA or day_type not in DAY_TYPES:
            continue
        hour = t.get("hour") if t.get("hourKnown") else None
        keys_with_events.add(key)
        store = cells if hour is not None else unknown_hour
        cpz, street = join_key_parts(key)
        cell = _get_cell(store, (key, stratum, day_type, hour),
                         key, cpz, street, stratum, day_type, hour)
        cell["pcnCount"] += 1
        d = t.get("date")
        if d and d not in cell["distinctDates"]:
            cell["distinctDates"].append(d)
        _bump(cell["contraventionClassCounts"], e.get("contraventionClass"))
        _bump(cell["ticketTypes"], e.get("ticketType"))
        _bump(cell["caseStatuses"], e.get("caseStatus"))
        _bump(cell["vehicleCategories"], e.get("vehicleCategory"))

    dates_by_daytype = date_index.get("datesByDayType") or {}
    for store in (cells, unknown_hour):
        for cell in store.values():
            cell["distinctDates"] = sorted(cell["distinctDates"])
            cell["dateCount"] = len(cell["distinctDates"])
            cap = capacity.get(cell["joinKey"])
            if cap and cap.get("spaceCount") is not None and cap["spaceCount"] > 0:
                cell["spaceCount"] = cap["spaceCount"]
                cell["capacitySuppliedByPublisher"] = True
                cell["capacityIsApproximate"] = bool(cap.get("capacityIsApproximate"))
                cell["capacityCoverageFraction"] = cap.get("capacityCoverageFraction")
            else:
                # None, never 0.0: unknown capacity is not zero capacity.
                cell["spaceCount"] = None
                cell["capacitySuppliedByPublisher"] = False
                cell["capacityIsApproximate"] = None
                cell["capacityCoverageFraction"] = (
                    cap.get("capacityCoverageFraction") if cap else None)
            exposure_dates = dates_by_daytype.get(cell["dayType"], 0)
            cell["exposureDates"] = exposure_dates
            cell["exposureBayDates"] = (
                cell["spaceCount"] * exposure_dates
                if cell["spaceCount"] is not None and exposure_dates else None)

    return {
        "cells": cells,
        "unknownHourCells": unknown_hour,
        "joinLevel": level,
        "joinKeyCount": len(keys),
        "joinKeyList": sorted(keys),
        "joinKeysWithNoEvents": sorted(keys - keys_with_events),
        "pcnEventsUnplaceable": unplaced,
        "dateIndex": date_index,
        "gridSemantics": ("Sparse: only cells containing >=1 PCN are present. An "
                          "absent (street, stratum, dayType, hour) combination "
                          "means ZERO events for that combination, and exposure "
                          "is analytic, so the zero is counted in every rate. "
                          "Enumerate joinKeyList x STRATA x DAY_TYPES x HOURS to "
                          "materialise the full grid."),
    }


def _bump(counter: dict, key) -> None:
    if key is None or (isinstance(key, str) and not key.strip()):
        key = "<missing>"
    counter[str(key)] = counter.get(str(key), 0) + 1


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

FORBIDDEN_CELL_KEYS = (
    "bayKey", "bayId", "markerId", "spaceId", "kerbsideId", "longitude",
    "latitude", "easting", "northing", "wkt", "geometry", "coordinates",
)


def assert_no_bay_level_join(cells: dict) -> None:
    """Fail loudly if any cell carries a bay-level identifier or a coordinate.

    This is a structural guarantee, not a convention. Camden's bay geometry is an
    arbitrary node on a polyline and individual spaces are not identifiable, so a
    bay-level join would fabricate precision the publisher explicitly disclaims.
    """
    for key, cell in cells.items():
        for field in cell:
            low = field.lower()
            for forbidden in FORBIDDEN_CELL_KEYS:
                if forbidden.lower() in low:
                    raise AssertionError(
                        f"cell {key} carries bay-level field {field!r}; the join "
                        "must be at street/CPZ level only")
        for part in key:
            if part is not None and isinstance(part, str) and "||" in part:
                cpz, street = join_key_parts(part)
                if street is not None and re.search(r"\b(bay|space|marker)\b", street):
                    raise AssertionError(
                        f"join key {part!r} appears to encode a bay-level "
                        "identifier; refusing to aggregate at that granularity")


# ---------------------------------------------------------------------------
# Explicit pooling - the only route to a combined stratum view
# ---------------------------------------------------------------------------

def pool_strata(cells: dict, strata_to_pool=STRATA) -> dict:
    """Sum cells across strata, stamping the result with what was pooled.

    Pooling is lossy and is never the default. The returned cells carry
    `pooledFrom` so that any report presenting a pooled number is forced to show
    which strata produced it and can therefore also show the effect of not
    pooling them.
    """
    out: dict[tuple, dict] = {}
    pooled_from: dict[tuple, dict[str, int]] = defaultdict(dict)
    for (key, stratum, day_type, hour), cell in cells.items():
        if stratum not in strata_to_pool:
            continue
        target = (key, "POOLED", day_type, hour)
        pooled_from[target][stratum] = pooled_from[target].get(stratum, 0) + cell["pcnCount"]
        if target not in out:
            new = dict(cell)
            new["spatialStratum"] = "POOLED"
            new["contraventionClassCounts"] = dict(cell["contraventionClassCounts"])
            new["ticketTypes"] = dict(cell["ticketTypes"])
            new["caseStatuses"] = dict(cell["caseStatuses"])
            new["vehicleCategories"] = dict(cell["vehicleCategories"])
            new["distinctDates"] = list(cell["distinctDates"])
            out[target] = new
            continue
        dst = out[target]
        dst["pcnCount"] += cell["pcnCount"]
        for field in ("contraventionClassCounts", "ticketTypes", "caseStatuses",
                      "vehicleCategories"):
            for k, v in cell[field].items():
                dst[field][k] = dst[field].get(k, 0) + v
        for d in cell["distinctDates"]:
            if d not in dst["distinctDates"]:
                dst["distinctDates"].append(d)

    for target, cell in out.items():
        cell["distinctDates"] = sorted(cell["distinctDates"])
        cell["dateCount"] = len(cell["distinctDates"])
        cell["pooledFrom"] = dict(sorted(pooled_from[target].items()))
    return out


def cell_sort_key(key: tuple) -> tuple:
    """Deterministic ordering for every emitted collection."""
    join, stratum, day_type, hour = key
    return (join or "", stratum or "", day_type or "",
            -1 if hour is None else hour)
