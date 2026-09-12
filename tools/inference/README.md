# Availability Inference Engine

`availability_engine.py` — estimates **P(a bay is free right now)** by fusing
whatever evidence exists, and reports how much that number should be trusted.

This is the inference layer, not a parking app. It does not relay sensors. It
answers "to the best of our ability, is there a space?" — and when the answer is
"we don't know", it says **UNKNOWN** instead of guessing.

Stdlib Python only. No numpy, no scipy, no network.

---

## Why this exists

Most cities have no parking sensors. Even cities that do have them publish
coverage for a fraction of their kerbside. A product that only works where a
municipal feed exists is a product that only works in a handful of places, and
in those places it competes with dozens of apps relaying the same feed.

The differentiator is inference: take historical archives, static bay inventory,
restriction metadata, time-of-day patterns and (where available) live sensors,
and produce a **calibrated probability** with an honest interval. That works on
a street nobody has ever instrumented.

## The three-state contract

Every answer is one of:

| State | Meaning | Gate |
|---|---|---|
| `HIGH` | Confidently free / confidently not | lower 95% bound of P(free) > 0.35 **and** ≥ 20 effective bay-slots **and** ≥ 12 distinct days |
| `LIMITED` | A real estimate, but the interval is wide | ≥ 5 distinct days, gate not cleared |
| `UNKNOWN` | Insufficient evidence | anything thinner, or no cell for that street/hour |

`HIGH` uses the **lower bound** of the interval, never the point estimate. A
confident-looking number from thin data cannot reach `HIGH`.

This is not cosmetic. On held-out data the label predicts its own accuracy:

```
HIGH       cells= 70   MAE=0.008
LIMITED    cells=170   MAE=0.022
```

A `HIGH` answer is ~2.75× more accurate than a `LIMITED` one. The confidence
tier carries real information rather than being decoration.

---

## Usage

```bash
# 1. build a model from a harvested event archive
python3 availability_engine.py build \
    --events archive/telemetry-events.jsonl \
    --out model.json \
    --prior-strength 30

# 2. query it
python3 availability_engine.py predict \
    --model model.json --street "Bourke St" --at "2026-09-15T15:30"

# 3. prove it works — score against dates the model never saw
python3 availability_engine.py validate \
    --events archive/telemetry-events.jsonl \
    --holdout 0.2 --report validation.json
```

Input is the normalized event stream from
[`../telemetry/telemetry_harvester.py`](../telemetry/telemetry_harvester.py).

---

## How it estimates

One cell per **(street, day type, hour)** — 24 × 2 = 48 cells per street.

1. **Denominator reconstruction.** An event archive only records bays that were
   *occupied*. The empty slots — which are the whole point — are missing. They
   must be rebuilt from inventory × calendar:

   ```
   totalSlots = distinct_bays(street) × distinct_dates(street, dayType) × slots_per_hour
   ```

   Getting this wrong is fatal and silent: counting only slots that appear in an
   event makes `occupied == total`, pins P(occupied) at 1.0, and reports "no
   space anywhere, ever". This was the first bug validation caught.

2. **Empirical-Bayes Beta posterior.** Each cell gets a Beta posterior. The prior
   comes from the city-level aggregate for that day type and hour, so a street
   with three observations is pulled toward the city pattern instead of
   reporting a wild number. `shrinkageToPrior` records how much.

3. **Overdispersion.** Bay-slots are **not** independent trials. One parking
   event covers many consecutive 15-minute slots, and demand varies day to day
   far more than a binomial allows. The factor φ is *measured*, not assumed:

   ```
   φ = observed between-date variance of the daily occupancy rate
       ÷ the variance a binomial would predict
   ```

   Measured per cell where ≥ 5 dates exist, else the city-level estimate. On the
   test archive φ ranged 1.0 – 140.3, median 4.7. Applied quasi-binomially:
   successes and failures are both divided by φ, which preserves the point
   estimate and inflates the variance.

4. **Two different uncertainties.** The subtle one. Conflating these produced
   badly overconfident intervals:

   - `sdMeanEstimate` — how well the cell's *average* is known. Shrinks with
     more evidence. This is the Beta posterior width.
   - `sdBetweenDays` — how far a *given day* departs from that average. Does
     **not** shrink with more evidence; it is a property of the street and hour.

   The product predicts a **future day**, so the published interval carries both:

   ```
   sdPredictive = √(sdMeanEstimate² + sdBetweenDays²)
   ```

   On the test archive `sdMeanEstimate` median 0.0087 vs `sdBetweenDays` median
   0.0325 — day-to-day variation dominates by ~4×. A Beta posterior alone was
   ~4× too confident.

5. **Unmeasurable dispersion gets a floor, never zero.** With too few dates, φ
   cannot be estimated. Falling back to `sd = 0` would publish a razor-thin
   interval built on almost no evidence — precisely the false certainty this
   engine exists to avoid. Instead a conservative `DEFAULT_SD_DAY = 0.10` floor
   applies and `sdDaySource` records `"default-floor(not-measurable)"`.

   The difference on a 2-date, 160-slot cell:

   ```
   before:  HIGH      P(free)=0.702  CI [0.637, 0.766]   ← confidently wrong
   after:   UNKNOWN   P(free)=0.702  CI [0.495, 0.908]   ← honest
   ```

6. **Graceful degradation.** A street with no observations at all falls back to
   the city prior for that hour and returns `UNKNOWN` with
   `usedCityPriorFallback: true` and `shrinkageToPrior: 1.0`. It never invents a
   street-level answer.

---

## Measured accuracy

Test archive: 319,009 rows → 306,582 events kept, 12,427 rejected
(7,664 negative duration, 4,761 imputed times, 2 implausible stay). 5 streets,
45 dates (2019-03-04 → 2019-04-17), 240 cells. 36 dates trained, 9 held out.

```
Brier                     : 0.00066
Brier (constant baseline) : 0.06025
Brier skill score         : +0.9890
log loss                  : 0.44189
mean absolute error       : 0.0180
95% CI coverage           : 0.971     (target ~0.95)
```

Reliability — predicted vs actually observed P(free) on held-out dates:

```
pred 0.10-0.25  n= 14  pred=0.220  obs=0.197  gap=-0.024
pred 0.25-0.40  n= 16  pred=0.310  obs=0.288  gap=-0.022
pred 0.40-0.55  n= 23  pred=0.477  obs=0.458  gap=-0.019
pred 0.55-0.70  n= 51  pred=0.623  obs=0.617  gap=-0.007
pred 0.70-0.85  n= 41  pred=0.781  obs=0.782  gap=+0.001
pred 0.85-1.00  n= 95  pred=0.946  obs=0.946  gap=+0.001
```

Every bin within 2.4 points of observed. MAE 0.018 means P(free) is right to
roughly ±2 points. Skill score +0.989 means it beats "say the same number
everywhere" almost perfectly.

Coverage arrived in stages, and each stage was a real correction:

| Interval method | 95% coverage |
|---|---|
| Beta posterior on raw slots | 0.304 |
| + city-level φ | 0.725 |
| + per-cell φ | 0.667 |
| + between-day dispersion in quadrature | **0.971** |

Per-cell φ *alone* made coverage worse — that was the clue that the Beta
posterior was answering the wrong question (uncertainty about the mean, not
about a future day).

0.971 is slightly over-covering. That is the right side to err on: intervals a
touch too wide cost nothing; intervals too narrow produce confident wrong
answers that a driver acts on.

### Known residual bias

The worst cells are systematic, not random:

```
Bourke St   weekday 15h  pred=0.650  obs=0.565   (+0.085)
Bourke St   weekday 16h  pred=0.690  obs=0.582   (+0.108)
Bourke St   weekday 17h  pred=0.735  obs=0.658   (+0.077)
```

Bourke St is over-predicted in the late afternoon across all held-out dates.
The 45-day window does not capture whatever drives that — a seasonal shift, a
nearby event venue, or construction. This is the honest limit of a
time-of-day-only model: it cannot know about things that changed. Widening the
interval hides it; the fix is more calendar features and a longer archive, not a
bigger error bar.

---

## Validation methodology

Hold-out is **by date**, never by row. Rows from the same day share weather,
events and demand; splitting them randomly leaks and inflates every score.
Dates are shuffled with a fixed seed (`--seed 1337`) so runs are reproducible.

The held-out denominator reuses the **same bay inventory** the model trained on.
Taking it only from held-out events would silently drop bays that were empty on
every held-out day, shrinking the denominator and overstating observed
occupancy — making the estimator look worse than it is.

Bay inventory *is* drawn from all events including held-out dates. That is
deliberate: inventory is static infrastructure, not an outcome. Excluding a bay
that happens to appear only on a held-out day would bias occupancy upward.
Documented rather than hidden.

---

## What this does not claim

**Availability only.** Nothing here says a space is *legal* to park in. The
legality lane is separate and a `HIGH` availability estimate must never upgrade
a `PROHIBITED` / `CONFLICT` / `UNKNOWN` legality verdict. Both facts have to
hold before a driver is sent anywhere.

**Timezone.** Hours are UTC as labelled by the harvester. If a publisher's
timestamps are local, the hour axis is shifted and must be corrected before use.
Every response carries `timezoneCaveat`.

**Not a live feed.** This is a climatological model — it predicts what a street
usually does at 15:00 on a weekday. Fusing it with a live sensor reading is the
next step, not something it does today.

---

## Implementation notes

- Continued-fraction incomplete beta (Lentz) + bisection inverse, stdlib only.
- `daily_cell` accumulation is hard-capped (`daily_cell_cap`, default 2M
  entries). Once capped, existing keys keep accumulating but no new keys are
  added; `perCellDatesCapped` reports it rather than silently degrading.
- Cells with < 5 dates fall back to the city-level φ and are labelled as such.
