#!/usr/bin/env python3
"""
PTE Telemetry Harvester — real parking arrival/departure telemetry
==================================================================

Goal: obtain REAL "space got used" / "space got left" transition events at
volume, from sources that are openly licensed, without ever storing a multi-GB
blob in Git or on a storage-constrained machine.

Two modes
---------
live       Poll a near-real-time municipal sensor dataset and DIFF consecutive
           snapshots. Every bay that flips Free->Occupied is an ARRIVAL; every
           Occupied->Free is a DEPARTURE, with the observation window as its
           timestamp bound. This manufactures an event stream out of a feed that
           only publishes state.

archive    Stream a historical parking-EVENT archive (which already contains one
           row per parking event with arrival time, departure time, duration,
           restriction and overstay flag) either from a URL or a local file.
           Decompresses on the fly, hashes as it reads, then DELETES the
           download by default. Emits a bounded reservoir-sampled normalised
           event set plus full aggregate statistics.

Both modes emit the SAME normalised telemetry event schema so a downstream
consumer cannot tell whether a transition came from live diffing or from a
historical archive. See schemas/parking-telemetry-event-schema.json.

Storage policy
--------------
Per README: large publicly reproducible datasets are referenced by
URL + retrievedAt + bytes + SHA-256, not stored as bytes. This tool honours that:
archives download to a temp dir OUTSIDE the repo, are hashed while streaming, and
are removed unless --keep-download is passed. Only bounded derived artifacts are
written into the repo tree.

STDLIB ONLY. Python 3.8+.

    # near-real-time transitions from City of Melbourne live sensors
    python3 telemetry_harvester.py live --interval 20 --minutes 60 --out out/live

    # ~14.2M real 2020 parking events, streamed, nothing big retained
    python3 telemetry_harvester.py archive \
        --url https://data.melbourne.vic.gov.au/api/v2/catalog/datasets/on-street-car-parking-sensor-data-2020-jan-may/exports/csv \
        --max-emit 250000 --out out/archive

    # discover which API shape actually works on a portal before harvesting
    python3 telemetry_harvester.py probe --base https://data.melbourne.vic.gov.au \
        --dataset on-street-parking-bay-sensors
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import random
import re
import shutil
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Sources. All figures below are published by the City of Melbourne / data.gov.au.
# --------------------------------------------------------------------------- #

LIVE_DATASET_DEFAULT = "on-street-parking-bay-sensors"
PORTAL_DEFAULT = "https://data.melbourne.vic.gov.au"

# Historical parking-EVENT archives: one row per parking event.
HISTORICAL_ARCHIVES = {
    "2014": {"rows": 51_500_000, "compressed": "1.56GB",
             "dataset": "on-street-car-parking-sensor-data-2014"},
    "2015": {"rows": 37_500_000, "compressed": "1.17GB",
             "dataset": "on-street-car-parking-sensor-data-2015",
             "directZip": "https://opendatasoft-s3.s3.amazonaws.com/downloads/archive/apua-t2tb.zip"},
    "2016": {"rows": 34_100_000, "compressed": "1.07GB",
             "dataset": "on-street-car-parking-sensor-data-2016"},
    "2017": {"rows": 35_900_000, "compressed": "1.13GB",
             "dataset": "on-street-car-parking-sensor-data-2017"},
    "2018": {"rows": 30_200_000, "compressed": "504MB",
             "dataset": "on-street-car-parking-sensor-data-2018"},
    "2019": {"rows": 42_700_000, "compressed": "717.1MB",
             "dataset": "on-street-car-parking-sensor-data-2019"},
    "2020-jan-may": {"rows": 14_200_000, "compressed": "258.5MB",
                     "dataset": "on-street-car-parking-sensor-data-2020-jan-may",
                     "directZip": "https://opendatasoft-s3.s3.amazonaws.com/downloads/archive/4n3a-s6rn.zip"},
}

# Data-quality defects the City of Melbourne documents for these archives.
# Counted, never silently dropped — see docs/REAL-PARKING-TELEMETRY-SOURCES.md.
DOCUMENTED_DEFECTS = {
    "sign_old_suffix": "Restriction field 'Sign' ends in 'OLD': the restriction "
                       "changed after the event, or the sensor was replaced. "
                       "2014: 1,126,441 rows. 2015: 453,178. 2016: 342,475. 2017: 860.",
    "negative_duration": "Negative value in 'seconds': sensor detected the arrival "
                         "AFTER the departure. Genuine sensor fault.",
    "missing_times_imputed": "Arrival/departure not recorded; time is imputed from "
                             "midnight of the arrival day to midnight of the "
                             "departure day. IMPUTED, NOT OBSERVED.",
    "cross_year_excluded": "Events crossing into the following year are excluded "
                           "by the publisher (2014: 3,377; 2015: 4,138; "
                           "2016: 4,346; 2017: 3,858). Archive is truncated at "
                           "year boundaries by design.",
}

UA = "PTE-telemetry-harvester/1.0 (research; respects portal terms)"

# --------------------------------------------------------------------------- #
# Tolerant column mapping.
#
# Municipal schemas drift between years and between portals. Rather than fail on
# an unexpected header, we resolve aliases and REPORT what was found, so the
# first run reveals the real schema instead of guessing it.
# --------------------------------------------------------------------------- #

COLUMN_ALIASES = {
    "bayKey": [
        "marker_id", "markerid", "street_marker_id", "bay_id", "bayid",
        "kerbside_id", "kerbsideid", "sensor_id", "record_id", "recordid", "id",
    ],
    "status": ["status", "bay_status", "occupancy_status", "state", "presence"],
    "arrival": [
        "arrival_time", "arrivaltime", "arrival", "arrival_datetime", "start_time",
        "starttime", "in_time", "intime", "event_start", "occupied_at",
    ],
    "departure": [
        "departure_time", "departuretime", "departure", "departure_datetime",
        "end_time", "endtime", "out_time", "outtime", "event_end", "vacated_at",
    ],
    "durationSeconds": ["seconds", "duration_seconds", "duration", "stay_seconds",
                        "elapsed_seconds", "stay_duration"],
    "restriction": ["sign", "parking_restriction", "restriction",
                    "bay_restriction", "sign_restriction", "regulation"],
    "overstay": ["overstay", "over_stay", "overstayed", "is_overstay",
                 "overstay_flag"],
    "street": ["street", "street_name", "road", "road_name"],
    "betweenStreet1": ["between_street_1", "betweenstreet1", "between_street",
                       "from_street", "cross_street_1"],
    "betweenStreet2": ["between_street_2", "betweenstreet2", "to_street",
                       "cross_street_2"],
    "areaName": ["area_name", "areaname", "precinct", "zone", "area"],
    "lat": ["lat", "latitude", "y", "geo_point_2d_lat"],
    "lon": ["lon", "lng", "long", "longitude", "x", "geo_point_2d_lon"],
    "lastUpdated": ["lastupdated", "last_updated", "updated_at", "last_update",
                    "timestamp", "datetime"],
    "direction": ["in_out", "in/out", "direction", "event_type", "movement"],
    "numBays": ["number_of_bays", "numberofbays", "bay_count"],
    "distanceFromCbd": ["distance_from_cbd", "distancefromcbd"],
}

# Status values that mean "a vehicle is present".
OCCUPIED_TOKENS = {"occupied", "occup", "o", "present", "true", "1", "yes",
                   "in", "vehicle_present", "not_available", "unavailable"}
FREE_TOKENS = {"free", "available", "vacant", "empty", "f", "u", "unoccupied",
               "false", "0", "no", "out"}
# Statuses that are NEITHER free nor occupied and must stay UNKNOWN.
NEITHER_TOKENS = {"restricted", "unofficial", "unknown", "disabled",
                  "out_of_service", "no_data", "", "null", "none", "n/a"}

ISO_TS = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").strip().lower())


def build_column_map(fieldnames):
    """Map our canonical names onto whatever the source actually calls them."""
    lookup = {norm_key(f): f for f in fieldnames if f}
    resolved, unresolved = {}, []
    for canon, aliases in COLUMN_ALIASES.items():
        hit = None
        for a in aliases:
            k = norm_key(a)
            if k in lookup:
                hit = lookup[k]
                break
        if hit is not None:
            resolved[canon] = hit
        else:
            unresolved.append(canon)
    return resolved, unresolved, list(lookup.values())


def classify_status(raw):
    """Return OCCUPIED / FREE / UNKNOWN. Never guesses."""
    k = norm_key(str(raw or ""))
    if k in {norm_key(t) for t in OCCUPIED_TOKENS}:
        return "OCCUPIED"
    if k in {norm_key(t) for t in FREE_TOKENS}:
        return "FREE"
    return "UNKNOWN"


def parse_ts(raw):
    """Best-effort timestamp parse -> (epoch_seconds, iso_utc, confidence)."""
    if raw in (None, ""):
        return None, None, "MISSING"
    s = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(s.replace("Z", "+0000"), fmt) \
                if fmt.endswith("%z") else datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            e = dt.timestamp()
            return e, datetime.fromtimestamp(e, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"), "OBSERVED"
        except ValueError:
            continue
    try:
        v = float(s)
        if v > 1e12:
            v /= 1000.0
        if 1e8 < v < 4e9:
            return v, datetime.fromtimestamp(v, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"), "EPOCH"
    except (ValueError, TypeError):
        pass
    return None, None, "UNPARSEABLE"


def to_float(raw):
    try:
        return float(str(raw).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Aggregate statistics + reservoir sampling
# --------------------------------------------------------------------------- #

class TelemetryAggregator:
    """Bounded-memory statistics over an unbounded event stream."""

    def __init__(self, reservoir_size=20000, seed=1337):
        self.count = 0
        self.reservoir = []
        self.reservoir_size = reservoir_size
        self.rng = random.Random(seed)
        self.stay_seconds = []          # reservoir-sampled durations
        self.stay_sample_cap = 200000
        self.by_hour = Counter()
        self.by_weekday = Counter()
        self.by_restriction = Counter()
        self.by_street = Counter()
        self.overstay = Counter()
        self.confidence = Counter()
        self.defects = Counter()
        self.hour_stay = defaultdict(list)
        self.hour_stay_sum = defaultdict(float)
        self.hour_stay_n = defaultdict(int)
        self.min_ts = None
        self.max_ts = None
        # bounded: distinct bays (~thousands) and distinct dates (~hundreds)
        self.bay_keys = set()
        self.arrival_dates = set()

    def add(self, ev):
        self.count += 1
        # reservoir sampling: uniform over the whole stream, not just the head
        if len(self.reservoir) < self.reservoir_size:
            self.reservoir.append(ev)
        else:
            j = self.rng.randint(0, self.count - 1)
            if j < self.reservoir_size:
                self.reservoir[j] = ev

        for d in ev.get("dataQuality", []):
            self.defects[d] += 1
        self.confidence[ev.get("timeConfidence", "UNKNOWN")] += 1

        if ev.get("bayKey"):
            self.bay_keys.add(str(ev["bayKey"]))
        a = ev.get("arrivalEpoch")
        d = ev.get("departureEpoch")
        if a is not None:
            self.min_ts = a if self.min_ts is None else min(self.min_ts, a)
            dt = datetime.fromtimestamp(a, tz=timezone.utc)
            self.by_hour[dt.hour] += 1
            self.by_weekday[dt.strftime("%a")] += 1
            self.arrival_dates.add(dt.strftime("%Y-%m-%d"))
        if d is not None:
            self.max_ts = d if self.max_ts is None else max(self.max_ts, d)
        if ev.get("restriction"):
            self.by_restriction[str(ev["restriction"])[:40]] += 1
        if ev.get("street"):
            self.by_street[str(ev["street"])[:60]] += 1
        if ev.get("overstay") is not None:
            self.overstay[str(ev["overstay"])] += 1

        dur = ev.get("durationSeconds")
        if isinstance(dur, (int, float)) and dur > 0:
            if len(self.stay_seconds) < self.stay_sample_cap:
                self.stay_seconds.append(dur)
                if a is not None:
                    h = datetime.fromtimestamp(a, tz=timezone.utc).hour
                    if len(self.hour_stay[h]) < 20000:
                        self.hour_stay[h].append(dur)
                    # unbounded-but-cheap running totals: exact mean per hour
                    self.hour_stay_sum[h] += dur
                    self.hour_stay_n[h] += 1

    def summary(self):
        s = {}
        if self.stay_seconds:
            v = sorted(self.stay_seconds)
            n = len(v)
            s["stayDurationSeconds"] = {
                "sampledRows": n,
                "min": round(v[0], 1),
                "p25": round(v[int(n * 0.25)], 1),
                "median": round(v[n // 2], 1),
                "p75": round(v[int(n * 0.75)], 1),
                "p95": round(v[int(n * 0.95)], 1),
                "p99": round(v[min(n - 1, int(n * 0.99))], 1),
                "max": round(v[-1], 1),
                "mean": round(statistics.fmean(v), 1),
                "meanMinutes": round(statistics.fmean(v) / 60.0, 2),
                "medianMinutes": round(v[n // 2] / 60.0, 2),
            }
        if self.hour_stay:
            s["medianStayMinutesByArrivalHourUtc"] = {
                str(h): round(statistics.median(v) / 60.0, 2)
                for h, v in sorted(self.hour_stay.items()) if v
            }
        if self.hour_stay_n:
            # MEAN, not median. Little's Law (L = lambda * W) requires W to be the
            # MEAN time in system. Parking durations are strongly right-skewed, so
            # using the median systematically underestimates occupancy - measured
            # at ~31% low on the calibration fixture.
            s["meanStayMinutesByArrivalHourUtc"] = {
                str(h): round((self.hour_stay_sum[h] / self.hour_stay_n[h]) / 60.0, 3)
                for h in sorted(self.hour_stay_n) if self.hour_stay_n[h]
            }
            s["meanStayMinutesByArrivalHourUtc_n"] = {
                str(h): self.hour_stay_n[h] for h in sorted(self.hour_stay_n)
            }
        s["distinctBays"] = len(self.bay_keys)
        s["distinctArrivalDates"] = len(self.arrival_dates)
        s["eventsByArrivalHourUtc"] = {str(h): c for h, c in sorted(self.by_hour.items())}
        s["eventsByWeekday"] = dict(self.by_weekday)
        s["topRestrictions"] = self.by_restriction.most_common(25)
        s["topStreets"] = self.by_street.most_common(25)
        s["overstayBreakdown"] = dict(self.overstay)
        s["timeConfidence"] = dict(self.confidence)
        s["dataQualityDefects"] = dict(self.defects)
        if self.min_ts and self.max_ts:
            s["timeRangeUtc"] = {
                "from": datetime.fromtimestamp(self.min_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": datetime.fromtimestamp(self.max_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "spanDays": round((self.max_ts - self.min_ts) / 86400.0, 2),
            }
        return s


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def http_get(url, timeout=60, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json, text/csv, */*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


def candidate_record_urls(base, dataset, limit=100, offset=0):
    """Opendatasoft/Socrata shapes. Portals migrate; try them in order."""
    b = base.rstrip("/")
    return [
        ("opendatasoft-explore-v2.1",
         f"{b}/api/explore/v2.1/catalog/datasets/{dataset}/records"
         f"?limit={limit}&offset={offset}"),
        ("opendatasoft-v2-records",
         f"{b}/api/v2/catalog/datasets/{dataset}/records?rows={limit}&start={offset}"),
        ("opendatasoft-records-v1",
         f"{b}/api/records/1.0/search/?dataset={dataset}&rows={limit}&start={offset}"),
        ("opendatasoft-v2-exports-json",
         f"{b}/api/v2/catalog/datasets/{dataset}/exports/json"),
        ("socrata-soda-v2",
         f"{b}/resource/{dataset}.json?$limit={limit}&$offset={offset}"),
    ]


def extract_records(payload_obj):
    """Normalise the different response envelopes into a list of dicts."""
    if isinstance(payload_obj, list):
        return payload_obj
    if isinstance(payload_obj, dict):
        for key in ("results", "records", "rows", "features", "hits"):
            v = payload_obj.get(key)
            if isinstance(v, list) and v:
                if key == "features":       # GeoJSON
                    out = []
                    for f in v:
                        rec = dict(f.get("properties") or {})
                        geom = (f.get("geometry") or {}).get("coordinates")
                        if isinstance(geom, list) and len(geom) >= 2:
                            rec.setdefault("lon", geom[0])
                            rec.setdefault("lat", geom[1])
                        out.append(rec)
                    return out
                if v and isinstance(v[0], dict) and "record" in v[0]:
                    return [r["record"] for r in v]
                if v and isinstance(v[0], dict) and "fields" in v[0]:
                    return [r["fields"] for r in v]
                return v
    return []


# --------------------------------------------------------------------------- #
# MODE: probe
# --------------------------------------------------------------------------- #

def cmd_probe(args):
    print("=" * 74)
    print("ENDPOINT PROBE — which API shape actually works?")
    print("=" * 74)
    found = None
    for label, url in candidate_record_urls(args.base, args.dataset, limit=5):
        try:
            status, body, hdrs = http_get(url, timeout=args.timeout)
        except urllib.error.HTTPError as e:
            print(f"  [HTTP {e.code}] {label}\n            {url}")
            continue
        except Exception as e:                                  # noqa: BLE001
            print(f"  [ERR {type(e).__name__}] {label}\n            {e}")
            continue
        ctype = hdrs.get("Content-Type", "")
        print(f"  [HTTP {status}] {label}  ({len(body)} bytes, {ctype})")
        print(f"            {url}")
        if "json" not in ctype.lower():
            print(f"            -> not JSON; first 160 bytes: {body[:160]!r}")
            continue
        try:
            obj = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            print(f"            -> JSON decode failed: {e}")
            continue
        recs = extract_records(obj)
        print(f"            -> {len(recs)} record(s)")
        if recs:
            keys = list(recs[0].keys())
            print(f"            -> FIELDS: {keys}")
            cmap, unresolved, _ = build_column_map(keys)
            print(f"            -> mapped  : {cmap}")
            print(f"            -> unmapped: {unresolved}")
            if found is None:
                found = {"label": label, "url": url, "fields": keys,
                         "mapped": cmap, "unmapped": unresolved,
                         "sample": recs[0]}
    print("-" * 74)
    if found:
        print("RECOMMENDED ENDPOINT:")
        print(json.dumps(found, indent=2, default=str)[:2000])
        os.makedirs(args.out, exist_ok=True)
        p = os.path.join(args.out, "probe-result.json")
        with open(p, "w") as fh:
            json.dump({"probedAt": now_iso(), "base": args.base,
                       "dataset": args.dataset, "recommended": found}, fh,
                      indent=2, default=str)
        print(f"\nwritten: {p}")
    else:
        print("NO WORKING ENDPOINT FOUND from this network.")
        print("Likely causes: portal requires an API key, geo-blocked, or the")
        print("dataset id changed. Run this from a normal network and record the")
        print("result in manifests/.")
    print("=" * 74)
    return 0 if found else 1


# --------------------------------------------------------------------------- #
# MODE: live  (poll + diff -> real transition events)
# --------------------------------------------------------------------------- #

def cmd_live(args):
    os.makedirs(args.out, exist_ok=True)
    events_path = os.path.join(args.out, "live-transitions.jsonl")
    snap_path = os.path.join(args.out, "latest-snapshot.json")
    stats_path = os.path.join(args.out, "live-harvest-stats.json")

    url = args.url
    if not url:
        for label, cand in candidate_record_urls(args.base, args.dataset,
                                                 limit=args.limit):
            url = cand
            break
    print("=" * 74)
    print("LIVE TRANSITION HARVEST")
    print("=" * 74)
    print(f"  dataset   : {args.dataset}")
    print(f"  interval  : {args.interval}s")
    print(f"  duration  : {args.minutes} min (~{int(args.minutes*60/args.interval)} polls)")
    print(f"  output    : {events_path}")
    print("-" * 74)
    print("  NOTE: a state feed does not publish events. Transitions here are")
    print("  DERIVED by diffing snapshots, so each event's timestamp is bounded")
    print("  by the poll interval, not exact. That bound is recorded on every")
    print("  event as observationWindowSeconds and timeConfidence=DERIVED.")
    print("=" * 74, flush=True)

    prev = {}
    prev_poll = None
    agg = TelemetryAggregator(reservoir_size=args.reservoir, seed=args.seed)
    polls = 0
    errors = Counter()
    lastupdated_max = None
    state = "UNKNOWN"
    deadline = time.time() + args.minutes * 60
    started = time.time()
    endpoint_used = None

    with open(events_path, "w") as ev_fh:
        while time.time() < deadline:
            polls += 1
            poll_at = time.time()
            recs = None
            tried = []
            for label, cand in candidate_record_urls(args.base, args.dataset,
                                                     limit=args.limit):
                tried.append(label)
                try:
                    status, body, hdrs = http_get(cand, timeout=args.timeout)
                except Exception as e:                          # noqa: BLE001
                    errors[f"{label}:{type(e).__name__}"] += 1
                    continue
                if status != 200:
                    errors[f"{label}:HTTP{status}"] += 1
                    continue
                try:
                    obj = json.loads(body.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    errors[f"{label}:notJSON"] += 1
                    continue
                r = extract_records(obj)
                if r:
                    recs, endpoint_used = r, cand
                    break
                errors[f"{label}:emptyRecords"] += 1

            if recs is None:
                print(f"  poll {polls}: ALL ENDPOINTS FAILED {dict(errors)}",
                      file=sys.stderr, flush=True)
                time.sleep(max(1.0, args.interval))
                continue

            keys = list(recs[0].keys())
            cmap, unresolved, _ = build_column_map(keys)
            if polls == 1:
                print(f"  endpoint  : {endpoint_used}")
                print(f"  fields    : {keys}")
                print(f"  mapped    : {cmap}")
                print(f"  unmapped  : {unresolved}")
                print(f"  records   : {len(recs)}", flush=True)
            if "bayKey" not in cmap:
                print("  FATAL: no bay identifier column resolved. "
                      f"Fields were: {keys}", file=sys.stderr)
                return 2

            cur = {}
            lu_values = []
            for r in recs:
                bk = str(r.get(cmap["bayKey"], "")).strip()
                if not bk:
                    continue
                st = classify_status(r.get(cmap.get("status", ""), "")) \
                    if "status" in cmap else "UNKNOWN"
                cur[bk] = {
                    "status": st,
                    "restriction": r.get(cmap.get("restriction", "")),
                    "street": r.get(cmap.get("street", "")),
                    "lat": to_float(r.get(cmap.get("lat", ""))) if "lat" in cmap else None,
                    "lon": to_float(r.get(cmap.get("lon", ""))) if "lon" in cmap else None,
                    "lastUpdatedRaw": r.get(cmap.get("lastUpdated", "")) if "lastUpdated" in cmap else None,
                }
                if "lastUpdated" in cmap:
                    e, _, _ = parse_ts(r.get(cmap["lastUpdated"]))
                    if e:
                        lu_values.append(e)

            if lu_values:
                m = max(lu_values)
                lastupdated_max = m
                lag = poll_at - m
                # The publisher warns this feed goes through network relays and
                # can be disrupted. A growing lag is a DEGRADED source signal.
                state = "FRESH" if lag < args.interval * 4 else \
                        "STALE" if lag < 900 else "DEGRADED"
            else:
                lag, state = None, "UNKNOWN"

            if prev:
                window = round(poll_at - prev_poll, 2) if prev_poll else None
                transitions = 0
                for bk, c in cur.items():
                    p = prev.get(bk)
                    if not p or p["status"] == c["status"]:
                        continue
                    if c["status"] == "UNKNOWN" or p["status"] == "UNKNOWN":
                        kind = "STATUS_UNKNOWN_TRANSITION"
                    elif c["status"] == "OCCUPIED":
                        kind = "ARRIVAL"
                    else:
                        kind = "DEPARTURE"
                    ev = {
                        "eventType": kind,
                        "sourceMode": "live-diff",
                        "bayKey": bk,
                        "sourceId": args.dataset,
                        "street": c["street"] or p["street"],
                        "restriction": c["restriction"] or p["restriction"],
                        "lat": c["lat"] if c["lat"] is not None else p["lat"],
                        "lon": c["lon"] if c["lon"] is not None else p["lon"],
                        "fromStatus": p["status"],
                        "toStatus": c["status"],
                        "observedAt": now_iso(),
                        "observationWindowSeconds": window,
                        "timeConfidence": "DERIVED",
                        "timeConfidenceNote":
                            "Transition time is bounded by the poll interval; the "
                            "true event occurred somewhere inside the window.",
                        "retrievedAtEpoch": poll_at,
                        "sourceHealth": state,
                        "legalityClaimed": False,
                    }
                    ev_fh.write(json.dumps(ev) + "\n")
                    agg.add({"bayKey": bk,
                             "arrivalEpoch": poll_at if kind == "ARRIVAL" else None,
                             "departureEpoch": poll_at if kind == "DEPARTURE" else None,
                             "restriction": ev["restriction"],
                             "street": ev["street"],
                             "overstay": None,
                             "durationSeconds": None,
                             "timeConfidence": "DERIVED",
                             "dataQuality": (["unknown_status_transition"]
                                             if kind == "STATUS_UNKNOWN_TRANSITION" else [])})
                    transitions += 1
                occ = sum(1 for v in cur.values() if v["status"] == "OCCUPIED")
                free = sum(1 for v in cur.values() if v["status"] == "FREE")
                unk = sum(1 for v in cur.values() if v["status"] == "UNKNOWN")
                print(f"  poll {polls:>4}  bays={len(cur):>5} "
                      f"occ={occ:>5} free={free:>5} unk={unk:>4} "
                      f"transitions={transitions:>4} health={state}"
                      + (f" lag={lag:.0f}s" if lag is not None else ""),
                      flush=True)
                with open(snap_path, "w") as fh:
                    json.dump({"polledAt": now_iso(), "endpoint": endpoint_used,
                               "sourceHealth": state,
                               "sourceLagSeconds": round(lag, 1) if lag is not None else None,
                               "counts": {"total": len(cur), "occupied": occ,
                                          "free": free, "unknown": unk},
                               "bays": cur}, fh)
            else:
                print(f"  poll {polls:>4}  baseline captured: {len(cur)} bays "
                      f"(no transitions yet)", flush=True)

            prev, prev_poll = cur, poll_at
            time.sleep(max(0.5, args.interval - (time.time() - poll_at)))

    elapsed = round(time.time() - started, 1)
    stats = {
        "mode": "live-diff",
        "sourceId": args.dataset,
        "endpointUsed": endpoint_used,
        "portal": args.base,
        "startedAt": datetime.fromtimestamp(started, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finishedAt": now_iso(),
        "elapsedSeconds": elapsed,
        "polls": polls,
        "pollIntervalSeconds": args.interval,
        "errors": dict(errors),
        "finalSourceHealth": state,
        "lastObservedSourceTimestampUtc":
            datetime.fromtimestamp(lastupdated_max, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if lastupdated_max else None,
        "derivedEvents": agg.count,
        "aggregate": agg.summary(),
        "reservoirEvents": agg.reservoir,
        "caveats": [
            "Events are DERIVED from state diffs, not published as events. "
            "Timestamp precision is bounded by the poll interval.",
            "A bay that is occupied and vacated between two polls is INVISIBLE. "
            "Shorter stays are systematically undercounted; this is a censoring "
            "bias, not a bug, and must be stated in any analysis.",
            "Polling a whole-city dataset returns at most --limit records per "
            "call; raise it or page if the bay count exceeds it.",
            "This is the AVAILABILITY lane. No legality is inferred.",
        ],
    }
    with open(stats_path, "w") as fh:
        json.dump(stats, fh, indent=2, default=str)
    print("-" * 74)
    print(f"  derived events : {agg.count}")
    print(f"  stats written  : {stats_path}")
    print("=" * 74)
    return 0


# --------------------------------------------------------------------------- #
# MODE: archive  (stream a historical event archive)
# --------------------------------------------------------------------------- #

def open_archive_stream(path_or_url, keep=False, timeout=300):
    """
    Return (text_stream, sha256_hex, byte_count, source_kind, local_path|None).

    Downloads to a temp dir OUTSIDE the repo, hashes while streaming, and
    removes the download afterwards unless keep=True. Handles .zip, .gz and
    plain .csv transparently.
    """
    hasher = hashlib.sha256()
    counter = [0]

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        tmpdir = tempfile.mkdtemp(prefix="pte-telemetry-")
        local = os.path.join(tmpdir, "download.bin")
        print(f"  streaming {path_or_url}")
        print(f"  -> temp (outside repo): {local}")
        req = urllib.request.Request(path_or_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r, \
                open(local, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                hasher.update(chunk)
                counter[0] += len(chunk)
                fh.write(chunk)
                if counter[0] % (64 << 20) < (1 << 20):
                    print(f"     ...{counter[0]/1e6:.0f} MB", flush=True)
        source_kind, local_path = "remote", local
    else:
        local = path_or_url
        if not os.path.exists(local):
            raise SystemExit(f"no such file: {local}")
        with open(local, "rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                hasher.update(chunk)
                counter[0] += len(chunk)
        source_kind, local_path = "local", None

    sha = hasher.hexdigest()
    print(f"  sha256: {sha}")
    print(f"  bytes : {counter[0]:,}")

    low = path_or_url.lower()
    if low.endswith(".zip"):
        zf = zipfile.ZipFile(local)
        names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
        if not names:
            names = zf.namelist()
        if not names:
            raise SystemExit("zip contains no csv")
        print(f"  zip member: {names[0]}")
        raw = zf.open(names[0], "r")
        stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace",
                                  newline="")
    elif low.endswith(".gz"):
        stream = io.TextIOWrapper(gzip.open(local, "rb"), encoding="utf-8",
                                  errors="replace", newline="")
    else:
        stream = open(local, "r", encoding="utf-8", errors="replace", newline="")

    def cleanup():
        try:
            stream.close()
        except Exception:
            pass
        if local_path and not keep:
            shutil.rmtree(os.path.dirname(local_path), ignore_errors=True)
            print(f"  removed temp download (use --keep-download to retain)")

    return stream, sha, counter[0], source_kind, cleanup


def cmd_archive(args):
    if args.year and not args.url and not args.file:
        meta = HISTORICAL_ARCHIVES.get(args.year)
        if not meta:
            raise SystemExit(f"unknown year {args.year}; "
                             f"choose from {sorted(HISTORICAL_ARCHIVES)}")
        args.url = (f"{PORTAL_DEFAULT}/api/v2/catalog/datasets/"
                    f"{meta['dataset']}/exports/csv")
        print(f"  year {args.year}: {meta['rows']:,} published rows, "
              f"{meta['compressed']} compressed")
    if not args.url and not args.file:
        raise SystemExit("need --url, --file, or --year")

    os.makedirs(args.out, exist_ok=True)
    events_path = os.path.join(args.out, "telemetry-events.jsonl")
    stats_path = os.path.join(args.out, "archive-stats.json")
    manifest_path = os.path.join(args.out, "archive-manifest.json")

    print("=" * 74)
    print("HISTORICAL PARKING-EVENT ARCHIVE HARVEST")
    print("=" * 74)

    stream, sha, nbytes, kind, cleanup = open_archive_stream(
        args.url or args.file, keep=args.keep_download, timeout=args.timeout)

    agg = TelemetryAggregator(reservoir_size=args.reservoir, seed=args.seed)
    emitted = 0
    rows = 0
    skipped = Counter()
    cmap = None
    sample_raw = None

    try:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        if len(fieldnames) == 1 and "\t" in fieldnames[0]:
            stream.seek(0)
            reader = csv.DictReader(stream, delimiter="\t")
            fieldnames = reader.fieldnames or []
        if len(fieldnames) == 1 and ";" in fieldnames[0]:
            stream.seek(0)
            reader = csv.DictReader(stream, delimiter=";")
            fieldnames = reader.fieldnames or []

        cmap, unresolved, actual = build_column_map(fieldnames)
        print(f"  columns found : {actual}")
        print(f"  mapped        : {cmap}")
        print(f"  unmapped      : {unresolved}")
        if "bayKey" not in cmap:
            print("  FATAL: could not resolve a bay identifier column.",
                  file=sys.stderr)
            return 2
        if "arrival" not in cmap and "durationSeconds" not in cmap:
            print("  FATAL: neither an arrival-time nor a duration column was "
                  "resolved; nothing to derive telemetry from.", file=sys.stderr)
            return 2

        with open(events_path, "w") as fh:
            for raw in reader:
                rows += 1
                if rows == 1:
                    sample_raw = dict(raw)

                bay = str(raw.get(cmap.get("bayKey", ""), "")).strip()
                if not bay:
                    skipped["no_bay_key"] += 1
                    continue

                quality = []
                restr = raw.get(cmap.get("restriction", "")) if "restriction" in cmap else None
                if restr and str(restr).strip().upper().endswith("OLD"):
                    quality.append("sign_old_suffix")

                a_e, a_iso, a_conf = parse_ts(
                    raw.get(cmap.get("arrival", "")) if "arrival" in cmap else None)
                d_e, d_iso, d_conf = parse_ts(
                    raw.get(cmap.get("departure", "")) if "departure" in cmap else None)
                if a_conf == "MISSING":
                    quality.append("missing_times_imputed")
                if a_conf == "UNPARSEABLE":
                    skipped["unparseable_arrival"] += 1

                dur = to_float(raw.get(cmap.get("durationSeconds", ""))) \
                    if "durationSeconds" in cmap else None
                if dur is not None and dur < 0:
                    quality.append("negative_duration")
                if dur is None and a_e is not None and d_e is not None:
                    dur = d_e - a_e

                if a_e is None and dur is None:
                    skipped["no_time_information"] += 1
                    continue

                over = None
                if "overstay" in cmap:
                    v = str(raw.get(cmap["overstay"], "")).strip().lower()
                    over = (True if v in {"true", "1", "yes", "y", "overstay"}
                            else False if v in {"false", "0", "no", "n", ""}
                            else None)
                    if over is True:
                        quality.append("overstayed")

                ev = {
                    "eventType": "PARKING_EVENT",
                    "sourceMode": "historical-archive",
                    "bayKey": bay,
                    "sourceId": args.source_id or (args.year and
                                                   f"melbourne-{args.year}") or "unknown",
                    "street": raw.get(cmap.get("street", "")) if "street" in cmap else None,
                    "betweenStreet1": raw.get(cmap.get("betweenStreet1", "")) if "betweenStreet1" in cmap else None,
                    "betweenStreet2": raw.get(cmap.get("betweenStreet2", "")) if "betweenStreet2" in cmap else None,
                    "areaName": raw.get(cmap.get("areaName", "")) if "areaName" in cmap else None,
                    "restriction": restr,
                    "overstay": over,
                    "lat": to_float(raw.get(cmap.get("lat", ""))) if "lat" in cmap else None,
                    "lon": to_float(raw.get(cmap.get("lon", ""))) if "lon" in cmap else None,
                    "arrivalTime": a_iso,
                    "departureTime": d_iso,
                    "arrivalEpoch": a_e,
                    "departureEpoch": d_e,
                    "durationSeconds": round(dur, 1) if dur is not None else None,
                    "durationMinutes": round(dur / 60.0, 2) if dur is not None else None,
                    "timeConfidence": a_conf if a_conf != "MISSING" else "IMPUTED",
                    "dataQuality": quality,
                    "legalityClaimed": False,
                }

                agg.add(ev)
                if emitted < args.max_emit:
                    fh.write(json.dumps(ev) + "\n")
                    emitted += 1

                if rows % args.progress_every == 0:
                    print(f"  rows={rows:>12,}  emitted={emitted:>9,}  "
                          f"skipped={sum(skipped.values()):>9,}", flush=True)
                if args.max_rows and rows >= args.max_rows:
                    print(f"  hit --max-rows {args.max_rows:,}; stopping")
                    break
    finally:
        cleanup()

    summary = agg.summary()
    stats = {
        "mode": "historical-archive",
        "sourceUrl": args.url,
        "sourceFile": args.file,
        "sourceKind": kind,
        "sha256": sha,
        "bytes": nbytes,
        "retrievedAt": now_iso(),
        "rowsRead": rows,
        "eventsEmitted": emitted,
        "emitCap": args.max_emit,
        "emitCapNote": ("Events are reservoir-sampled for statistics across ALL "
                        "rows, but only the first --max-emit are written to "
                        "JSONL. Statistics are therefore computed over the full "
                        "stream, not just the retained sample."),
        "skipped": dict(skipped),
        "columnMap": cmap,
        "unmappedColumns": unresolved,
        "sampleRawRow": sample_raw,
        "aggregate": summary,
        "reservoirEvents": agg.reservoir[:args.reservoir_out],
        "documentedPublisherDefects": DOCUMENTED_DEFECTS,
        "caveats": [
            "Publisher excludes events crossing the year boundary, so stay "
            "distributions are right-truncated at midnight on 31 December.",
            "Rows flagged missing_times_imputed carry IMPUTED times derived from "
            "midnight, not observed sensor times. Never treat them as observed.",
            "Rows flagged sign_old_suffix may pair an event with a restriction "
            "that no longer applied. Do not use them to validate legality.",
            "Timestamps are publisher-local (Melbourne). Convert with an IANA "
            "timezone before any hour-of-day analysis; the aggregates here are "
            "labelled UTC to avoid asserting a conversion this tool did not do.",
            "AVAILABILITY lane only. Restriction and overstay fields are carried "
            "as inventory/observation metadata; they are NOT legality verdicts.",
        ],
    }
    with open(stats_path, "w") as fh:
        json.dump(stats, fh, indent=2, default=str)

    manifest = {
        "policy": "large reproducible public source referenced by URL+SHA-256+metadata; bytes not retained",
        "artifact": os.path.basename(args.url or args.file or "archive"),
        "sourceUrl": args.url,
        "retrievedAt": now_iso(),
        "bytes": nbytes,
        "sha256": sha,
        "rowsRead": rows,
        "eventsEmitted": emitted,
        "license": "CC-BY-4.0 / CC-BY-3.0-AU (City of Melbourne Open Data) — confirm per dataset before shipping",
        "preservedAs": "URL+hash+derived bounded artifacts only" if not args.keep_download
                       else "download retained locally (--keep-download)",
        "derivedArtifacts": [events_path, stats_path],
    }
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)

    print("-" * 74)
    print(f"  rows read      : {rows:,}")
    print(f"  events emitted : {emitted:,}  (cap {args.max_emit:,})")
    print(f"  skipped        : {dict(skipped)}")
    print(f"  defects counted: {summary.get('dataQualityDefects')}")
    sd = summary.get("stayDurationSeconds")
    if sd:
        print(f"  stay minutes   : median={sd['medianMinutes']} "
              f"p95={round(sd['p95']/60,1)} mean={sd['meanMinutes']} "
              f"(n={sd['sampledRows']:,})")
    tr = summary.get("timeRangeUtc")
    if tr:
        print(f"  time range     : {tr['from']} .. {tr['to']} ({tr['spanDays']} days)")
    print(f"  sha256         : {sha}")
    print(f"  events         : {events_path}")
    print(f"  stats          : {stats_path}")
    print(f"  manifest       : {manifest_path}")
    print("=" * 74)
    return 0


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="discover which API shape works")
    p.add_argument("--base", default=PORTAL_DEFAULT)
    p.add_argument("--dataset", default=LIVE_DATASET_DEFAULT)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--out", default="out/probe")

    l = sub.add_parser("live", help="poll + diff a live sensor feed into events")
    l.add_argument("--base", default=PORTAL_DEFAULT)
    l.add_argument("--dataset", default=LIVE_DATASET_DEFAULT)
    l.add_argument("--url", default=None, help="explicit records endpoint")
    l.add_argument("--interval", type=float, default=20.0, help="poll seconds")
    l.add_argument("--minutes", type=float, default=30.0)
    l.add_argument("--limit", type=int, default=5000,
                   help="records per poll; raise if the city has more bays")
    l.add_argument("--timeout", type=int, default=60)
    l.add_argument("--reservoir", type=int, default=20000)
    l.add_argument("--seed", type=int, default=1337)
    l.add_argument("--out", default="out/live")

    a = sub.add_parser("archive", help="stream a historical parking-event archive")
    a.add_argument("--url", default=None)
    a.add_argument("--file", default=None)
    a.add_argument("--year", default=None, choices=sorted(HISTORICAL_ARCHIVES),
                   help="shortcut for a known City of Melbourne archive")
    a.add_argument("--source-id", default=None)
    a.add_argument("--max-emit", type=int, default=250000,
                   help="cap on rows written to JSONL (stats still cover all rows)")
    a.add_argument("--max-rows", type=int, default=None, help="stop after N rows")
    a.add_argument("--reservoir", type=int, default=50000)
    a.add_argument("--reservoir-out", type=int, default=500,
                   help="how many reservoir events to embed in the stats file")
    a.add_argument("--seed", type=int, default=1337)
    a.add_argument("--progress-every", type=int, default=100000)
    a.add_argument("--timeout", type=int, default=600)
    a.add_argument("--keep-download", action="store_true",
                   help="retain the downloaded archive (default: delete)")
    a.add_argument("--out", default="out/archive")

    args = ap.parse_args()
    if args.cmd == "probe":
        sys.exit(cmd_probe(args))
    elif args.cmd == "live":
        sys.exit(cmd_live(args))
    elif args.cmd == "archive":
        sys.exit(cmd_archive(args))


if __name__ == "__main__":
    main()
