# PTE-TEL-004 — Camden full-data CPZ result handoff

Status: **VALID EXPERIMENTAL RESULT = PARTIAL**

This file records the local full-data run performed after remote preflight commit `83a33d4e97e0e4702c59e99dae960bc401038dd8`. It is intentionally a small Git-visible manifest/handoff. The large Camden CSVs and generated local intermediates remain outside Git.

## Source files

- Camden Parking Bays dataset `7hiv-3r9k`
  - local file: `camden-parking-bays-7hiv-3r9k.csv`
  - rows: `8,789`
  - SHA-256: `0DFB2CE039EF4ED6D62589BD796FB4BE6D60FE8633566E2CC7009F6EB884EE0A`
- Camden PCN dataset `4k7m-4gkk`
  - local file: `camden-pcns-4k7m-4gkk.csv`
  - rows: `495,814`
  - SHA-256: `1C57FE1DFBC21CB347CE4FEFA37F5EDF211E4B6B67BD05CFDBC3296C09917820`

The actual `rows.csv` export headers were observed locally in Title Case before calculation. The approved external field map resolved:

- bays: `Parking Spaces`, `Parking Bay Length Metres`, `Controlled Parking Zone`
- PCNs: `Contravention Code Description`, `Controlled Parking Zone Area`, `Street`

After the field map, the material fields were resolved with no remaining PCN ambiguity. Bay `wkt` remained deliberately unresolved; PCN `parkingRestriction` and `pcnReference` remained deliberately unresolved.

## C3/C4A preparation

The authoritative London Councils code map remained unchanged.

Observed pre-run exception rows:

- 56 `NOT_PARKING` rows leaked through `CCTV TMA`:
  - `29J` one-way restriction: 46
  - `38L` must-pass-left: 6
  - `33G` local-buses-only route: 4
- 8 rows carried `Contravention Code = 11GWN`, publisher suffix `G`, description `Warning Notice - Parked without payment of the parking charge`.

The 8 `11GWN` rows were canonicalized to `11G` only after exact suffix/description checks, with the original code preserved in a separate column. This is input canonicalization, not a taxonomy or threshold change. Re-preparation then mapped all `495,814` source rows with `unmapped = 0`.

Final C3 gate required both:

1. ticket type in `O/S TMA` or `CCTV TMA`; and
2. authoritative `Parking Contravention = Yes`.

Final included population: `317,341` rows.

Final filtered CSV SHA-256: `3379EC47F67CCE58982CB8B59243FEFE4A00EAD9FF4BC2FF66E55A8935F224AC`.

Class counts entering the run:

- `MIXED`: 89,660
- `PROHIBITION_ENTITLEMENT`: 128,537
- `TURNOVER_PAYMENT`: 99,144

## Invalid first attempt — do not quote as a FAIL

An initial CPZ report had SHA-256:

`99DDBE8DB8FDDB431A2DA77B77F1EC4006DF936446A0A952B5F3D312124D8B5C`

That attempt is **INVALID_RUN_DATE_FORMAT**, not an experimental FAIL. Camden exported timestamps such as `28/01/2026 12:51:58 PM`, while the frozen parser accepted 24-hour `dd/MM/yyyy HH:mm:ss` but not the AM/PM form. The invalid attempt therefore produced 0 distinct dates and 100% unknown hours, making its downstream F2/F3/F5 triggers non-evidentiary.

No threshold, taxonomy or classifier was changed in response.

## C7 temporal normalization

A local-only format normalization converted the exact Camden 12-hour timestamp representation to an equivalent parser-supported ISO local wall-clock representation. No timezone conversion was performed and the original timestamp was preserved.

- input rows: `317,341`
- converted rows: `317,341`
- unmatched rows: `0`
- input SHA-256: `3379EC47F67CCE58982CB8B59243FEFE4A00EAD9FF4BC2FF66E55A8935F224AC`
- normalized output SHA-256: `07F4C799BEC221A75E1DA4B41E20659981890706591D52C353721F0F54A430CF`
- frozen parser result: `317,341 / 317,341 PARSED_DATETIME`
- distinct dates: `527`
- hour known: `317,341`
- hour unknown: `0`

## Valid CPZ result

Generated report local path:

`S:\Parking-Truth-Engine\sources\camden\downloads\camden-signal-CPZ-C7-v2.json`

Report SHA-256:

`313707FF0F3A943037A43F5E35E626B33885FB6E6C76BAEB34385C4F6D3A21DA`

Verdict: **PARTIAL**.

No approved hard fail criterion triggered. PASS remains unreachable in this run because no independent proxy was supplied.

### F3 coverage — PASS

- distinct CPZ join keys: `19` (minimum 10)
- distinct dates: `527` (minimum 28)
- capacity coverage fraction: `1.0` (minimum 0.5)
- CEO-GPS share: `0.899647` (minimum 0.05)
- PCN events unplaceable: `0`
- PCN hour unknown share: `0.0`
- inventory keys with no events: `0`

### F5 repeatability — PASS

Chronological split-half comparison:

- first half: 263 dates, 164,176 PCNs
- second half: 264 dates, 153,165 PCNs
- comparable CPZs: 19
- Spearman rho: `0.975439`
- threshold: `0.50`

Interpretation: the CPZ pressure ranking repeats strongly across comparable periods.

### F2 stratum isolation — PASS

- CEO-GPS CPZs with index: 19
- Fixed-CCTV CPZs with index: 9
- all-strata vs CEO-GPS Spearman rho: `0.945614` across 19 CPZs
- all-strata vs Fixed-CCTV Spearman rho: `0.0` across 9 CPZs
- threshold for headline isolation test: `0.50`

Interpretation: the headline ranking survives CEO-GPS isolation. The Fixed-CCTV divergence is a useful warning about camera/deployment effects but does not collapse the CEO-dominated headline ranking.

### F1 deployment-dominance diagnostics — PASS

- prohibition share overall: `0.405044` (threshold 0.50)
- class shares:
  - `AMBIGUOUS`: `0.282535`
  - `PROHIBITION_TYPE`: `0.405044`
  - `TURNOVER_TYPE`: `0.312421`
- raw-vs-capacity-normalized Gini gap: `0.033139` (threshold 0.25)
- Spearman(index, prohibition share): `-0.019298` across 19 CPZs (threshold 0.40)

No deployment-dominance indicator triggered. This does **not** prove demand causation; PCN data alone cannot separate enforcement attention from driver behavior.

### F4 independent validation

- state: `AVAILABLE_NOT_SUPPLIED`
- triggered: false
- verdict cap: `PARTIAL`

PASS requires an operator-asserted independent proxy and proxy correlation meeting the frozen threshold. No proxy was supplied in this run.

## Interpretation boundary

The defensible result is:

> Camden PCN administrative exhaust contains a geographically and temporally repeatable **relative** CPZ-level signal that survives CEO-GPS isolation, but this run does not establish that the signal equals physical parking occupancy, vacancy, probability of finding a space, availability, legality, or calibrated confidence.

Do not tune thresholds/taxonomy/classification against this result. Do not upgrade PARTIAL to PASS without an independent proxy.

## Known reporting defect, deferred

The report still emits `classificationIsHeuristic: true` in the contravention-mix metadata even though C4A classification uses the authoritative code table. Treat this as stale metadata only; the observed counts are the authoritative-table classes above. Fix after the result is preserved, not before.

## Smallest next research action

Find an independent Camden proxy and test it without changing the frozen thresholds. Highest-value candidate remains a genuinely independent payment/session or other occupancy-adjacent signal that can be joined at an honest spatial/temporal level. Any proxy must have its own provenance, license, freshness and independence assessment before use.

## Repository / governance note

This manifest records local outputs so browser/LMArena workers can continue from the same evidence. The raw full Camden files and large generated intermediates remain local/gitignored. No legality-kernel change, deployment, merge to `main`, threshold change, taxonomy change, or classifier tuning is authorized by this record.
