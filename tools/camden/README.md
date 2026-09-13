# Camden signal harness — PTE-TEL-003

Deterministic test of one question: **do Camden PCN event patterns contain a
reproducible street/time parking-pressure signal?**

It answers PASS, PARTIAL or FAIL, and it emits a **relative pressure index** —
never occupancy, never a probability of finding a space, never a confidence
percentage.

Record: [`docs/CAMDEN-SIGNAL-HARNESS.md`](../../docs/CAMDEN-SIGNAL-HARNESS.md)
Schema: [`schemas/camden-pressure-signal-schema.json`](../../schemas/camden-pressure-signal-schema.json)

---

## Status

**Built and self-tested. Not yet run against real Camden data.**

The self-test proves the pipeline's arithmetic and proves it detects each failure
mode it claims to detect. It does **not** prove the field mappings against a live
Camden export, because column spellings in the real download have not been
verified. See *Running on real data* below.

---

## Quick start

```bash
cd tools/camden

# 1. Self-test: 14 checks, no network, ~35 s
python3 run_selftest.py

# 2. Generate a fixture from known latent processes
python3 make_camden_fixture.py --out-dir /tmp/cam \
        --scenario demand-dominated --manifest /tmp/cam/manifest.json

# 3. Run the signal test on it
python3 camden_signal_test.py \
        --bays  /tmp/cam/bays.csv \
        --pcn   /tmp/cam/pcn.csv \
        --proxy /tmp/cam/proxy.csv \
        --out   /tmp/cam/report.json

# 4. Inspect a download's field resolution without running the test
python3 camden_sources.py --bays bays.csv --pcn pcn.csv --report resolve.json
```

Stdlib only. Python 3.11. No network access anywhere: adapters read local files,
so a download is a reproducible artefact rather than a side effect.

---

## Modules

| File | Deliverable | Role |
|---|---|---|
| `camden_sources.py` | 1 | Source adapters. Reads local CSV/JSON, resolves column names from candidates, stamps provenance, keeps the verbatim source row |
| `camden_normalize.py` | 2 | Deterministic normalisation. Temporal features, Spatial Accuracy strata, contravention classification |
| `camden_aggregate.py` | 3, 4 | Street/CPZ aggregation, stratification, sparse grid, exposure denominators |
| `camden_pressure.py` | 5 | Relative pressure index, concentration diagnostics, the forbidden-semantics guard |
| `camden_signal_test.py` | 7 | The five fail criteria, the verdict, the report |
| `make_camden_fixture.py` | 6 | Synthetic fixture from known latent demand + deployment processes |
| `run_selftest.py` | 6 | Grades the harness against truth it did not create |

---

## How the scope constraints are enforced

Every constraint from the approved scope is enforced by code, not by convention.

| Constraint | Enforcement |
|---|---|
| Join at street/CPZ, **never** bay level | No bay identifier or coordinate exists in a cell key. `assert_no_bay_level_join()` raises if any cell gains one. `joinLevel` enum has no `BAY` member |
| Preserve Spatial Accuracy strata separately | `STRATA` is a dimension of every cell. `CEO_GPS`, `FIXED_CCTV`, `UNKNOWN_OTHER` never share a cell |
| Never pool strata unless a report shows the effect | `pool_strata()` is the only route and stamps `pooledFrom` on its output. Nothing pools by default |
| Unrecognised publisher values must not hide | `map_spatial_accuracy()` returns an `UNRECOGNISED` disposition, and the raw value plus its count is reported verbatim |
| Capacity only where the publisher supplies it | `spaceCount` is `None`, never `0.0`, when absent. Zero spaces and unknown spaces mean different things to a rate |
| Preserve approximate-capacity flags | `capacityIsApproximate` propagates from bay → street → index entry → report. For Camden it is always true |
| Hours never imputed | A date-only PCN yields `hourKnown: false` and is excluded from hourly diagnostics. It never lands in bucket 0. `hourImputationPerformed` is asserted false |
| Output a relative index only | `assert_no_forbidden_semantics()` walks the emitted report and raises on any key containing `occupanc`, `probabilit`, `vacanc`, `availability`, `confidence`, `pFree`, etc. |
| No fake confidence percentages | Same guard. Negations are expressed as a value list (`doesNotClaim`) because a key named `isOccupancy: false` would trip the check meant to stop `occupancy: 0.62` |
| Independent proxy must not come from the PCN series | The harness cannot verify this; it is an operator assertion and is stamped as such. `--validation-route none_known` triggers F4 |
| Determinism | Sorted iteration everywhere, fixed rounding, no wall clock (`asOf` defaults to the max date in the data), seeded RNG. Same flags → same bytes |

The forbidden-semantics guard caught two of its author's own keys during
development (`isOccupancy`, `outputIsRelativeIndexNotOccupancy`). Both were
negations. That is the guard working, not a false positive: a namespace in which
denials are spelled with the forbidden vocabulary is a namespace one careless
edit away from asserting them.

---

## Verdict semantics

Five fail criteria, taken from the approved scope:

| ID | Criterion | Test |
|---|---|---|
| F1 | Signal dominated by enforcement deployment rather than parking demand | Prohibition-share dominance **and** the index rising with prohibition mix across streets |
| F2 | Results collapse when CEO GPS events are isolated | Spearman(all-strata ranking, CEO-GPS-only ranking) below threshold |
| F3 | Insufficient geographic / time coverage | Distinct streets, distinct dates, capacity coverage fraction, CEO-GPS share |
| F4 | No independent validation route | Three states: supplied / available-but-not-supplied / none-known |
| F5 | Unstable rankings across comparable periods | Spearman(first-half ranking, second-half ranking), split by chronological date halves |

- **FAIL** — any criterion triggered
- **PASS** — none triggered **and** an independent proxy supplied **and**
  `Spearman(index, proxy)` at or above threshold
- **PARTIAL** — none triggered but the PASS bar not met. In practice this means no
  proxy was supplied, so the output is descriptive signal characterisation only

Thresholds live in `DEFAULT_THRESHOLDS` and are overridable per run with
`--threshold NAME=VALUE`. A verdict whose cut-offs are buried in code cannot be
argued with; these are printed into every report.

---

## The central limitation

**PCN data alone cannot separate parking demand from enforcement deployment.** A
PCN is issued where an officer or camera looks *and* where a driver contravenes.
`PCN rate ≈ occupancy × violation rate × enforcement intensity`, and this harness
removes only the street-size term by dividing by capacity. The other two terms
remain entangled.

The F1 indicators narrow that ambiguity. Nothing computed from PCN data alone
resolves it. Only an independent proxy does — which is why F4 is a fail criterion
rather than a footnote, and why a run with no proxy is capped at PARTIAL.

A signal that correlates only with itself is not evidence.

---

## Scenarios

The fixture generates events from two **separate** latent processes — demand and
enforcement deployment — mixed in caller-controlled proportions, so the harness
can be graded against truth it did not create.

| Scenario | Latent mix | Expected |
|---|---|---|
| `demand-dominated` | demand 1.0, deployment 0.05, proxy supplied | PASS |
| `deployment-dominated` | demand 0.10, deployment 1.0, prohibition-heavy | FAIL F1 |
| `gps-biased` | CCTV on deployment streets, demand anti-correlated with deployment | FAIL F2 |
| `sparse-coverage` | 6 streets, 12 dates | FAIL F3 |
| `no-validation-route` | clean demand signal, `--validation-route none_known` | FAIL F4 |
| `drifting` | regime change at the midpoint | FAIL F5 |
| `demand-dominated-noproxy` | clean signal, no proxy supplied | PARTIAL |

`gps-biased` needed one non-obvious fix. With demand and deployment multipliers
drawn independently, the same streets topped both the all-strata and the
CEO-GPS-only rankings, so Spearman stayed high even though the magnitudes
diverged. **F2 tests order collapse; rescaling is not collapse.** The scenario now
anti-correlates the two multipliers so isolating CEO GPS genuinely reorders the
streets — and the observed rho goes to −0.30.

The fixture also reproduces the messy parts of a real export on purpose: PCNs with
a date but no time, an unrecognised `Spatial Accuracy` value, PCN streets absent
from the bay inventory, and bays with no publisher space count.

**The fixture is not real data.** Every number it produces describes the fixture.

---

## Running on real data

1. Download from [`opendata.camden.gov.uk`](https://opendata.camden.gov.uk/):
   the **Parking Bay Map** (`t4s2-xa5a`) and the **PCN series** (current plus
   historical financial years). Both OGL.
2. Inspect resolution before trusting anything:
   ```bash
   python3 camden_sources.py --bays bays.csv --pcn pcn.csv --report resolve.json
   ```
   Read `fieldMap`, `ambiguousFieldMatches`, `unresolvedOptionalFields`,
   `unconsumedSourceFields` and `spatialAccuracyValuesObserved`. A required field
   that fails to resolve raises rather than guessing.
3. Pin any mismatch with a field map — no code edit needed:
   ```json
   { "bay-map":   { "spaceCount": "Number Of Spaces" },
     "pcn-series": { "spatialAccuracy": "Spatial Accuracy " } }
   ```
   ```bash
   python3 camden_signal_test.py --bays bays.csv --pcn pcn.csv \
           --field-map fields.json --out report.json
   ```
4. **Without a proxy, expect PARTIAL at best.** That is the correct result, not a
   weak one. Candidate independent proxies must not be derived from the PCN
   series; if none can be found, declare `--validation-route none_known` and
   accept the FAIL rather than manufacturing a route.

`--field-map` is accepted by both `camden_sources.py` and
`camden_signal_test.py`, and takes the same file in both. It is applied only when
passed explicitly — nothing is auto-discovered from the input directory. The
overrides used are echoed into the report at `inputs.fieldMapOverrides` so a run
is reproducible from the report alone.

Verified behaviour: with a bay file whose `Road Name` and `Number of Spaces`
columns are renamed to strings no candidate matches, the harness exits non-zero
with `could not resolve required field(s)` rather than substituting a plausible
column. Supplying the field map for those two columns returns it to PASS.

---

## Hard boundaries

- **Availability-adjacent research lane.** Nothing here makes a legality claim;
  `legalityClaimed: false` throughout. A PCN says a car *was* there. It never says
  a car *may* be there.
- The legality kernel is not modified, imported or consulted.
- PTE-007 / PTE-008 evidence is untouched.
- The camera lane stays frozen. This harness consumes other people's published
  enforcement records; it operates no lens.
- No individual-space occupancy is inferred. Camden states individual spaces
  cannot be identified; the join refuses to pretend otherwise.
- Nothing is deployed and nothing is merged to main.
- Existing data is never overwritten: outputs go to new paths, and
  `tools/camden/.gitignore` keeps fixtures, downloads and reports out of git.
