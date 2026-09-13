# Availability Inference

Two layers that answer one question: **is there a space?**

| | File | Answers | Works where |
|---|---|---|---|
| **Layer 1 — climatology** | `availability_engine.py` | what a street *usually* does at this hour | everywhere, including streets nobody has ever instrumented |
| **Layer 2 — live fusion** | `live_fusion.py` | what it is doing *right now* | streets with sensors, and infers the bays that have none |

Neither relays a sensor feed. Layer 1 needs no sensors at all. Layer 2 uses
whatever partial sensing exists to infer the bays it cannot see — which is the
case almost everywhere in the world.

Stdlib Python only. No numpy, no scipy, no network.

```
tools/telemetry/make_test_fixture.py   deterministic synthetic archive (test input)
tools/telemetry/telemetry_harvester.py real archives -> normalised events
        |
        v
tools/inference/availability_engine.py build / predict / validate
        |
        v
tools/inference/live_fusion.py         fuse / validate-fusion / make-snapshot
```

---

## The four-state contract

| State | Meaning |
|---|---|
| `HIGH` | The 95% interval **resolves** the question. Two-sided: confidently *free* and confidently *full* are both `HIGH`. |
| `LIMITED` | A real estimate, but the interval straddles the ambiguous middle, or the evidence is thin. |
| `CONFLICT` | *(layer 2 only)* Sensors and climatology disagree beyond noise. The blended number is still returned — a conflict is information, not a refusal to answer — but never as high confidence. |
| `UNKNOWN` | Insufficient evidence. |

`HIGH` is gated on the **interval**, never the point estimate, plus ≥ 20
effective bay-slots and ≥ 12 distinct days. A pattern seen on two Tuesdays is a
rumour, not a model.

The label earns its place. On held-out data scored per date:

```
HIGH       cells=688   MAE=0.028
LIMITED    cells=392   MAE=0.083
```

A `HIGH` answer is 3× more accurate than a `LIMITED` one.

---

## Layer 1 — climatology

One cell per **(street, day type, hour)**.

```bash
python3 availability_engine.py build    --events archive/telemetry-events.jsonl --out model.json
python3 availability_engine.py predict  --model model.json --street "Bourke St" --at "2026-09-15T15:30"
python3 availability_engine.py validate --events archive/telemetry-events.jsonl --holdout 0.2
```

### How it estimates

1. **Denominator reconstruction.** An archive records only bays that were
   *occupied*; the empty slots — the whole point — are missing. They must be
   rebuilt from inventory × calendar:

   ```
   totalSlots = distinct_bays(street) × distinct_dates(street, dayType) × slots_per_hour
   ```

   Getting this wrong is fatal and silent: it makes `occupied == total`, pins
   P(occupied) at 1.0, and reports "no space anywhere, ever".

2. **Fractional slot weighting.** A bay present for 5 of a 15-minute slot
   contributes 0.333, not 1.0. Marking a slot occupied on *any* intersection
   overstates occupancy by `(S+L)/S − 1` — **+37% at a 40-minute mean stay, +75%
   at 20 minutes**. See *Bugs this caught* below; this one hid for a long time.

3. **Empirical-Bayes Beta posterior**, with the prior taken from the city-level
   aggregate for that day type and hour. A street with three observations is
   pulled toward the city pattern instead of reporting a wild number.
   `shrinkageToPrior` records how much.

4. **Measured overdispersion.** Bay-slots are not independent trials — one event
   covers many consecutive slots, and demand varies day to day. φ is measured
   from between-date variance, not assumed:

   ```
   φ = observed between-date variance of the daily occupancy rate
       ÷ the variance a binomial would predict
   ```

   Measured per cell where ≥ 5 dates exist, else the city-level estimate.

5. **Two different uncertainties.** Conflating these produced badly
   overconfident intervals:

   - `sdMeanEstimate` — how well the cell's *average* is known. Shrinks with evidence.
   - `sdBetweenDays` — how far a *given day* departs from that average. Does
     **not** shrink with evidence; it is a property of the street and hour.

   The product predicts a **future day**, so the published interval carries both:
   `sdPredictive = √(sdMeanEstimate² + sdBetweenDays²)`.

6. **Unmeasurable dispersion floors, never zeroes.** With too few dates φ cannot
   be estimated. Falling back to `sd = 0` publishes a razor-thin interval built
   on almost no evidence. Instead `DEFAULT_SD_DAY = 0.10` applies and
   `sdDaySource` records `"default-floor(not-measurable)"`. A 2-date, 160-slot
   cell that was publishing `HIGH` with CI `[0.637, 0.766]` now publishes
   `UNKNOWN` with `[0.495, 0.908]`.

### Measured accuracy

Fixture: 341,058 rows → 5 streets, 45 dates, 240 cells. 36 dates trained, 9 held
out, scored **per date** → 1,080 observations.

```
Brier skill score         : +0.8828
mean absolute error       : 0.0481    (±5 points on P(free))
95% CI coverage           : 0.975     (target ~0.95)
```

Coverage arrived in stages, each a real correction:

| Interval method | 95% coverage |
|---|---|
| Beta posterior on raw slots | 0.304 |
| + city-level φ | 0.725 |
| + per-cell φ | 0.667 |
| + between-day dispersion in quadrature | **0.975** |

Per-cell φ *alone* made coverage worse — the clue that the Beta posterior was
answering the wrong question (uncertainty about the mean, not about a future day).

---

## Layer 2 — live fusion

```bash
# reconstruct an offline test snapshot from an archive (no network needed)
python3 live_fusion.py make-snapshot --events archive/telemetry-events.jsonl \
    --at "2019-04-03T12:30" --coverage 0.30 --fault-rate 0.05 --stale-rate 0.10 \
    --out snapshot.json

# fuse it with a built model
python3 live_fusion.py fuse --model model.json --live snapshot.json --at "2019-04-03T12:30"

# does partial sensing actually predict the bays it cannot see?
python3 live_fusion.py validate-fusion --events archive/telemetry-events.jsonl \
    --holdout 0.2 --coverages "0.0,0.05,0.10,0.20,0.40,0.70"
```

`--live` accepts the realtime-sim feed's `/api/bays.geojson`, a plain JSON/JSONL
list of bay observations, a URL, or `-` for stdin.

### How it fuses

Bayesian update, not a hand-tuned blend:

```
prior      Beta(a0, b0)     moment-matched to the cell's predictive spread
likelihood Binomial(m, ρ)   over the m bays actually sensed
posterior  Beta(a0 + w·j, b0 + w·(m−j))
```

The prior's effective sample size falls out of the model's own uncertainty:

```
ν = ρ(1−ρ) / sdPredictive²
```

so **nobody has to decide how much to trust sensors** — the sample size decides.
A street the model is unsure about yields to live data quickly; one it knows well
does not. `liveShareOfPosterior` reports the split.

**Freshness is not a TTL.** A reading decays because *cars leave*, so the decay
constant is the measured stay duration:

```
w = 0.5 ** (age_minutes / median_stay_minutes)
```

A reading as old as the median stay has a ~50% chance of describing a car that
has already gone. A city with 2-hour stays tolerates older feeds than one with
20-minute turnover. `medianStayMinutes` is carried on the model so this is never
guessed.

Bays that are not sensable, whose sensor has failed, or whose feed went stale are
**excluded, never counted as free** — that single mistake would be the most
damaging available here.

### Measured accuracy

The question is not "can we predict bays we can see" — that is trivial. It is
**can we predict the bays we cannot see**. So `validate-fusion` reconstructs the
true instantaneous occupancy of every bay on held-out dates, hides a fraction
behind a fixed sensor installation, and scores against the *unsensed* remainder.

`excess over floor` is MAE minus the irreducible noise floor (see below). Lower
is better.

| Sensed | Climatology MAE | Live-only MAE | **Fusion MAE** | Floor | Excess: climatology | Excess: **fusion** | Gain |
|---|---|---|---|---|---|---|---|
| 0% | 0.0591 | — | 0.0591 | 0.0227 | +0.0364 | +0.0364 | — |
| 5% | 0.0594 | 0.1102 | **0.0524** | 0.0232 | +0.0361 | +0.0292 | **+19.1%** |
| 10% | 0.0594 | 0.0765 | **0.0456** | 0.0239 | +0.0355 | +0.0217 | **+38.8%** |
| 20% | 0.0601 | 0.0587 | **0.0428** | 0.0253 | +0.0348 | +0.0175 | **+49.8%** |
| 40% | 0.0607 | 0.0457 | **0.0382** | 0.0291 | +0.0317 | +0.0091 | **+71.2%** |
| 70% | 0.0692 | 0.0476 | **0.0455** | 0.0412 | +0.0280 | +0.0043 | **+84.7%** |

**Fusion beats both of its inputs at every coverage level.** With only 5% of bays
sensed — roughly 25 of 500 on a street — unsensed-bay error is already down 19%.

On **atypical days**, where reality departs from the climatological pattern by
more than the model's own day-to-day SD (95 of 1,080 cells), the gain is much
larger:

| Sensed | Excess: climatology | Excess: fusion | Gain |
|---|---|---|---|
| 5% | +0.1633 | +0.1194 | +26.9% |
| 10% | +0.1617 | +0.0870 | +46.2% |
| 20% | +0.1616 | +0.0606 | +62.5% |
| 40% | +0.1578 | +0.0333 | +78.9% |
| 70% | +0.1502 | +0.0128 | **+91.5%** |

This is the commercial argument in one table: **climatology handles the ordinary
day, live sensing catches the exception**, and the exception is exactly when a
driver most needs help. Fused 95% interval coverage held at 0.94–0.98
throughout, and the conflict detector fired 9–34 times per 1,080 cells.

### The noise floor, and why the sweep needs it

The target is the occupancy of the *unsensed* bays. As coverage rises, fewer bays
remain unsensed, so the target itself gets noisier — and every predictor's MAE
rises with it, including one that never changes. That is why raw fusion MAE goes
*up* from 0.0382 at 40% to 0.0455 at 70% while the estimator is genuinely
improving.

For `n` unsensed bays at occupancy `p`, the sample fraction has SD `√(p(1−p)/n)`,
and a predictor that knows `p` exactly still incurs `E|X−p| = √(2/π)·SD`. Without
subtracting that floor the coverage sweep is unreadable — it looks like more
sensing makes inference worse, when the yardstick is just wobbling more.

---

## Bugs this caught

Every one of these was found by scoring against reality, not by reading code.

1. **Denominator.** Counting only slots that appear in an event pins P(occupied)
   at 1.0. Validation reported `pFree = 0.000` everywhere, skill +0.000.

2. **Intersection vs fractional slots.** Marking a slot occupied on any overlap
   overstated occupancy by ~37%. It survived layer-1 validation *because that
   validation used the same definition for prediction and ground truth* — the
   bias cancelled exactly. It only appeared when layer 2 compared the model
   against a sensor-shaped quantity. Self-consistent validation cannot detect a
   shared definitional error.

3. **The test fixture allowed two cars in one bay.** Drawing Poisson arrival
   counts per bay-hour independently produced **31.8% same-bay overlapping
   events**. Count-based occupancy then read 0.513 while set-based read 0.402 at
   the same instant — a 25% disagreement that looked like a model bug. A bay is a
   single server: arrivals that find it busy are lost, so the required rate is
   `λ = ρ/((1−ρ)·E[S])`, **not** `λ = ρ/E[S]`. Overlaps now 0.

4. **The fixture had no day-to-day variation.** With every weekday on an
   identical curve, climatology is already near-optimal and live data can only
   inject sampling noise. Measured on that fixture, fusion was **worse** than
   climatology at every coverage (−19% to −42%) — correctly, but for a reason
   that has nothing to do with the real world. Adding a lognormal day multiplier
   (SD 0.20) and rare event days (6% of dates at ×1.8) is what made the
   experiment meaningful.

5. **Layer-1 validation averaged the held-out dates.** One observation per cell
   over 9 dates cancels day-to-day variation, so a model that cannot tell an
   ordinary Tuesday from a stadium event still scored well. It was validated
   against a 9-day mean — a quantity nobody ever needs. Now scored per date
   (1,080 observations), which is also what makes the two layers comparable.

6. **Freshness measured against the snapshot clock, not the prediction time.**
   Asking "what is it like at 12:30?" with a feed that stopped updating at 03:30
   scored every reading as brand new, and a 3am near-empty street overrode noon
   climatology outright: `pFree 0.897` instead of the correct `0.400`. It would
   have sent drivers to a full street. Age is now measured to the instant being
   predicted; that same case discounts to weight `0.00` and reverts to
   climatology.

7. **The conflict detector measured the posterior shift.** A strong prior damps
   the shift, so a genuine disagreement was averaged away without ever tripping
   it. Now a z-score between the two *sources*:
   `z = (ρ_live − ρ_clim) / √(var_live + sdPredictive²)`, flagged at `|z| ≥ 3`.
   Invariant to how much weight the prior carries.

8. **`HIGH` published during a 92-SD conflict.** Contradictory evidence now
   yields `CONFLICT`, never `HIGH`.

9. **`HIGH` was one-sided.** Testing only `pFree95Low > 0.35` labelled a street
   that is confidently *full* as merely `LIMITED`, because its `pFree` sits near
   zero and never clears a "confidently free" threshold. Both tails are
   knowledge; what is not knowledge is an interval straddling the middle.

10. **A silent feed produced no output at all.** With zero sensed bays the street
    list was empty and `fuse` printed nothing — which looks like the street does
    not exist. Now the union of live streets and model streets, so a silent
    sensor network still returns climatological answers.

---

## Test fixture

`tools/telemetry/make_test_fixture.py` generates a deterministic, byte-reproducible
synthetic archive so none of this needs a 258 MB download to re-run.

```bash
python3 ../telemetry/make_test_fixture.py --out /tmp/fx/events2019.csv
#  341,058 rows   sha256 b10ad4ef7be6eda755de0f3967ae2f4897bc7bda4bef2331277105a108c29758
#  mean stay 39.94 min (target 40.0)   800 bays   45 days   5 event days
```

It reproduces Melbourne's real column names, the four defects the publisher
documents in its own archives, a right-skewed stay distribution parameterised on
**both** median and mean (`σ = √(2·ln(mean/median))` — occupancy follows
Little's Law on the mean, and matching only the median understates ρ by ~31%), a
single-server renewal process per bay, and day-level demand effects.

**It is not real data.** Anything calibrated on it is calibrated on a fiction;
the point is to prove the arithmetic, not to publish numbers about Melbourne.

---

## Validation methodology

- Hold-out is **by date**, never by row. Rows from one day share weather, events
  and demand; splitting them randomly leaks and inflates every score. Dates are
  shuffled with a fixed seed (`--seed 1337`) so runs reproduce.
- Layer 2 scores against **unsensed bays only**. Predicting bays you can already
  see is not a claim worth making.
- The sensor installation is **fixed across dates** (deterministic CRC32 on the
  bay key). Real installations do not move day to day, and re-drawing per
  observation would leak.
- "Atypical" is decided from **ground truth**, not from any predictor's error, so
  it cannot favour one.
- The held-out denominator reuses the **same bay inventory** the model trained
  on. Taking it only from held-out events would drop bays that were empty on
  every held-out day, shrinking the denominator and making the estimator look
  worse than it is.
- Bay inventory *is* drawn from all events including held-out dates. Inventory is
  static infrastructure, not an outcome; excluding a bay that appears only on a
  held-out day would bias occupancy upward. Documented rather than hidden.

---

## What this does not claim

**Availability only.** Nothing here says a space is *legal* to park in. The
legality lane is separate, and a `HIGH` availability estimate must never upgrade
a `PROHIBITED` / `CONFLICT` / `UNKNOWN` legality verdict.

**Known residual bias.** Layer 1's worst cells are systematic, not random —
`Swanston St` weekend 11h–14h predicts `pFree` 0.37–0.42 against observed
0.65–0.67. With only 9 held-out dates the sample of weekend and event days is
small, and a time-of-day-only model cannot know about things that *changed*.
Widening the interval would hide this; the fix is more calendar features and a
longer archive, not a bigger error bar.

**Timezone.** Hours are UTC as labelled by the harvester. If a publisher's
timestamps are local, the hour axis is shifted and must be corrected before use.
Every response carries `timezoneCaveat`.

**Not a live feed by itself.** Layer 1 is climatological. Layer 2 is what makes
it live, and it needs a snapshot to do it.

---

## Implementation notes

- Continued-fraction incomplete beta (Lentz) + bisection inverse, stdlib only.
- `daily_cell` accumulation is hard-capped (`daily_cell_cap`, default 2M
  entries). Once capped, existing keys keep accumulating but no new keys are
  added; `perCellDatesCapped` reports it rather than silently degrading.
- `stayStatistics` (median/mean/p95) is carried on the model. The median is a
  reservoir sample capped at 50,000 durations — exact at 300k rows, impossible
  at 246M — and `medianMethod` records which.
- Overlapping same-bay events in a *real* archive would double-count fractional
  occupancy. The cell total is capped at its denominator, which bounds gross
  overflow but not per-slot overlap; a source with a high overlap rate should be
  treated as defective.
