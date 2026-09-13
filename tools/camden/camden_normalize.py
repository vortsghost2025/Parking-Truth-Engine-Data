#!/usr/bin/env python3
"""Deterministic normalisation for Camden records (PTE-TEL-003 deliverable 2).

WHY THIS EXISTS
---------------
Raw Camden rows have to become comparable cells before anything can be counted.
Every choice made here is a choice about what the signal means, so they are all
written down and all reversible from the provenance carried by the adapter.

THE THREE RULES THIS MODULE ENFORCES
------------------------------------
1. NOTHING IS IMPUTED. If a PCN carries a date but no time, its hour is UNKNOWN
   and stays UNKNOWN. It is not set to midnight. Melbourne's own archives
   document midnight-imputed times as a *defect*; reproducing that defect here
   would poison every hourly shape diagnostic. Unknown-hour records are counted
   in daily and street aggregates and explicitly excluded from hourly ones.

2. STRATA ARE NEVER POOLED. Camden's `Spatial Accuracy` column separates
   Civil Enforcement Officer GPS Location from Fixed CCTV Camera from Unknown.
   A CCTV record locates a *camera*, which the publisher warns "could be many
   metres from the vehicle in contravention"; a CEO GPS record locates a
   *handheld at the vehicle*. Those are different measurements and they are
   carried as separate strata end to end. Pooling them is a decision that must
   be made by a report that shows the effect, not by a default.

3. UNMAPPED VALUES ARE SURFACED, NOT ABSORBED. Anything that is not one of the
   three recognised `Spatial Accuracy` values falls into UNKNOWN_OTHER *and* is
   recorded verbatim with its count. A new publisher category must not silently
   become "unknown".

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not compute occupancy, probability, confidence, or any bay-level
quantity. It does not touch legality. It produces normalised events and bays,
plus derived temporal features - nothing more.

STDLIB ONLY. Deterministic: same inputs -> same outputs.
"""

from __future__ import annotations

from datetime import date, datetime

# ---------------------------------------------------------------------------
# Spatial Accuracy strata
# ---------------------------------------------------------------------------

STRATUM_CEO_GPS = "CEO_GPS"
STRATUM_FIXED_CCTV = "FIXED_CCTV"
STRATUM_UNKNOWN_OTHER = "UNKNOWN_OTHER"

STRATA = (STRATUM_CEO_GPS, STRATUM_FIXED_CCTV, STRATUM_UNKNOWN_OTHER)

# Canonical publisher wording -> stratum. Matched after case-folding and
# collapsing whitespace/punctuation, so trailing spaces in an export do not
# change the stratum.
_SPATIAL_ACCURACY_MAP = {
    "civil enforcement officer gps location": STRATUM_CEO_GPS,
    "ceo gps location": STRATUM_CEO_GPS,
    "ceo gps": STRATUM_CEO_GPS,
    "gps location": STRATUM_CEO_GPS,
    "civil enforcement officer gps": STRATUM_CEO_GPS,
    "officer gps location": STRATUM_CEO_GPS,
    "fixed cctv camera": STRATUM_FIXED_CCTV,
    "fixed cctv": STRATUM_FIXED_CCTV,
    "cctv camera": STRATUM_FIXED_CCTV,
    "cctv": STRATUM_FIXED_CCTV,
}

# Values that mean "the publisher told us nothing", as opposed to values we do
# not recognise. Both land in UNKNOWN_OTHER but they are reported separately:
# an empty field is missingness, an unrecognised string is a schema drift.
_SPATIAL_ACCURACY_EXPLICIT_UNKNOWN = {
    "unknown", "not known", "na", "n a", "none", "not recorded", "unspecified",
}


def _fold(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        out.append(" " if not ch.isalnum() else ch)
    return " ".join("".join(out).split())


def map_spatial_accuracy(raw: str | None) -> tuple[str, str]:
    """Map a publisher `Spatial Accuracy` value to a stratum.

    Returns (stratum, disposition) where disposition is one of:
      MAPPED            recognised publisher wording
      EXPLICIT_UNKNOWN  publisher said it does not know
      EMPTY             field absent or blank
      UNRECOGNISED      a value this adapter has never seen - schema drift,
                        must be surfaced to a human, never absorbed silently
    """
    if raw is None:
        return STRATUM_UNKNOWN_OTHER, "EMPTY"
    folded = _fold(raw)
    if not folded:
        return STRATUM_UNKNOWN_OTHER, "EMPTY"
    hit = _SPATIAL_ACCURACY_MAP.get(folded)
    if hit is not None:
        return hit, "MAPPED"
    if folded in _SPATIAL_ACCURACY_EXPLICIT_UNKNOWN:
        return STRATUM_UNKNOWN_OTHER, "EXPLICIT_UNKNOWN"
    return STRATUM_UNKNOWN_OTHER, "UNRECOGNISED"


# ---------------------------------------------------------------------------
# Temporal features
# ---------------------------------------------------------------------------

WEEKDAY_NAMES = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
                 "SATURDAY", "SUNDAY")

DAYTYPE_WEEKDAY = "WEEKDAY"
DAYTYPE_SATURDAY = "SATURDAY"
DAYTYPE_SUNDAY = "SUNDAY"

# Meteorological seasons, Northern Hemisphere. Camden is in London; the harness
# records the convention rather than assuming the reader knows it.
_SEASONS = {12: "WINTER", 1: "WINTER", 2: "WINTER",
            3: "SPRING", 4: "SPRING", 5: "SPRING",
            6: "SUMMER", 7: "SUMMER", 8: "SUMMER",
            9: "AUTUMN", 10: "AUTUMN", 11: "AUTUMN"}

_TIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
)


def parse_issue_time(raw: str | None) -> dict:
    """Parse a PCN issue timestamp WITHOUT imputing anything.

    Returns a dict with:
      date            ISO date string, or None
      hour            0-23 int, or None when the source carries no time
      hourKnown       bool - the only gate on hourly analysis
      weekday         MONDAY..SUNDAY, or None
      dayType         WEEKDAY / SATURDAY / SUNDAY, or None
      month           1-12, or None
      season          meteorological N-hemisphere season, or None
      isWeekend       bool or None
      parseStatus     PARSED_DATETIME | PARSED_DATE_ONLY | UNPARSEABLE | EMPTY
      parsedFormat    the format that matched, for audit

    Note the deliberate asymmetry: PARSED_DATE_ONLY yields a usable date and
    weekday but hour=None. Those records remain valid for daily, street and
    weekday analysis and are excluded from hourly analysis. Nothing is invented.
    """
    out = {
        "date": None, "hour": None, "hourKnown": False, "weekday": None,
        "dayType": None, "month": None, "season": None, "isWeekend": None,
        "parseStatus": "EMPTY", "parsedFormat": None,
    }
    if raw is None or not str(raw).strip():
        return out

    text = str(raw).strip().replace("Z", "").replace("z", "")
    parsed = None
    matched_fmt = None
    for fmt in _TIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            matched_fmt = fmt
            break
        except ValueError:
            continue

    if parsed is None:
        out["parseStatus"] = "UNPARSEABLE"
        return out

    has_time = bool(
        (parsed.hour or parsed.minute or parsed.second or parsed.microsecond)
        or ("H" in (matched_fmt or ""))
    )
    out["date"] = parsed.date().isoformat()
    out["weekday"] = WEEKDAY_NAMES[parsed.weekday()]
    out["dayType"] = _day_type(parsed.weekday())
    out["month"] = parsed.month
    out["season"] = _SEASONS[parsed.month]
    out["isWeekend"] = parsed.weekday() >= 5
    out["parsedFormat"] = matched_fmt

    if has_time:
        out["hour"] = parsed.hour
        out["hourKnown"] = True
        out["parseStatus"] = "PARSED_DATETIME"
    else:
        out["parseStatus"] = "PARSED_DATE_ONLY"
    return out


def _day_type(weekday_index: int) -> str:
    if weekday_index == 5:
        return DAYTYPE_SATURDAY
    if weekday_index == 6:
        return DAYTYPE_SUNDAY
    return DAYTYPE_WEEKDAY


def date_from_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Contravention-code classification
# ---------------------------------------------------------------------------
# Used ONLY as a confound diagnostic, never as a verdict. The distinction is
# heuristic and is reported as such: overstay/non-payment contraventions track
# turnover pressure, while prohibition-type contraventions track where officers
# look. A street dominated by the latter is more plausibly an artefact of
# enforcement deployment than of parking demand.

TURNOVER_CODE_HINTS = (
    "overstay", "exceeded", "no payment", "not paid", "without payment",
    "expired", "pay and display", "payment", "maximum stay", "longer than",
    "ticket", "meter",
)
PROHIBITION_CODE_HINTS = (
    "restricted", "prohibited", "no waiting", "no stopping", "clearway",
    "loading", "yellow line", "double yellow", "single yellow", "junction",
    "crossing", "zig zag", "school", "bus lane", "pedestrian", "footway",
    "permit", "resident", "disabled", "blue badge", "bay", "suspended",
    "controlled parking zone", "cpz", "contraflow", "wrong side", "obstruct",
)


def classify_contravention(code: str | None, description: str | None) -> dict:
    """Classify a contravention as turnover-type or prohibition-type.

    Returns a class plus the reason, because this classification is a heuristic
    over free text and every downstream reader deserves to see how it was
    reached. AMBIGUOUS is a real outcome and is reported as such rather than
    being forced into one bucket.
    """
    text = " ".join(
        str(x).lower() for x in (code, description) if x is not None and str(x).strip()
    )
    if not text:
        return {"contraventionClass": "UNSPECIFIED", "classReason": "no code or description"}
    turnover = any(h in text for h in TURNOVER_CODE_HINTS)
    prohibition = any(h in text for h in PROHIBITION_CODE_HINTS)
    if turnover and not prohibition:
        return {"contraventionClass": "TURNOVER_TYPE",
                "classReason": "matched turnover/non-payment wording only"}
    if prohibition and not turnover:
        return {"contraventionClass": "PROHIBITION_TYPE",
                "classReason": "matched prohibition/restriction wording only"}
    if turnover and prohibition:
        return {"contraventionClass": "AMBIGUOUS",
                "classReason": "matched both turnover and prohibition wording"}
    return {"contraventionClass": "UNCLASSIFIED",
            "classReason": "matched no known wording"}


# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------

def normalize_pcn(record: dict, sequence: int) -> dict:
    """Normalise one adapter PCN record into a comparable event.

    The verbatim source row and the adapter provenance are passed through
    unchanged, so nothing is normalised away.
    """
    n = record["normalized"]
    temporal = parse_issue_time(n.get("issueDateTimeRaw"))
    stratum, disposition = map_spatial_accuracy(n.get("spatialAccuracyRaw"))
    contravention = classify_contravention(
        n.get("contraventionCode"), n.get("contraventionDescription"))

    return {
        "kind": "PCN_EVENT",
        "sequence": sequence,
        # The join key is street/CPZ only. There is deliberately NO bay key and
        # NO coordinate here: Camden's bay geometry is an arbitrary node on a
        # polyline and individual spaces are not identifiable, so a bay-level
        # join would be spurious precision.
        "cpz": n.get("cpz"),
        "street": n.get("street"),
        "spatialStratum": stratum,
        "spatialAccuracyDisposition": disposition,
        "spatialAccuracyRaw": n.get("spatialAccuracyRaw"),
        "ticketType": n.get("ticketType"),
        "contraventionCode": n.get("contraventionCode"),
        "contraventionDescription": n.get("contraventionDescription"),
        "parkingRestriction": n.get("parkingRestriction"),
        "vehicleCategory": n.get("vehicleCategory"),
        "caseStatus": n.get("caseStatus"),
        "pcnReference": n.get("pcnReference"),
        "temporal": temporal,
        "contraventionClass": contravention["contraventionClass"],
        "contraventionClassReason": contravention["classReason"],
        # Standing constraint on this whole lane.
        "legalityClaimed": False,
        "semantics": ("PCN proves a vehicle was present at a time. It does not "
                      "prove a vehicle may be present, and it is not an "
                      "occupancy measurement."),
        "sourceRecord": record.get("sourceRecord"),
        "sourceRowIndex": record.get("sourceRowIndex"),
    }


def normalize_bay(record: dict, sequence: int) -> dict:
    """Normalise one adapter bay record.

    Capacity is used ONLY where the publisher supplies it, and the
    approximate-ness flags survive into every aggregate built from it.
    """
    n = record["normalized"]
    return {
        "kind": "PARKING_BAY",
        "sequence": sequence,
        "cpz": n.get("cpz"),
        "street": n.get("roadName"),
        "restrictionType": n.get("restrictionType"),
        "timesOfOperation": n.get("timesOfOperation"),
        "maximumStay": n.get("maximumStay"),
        "tariff": n.get("tariff"),
        "spaceCount": n.get("spaceCount"),
        "bayLengthM": n.get("bayLengthM"),
        "spaceCountIsApproximate": bool(n.get("spaceCountIsApproximate")),
        "bayLengthIsApproximate": bool(n.get("bayLengthIsApproximate")),
        "capacitySuppliedByPublisher": bool(n.get("capacitySuppliedByPublisher")),
        "centroidIsArbitraryNode": bool(n.get("centroidIsArbitraryNode")),
        "individualSpacesIdentifiable": False,
        "geometrySummary": record.get("geometrySummary"),
        "legalityClaimed": False,
        "sourceRecord": record.get("sourceRecord"),
        "sourceRowIndex": record.get("sourceRowIndex"),
    }


def normalize_all(bays_payload: dict, pcn_payload: dict) -> dict:
    """Normalise both payloads, returning records plus a missingness ledger.

    Deterministic ordering: records keep source order via `sequence`, and every
    derived collection is sorted before it is emitted.
    """
    bays = [normalize_bay(r, i) for i, r in enumerate(bays_payload["records"])]
    pcns = [normalize_pcn(r, i) for i, r in enumerate(pcn_payload["records"])]

    unmatched_spatial: dict[str, int] = {}
    for e in pcns:
        if e["spatialAccuracyDisposition"] == "UNRECOGNISED":
            key = e["spatialAccuracyRaw"] or "<empty>"
            unmatched_spatial[key] = unmatched_spatial.get(key, 0) + 1

    missingness = {
        "pcnTotal": len(pcns),
        "bayTotal": len(bays),
        "pcnMissingStreet": sum(1 for e in pcns if not e["street"]),
        "pcnMissingCpz": sum(1 for e in pcns if not e["cpz"]),
        "pcnHourUnknown": sum(1 for e in pcns if not e["temporal"]["hourKnown"]),
        "pcnDateOnly": sum(1 for e in pcns
                           if e["temporal"]["parseStatus"] == "PARSED_DATE_ONLY"),
        "pcnUnparseableTime": sum(1 for e in pcns
                                  if e["temporal"]["parseStatus"] == "UNPARSEABLE"),
        "pcnEmptyTime": sum(1 for e in pcns
                            if e["temporal"]["parseStatus"] == "EMPTY"),
        "pcnMissingContraventionCode": sum(1 for e in pcns
                                           if not e["contraventionCode"]),
        "bayMissingStreet": sum(1 for b in bays if not b["street"]),
        "bayMissingCpz": sum(1 for b in bays if not b["cpz"]),
        "bayWithoutPublisherCapacity": sum(
            1 for b in bays if not b["capacitySuppliedByPublisher"]),
        "bayWithApproximateCapacity": sum(
            1 for b in bays if b["spaceCountIsApproximate"]),
        "unrecognisedSpatialAccuracyValues": dict(sorted(unmatched_spatial.items())),
        "spatialStrataCounts": {
            s: sum(1 for e in pcns if e["spatialStratum"] == s) for s in STRATA
        },
        # Hours are never imputed; this records exactly how much of the series
        # cannot support an hourly analysis.
        "hourImputationPerformed": False,
    }

    return {
        "bays": bays,
        "pcns": pcns,
        "missingness": missingness,
        "provenance": {
            "bay-map": bays_payload["provenance"],
            "pcn-series": pcn_payload["provenance"],
        },
    }
