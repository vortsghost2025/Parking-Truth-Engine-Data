# PTE Real-Time Test Rig

**Synthetic. Not real parking data. Never show this to an end user as real availability.**

Two stdlib-only Python tools that let you prove the real-time plumbing works
**today**, without waiting on any municipal data agreement.

```
sim_feed.py     a live availability feed shaped like a real sensor network
gps_replay.py   a moving GPS position stream shaped like a real device
```

No dependencies. Python 3.8+. Nothing to `pip install`.

---

## Why this exists

The question was *"can I test whether the GPS part of my app works in real time?"*

That question does **not** need real parking data. It needs two live streams:

1. a **position** stream — where the car is, changing every second
2. an **availability** stream — which bays are free, changing every few seconds

Both are synthesised here. Real Hobart data does exist, but it is gated — see
[`docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md`](../../docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md)
for the full source preflight, including the finding that
`parking-occupancy.hobartcity.com.au` is **live and 1-second fresh** while
`parkmyride.au` sits behind a WAF and both are covered by
*"may not reuse or republish ... without written consent from the City."*

So: test the plumbing against this rig, and run the consent conversation in
parallel. Do not let the second block the first.

---

## Quickstart

```bash
cd tools/realtime-sim

# 1. Start the synthetic availability feed (binds 0.0.0.0 so proxies/previews work)
python3 sim_feed.py --port 8090 --speed 20

# 2. In another terminal, generate a parking-search drive
python3 gps_replay.py generate --minutes 10 --seed 7 --out fixtures

# 3. Stream it into YOUR app's GPS ingest endpoint at real-time speed
python3 gps_replay.py replay --fixtures fixtures \
    --post-url https://YOUR-HOSTINGER-APP/api/gps

# 4. Watch the feed move
curl -s http://localhost:8090/api/snapshot.json | python3 -m json.tool
curl -N http://localhost:8090/stream          # Server-Sent Events
```

`--speed 20` runs simulated time 20× faster than wall clock, so a lunchtime
saturation scenario unfolds in minutes instead of hours. `--sim-start 08:30`
starts the clock at a specific Hobart local time.

---

## `sim_feed.py` — endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/meta.json` | config, seed, counts, disclaimer, the legality/availability separation note |
| `GET /api/health` | **PTE-shaped source-health record**: `state`, coverage, fault rate, `DEGRADED` transitions |
| `GET /api/bays.geojson` | all bays + live status as GeoJSON `FeatureCollection` |
| `GET /api/carparks.json` | off-street occupancy: **real cited capacities**, synthetic counts |
| `GET /api/snapshot.json` | everything in one round trip, plus per-street rollup and recent events |
| `GET /api/bay/<bay_id>` | single bay detail incl. `occupiedSince` and `overstayed` |
| `GET /stream` | **Server-Sent Events**: `arrival` / `departure` / `sensor_fault` / `sensor_recovered` |
| `GET /healthz` | liveness probe |

Every response carries `"synthetic": true`, a `disclaimer`, and an
`X-PTE-Synthetic: true` header, so a stray test feed can never be mistaken for
production data downstream. CORS is open (`*`) for local testing.

Bay status vocabulary: `FREE`, `OCCUPIED`, `RESTRICTED`, `UNKNOWN`.
Car-park availability vocabulary matches the frontend contract exactly:
`HIGH`, `LIMITED`, `UNKNOWN` — and **`UNKNOWN` is reachable**, via a stale feed,
never as a synonym for "full".

Default tick is **15 s**, matching the published Park My Ride sensor cadence.
Off-street uses **60 s**, matching the published dashboard cadence.

### Flags

| Flag | Purpose |
|---|---|
| `--port` / `--host` | bind address (default `0.0.0.0:8090`) |
| `--tick SECONDS` | sensor tick interval |
| `--speed N` | simulated-time multiplier |
| `--seed N` | **reproducible** RNG — same seed, same scenario |
| `--sim-start HH:MM` | start the clock at a given Hobart local time |
| `--bays-per-block N` | override bay density |

Scenarios worth running deliberately:

```bash
python3 sim_feed.py --sim-start 12:30 --speed 30     # retail peak saturation
python3 sim_feed.py --sim-start 03:00 --speed 30     # overnight: mostly UNKNOWN/empty
python3 sim_feed.py --seed 5 --tick 0.2 --speed 60   # fast-forward to force faults + stale feeds
```

Saturday 08:00–15:00 adds a Salamanca Market spike, which is the realistic
worst case for Hobart.

---

## `gps_replay.py` — modes

```bash
generate    synthesise a CBD "cruising for a park" drive -> GPX + GeoJSON + JSONL
replay      stream a generated trace to your ingest URL at wall-clock speed
from-gpx    replay a REAL recorded trace (e.g. an OpenStreetMap public GPS trace)
```

### The POST payload

Deliberately mirrors what a browser `navigator.geolocation.watchPosition`
callback gives you, so an ingest endpoint written for real devices works
unchanged:

```json
{
  "deviceId": "pte-sim-device",
  "lat": -42.8829467,
  "lon": 147.3222219,
  "accuracyM": 5.7,
  "altitudeM": 6.5,
  "speedMs": 2.07,
  "speedKmh": 7.5,
  "bearingDeg": 200.1,
  "phase": "junction",
  "timestampUtc": "2026-09-12T18:56:34.648Z",
  "epochMs": 1789239394648,
  "provider": "simulated",
  "synthetic": true
}
```

Auth headers are supported and repeatable:

```bash
python3 gps_replay.py replay --fixtures fixtures \
  --post-url https://YOUR-APP/api/gps \
  --header "Authorization: Bearer XYZ" \
  --header "X-Device-Id: test-1"
```

`replay` exits non-zero if any POST failed, so it drops straight into CI.

### GPX for device simulators

`generate` writes `fixtures/trace.gpx`, which works as a mock-location file:

- **Android Studio emulator** → Extended Controls → Location → Routes → load GPX
- **Xcode** → Debug → Simulate Location → GPX File
- **adb** → `adb emu geo fix <lon> <lat>` per point
- **QGIS / geojson.io** → drop in `trace.geojson` to eyeball the route

That is how to test the *client* side. `replay --post-url` tests the *server*
side. Do both — they fail differently.

### Realism features (each individually switchable)

| Feature | Models | Disable with |
|---|---|---|
| Gaussian position noise scaled by accuracy | ordinary GPS error | `--no-noise` |
| Accuracy degradation at low speed / urban canyon | multipath between CBD buildings | `--no-accuracy-spikes` |
| Rare ~10× accuracy spikes and backwards drift | the "GPS says I'm in the Derwent" fix | `--no-accuracy-spikes` |
| Random dropped fixes (~1.5%) | tunnels, under a car-park deck | `--no-dropouts` |
| Final decelerate → stop → stationary jitter | actually parking | `--no-park` |
| Phase labels | ground truth for cruising detection | — |

**Phase labels** (`driving` / `searching` / `junction` / `manoeuvre` / `parked`)
are ground truth. `searching` is a 2.6–5.8 m/s block — the signature of someone
hunting for a bay. That lets a cruising-detection heuristic be developed and
*measured* against labelled truth before a single real user exists.

Each fix also carries `trueLat` / `trueLon` alongside the noisy `lat` / `lon`, so
you can compute actual positioning error rather than guessing.

---

## Failure modes this rig reproduces on purpose

These are the ones that break real integrations, and the ones the PTE contract
has to survive:

| Injected failure | Expected correct behaviour |
|---|---|
| Bay has no sensor | status `UNKNOWN` — **never** an inferred `FREE` |
| Sensor present but faulted | `sensorOk: false`, `UNKNOWN`, `source-health` → `DEGRADED` |
| Car-park counter feed goes stale | `availability: UNKNOWN`, not a confident stale number |
| All counters read zero overnight | Must not render "780 available" — see finding **H1-F2** |
| GPS dropout / accuracy spike | Client should not teleport or drop the track |
| `overstayed: true` on an occupied bay | Availability flags it; **legality is not inferred from it** |
| `restriction` present on a bay | Inventory metadata only — must **not** map to `ALLOWED`/`PROHIBITED` |

That last row is the architectural invariant from `README.md`: *occupancy never
determines legality*. This rig exists partly so you can write the regression test
that `PROHIBITED + HIGH availability` stays prohibited while a live feed is
actually moving underneath it.

---

## Geometry provenance — read this

The street skeleton in both files is a **hand-authored approximation** of the
Hobart CBD, ~12 streets, vertices placed to roughly the right shape and scale.
It is **not** survey data, **not** derived from any council source, and the bay
IDs (`SIM-HBT-nnnnn`) are invented.

Consequences:

- Fine for testing GPS handling, map rendering, refresh cadence, event streams,
  and error paths.
- **Not** fine for testing sign-to-curb attachment, curb-span legality, or
  anything where geometry accuracy is the thing under test. Per `README.md`,
  *"No spatial guessing for legal rules."*
- For real geometry use the City of Hobart ArcGIS layers — see finding **H4** in
  the preflight doc. The organisation exists (`hobartcc.maps.arcgis.com`); the
  specific service URLs still need capturing from a normal network.

Off-street **capacities** are the exception: those are real and cited (City of
Hobart media release, 2025-09-01). The **counts** against them are synthetic.

---

## Verified working

Both tools were exercised in the session that added them:

- all endpoints respond; `FREE` / `OCCUPIED` / `UNKNOWN` / `RESTRICTED` all occur
- a stale counter feed produced `availability: UNKNOWN` for one car park
- injected sensor faults produced `faultedSensors: 2` with `source-health: FRESH`
  (below the `DEGRADED` threshold, as designed)
- a 2.7-simulated-hour run produced 76 `overstayed` bays
- unknown `bayId` returns HTTP 404
- GPS replayer streamed 387 fixes: `sent=387 failed=0`, correct wall-clock pacing
  at ×1, ×20 and ×60
- SSE stream emits named events plus keepalive comments

---

## Storage note

Generated `fixtures/` output is reproducible from a seed and is not evidence, so
it should not accumulate in Git. If a particular trace becomes evidence for a
specific finding, preserve it under `sources/` or `evidence/` with a hash and a
record in `manifests/`, per the repository storage policy.
