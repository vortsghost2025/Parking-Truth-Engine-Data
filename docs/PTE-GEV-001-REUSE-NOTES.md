# PTE-GEV-001 — God's Eye View reuse notes and bounded next ticket

Status: **READ-ONLY ARCHITECTURE REVIEW COMPLETE; NO GEV CODE IMPORTED**

Revision: **rev 2 (2026-09-13)** — fail-closed correction to CCTV source-acquisition state and to Camden study-area scope. Rev-1 content is preserved except where a rev-2 amendment explicitly contradicts it; **where they conflict, the amendment governs.**

## Upstream review pinning [F]

The reviewed upstream is pinned to an exact revision. Do not cite this review against a moving `main`.

| Field | Value |
|---|---|
| Repository | `bilawalsidhu/gods-eye-view` |
| Commit | `2213c42200d7126dc5385b3801efcdda83928d0c` |
| Version | `0.1.1` |
| Code license | **MIT** (code only) |
| Data/provider terms | **Separate.** The MIT grant does not cover third-party datasets, provider content, imagery, models, or API terms. |

Rev-1 said "current `main` during the 2026-09-13 session"; that wording is superseded by the pin above.

## Reuse decision

Do **not** fork or merge the whole God's Eye View application into Parking Truth Engine. Reuse/adapt only bounded architecture and provider modules where they reduce implementation cost without weakening PTE truth semantics.

### Highest-value pieces

1. **TfL/Austin/Caltrans CCTV provider pattern**
   - server-side normalized camera catalog
   - independent provider failures
   - dedupe and source caps
   - cache/single-flight refresh
   - **[A] CORRECTED — serve-stale is NOT reusable on any PTE evidence path.** Rev-1 listed "serve-stale behavior instead of blanking the layer" as reusable. That recommendation is withdrawn for evidence-bearing use; see §A. Serve-stale remains acceptable only for UI continuity under the labelling rule in §A.
   - fixed/official upstream host validation
2. **CCTV browser layer/source separation**
   - source acquisition separated from rendering
   - injected services for terrain, picking, overlays, focus and rendering
   - useful seam for PTE camera evidence without coupling it to the legality kernel
3. **Traffic provider/source pattern**
   - bounded OSM/Overpass road requests
   - optional provider-backed traffic flow
   - server-side provider boundary rather than arbitrary browser fetches
   - **[A]** single-flight and the budget governor are reusable; the serve-stale half of the same file is not (see §A, §E).
4. **Attribution/provenance pattern**
   - per-layer data attribution
   - dynamic credit activation when a provider actually activates
   - explicit separation between MIT code and third-party data/provider terms
5. **Server-side key/proxy security pattern**
   - secret-bearing API keys remain server-side
   - browser receives constrained same-origin endpoints or short-lived tokens
   - no arbitrary upstream URL relay
   - request caps/timeouts/sanitized errors
6. **Voice tool pattern, later only**
   - fixed enumerated app-control tools rather than arbitrary execution
   - PTE voice, if added, must invoke bounded UI/query operations and must never compute or override parking verdicts itself

## PTE semantic boundary

GEV is an exploratory visualization product. PTE remains provenance-first and fail-closed.

Do not import assumptions that a visually plausible or live-looking feed is ground truth.

For PTE:

- legality and availability remain separate
- camera evidence is evidence, not automatic occupancy truth
- physical signage remains final authority for legality
- each source keeps provenance, retrieval time, source terms, freshness and reliability
- UNKNOWN is preferable to a fabricated precise answer

**[A] The boundary above is enforced in code, not only in prose.** GEV's provider layer encodes failure as an empty success; §A records the exact composition and the PTE rule that replaces it. A fail-closed posture that cannot distinguish "source down" from "source empty" is not fail-closed.

---

## A. Failure-state rule — explicit provider acquisition state (LOAD BEARING)

### The exact GEV composition at the pinned SHA

Two independent mechanisms compose into a single indistinguishable outcome:

**1. The TfL loader encodes every failure as an empty success.** In `server/providers/cctv/sources.js`, `loadTflSourcesFromOpenData()` returns `[]` on three distinct paths:

| Condition | Location |
|---|---|
| HTTP response not ok | `sources.js:271` → `return []` at `:273` |
| Payload present but not an array (malformed) | `sources.js:276` |
| Any caught exception (network, timeout, DNS) | `sources.js:332` → `return []` at `:334` |

`[]` is therefore simultaneously "TfL reports zero available cameras" and "we could not reach TfL."

**2. The catalog treats an empty refresh as a reason to serve the previous catalog.** In `server/providers/cctv/catalog.js`:

- `catalog.js:95` — "good prior catalog it serves stale rather than blanking the CCTV layer"
- `catalog.js:173` — `` `[CCTV] source refresh returned empty; serving ${_cctvSourceCache.length} stale cameras` ``

**Composed effect:** TfL fetch fails → `[]` → catalog reads "empty" → serves the previously cached camera list → layer renders populated. **Empty, current, stale, and unavailable collapse into one visually populated result.** This is deliberate and correct for an exploratory visualization product ("last-good data beats a dead layer", `server/providers/traffic.js:19-24`). It is not acceptable for an evidence inventory whose deliverable is a *count*.

### PTE rule

**The PTE adapter MUST return explicit acquisition state. It MUST NOT encode failure as `[]`.**

Required provider result vocabulary, at minimum:

| State | Meaning |
|---|---|
| `CURRENT` | Fresh successful acquisition; source reachable and returned usable records |
| `EMPTY_CURRENT` | Fresh successful acquisition; source reachable and legitimately returned **zero** usable records |
| `SOURCE_UNAVAILABLE` | Acquisition failed — HTTP error, malformed payload, timeout, or exception |
| `STALE` | Serving a previously successful acquisition because the current one failed |
| `CANCELLED` | Acquisition aborted by caller authority before completion |

`EMPTY_CURRENT` and `SOURCE_UNAVAILABLE` must never be representable by the same value. That distinction is the entire point of the rule.

Every result must carry:

- `retrievedAt`
- source-supplied timestamp, when the source provides one
- `staleSince` / `lastSuccessfulAt`, when state is `STALE`
- `reason` / error class, when state is `SOURCE_UNAVAILABLE`
- **catalog total before area filtering**
- **kept count after area filtering**

### Stale-data rule

Stale data may be retained for UI continuity **only if visibly labelled `STALE`**.

It **MUST NOT** silently satisfy the Camden camera-count, coverage, or evidence-inventory acceptance criteria.

Specifically:

- a source outage must never be reported as "0 cameras"
- stale cameras must never be reported as a fresh count

### Prior art already inside GEV

GEV's own layer manager has the stronger vocabulary the provider layer lacks — `src/data/manager.js:443`:

```
'found' | 'missing' | 'source-unavailable' | 'cancelled' | 'superseded' | 'destroyed'
```

and returns status paired with an explicit reason at `manager.js:401` (`{ status: 'unavailable', reason: 'layer-unavailable' }`). The PTE adaptation is to **port that principle down into the provider**, not to invent a new one. Borrowing the principle from GEV's manager while rejecting GEV's provider behaviour is internally consistent, because GEV itself is inconsistent between those two layers.

---

## B. Camden study-area predicate (LOAD BEARING)

### What the reviewed GEV adapter actually does

| Property | Value at pinned SHA |
|---|---|
| Endpoint | `https://api.tfl.gov.uk/Place/Type/JamCam` (`constants.js:25`) — **whole-London catalog**, not an area query |
| Default cap | `DEFAULT_TFL_MAX_SOURCES = 250` (`constants.js:28`) |
| Prioritization anchor | `LONDON_CENTER = { lat: 51.5074, lon: -0.1278 }` (`constants.js:29`) — Charing Cross |
| Truncation call | `prioritizeSources(cameras, maxCount, [LONDON_CENTER])` (`sources.js:327`) |
| Discard visibility | Logged count only (`console.log`); no per-record or inventory-level record of what was dropped |

This is **distance-to-one-anchor truncation**, not a study-area restriction. TfL publishes well over 250 JamCams, so outer boroughs are dropped by a central-London distance cut.

Porting it unchanged yields one of two wrong answers:

- leave `LONDON_CENTER` → the Camden inventory is an arbitrary central-London sample;
- repoint the anchor at Camden → 250 nearest-to-Camden, spanning neighbouring boroughs.

**DO NOT port that prioritization into PTE-GEV-001.**

### Replacement for ticket step 3

> Apply an explicit, provenance-recorded Camden / current 19-CPZ study-area predicate **BEFORE** any analysis or count used as a deliverable.

The result must report:

- upstream available-camera total
- the study-area predicate used (exact geometry source and its identifier/hash)
- cameras inside the study area
- cameras outside the study area
- any deliberate cap — which should normally be **NONE** for this bounded study

### Geometry dependency gate

If the repository does not already contain authoritative geometry adequate to define the 19-CPZ study area:

**STOP and report the geometry dependency.**

Do **NOT** substitute "nearest 250", nearest-to-Camden, a guessed radius, or any other silent truncation. An absent study-area boundary is a blocking dependency, not a licence to approximate one.

---

## C. Pre-registered coverage hypothesis

**PTE-GEV-001 is a COVERAGE INVENTORY, not independent-proxy validation.**

Pre-registered expectation:

> TfL JamCam useful overlap with the Camden study area **may be sparse or zero**. Sparse or zero overlap is a **valid experimental result**, not a failed implementation.

This is a hypothesis about coverage, recorded in advance so that a sparse outcome is interpreted as a finding. It is **not** a prediction that TfL will fail, and nothing in this note authorizes treating a sparse result as evidence against TfL cameras in general.

### Context, explicitly non-predictive

PTE-TEL-004's existing `FIXED_CCTV` stratum behaved differently from the headline signal (ρ = 0.0 across the comparable CPZs). That observation is recorded as context only.

**Do NOT claim that result predicts TfL JamCam usefulness.** The `FIXED_CCTV` stratum and TfL JamCams are **different camera populations under different operators with different purposes** — borough enforcement cameras on borough streets versus TfL-operated traffic cameras on the TfL road network. The prior result does not transfer, and must not be used to prejudge this spike in either direction.

### Proxy-test exclusion

The spike **must NOT** run the `proxySpearman` test.

Any later independent-proxy validation remains a **separate preregistered experiment**, with its own frozen thresholds and its own independence argument. A coverage inventory cannot discharge the PTE-TEL-004 PARTIAL ceiling, and must not be presented as though it could.

---

## D. Commercial / evidence-storage licensing boundary

Rev-1 correctly said to import zero **bundled** third-party datasets. Rev-2 adds the collision between PTE's evidence instinct and **live-source** provider terms.

**PTE's hash-and-preserve evidence instinct does NOT override provider terms.** Where a provider forbids storage, PTE's discipline must adapt — not the provider's terms.

Recorded specifically, per GEV's own source inventory (`DATA_SOURCES.md`) at the pinned SHA:

| Source | Term as documented by GEV | Consequence for PTE |
|---|---|---|
| **Google Maps** (tiles / geocodes / places) | Must remain live; **may not be cached, stored, rehosted, or committed** | Any PTE basemap/geocode layer must produce **no committed artifacts**. Live use only, outside the evidence repo. |
| **OpenSky** | Non-commercial; operational use "can require a prior written agreement… even for non-profit/government use" | Out of scope for a commercial direction. |
| **Google News RSS** | Personal / non-commercial use | Out of scope for a commercial direction. |
| **TeleGeography** (bundled) | **CC BY-NC-SA** | Not suitable for PTE commercial use without separate rights. |
| **TfL JamCams** | Attribution **required**: "Powered by TfL Open Data. Contains OS data © Crown copyright and database rights" | In scope for this ticket; attribution must be carried. |

The Google Maps row is the load-bearing one: PTE's method is to hash and commit artifacts into the evidence repo, and this provider term forbids exactly that for Google-derived content. The two disciplines are compatible **only if** Google-derived content stays live and outside the evidence repository.

### Scope for PTE-GEV-001

- Do **not** introduce Google, OpenSky, Google News, or TeleGeography dependencies.
- Only TfL material needed for the bounded camera study is in scope, subject to TfL terms.

---

## E. Additional reusable patterns (future reuse notes only)

Verified at the pinned SHA. Recorded for later reuse; **do NOT expand PTE-GEV-001 implementation scope to include these.**

- **Explicit provider status instead of exceptions-as-empty** — `src/data/manager.js:443` vocabulary (`found / missing / source-unavailable / cancelled / superseded / destroyed`), status paired with `reason` at `:401`.
- **Bounded request / rate-limit / query helpers** — dependency-free, Node builtins only: `server/providers/common/rate-limit.js` (67L), `request.js` (35L, capped body read raising typed `BODY_TOO_LARGE`), `query.js` (12L, `clampInt` / `requiredFiniteQueryNumber`), `geo.js` (18L). `rate-limit.js` also fixes the limiter map's growth with a hard key cap, and its `clientKey()` deliberately refuses `X-Forwarded-For` — reasoning recorded inline: a client-controlled rotating value "would mint fresh quota and grow the limiter map." Preserve that reasoning if the helper is reused.
- **Traffic single-flight + explicit budget governor** — `server/providers/traffic.js:19-24`: single-flight per tile, plus a persistent UTC-dated counter (`.gev-cache/tomtom/budget.json`) acting as a self-imposed ceiling **below** the provider's published allowance. Reuse single-flight and the budget governor; **not** the serve-stale half of the same pattern (§A).
- **Explained map/provider unavailable states** — `src/mapStackController.js` (494L): `MAP_STACKS` declares each stack's credential requirement (`requiresIon`), and `photorealUnavailableReason(hasCredentials)` makes unavailability an *explained* state rather than a silent fallback.
- **Mechanical package/import boundary enforcement** — `scripts/check-package-boundaries.mjs` (146L) with the written ownership doctrine in `docs/CODE-BOUNDARIES.md`, which requires a component's ownership and its consumer tests to be added **together**. This is the mechanism that would actually keep a ported camera layer from coupling to the legality kernel — the seam rev-1 item 2 wants, enforced by a linter rather than by intent.
- **GEV key-cost convention** — 🟢 no key · 🟡 free key · 🔴 metered ("Thirteen layers and map sources. Eleven have a keyless path."). Cheap to adopt in PTE source surveys (PTE-TEL-001/002) to publish key and cost burden per source.
- **Dependency-free coordinate coercion helpers** — `server/providers/cctv/normalize.js` (421L): `coerceLatLon`, `parsePointString`, `toFiniteNumber`. Relevant to PTE's Camden EPSG:27700 easting/northing vs lon/lat coercion. These **may be studied**; no unrelated porting in this ticket.

---

## TfL JamCam relevance to Camden

GEV already contains a TfL JamCam source adapter suitable for study. The reviewed implementation:

- fetches the TfL JamCam catalog
- keeps only records marked available
- requires finite coordinates
- pins frame URLs to the official TfL image origin (`sources.js:289`)
- creates provider-stable `tfl-*` identifiers (`sources.js:294`)
- labels TfL as the provider/source
- treats camera heading as unavailable and substitutes only a low-confidence pose prior
- uses still frames first rather than claiming a precise video pose
- carries required TfL attribution

This makes the adapter a strong starting point for a Camden **camera-evidence** spike, but not for automatic parking-occupancy inference.

**Two rev-2 qualifications apply to the above:** the adapter's failure encoding must be replaced per §A before it can support any count, and its whole-London/nearest-250 prioritization must be replaced per §B before it can support any Camden-scoped statement. The bullet list describes what GEV does accurately; it is not a statement that those behaviours are safe to inherit.

Note that the official-bucket pin (`imageUrl.startsWith(TFL_IMAGE_ORIGIN)`) is a genuine upstream-host validation control and **is** worth keeping — it rejects frame URLs not on TfL's official origin.

---

## Bounded engineering ticket

### PTE-GEV-001 — TfL Camera Evidence Spike

Goal: determine whether the MIT GEV TfL JamCam provider pattern can give PTE a useful, honest camera-evidence layer around Camden.

Scope:

1. Study/port only the minimum TfL JamCam provider logic needed for acquisition and normalization.
2. Fetch the live TfL JamCam catalog using official-source validation, **returning explicit acquisition state per §A** (never `[]`-as-failure).
3. **Apply an explicit, provenance-recorded Camden / current 19-CPZ study-area predicate BEFORE any analysis or count used as a deliverable** (§B). If authoritative study-area geometry is absent from the repository, **STOP and report the geometry dependency**; do not substitute a radius, a nearest-N cut, or any silent truncation.
4. Emit normalized camera records containing at minimum:
   - provider-stable ID
   - provider/source name
   - latitude/longitude
   - frame/source URL or opaque provider reference as appropriate
   - retrieved-at timestamp
   - upstream availability state
   - required attribution/license/terms reference
   - pose reliability (`LOW` where heading is not publisher-supplied)
5. Determine which cameras are geographically relevant to the 19 Camden CPZs **using the §B predicate**, and report upstream total, inside-count, and outside-count.
6. Produce counts and a machine-readable coverage inventory/map suitable for human review. **Counts derived from `STALE` state do not satisfy this step** (§A).
7. Keep every observation explicitly separate from parking legality and from the PTE-TEL-004 relative-pressure result.
8. Record the pre-registered coverage hypothesis (§C) alongside the result, so a sparse or zero-overlap outcome is reported as a valid finding.

Hard prohibitions:

- **provider failure must never be represented as an empty successful catalog**
- **stale catalog must never be silently counted as current**
- **no nearest-N / Charing-Cross truncation may define Camden coverage**
- **do not fabricate Camden/CPZ geometry if authoritative geometry is absent**
- **no occupancy / vacancy / legality / probability / confidence inference**
- do not infer physical bay occupancy from a camera merely because it exists nearby
- do not claim a camera covers a specific parking bay without independent geometry/calibration evidence
- **the spike must not run the `proxySpearman` test** (§C)
- do not modify the legality kernel
- do not alter PTE-TEL-004 thresholds, taxonomy or classifier
- do not merge to main or deploy
- **no GEV code import outside the minimum reviewed TfL-provider spike**
- do not import unrelated GEV layers, datasets, HUD/spy styling, aircraft, ships, satellites, military context or noncommercial datasets
- **do not introduce Google / OpenSky / Google News / TeleGeography dependencies** (§D)

Deliverables:

- exact upstream GEV files/patterns studied, cited against pinned SHA `2213c422…`
- exact TfL endpoint/provider terms and attribution
- normalized PTE camera-evidence schema proposal, including the §A state vocabulary
- the §B study-area predicate used, with its geometry source and identifier
- Camden camera count and CPZ relevance inventory (upstream total / inside / outside)
- acquisition-state handling evidence: how `SOURCE_UNAVAILABLE` is distinguished from `EMPTY_CURRENT`
- known geometry/pose limitations
- smallest next validation step

Acceptance criterion:

A reviewer can answer: **which public TfL cameras are plausibly useful as evidence around the Camden CPZ study area, what exactly does each camera prove, and what does it not prove?**

A reviewer must additionally be able to confirm that a reported count is a `CURRENT` acquisition under a stated study-area predicate — not a stale catalog and not a distance-truncated sample.

No claim of parking occupancy, vacancy, legality, probability or confidence is required or authorized by this spike.

---

## Rev-2 amendment log

Docs-only correction, committed on branch `arena/01a096f4-parking-truth-engine-data` from parent `a498d1b85e0ad7161923a0353d092423f2965ad0`. No code, threshold, taxonomy, result artifact, or `main` branch content was changed.

| Ref | Amendment | Load bearing |
|---|---|---|
| **A** | Withdraw rev-1's recommendation to reuse serve-stale. Record the exact GEV composition (`[]`-as-failure in the TfL loader + stale-on-empty in the catalog) and require explicit acquisition state (`CURRENT` / `EMPTY_CURRENT` / `SOURCE_UNAVAILABLE` / `STALE` / `CANCELLED`) with mandated per-result fields. Resolves an internal contradiction in rev-1: item 1 recommended importing the mechanism the "PTE semantic boundary" section forbids. | Yes |
| **B** | Record that the reviewed adapter is whole-London + nearest-250-to-Charing-Cross, not Camden-scoped. Replace ticket step 3 with an explicit provenance-recorded study-area predicate, and add a geometry-dependency stop gate. | Yes |
| **C** | Pre-register the coverage hypothesis: sparse/zero overlap is a valid result. Mark the PTE-TEL-004 `FIXED_CCTV` ρ = 0.0 observation as non-predictive context from a different camera population. Exclude the `proxySpearman` test from this spike. | Yes |
| **D** | Add the commercial / evidence-storage licensing boundary: PTE's hash-and-preserve instinct does not override provider terms; Google Maps content may not be cached/stored/rehosted/committed; OpenSky, Google News RSS, TeleGeography out of scope commercially; TfL attribution required. | Yes |
| **E** | Append verified additional reusable patterns as future notes only, explicitly not scope for this ticket. | No |
| **F** | Pin the upstream review to commit `2213c42200d7126dc5385b3801efcdda83928d0c`, version `0.1.1`, replacing "current `main`" wording. | No |

All cited GEV file paths and line numbers were verified against the pinned SHA by direct inspection of a read-only clone. No GEV code was imported into this repository.
