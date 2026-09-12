# Parking-Truth-Engine-Data (PRIVATE)

Private PTE research/evidence repository. Code lives separately in the
Parking-Truth-Engine workspace; this vault holds preserved evidence bytes,
manifests, schemas, and provenance that justify or reproduce PTE findings.

## Rules

- This repository is PRIVATE. Do not make it public.
- Large publicly reproducible datasets are generally referenced by
  URL + SHA-256 + retrievedAt + size + schema/profile, not permanently
  duplicated as bytes here (see manifests/reproducible-sources-manifest.json).
- Legality evidence and availability evidence remain separate by design;
  nothing in this vault combines them.
- Snapshot-semantics artifacts (AMD regulatory tables, pinned signage CSV,
  roadworks/snow snapshots) ARE preserved as bytes because their exact
  captured version matters to reproducibility of the corresponding studies.

## Structure

- sources/montreal/    captured source snapshots (AMD, signage, roadworks, snow, codification)
- evidence/camera/     derived camera benchmark outputs (PTE-CAM-002/003, frozen lane)
- evidence/montreal/   Montréal preflight evidence
- manifests/           inventories, sample manifests, reproducible-source references
- schemas/             dataset schema profiles
- docs/                storage/migration documentation

## Provenance

Every captured file's source URL, SHA-256, and retrieval timestamp is
recorded in manifests/ (local-inventory-staging.json and
reproducible-sources-manifest.json). Licenses: CC-BY-4.0 (Ville de Montréal),
CC BY (AMD, Melbourne), public domain (LA) unless noted otherwise.
Camera-derived outputs are computed from the CC-BY-4.0 annotated camera
dataset; no faces/plates identity work was performed or is permitted.
