# Parking Truth Engine — Data & Evidence Repository

> **Private internal project repository.**
>
> This repository is the evidence and reproducibility vault for **Parking Truth Engine (PTE)**. It preserves the source records, manifests, schemas, benchmark outputs, and research artifacts needed to explain and reproduce PTE findings without turning the development machine—or Git itself—into bulk data storage.

## What Parking Truth Engine is

Parking Truth Engine is an evidence-first parking platform built around two separate questions:

1. **Legality — “Can I legally park here for this entire requested time?”**
2. **Availability — “Is there likely to be an open space nearby?”**

Those questions are intentionally independent. A space can be vacant and still illegal to use. Availability can help rank legal options, but it can never turn an illegal, conflicted, or unknown curb into a legal one.

The goal is not another parking map that colors every street with unsupported certainty. PTE is designed to show **what the system knows, why it believes it, how fresh the evidence is, where sources disagree, and where the evidence is incomplete**.

> **Evidence wins. False certainty does not.**

## Why this project exists

Parking information is fragmented across municipal signage, paid-parking systems, roadworks, snow-removal restrictions, occupancy sensors, historical datasets, cameras, and future user/mesh signals. No single source describes the whole truth.

PTE combines those sources through a common evidence model and deterministic rule engine while retaining provenance. When the evidence is incomplete, PTE can return **UNKNOWN**. When equally authoritative evidence disagrees about the same claim, PTE can return **CONFLICT** instead of silently choosing a winner.

## Core principles

### Evaluate the whole requested interval

A curb that is legal at arrival can become illegal before the driver plans to leave. PTE evaluates the complete requested parking interval rather than checking only the arrival moment.

### Fail closed when evidence is incomplete

If a material part of the requested interval is not covered by trustworthy evidence, the result is **UNKNOWN**, not assumed legal.

### Preserve provenance

Important conclusions remain traceable to their source record, retrieval time, effective period, hash, and authority class.

### Keep conflicts visible

Same-claim disagreement is recorded as **CONFLICT** with the underlying evidence retained. It is not averaged away.

### Keep legality and availability separate

Occupancy, cameras, historical prediction, mesh signals, and future sensors may help determine whether parking is probably available. They do **not** determine whether it is legal.

### No spatial guessing for legal rules

A nearby sign is not automatically assumed to govern a curb. Sign-to-curb and source-to-segment attachment must be supported by authoritative keys, documented municipal methodology, or another reproducible rule. Otherwise the legality result remains UNKNOWN.

## Repository purpose

This repository is the **data/evidence companion** to the application code. It contains or is intended to contain:

- source manifests and source-health records
- exact source URLs and retrieval timestamps
- SHA-256 hashes for reproducibility
- small or version-sensitive source snapshots
- schemas and field profiles
- join and coverage evidence
- bounded source samples
- benchmark outputs
- camera/occupancy research artifacts worth preserving
- city-specific research records
- documentation separating PROVEN, PARTIAL, UNKNOWN, and BLOCKED findings

Large public datasets that can be reproduced from an authoritative source generally **should not** be repeatedly stored as Git blobs. For those sources, the preferred record is:

`source URL + retrievedAt + byte size + SHA-256 + schema/profile + licence/reuse metadata`

That keeps the project reproducible without turning Git into bulk object storage.

## Repository structure

```text
sources/
  montreal/           exact source snapshots where version preservation matters
  hobart/             City of Hobart live-feed observations (raw + structured)

evidence/
  camera/             derived camera benchmark outputs
  montreal/           Montréal source/preflight evidence

manifests/             hashes, inventories, reproducible-source references
schemas/               dataset schema/profile records
docs/                  architecture, storage, status, and owner-review documentation
tools/
  realtime-sim/        synthetic live availability feed + GPS trace replayer
                       (test rig only; NOT real parking data)
  telemetry/           harvester for REAL parking arrival/departure telemetry
                       (historical archives + live snapshot-diffing)
                       + Little's Law simulator calibrator
  inference/           availability inference engine — calibrated P(free) from
                       whatever evidence exists, with honest uncertainty
```

Existing storage/migration documentation is preserved in `docs/PTE-LOCAL-EVIDENCE-INVENTORY.md`.

## Where the code lives

This repository is **not** the primary application code repository.

During active development the code is split into two workspaces:

- **Core / evidence / rule engine:** `S:\Parking-Truth-Engine`
- **Frontend application:** `S:\Parking-Truth-Engine-App`

The frontend is deliberately separated from the rule kernel. The UI consumes a typed contract; it does not duplicate legal decision logic.

## Architecture at a glance

```text
Municipal / public / verified sources
              │
              ▼
        Raw evidence layer
              │
              ▼
     Source-specific adapters
              │
              ▼
  Normalized evidence / ParkingRule
              │
              ▼
   Deterministic legality kernel
              │
              ├──────────────► Evidence / Why / provenance
              │
              ▼
        Legality verdict
              │
              │       Availability evidence
              │       sensors / mesh / history / camera
              │                 │
              ▼                 ▼
         Legality gate      Availability rank
              │                 │
              └────────┬────────┘
                       ▼
              Parking search UI
```

Availability may rank candidates only **after** legality is established. It cannot upgrade `PROHIBITED`, `CONFLICT`, or `UNKNOWN` into `ALLOWED`.

## Normalized legality verdicts

The deterministic rule kernel supports:

- `ALLOWED`
- `ALLOWED_PAID`
- `TIME_LIMITED`
- `PERMIT_REQUIRED`
- `PROHIBITED`
- `SPECIAL_USE_ONLY`
- `CONFLICT`
- `UNKNOWN`

`ALLOWED_PAID` means payment is required; it does not mean payment has actually been made.

## Reliability and source health

Source freshness is tracked separately from the legal conclusion. Current source-health states include:

- `FRESH`
- `STALE`
- `DEGRADED`
- `UNAVAILABLE`

A successful network request does not automatically mean the evidence itself is current, and restored cached evidence retains its original timestamps.

## Current source/city work

### Montréal

The Montréal legality lane currently studies four major source categories:

- on-street parking signage / RPA codification
- Agence de mobilité durable paid-parking regulations and periods
- Info-travaux roadwork / obstruction data
- snow-operation parking information

A central unresolved question is how a geolocated sign post and its arrow code attach to the exact curb span governed by that sign without guessing. Until that relationship is proven from authoritative documentation or keys, affected curb legality remains UNKNOWN.

### Melbourne

Melbourne is used as an early software/data laboratory because it provides strong public occupancy, geometry, and historical parking datasets. Exact occupancy-to-geometry joins have been proven; some rule joins remain unresolved.

Two findings materially raise Melbourne's role (PTE-TEL-001):

**Real parking-event telemetry at scale.** The City of Melbourne publishes historical archives where each row is one real parking event with arrival time, departure time, duration, restriction and overstay flag — **≈246 million rows across 2014–2020**, CC-BY licensed. That is ground-truth occupancy transition telemetry rather than a proxy, so the availability lane does not need to *generate* data in order to be tested at realistic volume.

**A documented sign-to-curb attachment chain.** Melbourne publishes `sign-plates-located-in-each-parking-zone` and `parking-zones-linked-to-street-segments`, with documented join keys `marker_id` (sensors↔bays) and `bay_id` (sensors↔restrictions). That is precisely the "authoritative keys / documented municipal methodology" this README says would resolve sign-to-curb attachment — the same question currently blocking Montréal PTE-007. Melbourne is therefore a worked template for what to request from Montréal, and a candidate **legality**-lane city rather than only an availability laboratory. The publisher states that bays↔bay-restrictions do **not** currently join, so no transitive path may be assumed.

The publisher also documents four defects in its own archives: negative durations from arrival-detected-after-departure sensor faults, times imputed from midnight when not recorded, restrictions suffixed `OLD` where the rule changed after the event or the sensor was replaced, and year-boundary truncation of events crossing 31 December. These are counted and flagged, never silently coerced, and they are why the telemetry schema carries a `timeConfidence` field separating `OBSERVED` from `IMPUTED` from `DERIVED`.

See [`docs/REAL-PARKING-TELEMETRY-SOURCES.md`](docs/REAL-PARKING-TELEMETRY-SOURCES.md) and [`tools/telemetry/`](tools/telemetry/).

### The availability inference layer

The differentiator is **not** relaying sensor feeds. Dozens of apps already do
that in every city that publishes one, and most cities publish nothing at all. A
product that only works where a municipal feed exists works in a handful of
places.

The differentiator is inference: fuse every scrap of evidence that exists —
historical archives, static bay inventory, restriction metadata, time-of-day
patterns, and live sensors where available — into a **calibrated probability
that a space is free**, with an honest interval, on streets nobody has ever
instrumented.

[`tools/inference/availability_engine.py`](tools/inference/availability_engine.py)
implements this and, critically, **scores itself against reality it never saw**.
Validation holds out whole *dates* (never rows — rows from one day share weather
and demand, so random splitting leaks and inflates every score).

Measured on a 306,582-event archive, 240 cells, 36 dates trained / 9 held out:

| Metric | Value |
|---|---|
| Brier skill score vs a constant predictor | **+0.989** |
| Mean absolute error on P(free) | **0.018** (±2 points) |
| 95% interval coverage | **0.971** (target ~0.95) |
| Worst reliability-bin gap | 0.024 |

Every reliability bin lands within 2.4 points of observed. And the confidence
label predicts its own accuracy — `HIGH` cells score MAE 0.008 against `LIMITED`
at 0.022 — so the tier carries information rather than being decoration.

Three findings shaped the implementation, all caught by validation rather than
by reading the code:

- **The denominator is the trap.** An archive only records bays that were
  *occupied*; the empty slots are exactly what is missing. They must be rebuilt
  from `bays × dates × slots_per_hour`. Counting only observed slots silently
  pins P(occupied) at 1.0 and reports "no space anywhere, ever".
- **Bay-slots are not independent trials.** One event covers many consecutive
  slots. The overdispersion factor φ is *measured* from between-date variance
  (1.0 – 140.3 across cells, median 4.7), not assumed.
- **Two uncertainties, not one.** A Beta posterior reports how well a cell's
  *average* is known. The product must predict a *future day*, which also needs
  the measured day-to-day dispersion. Adding the two in quadrature moved
  coverage from 0.30 to 0.97; measured day-to-day SD (0.033) dominates
  estimation SD (0.009) by ~4×, so the posterior alone was ~4× too confident.

Where evidence is thin the engine degrades instead of guessing: a street with no
observations returns `UNKNOWN` on the city prior, and where dispersion cannot be
measured the interval falls back to a conservative floor rather than collapsing
to zero. A 2-date, 160-slot cell was publishing `HIGH` with CI `[0.637, 0.766]`;
it now publishes `UNKNOWN` with `[0.495, 0.908]`.

This remains the **availability lane only**. Nothing here makes an illegal,
conflicted or unknown curb legal.

See [`tools/inference/README.md`](tools/inference/README.md).

### Los Angeles

Los Angeles provides a second-city control case with exact `spaceid` occupancy/inventory joins and helps prove the shared adapter architecture is not Melbourne-specific.

### Hobart (Tasmania)

Hobart is a source-preflight case, not yet an adapter lane. The working
assumption that no live parking data exists there was **disproven**: the City of
Hobart operates in-ground sensors across the CBD, Midtown, North Hobart and
Salamanca with a 15-second refresh, published at `parkmyride.au` since
2025-09-01, plus a 60-second off-street occupancy dashboard.

The real blockers are access terms and API shape, not data existence:

- the occupancy dashboard was **verified live and one-second fresh** in this
  repository (`sources/hobart/occupancy-snapshot/`)
- `parkmyride.au` sits behind a WAF and refuses programmatic access
- the City prohibits reuse/republishing **without written consent**
- sensor coverage is **partial by design**, and non-sensored bays remain
  enforceable, which keeps legality independent of coverage

Two availability findings are recorded unresolved: a same-authority **capacity
CONFLICT** between the dashboard and the council's own media release, and an
**all-zero counter** that cannot be distinguished from a facility closed
overnight — a concrete false-certainty trap.

See [`docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md`](docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md)
and `manifests/hobart-availability-sources-manifest.json`.

### Camera lane

The camera research lane is currently **frozen** at `CAMERA_FIXED_VIEW_PARTIAL`. Archived Montréal imagery showed vehicle detection plus fixed ROI association is technically plausible, but live access, geo-alignment, and broad fixed-view coverage remain unresolved. Camera evidence is therefore an optional **availability** input, not a core dependency.

## Current engineering checkpoint

At the latest reviewed checkpoint:

- deterministic parking rule kernel implemented
- whole-interval evaluation implemented
- fail-closed `UNKNOWN` implemented
- same-precedence conflict preservation implemented
- occupancy structurally excluded from legality evaluation
- IANA timezone handling added
- `America/Toronto` DST regression coverage added
- ordinary core test command: **126/126 passing**
- Montréal PTE-007 translation/source-coverage study in progress
- separate Next.js/TypeScript/MapLibre frontend shell built with mock data only
- frontend typecheck and production build reported passing
- camera lane frozen pending new external evidence

These are development-status notes, **not** a claim that Montréal curb verdicts are production-ready.

## Frontend concept

The frontend is map-first and explainability-first. A selected curb can show:

- legality verdict
- requested parking interval
- “Why?” explanation
- applicable rules
- source names
- source timestamps
- freshness and reliability
- conflicts
- payment requirements
- maximum stay
- restrictions/exceptions
- evidence/provenance

The UI intentionally keeps **LEGALITY** and **AVAILABILITY** visually separate.

Example states include:

- legal + likely available
- legal + availability unknown
- paid parking
- time-limited parking
- prohibited parking
- conflicting authoritative evidence
- unknown because evidence is incomplete
- prohibited + vacant

That last state is intentional: **vacant does not mean legal**.

## Data and storage policy

The development machine is storage constrained, so PTE follows a remote-evidence policy:

- preserve small, unique, or version-sensitive evidence remotely
- preserve hashes/manifests for large reproducible public datasets
- avoid keeping large public archives permanently on the development machine
- verify remote preservation or reproducibility records before deleting local bytes
- never delete source code or unique hand-authored evidence as part of data cleanup
- keep legality evidence and availability evidence separate

This private repository is intended to be the canonical off-PC evidence store for that policy.

## For the owner / stakeholder reviewer

You do not need to understand every TypeScript function or municipal dataset to review the project effectively. Start with these questions:

1. **Does the system explain why it reached a parking result?**
2. **Can the result be traced back to real evidence?**
3. **Does it admit UNKNOWN when evidence is incomplete?**
4. **Does occupancy remain separate from legality?**
5. **Do tests cover boundary times, overnight rules, DST, conflicts, and missing evidence?**
6. **Can a new city be added through adapters without rewriting the core rule engine?**
7. **Does the UI make uncertainty understandable instead of hiding it?**

See [`docs/OWNER_REVIEW_GUIDE.md`](docs/OWNER_REVIEW_GUIDE.md) for a plain-language walkthrough.

Additional documentation:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/PTE-LOCAL-EVIDENCE-INVENTORY.md`](docs/PTE-LOCAL-EVIDENCE-INVENTORY.md)
- [`docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md`](docs/HOBART-AVAILABILITY-SOURCE-PREFLIGHT.md)
- [`docs/REAL-PARKING-TELEMETRY-SOURCES.md`](docs/REAL-PARKING-TELEMETRY-SOURCES.md)
- [`schemas/parking-telemetry-event-schema.json`](schemas/parking-telemetry-event-schema.json)
- [`tools/realtime-sim/README.md`](tools/realtime-sim/README.md)
- [`tools/telemetry/README.md`](tools/telemetry/README.md)
- [`tools/inference/README.md`](tools/inference/README.md)

## Safety and scope

PTE is under active development. Machine-derived parking verdicts are not yet a substitute for physical signage or official instructions. Real-city integration remains gated on source verification, measured coverage, and human review.

The project intentionally prefers a cautious UNKNOWN result over an unsupported “legal to park” claim.

## Repository visibility

This repository is **PRIVATE** and intended for internal project use, owner review, and reproducibility of the PTE research/evidence layer.

---

**Parking Truth Engine**  
**Evidence first. Explainable by design. Legality before availability.**
