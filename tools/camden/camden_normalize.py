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

import hashlib
import json
import os
import re
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
# AMENDED BY PTE-TEL-004 C4A, BEFORE ANY CAMDEN ROW WAS READ.
#
# This section was originally a keyword heuristic over the code plus description
# text. The C4 audit (sources/camden/code-classification-audit.json) ran that
# heuristic against the authoritative London Councils descriptions and found it
# recognised only 9 of 18 declared turnover codes and 31 of 46 declared
# prohibition codes. The loss was asymmetric, and because the F1 share is
# PROHIBITION_TYPE over ALL classes, asymmetric attenuation biased
# prohibitionShareOverall UPWARD by +0.030 to +0.074 - enough to carry a true
# share of 0.45 to a reported 0.524 and cross the frozen F1 threshold of 0.50
# unaided. A false F1 trigger produces FAIL, whose pre-registered reading is
# "drop the PCN-exhaust source class as enforcement-biased". The defect could
# therefore manufacture the evidence for abandoning the approach.
#
# Classification is now a LOOKUP against the frozen authoritative artifact. The
# keyword heuristic is retained below, unchanged, and is reachable ONLY as an
# explicit fallback for codes genuinely absent from the artifact. Every fallback
# is counted and reported; it is never silent.
#
# Used ONLY as a confound diagnostic, never as a verdict. The distinction is
# reported as such: overstay/non-payment contraventions track turnover pressure,
# while prohibition-type contraventions track where officers look. A street
# dominated by the latter is more plausibly an artefact of enforcement deployment
# than of parking demand.
#
# WHAT IS *NOT* CHANGED BY C4A: no F1-F5 numerical threshold; no verdict logic;
# no join level; no strata handling. Suffix "j" (camera enforcement) is recorded
# in the artifact as future evidence and is deliberately NOT used to alter any
# verdict - expanding F1 to read it would be a separate amendment.

CLASS_TURNOVER = "TURNOVER_TYPE"
CLASS_PROHIBITION = "PROHIBITION_TYPE"
CLASS_AMBIGUOUS = "AMBIGUOUS"
CLASS_NOT_PARKING = "NOT_PARKING"
CLASS_RESERVED = "RESERVED"
CLASS_UNCLASSIFIED = "UNCLASSIFIED"
CLASS_UNSPECIFIED = "UNSPECIFIED"

# The declared taxonomy in the artifact is OURS; these are the harness labels it
# maps onto. NOT_PARKING and RESERVED are excluded by the already-declared C3
# policy at the input layer, so under a correctly filtered series they should
# never reach here. If any do, they are labelled and counted loudly rather than
# quietly folded into the denominator.
DECLARED_TO_CLASS = {
    "TURNOVER_PAYMENT": CLASS_TURNOVER,
    "PROHIBITION_ENTITLEMENT": CLASS_PROHIBITION,
    "MIXED": CLASS_AMBIGUOUS,
    "NOT_PARKING": CLASS_NOT_PARKING,
    "RESERVED": CLASS_RESERVED,
}
C3_EXCLUDED_CLASSES = frozenset({CLASS_NOT_PARKING, CLASS_RESERVED})

METHOD_TABLE = "AUTHORITATIVE_TABLE_LOOKUP"
METHOD_KEYWORDS = "KEYWORD_FALLBACK"
METHOD_NONE = "NO_CODE_MAP"

CODE_MAP_FILENAME = "london-councils-contravention-codes-v7.0.json"
CODE_MAP_ENV = "PTE_CAMDEN_CODE_MAP"

# Retained VERBATIM from PTE-TEL-003 (commit a602244). Fallback only.
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

# Codes are 1-2 digits; every suffix in the source legend is a SINGLE character
# (a-z, 0-9). Bounding the suffix to one character stops a value like "1234"
# from being silently truncated into a real base code.
_CODE_RE = re.compile(r"^\s*(\d{1,2})([A-Za-z0-9]?)\s*$")


def split_contravention_code(raw: str | None) -> dict:
    """Split `12R` into base `12` and suffix `R`, preserving the raw value.

    Camden emits alphanumeric codes with an upper-case suffix while the source
    lists suffixes in lower case, so suffix comparison is case-insensitive. The
    raw value is never overwritten: normalising away provenance is forbidden on
    this lane.
    """
    out = {"raw": raw, "baseCode": None, "suffix": None, "parseStatus": "EMPTY",
           "suffixValidForBaseCode": None}
    if raw is None or not str(raw).strip():
        return out
    text = str(raw).strip()
    m = _CODE_RE.match(text)
    if not m:
        out["parseStatus"] = "UNPARSEABLE"
        return out
    out["baseCode"] = m.group(1).zfill(2)
    out["suffix"] = m.group(2).upper() or None
    out["parseStatus"] = "PARSED"
    return out


def suffix_valid_for_base_code(base_code: str | None, suffix: str | None,
                               code_map: dict | None) -> bool | None:
    """Is `suffix` one the source permits on `base_code`?

    None when it cannot be determined (no suffix, or no code map). A suffix the
    source does not list for that base code is a DATA-QUALITY signal about the
    publisher's own coding, not a reason to change the class: the base code is
    what the declaration is made against. It is surfaced so that a value like
    "999" - which parses structurally as base 99 with suffix 9, a suffix code 99
    does not permit - is visible instead of being quietly absorbed as a real
    pedestrian-crossing contravention.
    """
    if not suffix or code_map is None or not base_code:
        return None
    entry = code_map["codes"].get(base_code)
    if entry is None:
        return None
    permitted = set((entry.get("generalSuffixes") or "").lower())
    permitted |= set((code_map.get("codeSpecificSuffixes") or {})
                     .get(base_code, {}).keys())
    if not permitted:
        return None
    return suffix.lower() in permitted


def classify_contravention_keywords(code: str | None, description: str | None) -> dict:
    """The PTE-TEL-003 keyword heuristic, retained VERBATIM as fallback only.

    Kept byte-for-byte in behaviour so the C4 audit remains reproducible against
    it, and so the fallback is auditable rather than a rewrite nobody measured.
    Its defects are documented above; it is no longer the primary path.
    """
    text = " ".join(
        str(x).lower() for x in (code, description) if x is not None and str(x).strip()
    )
    if not text:
        return {"contraventionClass": CLASS_UNSPECIFIED, "classReason": "no code or description",
                "classificationMethod": METHOD_KEYWORDS}
    turnover = any(h in text for h in TURNOVER_CODE_HINTS)
    prohibition = any(h in text for h in PROHIBITION_CODE_HINTS)
    if turnover and not prohibition:
        return {"contraventionClass": CLASS_TURNOVER,
                "classReason": "matched turnover/non-payment wording only",
                "classificationMethod": METHOD_KEYWORDS}
    if prohibition and not turnover:
        return {"contraventionClass": CLASS_PROHIBITION,
                "classReason": "matched prohibition/restriction wording only",
                "classificationMethod": METHOD_KEYWORDS}
    if turnover and prohibition:
        return {"contraventionClass": CLASS_AMBIGUOUS,
                "classReason": "matched both turnover and prohibition wording",
                "classificationMethod": METHOD_KEYWORDS}
    return {"contraventionClass": CLASS_UNCLASSIFIED,
            "classReason": "matched no known wording",
            "classificationMethod": METHOD_KEYWORDS}


def default_code_map_path() -> str:
    """Repo-relative location of the frozen authoritative artifact."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "sources", "camden",
                                         CODE_MAP_FILENAME))


def resolve_code_map_path(path: str | None = None) -> str | None:
    """Explicit argument, then PTE_CAMDEN_CODE_MAP, then the repo default.

    An EXPLICIT path that does not exist is an error, not a reason to fall through
    to the default. Falling through would let a typo'd --code-map silently load a
    different artifact from the one the operator asked for - which is the same
    class of silent substitution this whole amendment exists to remove. Fall-through
    happens only when no explicit path was supplied.
    """
    if path:
        return os.path.abspath(path) if os.path.isfile(path) else None
    for cand in (os.environ.get(CODE_MAP_ENV), default_code_map_path()):
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_code_map(path: str | None = None, required: bool = True) -> dict | None:
    """Load and validate the frozen authoritative contravention-code artifact.

    Raises rather than returning None when the artifact is missing and `required`
    is set, because silently degrading to the keyword heuristic is exactly the
    failure mode C4A exists to remove. An operator who genuinely wants the
    keyword-only path must ask for it explicitly via required=False.
    """
    resolved = resolve_code_map_path(path)
    if resolved is None:
        if required:
            asked = (f"the explicit path {path!r}, which does not exist. An "
                     "explicit path never falls through to the default, because a "
                     "typo'd --code-map must not silently load a different "
                     "artifact." if path else
                     f"no explicit path; looked for ${CODE_MAP_ENV} and "
                     f"{default_code_map_path()}.")
            raise FileNotFoundError(
                "PTE-TEL-004 C4A requires the authoritative contravention-code "
                f"artifact and could not resolve one: {asked} Pass --code-map "
                "PATH. Refusing to fall back to the keyword heuristic silently, "
                "because that path is known to bias prohibitionShareOverall "
                "upward by up to +0.074.")
        return None
    with open(resolved, encoding="utf-8") as fh:
        art = json.load(fh)
    codes = art.get("codes")
    if not isinstance(codes, dict) or not codes:
        raise ValueError(f"{resolved}: artifact has no 'codes' object")
    unknown = sorted({e.get("declaredPressureClass") for e in codes.values()}
                     - set(DECLARED_TO_CLASS))
    if unknown:
        raise ValueError(f"{resolved}: undeclared pressure class(es) {unknown}; "
                         "extend DECLARED_TO_CLASS before the run, not after a result")
    return {
        "path": resolved,
        "sha256": _sha256_file(resolved),
        "artifactVersion": art.get("artifactVersion"),
        "codeListVersion": (art.get("source") or {}).get("codeListVersion"),
        "sourcePublisher": (art.get("source") or {}).get("publisher"),
        "codes": codes,
        "declaredClasses": art.get("declaredClasses"),
        "codeSpecificSuffixes": art.get("codeSpecificSuffixes") or {},
        "suffixLegend": art.get("suffixLegend") or {},
        "cameraEnforcementSuffix": art.get("cameraEnforcementSuffix"),
        # Recorded for provenance and future amendment only. NOT read by any
        # classification or verdict path.
        "cameraSuffixUsedInVerdict": False,
    }


def classify_contravention(code: str | None, description: str | None,
                           code_map: dict | None = None) -> dict:
    """Classify a contravention by AUTHORITATIVE base-code lookup.

    Primary path: parse the base code, look it up in the frozen London Councils
    artifact, and return the harness label our pre-declared class maps onto. The
    declaration was frozen before any Camden row was read, so this cannot be
    post-hoc tuning.

    Fallback path: a code genuinely absent from the artifact falls through to the
    unchanged keyword heuristic, with classificationMethod = KEYWORD_FALLBACK so
    the count can be reported. Nothing is guessed silently.
    """
    parsed = split_contravention_code(code)
    out = {
        "baseCode": parsed["baseCode"],
        "codeSuffix": parsed["suffix"],
        "codeParseStatus": parsed["parseStatus"],
        "declaredPressureClass": None,
        "cameraEnforcementSuffixPresent": None,
        "excludedByC3Policy": False,
        "suffixValidForBaseCode": None,
    }
    if code_map is None:
        kw = classify_contravention_keywords(code, description)
        out.update(kw)
        out["classificationMethod"] = METHOD_NONE
        out["classReason"] = ("no authoritative code map supplied; keyword "
                              "heuristic used (" + kw["classReason"] + ")")
        return out

    entry = code_map["codes"].get(parsed["baseCode"] or "")
    if entry is None:
        kw = classify_contravention_keywords(code, description)
        out.update(kw)
        out["classificationMethod"] = METHOD_KEYWORDS
        out["classReason"] = (f"base code {parsed['baseCode'] or '<unparseable>'} "
                              "absent from the authoritative artifact; keyword "
                              "fallback used (" + kw["classReason"] + ")")
        return out

    declared = entry["declaredPressureClass"]
    cls = DECLARED_TO_CLASS[declared]
    suffix = (parsed["suffix"] or "").lower()
    cam_suffix = (code_map.get("cameraEnforcementSuffix") or "j")
    out["suffixValidForBaseCode"] = suffix_valid_for_base_code(
        parsed["baseCode"], parsed["suffix"], code_map)
    out.update({
        "contraventionClass": cls,
        "classificationMethod": METHOD_TABLE,
        "declaredPressureClass": declared,
        "excludedByC3Policy": cls in C3_EXCLUDED_CLASSES,
        "cameraEnforcementSuffixPresent": bool(suffix and cam_suffix in suffix),
        "officialDescription": entry.get("officialDescription"),
        "classReason": (f"authoritative lookup: base code {parsed['baseCode']} "
                        f"declared {declared} -> {cls} "
                        f"({code_map.get('codeListVersion') or 'code map'})"),
    })
    return out


# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------

def normalize_pcn(record: dict, sequence: int, code_map: dict | None = None) -> dict:
    """Normalise one adapter PCN record into a comparable event.

    The verbatim source row and the adapter provenance are passed through
    unchanged, so nothing is normalised away.
    """
    n = record["normalized"]
    temporal = parse_issue_time(n.get("issueDateTimeRaw"))
    stratum, disposition = map_spatial_accuracy(n.get("spatialAccuracyRaw"))
    contravention = classify_contravention(
        n.get("contraventionCode"), n.get("contraventionDescription"),
        code_map=code_map)

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
        # C4A provenance: how this class was reached must be visible per row, so
        # the keyword fallback can never hide inside an aggregate.
        "classificationMethod": contravention["classificationMethod"],
        "contraventionBaseCode": contravention["baseCode"],
        "contraventionCodeSuffix": contravention["codeSuffix"],
        "suffixValidForBaseCode": contravention["suffixValidForBaseCode"],
        "declaredPressureClass": contravention["declaredPressureClass"],
        "excludedByC3Policy": contravention["excludedByC3Policy"],
        "cameraEnforcementSuffixPresent": contravention["cameraEnforcementSuffixPresent"],
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


def normalize_all(bays_payload: dict, pcn_payload: dict,
                  code_map: dict | None = None,
                  code_map_path: str | None = None) -> dict:
    """Normalise both payloads, returning records plus a missingness ledger.

    Deterministic ordering: records keep source order via `sequence`, and every
    derived collection is sorted before it is emitted.

    C4A: the authoritative code map is loaded here unless one is passed in, and
    loading is REQUIRED by default. Silently degrading to the keyword heuristic
    is the failure mode C4A exists to remove, so an absent artifact raises
    instead of proceeding.
    """
    if code_map is None:
        code_map = load_code_map(code_map_path, required=True)
    bays = [normalize_bay(r, i) for i, r in enumerate(bays_payload["records"])]
    pcns = [normalize_pcn(r, i, code_map=code_map)
            for i, r in enumerate(pcn_payload["records"])]

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

    method_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    declared_counts: dict[str, int] = {}
    fallback_codes: dict[str, int] = {}
    invalid_suffix_codes: dict[str, int] = {}
    for e in pcns:
        method_counts[e["classificationMethod"]] = \
            method_counts.get(e["classificationMethod"], 0) + 1
        class_counts[e["contraventionClass"]] = \
            class_counts.get(e["contraventionClass"], 0) + 1
        if e["declaredPressureClass"]:
            declared_counts[e["declaredPressureClass"]] = \
                declared_counts.get(e["declaredPressureClass"], 0) + 1
        if e["classificationMethod"] != METHOD_TABLE:
            key = str(e["contraventionCode"] or "<empty>")
            fallback_codes[key] = fallback_codes.get(key, 0) + 1
        if e["suffixValidForBaseCode"] is False:
            key = str(e["contraventionCode"] or "<empty>")
            invalid_suffix_codes[key] = invalid_suffix_codes.get(key, 0) + 1

    fallback_rows = sum(n for m, n in method_counts.items() if m != METHOD_TABLE)
    total = len(pcns)
    classification = {
        # C4A: classification is now a lookup against a frozen authoritative
        # codebook, and the keyword heuristic is a counted fallback rather than
        # the primary path.
        "amendedBy": "PTE-TEL-004-C4A",
        "primaryMethod": METHOD_TABLE,
        "methodCounts": dict(sorted(method_counts.items())),
        "classCounts": dict(sorted(class_counts.items())),
        "declaredPressureClassCounts": dict(sorted(declared_counts.items())),
        "fallbackRows": fallback_rows,
        "fallbackShare": round(fallback_rows / total, 6) if total else None,
        "fallbackCodes": dict(sorted(fallback_codes.items(),
                                     key=lambda kv: (-kv[1], kv[0]))),
        "invalidSuffixRows": sum(invalid_suffix_codes.values()),
        "invalidSuffixCodes": dict(sorted(invalid_suffix_codes.items(),
                                          key=lambda kv: (-kv[1], kv[0]))),
        "invalidSuffixNote": (
            "Rows whose suffix is not one the source permits on that base code. "
            "The class is still taken from the base code, because that is what the "
            "declaration is made against; the mismatch is surfaced as a publisher "
            "data-quality signal rather than used to reclassify."),
        "keywordClassifierRole": "FALLBACK_ONLY",
        "codeMapPath": code_map["path"],
        "codeMapSha256": code_map["sha256"],
        "codeMapArtifactVersion": code_map["artifactVersion"],
        "codeMapCodeListVersion": code_map["codeListVersion"],
        "codeMapSourcePublisher": code_map["sourcePublisher"],
        # Recorded as future evidence. Deliberately not used to alter any verdict:
        # expanding F1 to read deployment from suffix 'j' would be a separate
        # pre-registered amendment.
        "cameraEnforcementSuffixRows": sum(
            1 for e in pcns if e["cameraEnforcementSuffixPresent"]),
        "cameraEnforcementSuffixUsedInVerdict": False,
        "c3PolicyRowsStillPresent": sum(
            1 for e in pcns if e["excludedByC3Policy"]),
        "c3PolicyNote": (
            "NOT_PARKING and RESERVED codes are meant to be removed by the C3 "
            "filter at the input layer. A non-zero count here means non-parking "
            "rows reached the harness and are sitting in the F1 denominator; the "
            "count is surfaced rather than absorbed."),
    }

    return {
        "bays": bays,
        "pcns": pcns,
        "missingness": missingness,
        "classification": classification,
        "provenance": {
            "bay-map": bays_payload["provenance"],
            "pcn-series": pcn_payload["provenance"],
        },
    }
