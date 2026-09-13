# Availability Inference — handoff record

**Record ID:** PTE-INF-001
**Snapshot date:** 2026-09-13
**Lane:** AVAILABILITY
**Legality claim made:** none. Every artifact described here carries
`legalityClaimed: false`, and nothing in the inference stack may upgrade a
legality verdict.
**Companion tooling:** `tools/inference/availability_engine.py`,
`tools/inference/live_fusion.py`, `tools/telemetry/make_test_fixture.py`,
`tools/telemetry/calibrate_sim.py`, `tools/telemetry/telemetry_harvester.py`
**Companion manifest:** `manifests/availability-inference-manifest.json`
**Companion narrative:** [`tools/inference/README.md`](../tools/inference/README.md)
**Upstream evidence:** [`REAL-PARKING-TELEMETRY-SOURCES.md`](REAL-PARKING-TELEMETRY-SOURCES.md) (PTE-TEL-001)

This document is written to be handed to an agent or engineer cold. Everything
in it is reproducible from a clean checkout with the commands in §3.

---

## 1. What this is, and what it is not

**It is the inference layer.** The product question is *"to the best of our
ability, is there a space?"* — answered as a calibrated probability with an
honest interval, on streets nobody has ever instrumented.

**It is not a parking-finder app and not a sensor relay.** Cities that publish a
live feed already have dozens of apps relaying it; cities that do not publish one
get nothing from a relay. The differentiator is inference from whatever evidence
exists: historical archives, static bay inventory, restriction metadata,
time-of-day patterns, and partial live sensing.

Two layers:

| Layer | File | Question it answers | Needs sensors? |
|---|---|---|---|
| 1 — climatology | `availability_engine.py` | what a street *usually* does at this hour | no |
| 2 — live fusion | `live_fusion.py` | what it is doing *right now*, including at bays with no sensor | no — partial is the point |

**Availability and legality stay separate.** A space can be vacant and still
illegal to use. A `HIGH` availability estimate must never upgrade a
`PROHIBITED` / `CONFLICT` / `UNKNOWN` legality verdict. This is enforced in
output payloads (`legalityClaimed: false`, `separationNote`) and is a standing
constraint, not a preference.

---

## 2. Where things live

```
tools/telemetry/make_test_fixture.py    deterministic synthetic archive (TEST INPUT, not real data)
tools/telemetry/telemetry_harvester.py  real archives / live feeds -> normalised events
tools/telemetry/calibrate_sim.py        archive stats -> simulator calibration (Little's Law)
tools/realtime-sim/sim_feed.py          synthetic live availability feed (test rig)
tools/realtime-sim/gps_replay.py        GPS trace generator + replayer (test rig)

tools/inference/availability_engine.py  LAYER 1: build / predict / validate
tools/inference/live_fusion.py          LAYER 2: fuse / validate-fusion / make-snapshot
tools/inference/README.md               narrative + full bug catalogue

schemas/parking-telemetry-event-schema.json   normalised event schema (draft-07)
docs/REAL-PARKING-TELEMETRY-SOURCES.md        where real data comes from (PTE-TEL-001)
```

Stdlib Python only throughout. No numpy, no scipy, no network access required for
any validation.

---

## 3. Reproduce everything

Verified from a clean checkout on 2026-09-13. Runs in under a minute total.

```bash
W=/tmp/repro; rm -rf $W; mkdir -p $W

# 1. deterministic fixture (341,058 rows; same flags -> same bytes)
python3 tools/telemetry/make_test_fixture.py --out $W/events2019.csv

# 2. normalise it through the same harvester real archives use
python3 tools/telemetry/telemetry_harvester.py archive \
    --file $W/events2019.csv --max-emit 400000 --out $W/archive

# 3. build the climatological model
python3 tools/inference/availability_engine.py build \
    --events $W/archive/telemetry-events.jsonl --out $W/model.json

# 4. score layer 1 against dates it never saw
python3 tools/inference/availability_engine.py validate \
    --events $W/archive/telemetry-events.jsonl --holdout 0.2 \
    --model-out $W/model_h.json --report $W/validation.json

# 5. score layer 2: can partial sensing predict the UNSEEN bays?
python3 tools/inference/live_fusion.py validate-fusion \
    --events $W/archive/telemetry-events.jsonl --holdout 0.2 \
    --coverages "0.0,0.05,0.10,0.20,0.40,0.70" --report $W/fusion.json

# 6. (optional) drive the realtime sim from the same real-shaped statistics
python3 tools/telemetry/calibrate_sim.py \
    --stats $W/archive/archive-stats.json --out $W/calibration.json
```

Expected output, exactly:

```
fixture      rows 341,058   sha256 b10ad4ef7be6eda755de0f3967ae2f4897bc7bda4bef2331277105a108c29758
             mean stay 39.94 min (target 40.0)   800 bays   45 days   5 event days
harvest      events emitted 341,058   stay median 28.0 / mean 39.96 min
             range 2019-03-04 .. 2019-04-17 (45.0 days)
build        events used 327,752   cells 240 (240 sufficient, 0 UNKNOWN)   streets 5
layer 1      cells scored 1080   Brier skill +0.8828   MAE 0.0481   coverage 0.975
             HIGH 688 cells MAE 0.028   LIMITED 392 cells MAE 0.083
layer 2      see §5
calibrator   peak hour 11:00 at rho=0.627   usable: True
```

If any of those numbers differ, something changed — investigate before building
on top.

### Operational use

```bash
# single-street climatological query
python3 tools/inference/availability_engine.py predict \
    --model $W/model.json --street "Bourke St" --at "2026-09-15T15:30"

# reconstruct an offline live snapshot for testing fusion (no network needed)
python3 tools/inference/live_fusion.py make-snapshot \
    --events $W/archive/telemetry-events.jsonl --at "2019-04-03T12:30" \
    --coverage 0.30 --fault-rate 0.05 --stale-rate 0.10 --out $W/snapshot.json

# fuse it
python3 tools/inference/live_fusion.py fuse \
    --model $W/model.json --live $W/snapshot.json --at "2019-04-03T12:30"
```

`--live` also accepts the sim feed's `/api/bays.geojson`, a URL, a plain
JSON/JSONL list of `{bayKey, street, state, observedAt}`, or `-` for stdin.

---

## 4. The contract

Four states. Consumers must handle all four; three is a bug.

| State | Meaning | Gate |
|---|---|---|
| `HIGH` | The 95% interval **resolves** the question. **Two-sided**: confidently *free* and confidently *full* are both `HIGH`. | interval excludes the ambiguous middle (`lo > 0.35` or `hi < 0.65`) **and** ≥ 20 effective bay-slots **and** ≥ 12 distinct days |
| `LIMITED` | A real estimate, but the interval straddles the middle, or the evidence is thin. | ≥ 5 distinct days |
| `CONFLICT` | *(layer 2 only)* Sensors and climatology disagree by ≥ 3 combined SDs. The blended number is still returned — a conflict is information, not a refusal to answer — but never as high confidence. | `liveVsClimatologyZ` ≥ 3 |
| `UNKNOWN` | Insufficient evidence. | anything thinner, or no cell and no live bays |

Key fields every response carries:

- `pFree`, `pFree95` — point estimate and interval
- `sdMeanEstimate`, `sdBetweenDays`, `sdPredictive` — the uncertainty decomposition (§6, invariant I5)
- `overdispersionPhi`, `phiSource`, `sdDaySource` — whether dispersion was measured or floored
- `totalSlots`, `effectiveSlots`, `datesUsed`, `shrinkageToPrior` — evidence volume
- layer 2 adds `liveOccupancy`, `liveVsClimatologyZ`, `liveShareOfPosterior`,
  `priorEffectiveSampleSize`, `liveEffectiveSampleSize`, `conflict`
- always: `legalityClaimed: false`, `separationNote`, `timezoneCaveat`

---

## 5. Measured results

### Layer 1 — climatology

1,080 held-out street-hours (5 streets × 24 hours × 9 dates), scored **per date**.

| Metric | Value |
|---|---|
| Brier skill score vs a constant predictor | **+0.8828** |
| Mean absolute error on P(free) | **0.0481** |
| 95% interval coverage | **0.975** (target ~0.95) |
| `HIGH` accuracy | MAE 0.028 (688 cells) |
| `LIMITED` accuracy | MAE 0.083 (392 cells) |

The confidence label predicts its own accuracy — `HIGH` is 3× better than
`LIMITED`. That is what makes the label worth publishing.

Interval coverage was arrived at in stages, each a real correction:

| Interval method | 95% coverage |
|---|---|
| Beta posterior on raw slots | 0.304 |
| + city-level overdispersion φ | 0.725 |
| + per-cell φ | 0.667 ← *worse*; the clue that the question was wrong* |
| + between-day dispersion in quadrature | **0.975** |

### Layer 2 — live fusion

Scored against the **unsensed** bays only. `excess` = MAE minus the irreducible
noise floor (§6, invariant I9), so the column is comparable across coverage
levels. Lower is better.

| Bays sensed | Climatology | Live only | **Fusion** | Fusion gain | Fused CI coverage |
|---|---|---|---|---|---|
| 0% | +0.0364 | — | +0.0364 | — | 0.956 |
| 5% | +0.0361 | +0.0869 | **+0.0292** | **+19.1%** | 0.966 |
| 10% | +0.0355 | +0.0526 | **+0.0217** | **+38.8%** | 0.970 |
| 20% | +0.0348 | +0.0334 | **+0.0175** | **+49.8%** | 0.970 |
| 40% | +0.0317 | +0.0166 | **+0.0091** | **+71.2%** | 0.983 |
| 70% | +0.0280 | +0.0064 | **+0.0043** | **+84.7%** | 0.939 |

**Fusion beats both of its inputs at every coverage level.** With ~25 of 500 bays
sensed, error on the bays nobody can see is already down 19%.

On **atypical days** — where reality departs from the climatological pattern by
more than the model's own day-to-day SD (95 of 1,080 cells):

| Bays sensed | Climatology | Fusion | Gain |
|---|---|---|---|
| 5% | +0.1633 | +0.1194 | +26.9% |
| 20% | +0.1616 | +0.0606 | +62.5% |
| 40% | +0.1578 | +0.0333 | +78.9% |
| 70% | +0.1502 | +0.0128 | **+91.5%** |

**This is the commercial argument.** Climatology handles the ordinary day; live
sensing catches the exception — and the exception is exactly when a driver needs
help. It is also the honest limit: on a day that behaves normally, sensors add
almost nothing.

Conflict detector fired 9–34 times per 1,080 cells across the sweep, so it is
live rather than inert.

### Simulator calibration

`sim_feed.py` driven by `calibration.json`, pinned to Tuesday 2026-09-15,
`--speed 1 --tick 1`, 12 s hold, each run on its own port:

| Sim hour | Observed ρ | Citywide target | Ratio |
|---|---|---|---|
| 09:00 | 0.452 | 0.466 | 0.97 |
| 12:00 | 0.556 | 0.604 | 0.92 |
| 18:00 | 0.224 | 0.244 | 0.91 |

Ratios sit below 1.0 for a reason that is not error: the target is the
**citywide** curve, and the sim then applies per-precinct multipliers (cbd-core
1.00, cbd-east 0.86, cbd-north 0.80, cbd-south 0.90, salamanca 0.94) averaging
~0.90. `unknown` bays (injected sensor defects) are excluded from the ρ
denominator rather than counted as free.

---

## 6. INVARIANTS — do not break these

Each was found by scoring against reality, not by reading code. Each lists the
**symptom** so a regression is recognisable.

**I1. The denominator is reconstructed, never counted.**
`totalSlots = distinct_bays(street) × distinct_dates(street, dayType) × slots_per_hour`.
An archive records only bays that were *occupied*; the empty slots are exactly
what is missing from it.
*Symptom if broken:* `pFree = 0.000` everywhere, Brier skill +0.000, coverage
0.000 — the model reports "no space anywhere, ever".

**I2. Slots are weighted by the FRACTION occupied, not by intersection.**
A bay present for 5 of a 15-minute slot contributes 0.333, not 1.0. Intersection
semantics overstate occupancy by `(S+L)/S − 1`: **+37% at a 40-minute mean stay,
+75% at 20 minutes.**
*Symptom if broken:* nothing visible in layer-1 validation — the bias cancels
when prediction and ground truth share the definition. It appears only when the
model is compared to a sensor-shaped quantity (layer 2, or a real live feed), as
a systematic ~25–37% occupancy overstatement. **This is the most dangerous
invariant on the list precisely because layer 1 cannot detect its violation.**

**I3. A bay is a single server.**
Arrivals that find a bay busy are lost, so the arrival rate that produces target
occupancy ρ is `λ = ρ / ((1−ρ)·E[S])`, **not** `λ = ρ/E[S]`. Applies to the
fixture generator and to `sim_feed.py`.
*Symptom if broken:* same-bay overlapping events (the fixture had 31.8%). Then
count-based and set-based occupancy disagree — 0.513 vs 0.402 at the same instant
— which looks like a model bug and is not.

**I4. Validation holds out DATES, never rows, and scores PER DATE.**
Rows from one day share weather, events and demand; random splitting leaks and
inflates every score. Aggregating the held-out dates into one observation per
cell cancels day-to-day variation.
*Symptom if broken:* implausibly good scores. Aggregating 9 dates produced MAE
0.048 while claiming to measure single-day accuracy; a model that cannot tell an
ordinary Tuesday from a stadium event still passes. Nobody ever needs a nine-day
mean.

**I5. Two uncertainties, combined in quadrature.**
`sdMeanEstimate` (how well the cell *average* is known — shrinks with evidence)
and `sdBetweenDays` (how far a *given day* departs from it — does **not** shrink)
are different quantities. The product predicts a future day, so
`sdPredictive = √(sdMeanEstimate² + sdBetweenDays²)`.
*Symptom if broken:* coverage ~0.30–0.70 on a nominal 95% interval. Measured
`sdBetweenDays` 0.15 vs `sdMeanEstimate` 0.03 — day-to-day variation dominates,
so a Beta posterior alone is several times too confident.

**I6. Unmeasurable dispersion floors, never zeroes.**
With too few dates, φ cannot be estimated. Use `DEFAULT_SD_DAY = 0.10` and record
`sdDaySource: "default-floor(not-measurable)"`.
*Symptom if broken:* thin evidence publishes as confident. A 2-date, 160-slot
cell published `HIGH` with CI `[0.637, 0.766]`; correct behaviour is `UNKNOWN`
with `[0.495, 0.908]`.

**I7. Freshness is measured against the instant being PREDICTED.**
`w = 0.5 ** (age_minutes / median_stay_minutes)`, where age runs from
`observedAt` to the query time — not to the snapshot's own clock. The half-life
is the *measured* median stay, because a reading goes stale when the car leaves.
*Symptom if broken:* a stale feed overrides history. Asking "what is it like at
12:30?" with a feed that stopped at 03:30 returned `pFree 0.897` instead of the
correct `0.400` — it would have sent drivers to a full street. Correct behaviour
discounts those readings to weight `0.00` and reverts to climatology.

**I8. Conflicts are detected between SOURCES, not in the posterior.**
`z = (ρ_live − ρ_clim) / √(var_live + sdPredictive²)`, flagged at `|z| ≥ 3`.
A conflict caps the state at `CONFLICT`; it may never publish `HIGH`.
*Symptom if broken:* measuring the posterior shift instead means a strong prior
damps the shift and real disagreements are averaged away silently — the detector
never fires. Publishing `HIGH` alongside a 92-SD conflict is the failure this
prevents.

**I9. Report the irreducible noise floor.**
The layer-2 target is the occupancy of the *unsensed* bays. As coverage rises,
fewer bays remain unsensed, so the target itself gets noisier and every
predictor's MAE rises — including one that never changes. For `n` bays at
occupancy `p`, floor `= √(2/π)·√(p(1−p)/n)`.
*Symptom if broken:* the coverage sweep looks like more sensing makes inference
worse (raw fusion MAE rises 0.0382 → 0.0455 from 40% to 70% while the estimator
is genuinely improving).

**I10. `HIGH` is two-sided.**
Both `pFree95Low > 0.35` (confidently free) and `pFree95High < 0.65`
(confidently full) are knowledge. What is *not* knowledge is an interval
straddling the middle.
*Symptom if broken:* a street that is confidently full is labelled merely
`LIMITED`, because its `pFree` sits near zero and never clears a
"confidently free" threshold.

**I11. Unsensable, failed and stale bays are excluded — never counted as free.**
*Symptom if broken:* availability is systematically overstated in exactly the
places where sensors are broken, which is where drivers are most misled.

**I12. A silent feed must not produce silence.**
The street list is the **union** of live-feed streets and model streets.
*Symptom if broken:* zero sensed bays prints nothing at all, which a consumer
reads as "this street does not exist" rather than "no sensors here".

**I13. Little's Law consumes the MEAN stay, not the median.**
Durations are strongly right-skewed; the median understates ρ by ~31% on the
fixture. The calibrator records `stayStatisticUsed`.
*Symptom if broken:* the whole occupancy curve is scaled down and the simulator
undershoots every target.

**I14. Stay distributions are parameterised on median AND mean.**
`σ = √(2·ln(mean/median))` for a lognormal.
*Symptom if broken:* a fixture whose implied occupancy is ~31% low, silently
mis-testing every consumer.

**I15. Bay inventory is shared between training and validation.**
The held-out denominator must use the same inventory the model trained on.
Inventory is static infrastructure, not an outcome, so it is legitimately drawn
from all events including held-out dates.
*Symptom if broken:* bays that were empty on every held-out day drop out of the
denominator, overstating observed occupancy and making the estimator look worse
than it is.

**I16. The fixture must contain day-to-day variation.**
Without a day-level demand effect, every weekday is identical, climatology is
already near-optimal, and live data can only inject sampling noise.
*Symptom if broken:* fusion measures as **harmful** (−19% to −42% at every
coverage level) — correctly, but for a reason that has nothing to do with the
real world. This nearly produced the wrong conclusion about the product.

---

## 6a. Frontend contract implications — needs an owner decision

[`FRONTEND_INTEGRATION_CONTRACT.md`](FRONTEND_INTEGRATION_CONTRACT.md) currently
types the availability lane as:

> Current availability categories are deliberately non-numeric: `HIGH`,
> `LIMITED`, `UNKNOWN`

This layer changes two things, and neither should be merged silently.

**1. A fourth state.** Layer 2 emits `CONFLICT` when sensors and climatology
disagree beyond noise. This is *consistent* with the repo's existing rule that
"`CONFLICT` applies to disagreement about the same claim" — both sources are
claiming the same thing, current occupancy — but `lib/api/types.ts`,
`lib/api/presentation.ts` and the curb-state legend all enumerate three states
today. An unhandled fourth will fall through to a default branch in the UI.

**2. The numbers are the product.** The contract says availability is
"deliberately non-numeric", but a calibrated `pFree` with an honest interval *is*
the output of this layer — collapsing it to three buckets discards most of the
information it produces, and specifically discards the difference between
"probably free" and "free within a wide interval". The UI is still free to render
only the state; that is a presentation choice. What must not happen is the
contract continuing to assert that no number exists.

Recommended resolution, not yet applied: keep `state` as the required rendering
field and add optional `pFree` / `pFree95` / `evidenceSlots` / `sdDaySource` so
consumers can render precisely or coarsely without changing the enum contract.
Flagged rather than decided, because it changes a typed boundary another
workspace depends on.

The separation rule is unaffected and is preserved everywhere in this stack:
`PROHIBITED + HIGH availability` still means **do not park there**.

---

## 7. Known limitations and open work

**Residual bias is systematic, not random.** Layer 1's worst cells:
`Swanston St` weekend 11h–14h predicts `pFree` 0.37–0.42 against observed
0.65–0.67; `Bourke St` weekday 15h–17h is over-predicted by 0.08–0.11. A
time-of-day-only model cannot know about things that *changed* — a season, an
event venue, construction. Widening the interval would hide this. The fix is more
calendar features and a longer archive, not a bigger error bar.

**Small held-out sample.** 9 dates is a thin sample of weekends and event days.
Some reliability-bin gaps reach +0.037. Re-run on the real Melbourne archive
(246M rows) before quoting any number externally.

**Not yet run against real data.** The sandbox used for development has no
outbound network. Every number here comes from the deterministic synthetic
fixture. The pipeline is proven; **the calibration on real Melbourne data is
not.** That is the single highest-value next step. See
[`REAL-PARKING-TELEMETRY-SOURCES.md`](REAL-PARKING-TELEMETRY-SOURCES.md) for
confirmed URLs and the smallest starting download (2020 Jan–May, 258 MB, 14.2M
rows).

**Open work, in rough priority order:**

1. Run the whole chain on the real 2020 Jan–May Melbourne archive. Expect the
   fixture's numbers to move; the invariants in §6 should not.
2. Add calendar features (public holidays, school terms, event calendars) to
   attack the residual bias above.
3. Spatial borrowing: a street with no history and no sensors currently falls
   back to the city prior for that hour. Neighbouring-street and precinct-level
   priors would be strictly better.
4. Per-bay rather than per-street fusion. Layer 2 currently estimates a street's
   occupancy; a bay-level model could use adjacency and restriction type.
5. Overlapping same-bay events in a *real* archive would double-count fractional
   occupancy. The cell total is capped at its denominator, which bounds gross
   overflow but not per-slot overlap. Add an overlap diagnostic before ingesting
   a new source.
6. Timezone. Hours are UTC as labelled by the harvester. If a publisher's
   timestamps are local, the hour axis is shifted. Every response carries
   `timezoneCaveat`, but nothing corrects it yet.
7. Resolve the frontend contract question in §6a before wiring either layer into
   `S:\Parking-Truth-Engine-App`. It changes a typed boundary another workspace
   depends on, so it needs an owner decision rather than an inference-layer one.

---

## 8. Environment gotchas

Learned the hard way; each cost a wrong conclusion at least once.

- **`/tmp` does not persist between sessions.** Neither do ad-hoc scripts left
  there. Anything worth keeping is committed — which is why
  `make_test_fixture.py` exists rather than a scratch generator.
- **Give every simulator run its own port.** A previous `sim_feed.py` still
  holding the port makes the new one die at bind time while the old one keeps
  answering requests, so every measurement silently comes from the wrong
  scenario. This produced readings that looked like calibration had stopped
  working — observed ρ *identical* at 09:00, 12:00 and 18:00. Verify the process
  is alive and the startup banner shows the expected sim clock before trusting
  any number.
- **`pkill -f "sim_feed.py"` matches your own shell** when the pattern appears in
  the shell's command line. Kill by `$!` PID instead.
- **Simulator time is not wall-clock time.** At `--speed 600 --tick 0.05`, 18
  real seconds is ~3 simulated *days*. Use `--speed 1 --tick 1` for
  equilibrium-hold tests, and `--sim-start YYYY-MM-DDTHH:MM` to pin the date
  (weekday multipliers and the Saturday market spike depend on it).
- **Overnight hours are noise, not failure.** At 03:00 only ~14 of 807 bays are
  expected occupied, so Poisson noise dominates. Do not read a single overnight
  sample as a calibration failure.
- **The local git clone can be rolled back to the branch base by a sandbox
  restart** while the working tree survives. This happened twice in one session.
  Always check `git ls-remote origin` before assuming work is lost — the remote
  normally still has every commit.

  Two distinct cases, with different fixes:

  *Nothing committed yet since the rollback.* Committed files show as untracked
  (`??`). Recover with `git fetch origin <branch>` then
  `git reset --mixed <remote-sha>`, which moves HEAD and the index but does not
  touch the working tree. Status then shows only your genuine new edits.

  *Already committed on the wrong base.* The push is rejected as non-fast-forward,
  and `git log` shows your commit parented on the branch base. Because the
  rollback kept the working tree, that commit's diff is taken against the old
  base and therefore **contains both the missing commits' content and your new
  work**. Fix with `git fetch origin <branch> && git rebase FETCH_HEAD`. The
  earlier commits are already upstream, so every conflict resolves in favour of
  the incoming commit (`git checkout --theirs <file>`). Afterwards
  `git diff --stat <remote-sha> HEAD` should show **only** the new work — if it
  shows more, something was duplicated or lost. Verify key files still exist
  before pushing.

---

## 9. Provenance of the numbers in this record

Every figure in §5 was produced by the commands in §3 from fixture
`sha256 b10ad4ef7be6eda755de0f3967ae2f4897bc7bda4bef2331277105a108c29758`,
verified end-to-end from a clean directory on 2026-09-13. Hold-out splits use
`--seed 1337`, so the same dates are held out on every run.

**The fixture is not real data.** It is a test input that exists to prove the
pipeline's arithmetic. Nothing here is a measurement of Melbourne, and no number
in this document should be quoted externally as one.
