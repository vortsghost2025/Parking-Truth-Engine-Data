# PTE-GEV-001 — God's Eye View reuse notes and bounded next ticket

Status: **READ-ONLY ARCHITECTURE REVIEW COMPLETE; NO GEV CODE IMPORTED**

Upstream reviewed: `bilawalsidhu/gods-eye-view` current `main` during the 2026-09-13 session.

## Reuse decision

Do **not** fork or merge the whole God's Eye View application into Parking Truth Engine. Reuse/adapt only bounded architecture and provider modules where they reduce implementation cost without weakening PTE truth semantics.

### Highest-value pieces

1. **TfL/Austin/Caltrans CCTV provider pattern**
   - server-side normalized camera catalog
   - independent provider failures
   - dedupe and source caps
   - cache/single-flight refresh
   - serve-stale behavior instead of blanking the layer
   - fixed/official upstream host validation

2. **CCTV browser layer/source separation**
   - source acquisition separated from rendering
   - injected services for terrain, picking, overlays, focus and rendering
   - useful seam for PTE camera evidence without coupling it to the legality kernel

3. **Traffic provider/source pattern**
   - bounded OSM/Overpass road requests
   - optional provider-backed traffic flow
   - server-side provider boundary rather than arbitrary browser fetches

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

## TfL JamCam relevance to Camden

GEV already contains a TfL JamCam source adapter suitable for study. The reviewed implementation:

- fetches the TfL JamCam catalog
- keeps only records marked available
- requires finite coordinates
- pins frame URLs to the official TfL image origin
- creates provider-stable `tfl-*` identifiers
- labels TfL as the provider/source
- treats camera heading as unavailable and substitutes only a low-confidence pose prior
- uses still frames first rather than claiming a precise video pose
- carries required TfL attribution

This makes the adapter a strong starting point for a Camden **camera-evidence** spike, but not for automatic parking-occupancy inference.

## Licensing boundary

GEV source code is MIT, subject to preserving the license/copyright notice for reused/substantial code.

The MIT grant does **not** cover third-party datasets, provider content, imagery, models or API terms. Evaluate every PTE source independently. Do not copy GEV's bundled datasets into PTE merely because the application code is MIT.

For a work/commercial direction, default to importing zero bundled third-party datasets until their terms are separately reviewed.

## Bounded engineering ticket

### PTE-GEV-001 — TfL Camera Evidence Spike

Goal: determine whether the MIT GEV TfL JamCam provider pattern can give PTE a useful, honest camera-evidence layer around Camden.

Scope:

1. Study/port only the minimum TfL JamCam provider logic needed for acquisition and normalization.
2. Fetch the live TfL JamCam catalog using official-source validation.
3. Restrict analysis to Camden / the current 19 CPZ study area.
4. Emit normalized camera records containing at minimum:
   - provider-stable ID
   - provider/source name
   - latitude/longitude
   - frame/source URL or opaque provider reference as appropriate
   - retrieved-at timestamp
   - upstream availability state
   - required attribution/license/terms reference
   - pose reliability (`LOW` where heading is not publisher-supplied)
5. Determine which cameras are geographically relevant to the 19 Camden CPZs.
6. Produce counts and a machine-readable coverage inventory/map suitable for human review.
7. Keep every observation explicitly separate from parking legality and from the PTE-TEL-004 relative-pressure result.

Hard prohibitions:

- do not infer physical bay occupancy from a camera merely because it exists nearby
- do not claim a camera covers a specific parking bay without independent geometry/calibration evidence
- do not modify the legality kernel
- do not alter PTE-TEL-004 thresholds, taxonomy or classifier
- do not merge to main or deploy
- do not import unrelated GEV layers, datasets, HUD/spy styling, aircraft, ships, satellites, military context or noncommercial datasets

Deliverables:

- exact upstream GEV files/patterns studied
- exact TfL endpoint/provider terms and attribution
- normalized PTE camera-evidence schema proposal
- Camden camera count and CPZ relevance inventory
- known geometry/pose limitations
- smallest next validation step

Acceptance criterion:

A reviewer can answer: **which public TfL cameras are plausibly useful as evidence around the Camden CPZ study area, what exactly does each camera prove, and what does it not prove?**

No claim of parking occupancy, vacancy, legality, probability or confidence is required or authorized by this spike.
