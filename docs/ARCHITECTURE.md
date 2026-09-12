# Parking Truth Engine — Architecture Overview

## Design goal

PTE is a city-agnostic parking evidence and rule platform. City-specific adapters translate municipal/public data into normalized evidence and rules. A deterministic kernel evaluates legality. Availability is a separate downstream layer.

## Major lanes

### PTE Core

Responsibilities:

- normalized evidence model
- normalized parking rules
- rule precedence
- conflict detection
- whole-interval evaluation
- provenance
- source health/freshness
- fail-closed UNKNOWN

### City adapters

Responsibilities:

- retrieve or ingest source data
- preserve raw evidence
- normalize source-specific fields
- use authoritative join/attachment rules
- emit normalized evidence/rules
- quantify coverage and UNKNOWN causes

Adapters must not invent curb attachment, time semantics, or precedence.

### Availability

Possible inputs:

- municipal occupancy sensors
- fixed-view camera evidence
- privacy-preserving phone/mesh events
- historical occupancy/arrival/departure data
- future physical sensors

Availability ranks candidates only after legality gating.

### Frontend

Responsibilities:

- map interaction
- requested arrival/departure interval
- verdict display
- Evidence / Why panel
- source/freshness display
- legality vs availability separation
- Find Parking
- Park My Car snapshot

The frontend does not reproduce the rule kernel.

## Core rule result

A legality result should be capable of carrying:

- verdict
- evaluated interval
- interval segments
- applicable rule IDs
- evidence/source IDs
- conflicts
- restrictions
- payment requirement
- maximum stay
- freshness
- reliability category
- explanatory notes

## Verdicts

- `ALLOWED`
- `ALLOWED_PAID`
- `TIME_LIMITED`
- `PERMIT_REQUIRED`
- `PROHIBITED`
- `SPECIAL_USE_ONLY`
- `CONFLICT`
- `UNKNOWN`

## Precedence

Precedence is evidence-derived and explicit. Higher-precedence rules govern only where they actually apply.

Same-precedence contradictory rules do not get silently resolved. They produce `CONFLICT` with both records retained.

## Whole-interval semantics

The requested parking interval is split at relevant rule boundaries.

Any uncovered material interval causes the overall request to fail closed to `UNKNOWN`.

This prevents a driver from receiving “allowed” because the curb is legal at arrival even though it becomes illegal before departure.

## Timezones

Real-city rules require local civil-time evaluation.

The current kernel includes IANA timezone support and dedicated `America/Toronto` DST regression coverage for Montréal.

## Source health

Network success and evidence freshness are separate concepts.

Source health can include:

- `FRESH`
- `STALE`
- `DEGRADED`
- `UNAVAILABLE`

Restored/cached evidence retains its original success/evidence timestamps.

## Provenance

Evidence should retain enough metadata to answer:

- where did this come from?
- what source record did it originate from?
- when was it observed/effective?
- when was it retrieved?
- has the raw payload changed?
- what authority class does the source belong to?
- how was it attached to this curb/space?

## Conflict semantics

`CONFLICT` means evidence disagrees about the **same claim**.

It does not mean legality and availability differ.

Examples:

- `PROHIBITED + VACANT` — valid pair of independent facts, not a conflict
- two same-authority rules that say allowed vs prohibited for the same interval — conflict

## Storage architecture

Large reproducible public datasets should generally remain at the authoritative source.

PTE preserves:

- URL
- timestamp
- SHA-256
- size
- schema/profile
- licence/reuse notes

Unique, derived, small, or version-sensitive artifacts belong in the private evidence repository.

## Current integration boundary

The frontend currently uses mock data and should evolve toward a typed client interface.

The live integration should replace the mock client with a core API implementation without copying rule logic into the UI.
