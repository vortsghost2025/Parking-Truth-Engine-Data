# PTE Local Evidence Inventory (2026-09-11, storage-constrained PC)

Purpose: exact accounting of what PTE source/evidence data currently occupies
on this PC, whether each file is reproducible from its public source, and a
recommendation for what becomes remote-only (URL + SHA-256 + timestamp) versus
preserved locally or moved to the canonical private data repository
`vortsghost2025/Parking-Truth-Engine-Data`.

**No file has been deleted, moved, uploaded, or committed. This is an
inventory only. Migration awaits explicit approval.**

## Totals

| Tree | Files | Bytes | ~MB |
|---|---:|---:|---:|
| `data/raw/` (Melbourne/LA live-fetch snapshots) | 258 | 40,282,882 | 38.4 |
| `data/camera/montreal/` (PTE-CAM archive + AMD Places + S-512) | 122 | 78,308,570* | 74.6* |
| `docs/montreal/evidence/` (PTE-007 source preflight) | 14 | 99,272,282 | 94.7 |
| `docs/source-preflight/evidence/` (PTE-001 samples) | 53 | 117,951 | 0.1 |
| **Total measured** | **447** | **~217.7 MB** | |

\* `data/camera/montreal/` includes `data/camera/montreal/outputs/` etc.;
the 78.3 MB figure is the whole `data/` tree minus `data/raw/` overlap —
see per-file table below for the precise split. Grand total across all
measured trees: **217,681,685 bytes (207.2 MiB)**.

Largest single consumers:

1. `docs/montreal/evidence/mtl-catalogue-signalisation-2015.pdf` — 65,333,387 B
2. `docs/montreal/evidence/mtl-signage-full.csv` — 31,144,523 B
3. `data/camera/montreal/models/S-512.pt` — 14,775,628 B
4. `data/raw/los-angeles/inventory/*` — 3 × 13,540,079 B (near-identical snapshots)
5. `data/camera/montreal/Places.csv` — 3,179,980 B
6. `data/raw/melbourne/geometry/*` — 7,700,722 B (2 snapshots, one dedup'd)

## PTE-007 Montréal evidence (`docs/montreal/evidence/`, 14 files, 99,272,282 B)

| File | Bytes | SHA-256 (prefix) | Public source | Reproducible | Recommendation |
|---|---:|---|---|---|---|
| mtl-catalogue-signalisation-2015.pdf | 65,333,387 | 2aac9662… | donnees.montreal.ca → panneaux-de-signalisation → catalogue PDF (65,333,387 B, Range-verified) | YES (exact URL recorded) | REMOTE-ONLY — big, static, publicly hosted; keep URL+hash+the 5 extracted legend pages as text excerpts |
| mtl-signage-full.csv | 31,144,523 | c7878615… | donnees.montreal.ca → stationnement-sur-rue-signalisation-courant → signalisation_stationnement.csv | YES (daily-ish refresh; hash pins THIS version) | MOVE-TO-DATA-REPO or REMOTE-ONLY — but note: daily refresh means a retained copy is the only way to reproduce today's profile; if PTE-007 bounded study depends on this exact version, preserve it in the data repo, not on S: |
| EmplacementReglementation.csv | 1,106,551 | 2048eff7… | agencemobilitedurable.ca/images/data/ | YES (Last-Modified 2026-09-10) | DATA-REPO — small, structured, central to AMD translation |
| mtl-entraves-travaux-en-cours.csv | 876,999 | 61b8f60a… | donnees.montreal.ca → info-travaux | YES (daily refresh; hash pins snapshot) | DATA-REPO — snapshot semantics matter for roadworks overlay study |
| mtl-codification-rpa-full.json | 318,548 | 5f037c45… | donnees.montreal.ca → panneaux-de-signalisation → codification-rpa.json | YES | LOCAL-KEEP — small, authoritative codification, actively used |
| mtl-rpa-codification.csv | 202,149 | 3af77a62… | same dataset, CSV variant | YES | LOCAL-KEEP (small; CSV↔JSON cross-check used in Phase D) |
| mtl-stationnements-hiver-2025-2026.geojson | 73,120 | a1795ebe… | donnees.montreal.ca → stationnements-deneigement | YES (seasonal resource) | LOCAL-KEEP — small, seasonal snapshot with hash |
| mtl-signage-geojson.head.bin | 65,536 | (partial) | Range-probe of signalisation_stationnement.geojson | YES | DELETE-CANDIDATE after migration (diagnostic only; schema + Point-geometry finding recorded in docs) |
| ReglementationPeriode.csv | 45,641 | 7263002f… | agencemobilitedurable.ca | YES | LOCAL-KEEP |
| mtl-stationnements-hiver-2025-2026.csv | 39,100 | 38f81c12… | donnees.montreal.ca | YES | LOCAL-KEEP (CSV twin of the GeoJSON; note semicolon-DQ issue recorded in profile) |
| mtl-signage-metadata.json | 27,883 | (metadata) | CKAN package_show | YES | LOCAL-KEEP |
| Periodes.csv | 24,414 | 11202678… | agencemobilitedurable.ca | YES | LOCAL-KEEP |
| Reglementations.csv | 14,009 | 6b262314… | agencemobilitedurable.ca | YES | LOCAL-KEEP |
| mtl-rtp-codification.csv | 422 | ccea54cc… | donnees.montreal.ca | YES | LOCAL-KEEP |

Fetch timestamps for all of the above: 2026-09-11T22:00:00Z (recorded in the
PTE-007 preflight script/session log). Exact URLs are recorded in this
document's companion staging file `docs/data-storage/.inventory-staging.json`
and in the PTE-007 source-preflight doc when written.

## PTE-CAM camera archive (`data/camera/montreal/`, ~38.1 MB)

| Item | Bytes | Reproducible | Recommendation |
|---|---:|---|---|
| `source/*.jpeg` (80 frames) | ~2.9 MB total | YES — bounded ZIP-Range extraction from CC-BY-4.0 detection archive; per-file SHA-256 in `sample-manifest.json` | REMOTE-ONLY — manifest already contains everything needed to re-extract |
| `annotations/` (80 VOC XML) | ~0.2 MB | YES (same manifest) | REMOTE-ONLY |
| `models/S-512.pt` | 14,775,628 | YES (GitHub release v0.1-alpha) | REMOTE-ONLY — license TERMS_UNCLEAR; explicitly do-not-redistribute; hash `e5e488f1…` recorded in PTE-CAM-002 docs |
| `Places.csv` (AMD) | 3,179,980 | YES (agencemobilitedurable.ca, Last-Modified 2026-09-10) | DATA-REPO (single authoritative AMD places snapshot) |
| `outputs/` (detections, ROI calls/metrics, fingerprints, triage sheets, view evidence) | ~16.8 MB | Derived (recomputable from archived inputs + scripts) | DATA-REPO for the JSON artifacts; triage JPEGs can be regenerated — REMOTE-ONLY or drop after data repo holds them |
| `rois.json`, `alignment.json`, `view-rois.json`, `sample-manifest.json` | ~50 KB | Hand-authored / manifest | LOCAL-KEEP (tiny, canonical inputs to tests) |

## Live-fetch snapshots (`data/raw/`, 38.4 MB)

All fetched 2026-09-11 by the evidence-service smoke runs; every body has a
`.meta.json` with URL, timestamp, and SHA-256 (that is the whole point of the
store).

| Item | Bytes | Reproducible | Recommendation |
|---|---:|---|---|
| LA inventory × 3 near-identical snapshots | ~40.6 MB combined | YES (Socrata live) | DELETE-CANDIDATES ×2 (keep newest body + all three metas — the store's dedup design keeps 1 body / 3 metas; the extra bodies here are from separate `rawBaseDir` runs) |
| Melbourne geometry × 2 | ~7.7 MB + 1 dup | YES (Opendatasoft live) | Keep 1 body + metas |
| Melbourne/LA occupancy snapshots | ~3.8 MB | YES (live feeds) | Keep newest per city; rest remote-only |
| `manifest.jsonl` | small | — | LOCAL-KEEP (provenance ledger) |

## PTE-001 preflight samples (`docs/source-preflight/evidence/`, 0.1 MB)

53 small samples (≤8 KB each) + metas. All reproducible; all LOCAL-KEEP —
they are the historical verification record and cost nothing.

## Sizing conclusion

- **~170 MB (78%) is publicly re-downloadable at any time** (catalogue PDF,
  signage CSV, live-feed snapshots, S-512.pt, camera frames). Under the new
  policy this becomes URL + SHA-256 + timestamp + schema profile, not local
  bytes.
- **~47 MB deserves preservation but not on S:** — AMD regulatory tables
  (snapshot semantics), derived camera outputs, bounded-study inputs. These
  belong in `vortsghost2025/Parking-Truth-Engine-Data`.
- **< 1 MB must stay local** — hand-authored ROIs/manifests/alignment, metas,
  manifests of record, the small codification tables actively used by
  PTE-007 Phase D translation work.

## Proposed migration (awaiting approval — nothing executed)

1. Create private repo `vortsghost2025/Parking-Truth-Engine-Data` (user
   action; PTE will not create/push anything itself).
2. Move, not copy: AMD tables + Places.csv + camera derived-outputs + the
   pinned mtl-signage-full.csv snapshot.
3. Replace moved/deleted items with a stub manifest row (path, URL, SHA-256,
   retrieval timestamp, byte count) so scripts and docs still resolve.
4. Delete only the two flagged DELETE-CANDIDATE classes (diagnostic head
   probe, duplicate live-feed bodies) — both fully reproducible and hashed.
5. Re-run `npm test` after any change that touches test-input paths
   (camera tests read `rois.json`/`view-rois.json` etc. — those stay local).

Estimated post-migration local footprint of source/evidence data:
**< 5 MB**, with zero loss of reproducibility.
