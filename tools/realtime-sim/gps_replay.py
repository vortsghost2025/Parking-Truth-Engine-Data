#!/usr/bin/env python3
"""
PTE GPS Trace Generator & Replayer
==================================

Answers the question: "does the GPS part of my app work in real time?"

You do NOT need real parking data to prove that, and you do not need to be
sitting in a car in Hobart. This tool produces a realistic moving position
stream and pushes it into whatever endpoint your app listens on, at real wall
clock speed (or a multiplier).

Three modes
-----------
1. generate  — synthesise a "cruising for a park" drive through the Hobart CBD
               street skeleton and write GPX + GeoJSON + JSONL fixtures.
2. replay    — stream points at your app's ingest URL over HTTP POST, one fix
               per second, so you can watch your map move live.
3. from-gpx  — load a REAL recorded trace (e.g. an OpenStreetMap public GPS
               trace around Hobart) and replay it at a chosen speed factor.

The GPX output also works as a mock-location file for device simulators:
  * Android Studio emulator -> Extended Controls -> Location -> Routes (GPX)
  * Xcode                   -> Debug -> Simulate Location -> GPX File
  * adb                     -> `adb emu geo fix <lon> <lat>` per point

Realism features (each individually switchable so you can isolate bugs)
----------------------------------------------------------------------
  * horizontal accuracy that varies with speed and urban canyon conditions
  * Gaussian position noise proportional to reported accuracy
  * occasional dropped fixes (tunnel / under a multi-storey car park deck)
  * occasional accuracy spikes and brief backwards drift (the classic
    "GPS says I'm in the Derwent" failure mode)
  * a parking manoeuvre: decelerate, stop, then stationary jitter while parked
  * speeds in m/s with a plausible CBD cruising/searching profile

STDLIB ONLY. Python 3.8+.

    python3 gps_replay.py generate --minutes 12 --seed 7 --out fixtures/
    python3 gps_replay.py replay   --fixtures fixtures/ --post-url https://YOUR-HOSTINGER-APP/api/gps
    python3 gps_replay.py replay   --fixtures fixtures/ --post-url ... --speed 4
    python3 gps_replay.py from-gpx --gpx my_drive.gpx --post-url ... --speed 2
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Same approximate CBD skeleton as sim_feed.py. NOT surveyed geometry.
STREETS = {
    "Elizabeth St":   [(-42.87750, 147.32550), (-42.88300, 147.32630), (-42.88850, 147.32750)],
    "Liverpool St":   [(-42.87900, 147.32350), (-42.88350, 147.32430), (-42.88800, 147.32500)],
    "Argyle St":      [(-42.87800, 147.32800), (-42.88350, 147.32880), (-42.88900, 147.32950)],
    "Campbell St":    [(-42.88000, 147.32950), (-42.88400, 147.33020), (-42.88800, 147.33100)],
    "Harrington St":  [(-42.87950, 147.32650), (-42.88300, 147.32700)],
    "Bathurst St":    [(-42.88000, 147.32300), (-42.88040, 147.32650), (-42.88080, 147.33000)],
    "Collins St":     [(-42.88380, 147.32180), (-42.88430, 147.32600), (-42.88480, 147.33000)],
    "Murray St":      [(-42.88300, 147.32220), (-42.88340, 147.32640), (-42.88380, 147.33050)],
    "Macquarie St":   [(-42.88480, 147.32150), (-42.88530, 147.32570), (-42.88580, 147.32980)],
    "Davey St":       [(-42.88620, 147.32250), (-42.88660, 147.32630), (-42.88700, 147.33000)],
    "Salamanca Pl":   [(-42.88680, 147.32880), (-42.88770, 147.32940), (-42.88850, 147.33000)],
    "Morrison St":    [(-42.88780, 147.32820), (-42.88830, 147.32900)],
}

SYNTHETIC_NOTE = ("SYNTHETIC / APPROXIMATE geometry. Hand-authored Hobart CBD "
                  "street skeleton for GPS pipeline testing. Not survey data.")


def haversine_m(a, b):
    (a_lat, a_lon), (b_lat, b_lon) = a, b
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #

def build_graph(cross_link_m=160.0):
    """Nodes = street vertices; edges = within-street + nearby cross-street."""
    nodes, edges = [], set()

    def node_for(pt):
        key = (round(pt[0], 5), round(pt[1], 5))
        for i, (n, k) in enumerate(nodes):
            if k == key:
                return i
        nodes.append((pt, key))
        return len(nodes) - 1

    for street, verts in STREETS.items():
        idxs = [node_for(v) for v in verts]
        for a, b in zip(idxs, idxs[1:]):
            edges.add((min(a, b), max(a, b)))

    # cross-links: intersections are approximate, so join anything close
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if haversine_m(nodes[i][0], nodes[j][0]) <= cross_link_m:
                edges.add((i, j))

    adj = {i: set() for i in range(len(nodes))}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    return nodes, adj


def random_route(adj, rng, n_nodes=14, start=None):
    """Random walk over the street graph -> list of node indices."""
    cur = start if start is not None else rng.choice(list(adj))
    route = [cur]
    prev = None
    for _ in range(n_nodes):
        opts = [n for n in adj[cur] if n != prev] or list(adj[cur])
        nxt = rng.choice(opts)
        route.append(nxt)
        prev, cur = cur, nxt
    # de-duplicate consecutive
    out = [route[0]]
    for n in route[1:]:
        if n != out[-1]:
            out.append(n)
    return out


# --------------------------------------------------------------------------- #
# Trace synthesis
# --------------------------------------------------------------------------- #

def densify(nodes, route, rng, step_m=4.0):
    """Expand the node route into (lat, lon, is_search_zone) ground-truth pts."""
    pts = []
    for a, b in zip(route, route[1:]):
        pa, pb = nodes[a][0], nodes[b][0]
        dist = haversine_m(pa, pb)
        steps = max(2, int(dist / step_m))
        searching = rng.random() < 0.35      # some blocks are "looking for a park"
        for i in range(steps):
            t = i / steps
            pts.append((pa[0] + (pb[0] - pa[0]) * t,
                        pa[1] + (pb[1] - pa[1]) * t,
                        searching))
    return pts


def synth_trace(minutes=10.0, seed=1337, hz=1.0,
                noise=True, dropouts=True, accuracy_spikes=True,
                park_at_end=True, park_seconds=90.0):
    """Build a wall-clock-timed list of GPS fixes for a CBD parking search."""
    rng = random.Random(seed)
    nodes, adj = build_graph()
    route = random_route(adj, rng, n_nodes=max(8, int(minutes * 1.6)))
    ground = densify(nodes, route, rng)
    if not ground:
        raise SystemExit("could not build a route; try a different --seed")

    dt = 1.0 / hz
    fixes, gi, t = [], 0, 0.0
    total_s = minutes * 60.0

    def emit(lat, lon, speed, phase):
        nonlocal t
        # --- reported horizontal accuracy degrades in the urban canyon ------
        base_acc = 5.0 + speed * 0.35
        if rng.random() < 0.10:
            base_acc *= rng.uniform(1.6, 3.2)      # multipath between buildings
        if accuracy_spikes and rng.random() < 0.012:
            base_acc *= rng.uniform(6.0, 14.0)     # the "in the Derwent" fix
        acc = round(base_acc, 1)

        # --- noise on the true position, scaled by accuracy ----------------
        olat, olon = lat, lon
        if noise:
            sigma_deg = (acc * 0.55) / 111320.0
            olat += rng.gauss(0, sigma_deg)
            olon += rng.gauss(0, sigma_deg / max(0.2, math.cos(math.radians(lat))))
            if accuracy_spikes and rng.random() < 0.006:
                olat += rng.gauss(0, sigma_deg * 9)   # rare big backwards jump
                olon += rng.gauss(0, sigma_deg * 9)

        # --- dropout: no fix reported at all -------------------------------
        if dropouts and rng.random() < 0.015:
            return

        fixes.append({
            "t": round(t, 3),
            "lat": round(olat, 7),
            "lon": round(olon, 7),
            "trueLat": round(lat, 7),
            "trueLon": round(lon, 7),
            "speedMs": round(speed, 2),
            "speedKmh": round(speed * 3.6, 1),
            "accuracyM": acc,
            "altitudeM": round(rng.uniform(2, 40), 1),
            "bearingDeg": None,
            "phase": phase,
            "provider": "simulated",
            "synthetic": True,
            "timestampUtc": None,   # filled in at write/replay time
        })

    while t < total_s and gi < len(ground) - 1:
        lat, lon, searching = ground[gi]
        # CBD speed profile: 8-12 m/s flowing, 3-6 m/s while hunting a bay
        if searching:
            speed = rng.uniform(2.6, 5.8)
            phase = "searching"
        else:
            speed = rng.uniform(7.0, 11.5)
            phase = "driving"
        # slow for the (implicit) intersections
        if gi % 24 < 3:
            speed = rng.uniform(0.8, 3.0)
            phase = "junction"
        emit(lat, lon, speed, phase)

        # advance along ground truth by speed*dt
        advance = max(1, int(round(speed * dt / 4.0)))
        gi = min(len(ground) - 1, gi + advance)
        t += dt

    # bearing pass (needs neighbours)
    for i, f in enumerate(fixes):
        j = min(i + 1, len(fixes) - 1)
        k = max(i - 1, 0)
        dlat = fixes[j]["trueLat"] - fixes[k]["trueLat"]
        dlon = (fixes[j]["trueLon"] - fixes[k]["trueLon"]) * math.cos(math.radians(f["trueLat"]))
        f["bearingDeg"] = round((math.degrees(math.atan2(dlon, dlat)) + 360) % 360, 1)

    # --- final parking manoeuvre -------------------------------------------
    if park_at_end and fixes:
        last = fixes[-1]
        plat, plon = last["trueLat"], last["trueLon"]
        t = fixes[-1]["t"]
        for decel in (2.4, 1.6, 0.9, 0.4, 0.1):
            t += dt
            emit(plat, plon, decel, "manoeuvre")
        parked_start = len(fixes)
        n_parked = int(park_seconds / dt)
        for i in range(n_parked):
            t += dt
            emit(plat, plon, 0.0, "parked")
        for f in fixes[parked_start:]:
            f["parkedBayHint"] = "SIM-PARK-END"

    return fixes, {"seed": seed, "minutes": minutes, "hz": hz,
                   "noise": noise, "dropouts": dropouts,
                   "accuracySpikes": accuracy_spikes,
                   "parkAtEnd": park_at_end, "syntheticNote": SYNTHETIC_NOTE}


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #

def stamp(fixes, start_epoch=None):
    start = start_epoch if start_epoch is not None else time.time()
    for f in fixes:
        f["timestampUtc"] = datetime.fromtimestamp(
            start + f["t"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        f["epochMs"] = int((start + f["t"]) * 1000)
    return fixes


def write_fixtures(fixes, meta, outdir):
    os.makedirs(outdir, exist_ok=True)
    p_jsonl = os.path.join(outdir, "trace.jsonl")
    p_geo = os.path.join(outdir, "trace.geojson")
    p_gpx = os.path.join(outdir, "trace.gpx")
    p_meta = os.path.join(outdir, "trace.meta.json")

    with open(p_jsonl, "w") as fh:
        for f in fixes:
            fh.write(json.dumps(f) + "\n")

    geo = {
        "type": "FeatureCollection",
        "properties": meta,
        "features": [{
            "type": "Feature",
            "properties": {"name": "PTE synthetic CBD parking-search drive",
                           "synthetic": True, "note": SYNTHETIC_NOTE},
            "geometry": {"type": "LineString",
                         "coordinates": [[f["lon"], f["lat"]] for f in fixes]},
        }, {
            "type": "Feature",
            "properties": {"name": "ground truth (no noise)", "synthetic": True},
            "geometry": {"type": "LineString",
                         "coordinates": [[f["trueLon"], f["trueLat"]] for f in fixes]},
        }],
    }
    with open(p_geo, "w") as fh:
        json.dump(geo, fh, indent=1)

    gpx = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="PTE gps_replay.py" '
           'xmlns="http://www.topografix.com/GPX/1/1">',
           '<metadata><name>PTE synthetic parking-search trace</name>'
           f'<desc>{SYNTHETIC_NOTE}</desc></metadata>', '<trk>',
           '<name>PTE-synthetic-hobart-cbd</name>', '<trkseg>']
    for f in fixes:
        gpx.append(f'<trkpt lat="{f["lat"]}" lon="{f["lon"]}">'
                   f'<ele>{f["altitudeM"]}</ele><time>{f["timestampUtc"]}</time>'
                   f'<speed>{f["speedMs"]}</speed></trkpt>')
    gpx += ['</trkseg>', '</trk>', '</gpx>']
    with open(p_gpx, "w") as fh:
        fh.write("\n".join(gpx))

    with open(p_meta, "w") as fh:
        json.dump({"points": len(fixes), "durationSeconds": fixes[-1]["t"] if fixes else 0,
                   "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
                   **meta}, fh, indent=2)

    return p_jsonl, p_geo, p_gpx, p_meta


def load_jsonl(path):
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_gpx(path):
    """Parse a REAL recorded GPX into the same fix shape (no truth available)."""
    tree = ET.parse(path)
    root = tree.getroot()
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    fixes, t = [], 0.0
    prev_time = None
    for pt in root.iter(f"{ns}trkpt"):
        try:
            lat = float(pt.get("lat")); lon = float(pt.get("lon"))
        except (TypeError, ValueError):
            continue
        tel = pt.find(f"{ns}time")
        when = None
        if tel is not None and tel.text:
            txt = tel.text.strip().replace("Z", "+00:00")
            try:
                when = datetime.fromisoformat(txt).timestamp()
            except ValueError:
                when = None
        if when is not None and prev_time is not None:
            t += max(0.0, when - prev_time)
        prev_time = when if when is not None else prev_time
        sel = pt.find(f"{ns}speed")
        speed = float(sel.text) if (sel is not None and sel.text) else None
        fixes.append({"t": round(t, 3), "lat": lat, "lon": lon,
                      "trueLat": lat, "trueLon": lon,
                      "speedMs": speed if speed is not None else 0.0,
                      "speedKmh": round((speed or 0.0) * 3.6, 1),
                      "accuracyM": None, "altitudeM": None, "bearingDeg": None,
                      "phase": "recorded", "provider": "gpx",
                      "synthetic": False, "timestampUtc": None})
    if not fixes:
        raise SystemExit(f"no trackpoints found in {path}")
    return fixes


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #

def replay(fixes, post_url=None, speed=1.0, hz=None, dry_run=False,
           device_id="pte-sim-device", headers=None, verbose=True):
    """
    Stream fixes in real time.

    With --post-url each fix is POSTed as JSON. Payload shape deliberately
    mirrors what a browser Geolocation watchPosition callback gives you, plus
    server-side fields, so an ingest endpoint written for real devices works
    unchanged:

      { deviceId, lat, lon, accuracyM, altitudeM, speedMs, bearingDeg,
        timestampUtc, epochMs, provider, synthetic }

    Without --post-url it prints to stdout (dry run) so you can eyeball cadence.
    """
    hdrs = {"Content-Type": "application/json",
            "User-Agent": "PTE-gps-replay/1.0 (synthetic test traffic)"}
    hdrs.update(headers or {})

    sent = failed = 0
    t_start = time.time()
    for i, f in enumerate(fixes):
        payload = {
            "deviceId": device_id,
            "lat": f["lat"], "lon": f["lon"],
            "accuracyM": f.get("accuracyM"), "altitudeM": f.get("altitudeM"),
            "speedMs": f.get("speedMs"), "speedKmh": f.get("speedKmh"),
            "bearingDeg": f.get("bearingDeg"),
            "phase": f.get("phase"),
            "timestampUtc": f.get("timestampUtc"),
            "epochMs": f.get("epochMs"),
            "provider": f.get("provider", "simulated"),
            "synthetic": bool(f.get("synthetic", True)),
        }

        if post_url and not dry_run:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(post_url, data=body, headers=hdrs,
                                         method="POST")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    sent += 1
                    if verbose and resp.status >= 400:
                        print(f"  !! {resp.status} on fix {i}")
            except urllib.error.HTTPError as e:
                failed += 1
                if verbose and failed <= 5:
                    print(f"  !! HTTP {e.code} on fix {i}: {e.reason}", file=sys.stderr)
            except Exception as e:                      # noqa: BLE001
                failed += 1
                if verbose and failed <= 5:
                    print(f"  !! {type(e).__name__} on fix {i}: {e}", file=sys.stderr)
        else:
            if dry_run or not post_url:
                sent += 1
                if verbose:
                    print(json.dumps(payload))

        # pace to wall clock
        target = t_start + (f["t"] / speed)
        wait = target - time.time()
        if wait > 0:
            time.sleep(wait)

    elapsed = time.time() - t_start
    return {"sent": sent, "failed": failed, "elapsedSeconds": round(elapsed, 2),
            "postUrl": post_url, "dryRun": dry_run or not post_url}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="synthesise a CBD parking-search drive")
    g.add_argument("--minutes", type=float, default=10.0)
    g.add_argument("--seed", type=int, default=1337)
    g.add_argument("--hz", type=float, default=1.0, help="fixes per second")
    g.add_argument("--out", default="fixtures", help="output directory")
    g.add_argument("--no-noise", action="store_true")
    g.add_argument("--no-dropouts", action="store_true")
    g.add_argument("--no-accuracy-spikes", action="store_true")
    g.add_argument("--no-park", action="store_true",
                   help="omit the final park-and-stationary-jitter phase")
    g.add_argument("--park-seconds", type=float, default=90.0)

    r = sub.add_parser("replay", help="stream a generated trace to your app")
    r.add_argument("--fixtures", default="fixtures", help="dir containing trace.jsonl")
    r.add_argument("--trace", default=None, help="explicit trace.jsonl path")
    r.add_argument("--post-url", default=None, help="your app's GPS ingest endpoint")
    r.add_argument("--speed", type=float, default=1.0,
                   help="replay multiplier (1 = real time, 10 = 10x)")
    r.add_argument("--device-id", default="pte-sim-device")
    r.add_argument("--header", action="append", default=[],
                   help='extra header "Name: Value", repeatable (e.g. auth token)')
    r.add_argument("--dry-run", action="store_true", help="print instead of POST")
    r.add_argument("--quiet", action="store_true")

    x = sub.add_parser("from-gpx", help="replay a REAL recorded GPX trace")
    x.add_argument("--gpx", required=True)
    x.add_argument("--post-url", default=None)
    x.add_argument("--speed", type=float, default=1.0)
    x.add_argument("--device-id", default="pte-gpx-device")
    x.add_argument("--header", action="append", default=[])
    x.add_argument("--dry-run", action="store_true")
    x.add_argument("--quiet", action="store_true")
    x.add_argument("--out", default=None, help="also re-write as fixtures")

    args = ap.parse_args()

    if args.cmd == "generate":
        fixes, meta = synth_trace(
            minutes=args.minutes, seed=args.seed, hz=args.hz,
            noise=not args.no_noise, dropouts=not args.no_dropouts,
            accuracy_spikes=not args.no_accuracy_spikes,
            park_at_end=not args.no_park, park_seconds=args.park_seconds)
        stamp(fixes)
        paths = write_fixtures(fixes, meta, args.out)
        print("=" * 70)
        print("PTE GPS TRACE GENERATED — SYNTHETIC, APPROXIMATE GEOMETRY")
        print("=" * 70)
        print(f"  points      : {len(fixes)}")
        print(f"  duration    : {fixes[-1]['t']:.0f}s ({args.minutes} min target)")
        print(f"  rate        : {args.hz} Hz")
        print(f"  seed        : {args.seed}  (reproducible)")
        phases = {}
        for f in fixes:
            phases[f["phase"]] = phases.get(f["phase"], 0) + 1
        print(f"  phases      : {phases}")
        print(f"  bboxes      : lat [{min(f['trueLat'] for f in fixes):.5f}, "
              f"{max(f['trueLat'] for f in fixes):.5f}]  "
              f"lon [{min(f['trueLon'] for f in fixes):.5f}, "
              f"{max(f['trueLon'] for f in fixes):.5f}]")
        for label, p in zip(("JSONL", "GeoJSON", "GPX", "META"), paths):
            print(f"  {label:<9} : {p}")
        print("-" * 70)
        print(SYNTHETIC_NOTE)
        print("=" * 70)

    elif args.cmd == "replay":
        trace_path = args.trace or os.path.join(args.fixtures, "trace.jsonl")
        if not os.path.exists(trace_path):
            raise SystemExit(f"no trace at {trace_path}; run `generate` first")
        fixes = stamp(load_jsonl(trace_path))
        hdrs = dict(h.split(":", 1) for h in args.header) if args.header else None
        hdrs = {k.strip(): v.strip() for k, v in (hdrs or {}).items()}
        print(f"[replay] {len(fixes)} fixes -> {args.post_url or 'STDOUT (dry run)'} "
              f"at x{args.speed}")
        res = replay(fixes, post_url=args.post_url, speed=args.speed,
                     dry_run=args.dry_run, device_id=args.device_id,
                     headers=hdrs, verbose=not args.quiet)
        print(f"[replay] done: sent={res['sent']} failed={res['failed']} "
              f"elapsed={res['elapsedSeconds']}s")
        if res["failed"]:
            sys.exit(1)

    elif args.cmd == "from-gpx":
        fixes = stamp(load_gpx(args.gpx))
        print(f"[from-gpx] {len(fixes)} recorded trackpoints from {args.gpx}")
        if args.out:
            paths = write_fixtures(fixes, {"source": args.gpx, "synthetic": False},
                                   args.out)
            print(f"[from-gpx] re-written to {paths[0]}")
        hdrs = {k.strip(): v.strip()
                for k, v in (dict(h.split(":", 1) for h in args.header) or {}).items()}
        res = replay(fixes, post_url=args.post_url, speed=args.speed,
                     dry_run=args.dry_run, device_id=args.device_id,
                     headers=hdrs or None, verbose=not args.quiet)
        print(f"[from-gpx] done: sent={res['sent']} failed={res['failed']} "
              f"elapsed={res['elapsedSeconds']}s")


if __name__ == "__main__":
    main()
