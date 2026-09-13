#!/usr/bin/env python3
"""Camden open-data source adapters (PTE-TEL-003 deliverable 1).

WHY THIS EXISTS
---------------
Camden publishes two datasets that together make a parking-pressure test
possible with no procurement step at all:

  * Parking Bay Map  (t4s2-xa5a) - bay geometry, approximate space count,
    restriction type, times of operation, maximum stay, tariff, road name, CPZ
  * PCN series       (transactional penalty charge notices) - contravention
    code, ticket type, street, parking restriction, vehicle category, case
    status, and a `Spatial Accuracy` column separating CEO GPS locations from
    fixed CCTV camera locations from unknown

Both are OGL and API-enabled. This module reads them from LOCAL FILES only.
It performs no network access; that is deliberate, so the harness is testable
offline and so a download is a reproducible artefact rather than a side effect.

THE PROVENANCE RULE
-------------------
Adapters must ingest raw source fields WITHOUT silently normalising away
provenance. Concretely, every record returned by this module carries:

  sourceRecord        the verbatim source row, unmodified
  provenance          dataset id, publisher, licence, source URL, adapter
                      version, the field map actually used, and the source
                      fields that no normalised key consumed
  normalized          the normalised view

Nothing is dropped, renamed in place, or coerced without a record of it. If a
field cannot be resolved it is reported, never guessed.

FIELD NAMES ARE CANDIDATES, NOT FACTS
-------------------------------------
The exact column spellings in a live Camden export have NOT been verified
against a real download (see docs/CAMDEN-SIGNAL-HARNESS.md, limitations). Socrata
portals vary column casing and sometimes append `:latest` or expose both a human
name and a machine name. So resolution is candidate-driven, case-insensitive,
tolerant of Socrata suffixes - and the adapter REPORTS which candidate matched
and which source fields went unused. Use --field-map to pin a real download
without editing code.

An adapter that cannot find a REQUIRED field raises rather than substituting a
default. A silent wrong column is worse than a loud failure.

    python3 camden_sources.py --bays /tmp/camden/bays.csv --pcn /tmp/camden/pcn.csv
    python3 camden_sources.py --pcn p.csv --field-map pcn.json --report r.json

STDLIB ONLY. Deterministic: same inputs -> same outputs, byte for byte.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys

ADAPTER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Dataset provenance. These are the constants stamped onto every record.
# ---------------------------------------------------------------------------

DATASETS: dict[str, dict[str, str]] = {
    "bay-map": {
        "datasetId": "t4s2-xa5a",
        "title": "Camden Parking Bay Map",
        "publisher": "London Borough of Camden",
        "licence": "Open Government Licence (OGL)",
        "sourceUrl": "https://opendata.camden.gov.uk/d/t4s2-xa5a",
        # Recorded because it constrains every downstream join: a bay is a run
        # of spaces, individual spaces are NOT identifiable, and the coordinates
        # are derived from an arbitrary node along the polyline.
        "publisherNotes": (
            "A parking bay consists of a number of parking spaces; individual "
            "parking spaces cannot be identified. Longitude/Latitude and "
            "Easting/Northing are automatically calculated based on an ARBITRARY "
            "NODE along the polyline geometry. Approximate length and approximate "
            "number of spaces are supplied."
        ),
    },
    "pcn-series": {
        "datasetId": "camden-transactional-pcn",
        "title": "Camden transactional Penalty Charge Notice data",
        "publisher": "London Borough of Camden",
        "licence": "Open Government Licence (OGL)",
        "sourceUrl": "https://opendata.camden.gov.uk/",
        "publisherNotes": (
            "Transactional PCN data including PCNs issued by Civil Enforcement "
            "Officers on street and via CCTV. The 'Spatial Accuracy' column "
            "records whether the location is a Civil Enforcement Officer GPS "
            "Location, a Fixed CCTV Camera location (which could be many metres "
            "from the vehicle in contravention), or Unknown."
        ),
    },
}

# Candidate source column names, in preference order. Matching is
# case-insensitive after stripping Socrata suffixes and punctuation.
BAY_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "cpz": ("cpz", "controlled parking zone", "cpz code", "zone"),
    "roadName": ("road name", "roadname", "street", "street name", "road"),
    "restrictionType": (
        "restriction type", "restrictiontype", "restriction",
        "bay restriction", "type of restriction",
    ),
    "timesOfOperation": (
        "times of operation", "timesofoperation", "operational times",
        "hours of operation", "times",
    ),
    "maximumStay": ("maximum stay", "maximumstay", "max stay", "stay limit"),
    "tariff": ("tariff", "tariff type", "charge", "charge type"),
    "bayLengthM": (
        "length (m)", "length m", "length in metres", "length metres",
        "approximate length", "length", "bay length",
    ),
    "spaceCount": (
        "number of spaces", "no of spaces", "spaces", "space count",
        "approximate number of spaces", "capacity",
    ),
    "wkt": ("wkt", "the wkt", "geometry", "wkt geometry", "shape"),
}

PCN_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "pcnReference": (
        "pcn", "pcn number", "pcn reference", "penalty charge notice",
        "ticket number", "notice number", "id",
    ),
    "issueDateTime": (
        "date of contravention", "contravention date", "date issued",
        "issue date", "ticket date", "pcn date", "date",
        "date of contravention time", "contravention time",
    ),
    "contraventionCode": (
        "contravention code", "contraventioncode", "code", "offence code",
    ),
    "contraventionDescription": (
        "contravention description", "contravention", "description",
        "offence description", "reason",
    ),
    "ticketType": (
        "ticket type", "tickettype", "pcn type", "notice type", "type",
    ),
    "street": ("street", "street name", "location", "road name", "road", "location street"),
    "parkingRestriction": (
        "parking restriction", "restriction", "restriction type",
        "bay restriction",
    ),
    "vehicleCategory": (
        "vehicle category", "vehiclecategory", "vehicle type", "vehicle class",
    ),
    "caseStatus": ("case status", "status of case", "status", "case state"),
    "spatialAccuracy": (
        "spatial accuracy", "spatialaccuracy", "location accuracy",
        "spatial accuracy ", "accuracy",
    ),
    "cpz": ("cpz", "controlled parking zone", "zone", "cpz code"),
}

# Fields that MUST resolve. Missing -> raise. Everything else is optional.
BAY_REQUIRED = ("roadName",)
PCN_REQUIRED = ("issueDateTime", "contraventionCode")


# ---------------------------------------------------------------------------
# Low-level readers
# ---------------------------------------------------------------------------

def _clean_key(key: str) -> str:
    """Normalise a column name for candidate matching.

    Lowercases, strips Socrata's ':latest'/':@computed_...' suffixes, collapses
    whitespace and drops punctuation so that 'Length (m)', 'length_m' and
    'LENGTH M' all compare equal.
    """
    k = key.strip().lower()
    if ":" in k:                      # Socrata suffixes
        k = k.split(":", 1)[0]
    out: list[str] = []
    for ch in k:
        out.append(" " if not (ch.isalnum()) else ch)
    return " ".join("".join(out).split())


def read_rows(path: str) -> list[dict[str, str]]:
    """Read a local CSV or JSON export into a list of flat string-valued rows.

    Accepts: plain CSV, gzipped CSV, a bare JSON array, or the common Socrata
    wrappers ({"rows": [...]}, {"results": [...]}, {"data": [...]}). Values are
    stringified so that nothing is silently type-coerced before normalisation.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"source file not found: {path}")

    opener = open
    mode = "rt"
    if path.endswith(".gz"):
        import gzip
        opener = gzip.open
    else:
        import builtins
        opener = builtins.open

    with opener(path, mode, encoding="utf-8-sig", newline="") as fh:
        head = fh.read(4096)
        fh.seek(0)
        stripped = head.lstrip()
        if stripped.startswith(("[", "{")):
            payload = json.load(fh)
            rows = _unwrap_json(payload)
            return [_stringify(r) for r in rows]
        fh.seek(0)
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return []
        return [_stringify(dict(r)) for r in reader]


def _unwrap_json(payload) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "results", "data", "records", "features"):
            inner = payload.get(key)
            if isinstance(inner, list) and inner:
                # GeoJSON features: merge properties into the row.
                if key == "features":
                    merged = []
                    for feat in inner:
                        if not isinstance(feat, dict):
                            continue
                        row = dict(feat.get("properties") or {})
                        merged.append(row)
                    return merged
                return [r for r in inner if isinstance(r, dict)]
    raise ValueError("unrecognised JSON export shape; expected a list or a "
                     "rows/results/data/records/features wrapper")


def _stringify(row: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in row.items():
        if k is None:
            continue
        out[str(k)] = "" if v is None else str(v)
    return out


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------

def resolve_fields(
    source_keys: list[str],
    candidates: dict[str, tuple[str, ...]],
    overrides: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str], dict[str, list[str]]]:
    """Map normalised keys onto actual source column names.

    Returns (fieldMap, unresolvedOptional, ambiguous) where fieldMap maps
    normalisedKey -> sourceKey. Overrides win absolutely and are used verbatim,
    which is how a real download gets pinned without editing code.

    Ambiguity is reported rather than silently resolved: if two different source
    columns both match a normalised key, that is recorded so a human can decide.
    """
    overrides = overrides or {}
    cleaned = {_clean_key(k): k for k in source_keys}
    field_map: dict[str, str] = {}
    ambiguous: dict[str, list[str]] = {}

    for norm_key, cands in candidates.items():
        if norm_key in overrides:
            pinned = overrides[norm_key]
            if pinned not in source_keys:
                raise KeyError(
                    f"field-map override {norm_key}={pinned!r} is not present in "
                    f"the source columns: {sorted(source_keys)}"
                )
            field_map[norm_key] = pinned
            continue

        matched: list[str] = []
        for cand in cands:
            hit = cleaned.get(_clean_key(cand))
            if hit is not None and hit not in matched:
                matched.append(hit)
        if len(matched) == 1:
            field_map[norm_key] = matched[0]
        elif len(matched) > 1:
            # Deterministic: first candidate in preference order wins, but the
            # full set is surfaced so the choice is visible.
            field_map[norm_key] = matched[0]
            ambiguous[norm_key] = sorted(matched)

    used = set(field_map.values())
    unresolved_optional = sorted(
        k for k in candidates
        if k not in field_map and k not in overrides
    )
    return field_map, unresolved_optional, ambiguous


def _require(field_map: dict[str, str], required: tuple[str, ...], label: str,
             source_keys: list[str]) -> None:
    missing = [k for k in required if k not in field_map]
    if missing:
        raise KeyError(
            f"{label}: could not resolve required field(s) {missing}. "
            f"Source columns were {sorted(source_keys)}. "
            "Pass --field-map to pin them explicitly rather than editing this "
            "adapter; guessing a column is worse than failing loudly."
        )


def _extract(row: dict[str, str], field_map: dict[str, str], norm_key: str):
    src = field_map.get(norm_key)
    if src is None or src not in row:
        return None
    val = row[src]
    val = val.strip()
    return val if val else None


def _to_float(value) -> float | None:
    """Parse a publisher-supplied number without inventing one.

    Returns None when the publisher supplied nothing usable. Never returns 0.0
    for a missing value, because 0 spaces and unknown spaces mean very different
    things to a per-bay rate.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "").replace("£", "").strip()
    # Tolerate "12 (approx)" / "12 spaces" style annotations.
    digits = ""
    for ch in s:
        if ch.isdigit() or ch in ".-":
            digits += ch
        elif digits:
            break
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# WKT summary - deliberately shallow
# ---------------------------------------------------------------------------

def wkt_summary(wkt: str | None) -> dict:
    """Summarise geometry WITHOUT using it.

    The join in this harness is at street/CPZ level. Camden states its bay
    coordinates come from an ARBITRARY NODE on the polyline, so any geometry
    math here would be spurious precision. This function records only that
    geometry exists, its type and its vertex count - enough for a coverage
    report, not enough to locate anything.
    """
    if not wkt:
        return {"present": False, "geometryType": None, "vertexCount": 0}
    head = wkt.strip().split("(", 1)[0].strip().upper()
    vertex_count = wkt.count(",") + (1 if "(" in wkt else 0)
    return {"present": True, "geometryType": head or None,
            "vertexCount": int(vertex_count)}


# ---------------------------------------------------------------------------
# Public adapters
# ---------------------------------------------------------------------------

def _provenance(dataset_key: str, source_path: str, field_map: dict[str, str],
                source_keys: list[str], ambiguous: dict[str, list[str]],
                unresolved: list[str], source_format: str) -> dict:
    ds = DATASETS[dataset_key]
    unmatched = sorted(k for k in source_keys if k not in set(field_map.values()))
    return {
        "datasetId": ds["datasetId"],
        "datasetTitle": ds["title"],
        "publisher": ds["publisher"],
        "licence": ds["licence"],
        "sourceUrl": ds["sourceUrl"],
        "publisherNotes": ds["publisherNotes"],
        "adapterVersion": ADAPTER_VERSION,
        "sourcePath": os.path.abspath(source_path),
        "sourceFormat": source_format,
        "fieldMap": dict(sorted(field_map.items())),
        "ambiguousFieldMatches": ambiguous,
        "unresolvedOptionalFields": unresolved,
        "unconsumedSourceFields": unmatched,
        "legalityClaimed": False,
    }


def _format_of(path: str) -> str:
    low = path.lower()
    if low.endswith(".csv") or low.endswith(".csv.gz"):
        return "csv"
    if low.endswith(".json") or low.endswith(".geojson"):
        return "json"
    return "unknown"


def load_bay_map(path: str, field_overrides: dict[str, str] | None = None) -> dict:
    """Load the Parking Bay Map. Individual spaces are NOT identifiable here."""
    rows = read_rows(path)
    if not rows:
        raise ValueError(f"bay map produced no rows: {path}")
    source_keys = sorted({k for r in rows for k in r})
    field_map, unresolved, ambiguous = resolve_fields(
        source_keys, BAY_FIELD_CANDIDATES, field_overrides)
    _require(field_map, BAY_REQUIRED, "bay map", source_keys)

    records = []
    for idx, row in enumerate(rows):
        space_count = _to_float(_extract(row, field_map, "spaceCount"))
        bay_length = _to_float(_extract(row, field_map, "bayLengthM"))
        wkt = _extract(row, field_map, "wkt")
        records.append({
            "normalized": {
                "cpz": _extract(row, field_map, "cpz"),
                "roadName": _extract(row, field_map, "roadName"),
                "restrictionType": _extract(row, field_map, "restrictionType"),
                "timesOfOperation": _extract(row, field_map, "timesOfOperation"),
                "maximumStay": _extract(row, field_map, "maximumStay"),
                "tariff": _extract(row, field_map, "tariff"),
                "spaceCount": space_count,
                "bayLengthM": bay_length,
                # Camden describes both as approximate. Carried as flags, never
                # silently treated as exact.
                "spaceCountIsApproximate": space_count is not None,
                "bayLengthIsApproximate": bay_length is not None,
                "capacitySuppliedByPublisher": space_count is not None,
                # The geometry limitation, attached to every record so no
                # downstream consumer can lose sight of it.
                "centroidIsArbitraryNode": True,
                "individualSpacesIdentifiable": False,
            },
            "geometrySummary": wkt_summary(wkt),
            "sourceRowIndex": idx,
            "sourceRecord": dict(row),
        })

    return {
        "dataset": "bay-map",
        "recordCount": len(records),
        "provenance": _provenance("bay-map", path, field_map, source_keys,
                                  ambiguous, unresolved, _format_of(path)),
        "records": records,
    }


def load_pcn_series(path: str, field_overrides: dict[str, str] | None = None) -> dict:
    """Load the transactional PCN series.

    These are enforcement events. They are evidence that a vehicle was present;
    they are NOT evidence that a vehicle may be present, and nothing downstream
    may treat them as a legality signal.
    """
    rows = read_rows(path)
    if not rows:
        raise ValueError(f"PCN series produced no rows: {path}")
    source_keys = sorted({k for r in rows for k in r})
    field_map, unresolved, ambiguous = resolve_fields(
        source_keys, PCN_FIELD_CANDIDATES, field_overrides)
    _require(field_map, PCN_REQUIRED, "PCN series", source_keys)

    records = []
    for idx, row in enumerate(rows):
        records.append({
            "normalized": {
                "pcnReference": _extract(row, field_map, "pcnReference"),
                "issueDateTimeRaw": _extract(row, field_map, "issueDateTime"),
                "contraventionCode": _extract(row, field_map, "contraventionCode"),
                "contraventionDescription":
                    _extract(row, field_map, "contraventionDescription"),
                "ticketType": _extract(row, field_map, "ticketType"),
                "street": _extract(row, field_map, "street"),
                "parkingRestriction": _extract(row, field_map, "parkingRestriction"),
                "vehicleCategory": _extract(row, field_map, "vehicleCategory"),
                "caseStatus": _extract(row, field_map, "caseStatus"),
                "spatialAccuracyRaw": _extract(row, field_map, "spatialAccuracy"),
                "cpz": _extract(row, field_map, "cpz"),
            },
            "sourceRowIndex": idx,
            "sourceRecord": dict(row),
        })

    return {
        "dataset": "pcn-series",
        "recordCount": len(records),
        "provenance": _provenance("pcn-series", path, field_map, source_keys,
                                  ambiguous, unresolved, _format_of(path)),
        "records": records,
    }


def load_proxy(path: str) -> dict:
    """Load an OPTIONAL independent validation proxy.

    A proxy is a time/street-resolved measure of parking pressure that is NOT
    derived from the PCN series being tested - otherwise the test is circular.
    Expected columns (case-insensitive): street, cpz, date or datetime, value,
    and optionally units and source. The harness refuses to invent one: if no
    proxy is supplied the verdict is capped, because a signal that correlates
    only with itself proves nothing.
    """
    rows = read_rows(path)
    cleaned_rows = []
    for row in rows:
        c = {_clean_key(k): v for k, v in row.items()}
        street = c.get("street") or c.get("road name")
        value = _to_float(c.get("value") or c.get("proxy value"))
        when = c.get("date") or c.get("datetime") or c.get("timestamp")
        if street is None or value is None or when is None:
            continue
        cleaned_rows.append({
            "street": str(street).strip(),
            "cpz": (c.get("cpz") or "").strip() or None,
            "when": str(when).strip(),
            "value": value,
            "units": (c.get("units") or "").strip() or None,
            "source": (c.get("source") or "").strip() or None,
        })
    if not cleaned_rows:
        raise ValueError(f"proxy file produced no usable rows: {path}")
    return {
        "dataset": "independent-proxy",
        "recordCount": len(cleaned_rows),
        "provenance": {
            "sourcePath": os.path.abspath(path),
            "legalityClaimed": False,
            "independenceDeclaredByOperator": True,
            "warning": ("The harness CANNOT verify that this proxy is "
                        "independent of the PCN series. That is an operator "
                        "assertion. If it is derived from PCNs the test is "
                        "circular and the verdict is meaningless."),
        },
        "records": cleaned_rows,
    }


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# CLI - inspect a download and report what resolved
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Inspect Camden open-data exports and report field resolution.")
    ap.add_argument("--bays", help="Parking Bay Map export (CSV or JSON)")
    ap.add_argument("--pcn", help="PCN series export (CSV or JSON)")
    ap.add_argument("--proxy", help="optional independent validation proxy")
    ap.add_argument("--field-map", help="JSON pinning normalised->source columns")
    ap.add_argument("--report", help="write the resolution report here")
    args = ap.parse_args(argv)

    overrides: dict[str, dict[str, str]] = {"bay-map": {}, "pcn-series": {}}
    if args.field_map:
        with open(args.field_map, encoding="utf-8") as fh:
            raw = json.load(fh)
        for k, v in raw.items():
            if k in overrides and isinstance(v, dict):
                overrides[k] = {str(a): str(b) for a, b in v.items()}

    if not args.bays and not args.pcn:
        ap.error("supply at least one of --bays / --pcn")

    report: dict = {"adapterVersion": ADAPTER_VERSION, "datasets": {}}
    if args.bays:
        loaded = load_bay_map(args.bays, overrides["bay-map"])
        prov = loaded["provenance"]
        report["datasets"]["bay-map"] = {
            "sourceSha256": sha256_of(args.bays),
            "recordCount": loaded["recordCount"],
            "fieldMap": prov["fieldMap"],
            "ambiguousFieldMatches": prov["ambiguousFieldMatches"],
            "unresolvedOptionalFields": prov["unresolvedOptionalFields"],
            "unconsumedSourceFields": prov["unconsumedSourceFields"],
            "capacitySuppliedCount": sum(
                1 for r in loaded["records"]
                if r["normalized"]["capacitySuppliedByPublisher"]),
        }
    if args.pcn:
        loaded = load_pcn_series(args.pcn, overrides["pcn-series"])
        prov = loaded["provenance"]
        report["datasets"]["pcn-series"] = {
            "sourceSha256": sha256_of(args.pcn),
            "recordCount": loaded["recordCount"],
            "fieldMap": prov["fieldMap"],
            "ambiguousFieldMatches": prov["ambiguousFieldMatches"],
            "unresolvedOptionalFields": prov["unresolvedOptionalFields"],
            "unconsumedSourceFields": prov["unconsumedSourceFields"],
            "spatialAccuracyValuesObserved": sorted({
                (r["normalized"]["spatialAccuracyRaw"] or "<empty>")
                for r in loaded["records"]}),
        }
    if args.proxy:
        loaded = load_proxy(args.proxy)
        report["datasets"]["independent-proxy"] = {
            "sourceSha256": sha256_of(args.proxy),
            "recordCount": loaded["recordCount"],
        }

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"resolution report -> {args.report}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
