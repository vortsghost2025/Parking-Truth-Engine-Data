# Owner / Stakeholder Review Guide

This document is for a nontechnical or semi-technical owner who wants to understand what Parking Truth Engine does, what has actually been built, and what to look for when reviewing the code.

## The shortest explanation

Parking Truth Engine is being built to answer:

> **Can I legally leave my car here for the time I need — and why?**

A separate availability layer can later answer:

> **Where am I most likely to find an open legal space?**

The project deliberately does not treat those as the same problem.

## Why that distinction matters

A parking space can be:

- vacant but illegal
- occupied but legal
- legal now but illegal before the driver plans to leave
- covered by conflicting municipal information
- impossible to classify confidently because the available evidence is incomplete

PTE is designed to show those cases honestly.

## What to inspect first

### 1. Rule engine

The rule engine should be deterministic. Given the same rules, requested interval, and vehicle context, it should return the same result every time.

Important behaviors to look for:

- entire requested parking interval is evaluated
- overnight rules are supported
- local timezone and DST are handled
- missing time coverage fails to UNKNOWN
- conflicting same-level rules produce CONFLICT
- payment requirements do not imply payment has happened
- availability/occupancy cannot change legality

### 2. Evidence and provenance

A result should not be a mystery.

For a real-city result, the system should eventually be able to show:

- source
- source record identifier
- retrieval time
- effective dates/times
- applied rule
- conflicts
- freshness
- why the result was reached

### 3. Montréal adapter work

Montréal is difficult because official data exists in several different systems.

Current research includes:

- on-street signage
- RPA/RTP sign codification
- paid-parking regulations
- schedule periods
- roadworks
- snow operations

The project does **not** assume that two records belong together because they are geographically close. If the City does not provide an authoritative way to attach a sign to a curb span, the result stays UNKNOWN.

### 4. Frontend

The frontend should make the difference between legality and availability obvious.

A useful review is to click through mock/demo examples such as:

- allowed
- paid
- time-limited
- prohibited
- conflict
- unknown
- legal + likely vacant
- prohibited + vacant

The last example is especially important. A vacant space is not necessarily a usable space.

## Current code locations

During active development, the code is split locally:

- `S:\Parking-Truth-Engine` — core rule engine, evidence, adapters, tests
- `S:\Parking-Truth-Engine-App` — frontend application

This GitHub repository is the private evidence/data companion, not yet the full application code repository.

## Tests

At the latest checkpoint, the core ordinary test command reports:

**126 / 126 passing**

That includes dedicated IANA timezone/DST regression coverage in addition to the rule-engine and adapter/reliability work.

A passing test count is useful, but the important question is what the tests prove. Reviewers should look for cases covering:

- whole-interval legality
- uncovered minutes
- overnight rules
- `24:00`
- DST transitions
- precedence
- conflicts
- malformed input
- source failure
- occupancy independence

## What is intentionally unfinished

The project is not being presented as a finished city-wide legal-parking authority.

Important unresolved areas include:

- exact Montréal sign-to-curb attachment semantics
- complete Montréal legality coverage
- human review of bounded real-curb machine-derived verdicts
- calibrated availability probabilities
- broad sensor deployment economics
- live camera access/coverage

Those are documented as gaps rather than hidden.

## Camera and sensor work

Camera research showed that vehicle-to-parking-ROI occupancy detection is plausible, but that lane is currently frozen because coverage and live-access questions are unresolved.

Physical sensors are considered a future optional layer. The product architecture is intentionally being designed so it can provide value without requiring a sensor in every parking space.

## What success looks like

A strong version of PTE should be able to say:

> “For this curb, vehicle, arrival time, and departure time, this is the legality result. These are the rules that produced it. These are the sources. This is how fresh they are. Here is anything that conflicts or is missing.”

Then, separately:

> “Among the legal options, these locations are the best places to search for an available space.”

## Questions worth asking during a code review

- Where does this conclusion come from?
- Can I trace it back to a source?
- What happens when the source is unavailable?
- What happens if two authoritative sources disagree?
- What happens at midnight?
- What happens during a DST change?
- Can an occupancy signal accidentally make an illegal curb look legal?
- Can a city-specific adapter be replaced without rewriting the kernel?
- Does the UI show uncertainty clearly?
- Are real-city claims kept separate from demo/mock data?

If those questions can be answered clearly from the code, tests, and evidence, the architecture is doing its job.
