# PTE Telemetry Harvester

**Real** parking arrival/departure telemetry, from openly licensed municipal
sources, without ever storing a multi-GB blob.

```
telemetry_harvester.py probe     which API shape actually works?
telemetry_harvester.py live      poll a live sensor feed, diff it, emit transitions
telemetry_harvester.py archive   stream a historical parking-EVENT archive
```

Stdlib only. Python 3.8+. Nothing to install.

**Why:** ~246 million real parking events already exist, openly licensed, from the
City of Melbourne — one row per event with arrival time, departure time,
duration, restriction and overstay flag, spanning 2014–2020. You do not need to
generate this data. Full findings, source table and the publisher's own documented
defect list are in
[`docs/REAL-PARKING-TELEMETRY-SOURCES.md`](../../docs/REAL-PARKING-TELEMETRY-SOURCES.md).

Every event written conforms to
[`schemas/parking-telemetry-event-schema.json`](../../schemas/parking-telemetry-event-schema.json)
and carries `legalityClaimed: false`. **Availability lane only.**

---

## Start here

```bash
cd tools/telemetry

# 1. Find out which endpoint actually works. Do not skip this.
python3 telemetry_harvester.py probe \
    --base https://data.melbourne.vic.gov.au \
    --dataset on-street-parking-bay-sensors

# 2. Smallest real archive: 258 MB, 14.2M real 2020 parking events.
#    Streams to a temp dir OUTSIDE the repo, hashes, then deletes.
python3 telemetry_harvester.py archive --year 2020-jan-may \
    --max-emit 250000 --out out/archive

# 3. Real near-live transitions, derived by diffing snapshots.
python3 telemetry_harvester.py live --interval 20 --minutes 60 \
    --limit 5000 --out out/live
```

---

## Modes

### `probe` — endpoint discovery

Tries five API shapes in order and reports which respond, with the field list and
the resolved column map for each:

| Shape | Example |
|---|---|
| Opendatasoft explore v2.1 | `/api/explore/v2.1/catalog/datasets/{ds}/records` |
| Opendatasoft v2 records | `/api/v2/catalog/datasets/{ds}/records` |
| Opendatasoft records v1.0 | `/api/records/1.0/search/?dataset={ds}` |
| Opendatasoft v2 export | `/api/v2/catalog/datasets/{ds}/exports/json` |
| Socrata SODA v2.0 | `/resource/{ds}.json` |

This exists because portals migrate. Melbourne moved **off Socrata**: the
`/resource/vh2v-4nfs.json` endpoint that older tutorials and this project's own
prior notes point at now returns **HTTP 404**. Anything hardcoded against it is
already broken. Run `probe`, then record the working URL in `manifests/`.

Exits non-zero if nothing worked.

### `archive` — historical parking events

One input row = one real parking event. Accepts `--year` (a known City of
Melbourne archive), `--url`, or `--file`. Handles `.zip`, `.gz` and plain `.csv`,
and auto-detects `;` or tab delimiters.

| Flag | Purpose |
|---|---|
| `--year 2020-jan-may` | shortcut for a known archive; builds the export URL |
| `--max-emit N` | cap rows written to JSONL (default 250,000) |
| `--max-rows N` | stop reading after N rows |
| `--reservoir N` | size of the representative event sample embedded in stats |
| `--keep-download` | retain the archive instead of deleting it |
| `--progress-every N` | log every N rows |

Two things worth understanding:

- **Statistics cover every row; only the file is capped.** Percentiles,
  hour-of-day, weekday, restriction, street and defect counts are computed across
  the entire stream. `--max-emit` only bounds what lands on disk.
- **The retained sample is reservoir-sampled**, so it is representative of the
  whole stream rather than being the first N rows. Important when the archive is
  sorted by date or street.

### `live` — poll and diff into transitions

The live feed publishes **state**, not events. This mode manufactures an event
stream from it:

- `Free → Occupied` ⇒ `ARRIVAL`
- `Occupied → Free` ⇒ `DEPARTURE`
- anything touching `Restricted` / `Unofficial` / a faulted sensor ⇒
  `STATUS_UNKNOWN_TRANSITION` — recorded, never coerced to FREE or OCCUPIED

| Flag | Purpose |
|---|---|
| `--interval SEC` | poll interval (default 20) |
| `--minutes N` | how long to run |
| `--limit N` | records per poll — raise if the city has more bays than this |
| `--url` | skip discovery, use an explicit endpoint |

**Read the caveat before analysing the output.** A bay occupied *and* vacated
entirely between two polls is invisible, so short stays are systematically
undercounted and the bias grows with the poll interval. That is inherent to
diffing a state feed, not a bug. Every event therefore carries
`timeConfidence: "DERIVED"` and an `observationWindowSeconds` bound instead of a
false-precision timestamp.

Source health is computed as `lag = pollTime − max(lastupdated)` and mapped to
`FRESH` / `STALE` / `DEGRADED`, because the publisher explicitly warns the feed
goes through network relays and can be disrupted.

---

## Output

```
out/archive/telemetry-events.jsonl   normalised events (bounded)
out/archive/archive-stats.json       aggregates over ALL rows + defect counts
out/archive/archive-manifest.json    URL + SHA-256 + bytes + rows (repo policy)

out/live/live-transitions.jsonl      derived ARRIVAL/DEPARTURE events
out/live/latest-snapshot.json        most recent full bay state
out/live/live-harvest-stats.json     polls, errors, health, aggregates, caveats
```

Example event:

```json
{
  "eventType": "PARKING_EVENT",
  "sourceMode": "historical-archive",
  "bayKey": "M-200000",
  "sourceId": "melbourne-2020-fixture",
  "street": "Collins St",
  "restriction": "1P",
  "overstay": false,
  "arrivalTime": "2020-03-11T02:14:07Z",
  "departureTime": "2020-03-11T02:31:52Z",
  "durationSeconds": 1065.0,
  "durationMinutes": 17.75,
  "timeConfidence": "OBSERVED",
  "dataQuality": [],
  "legalityClaimed": false
}
```

---

## Data quality: counted, never silently fixed

The City of Melbourne documents four defects in its own archives. The harvester
flags every occurrence on the event and tallies it in `aggregate.dataQualityDefects`.
None are coerced, dropped without counting, or "cleaned" invisibly.

| Flag | Meaning | Do not |
|---|---|---|
| `negative_duration` | Sensor detected arrival *after* departure. A real fault. | `abs()` it or clamp to 0 |
| `missing_times_imputed` | Times were reconstructed from **midnight**, not observed | include in stay-duration medians |
| `sign_old_suffix` | Restriction changed after the event, or the sensor was replaced | use the row to validate legality |
| `cross_year_excluded` | Publisher drops events crossing 31 Dec | assume the distribution is uncensored |
| `overstayed` | Publisher's overstay flag | treat as a legality verdict |
| `unknown_status_transition` | Status changed to/from a neither-free-nor-occupied value | infer FREE or OCCUPIED |

`timeConfidence` is the field that keeps these honest. Its values — `OBSERVED`,
`EPOCH`, `DERIVED`, `IMPUTED`, `UNPARSEABLE`, `MISSING` — mean that **any
hour-of-day or stay-duration analysis must stratify on it**, or it will silently
mix real sensor timestamps with midnight-derived fiction.

---

## Tolerant column mapping

Municipal schemas drift between years and portals. Columns are resolved through an
alias table (`COLUMN_ALIASES` in the source) and the tool **prints what it mapped
and what it could not** rather than failing on an unexpected header.

So the first run against a new year reveals that year's real schema. If a
canonical name you need shows up under `unmapped`, add the alias — that is the
intended extension point.

---

## Verified

Against a purpose-built 24,000-row fixture reproducing Melbourne's documented
column names and defect rates:

- 16/16 columns mapped; only genuinely-absent names reported unmapped
- injected defects recovered exactly — `negative_duration` 649 detected vs 648
  expected at 1/37, `missing_times_imputed` 453 vs 453 at 1/53
- stay distribution recovered the generator's lognormal: median 9.08 min vs 9.07
  expected; 140.68-day range
- `.zip` streamed and hashed without extracting to disk; `;`-delimited variant
  auto-detected

Against a mock Opendatasoft portal:

- `probe` identified 3 of 5 endpoint shapes as live and recommended one
- `live` ran 9 polls over 120 bays and derived **66 real transitions** with
  `observationWindowSeconds: 2.0`, `timeConfidence: DERIVED`, zero errors
- two bays forced to `Restricted` / `Unofficial` correctly counted as UNKNOWN and
  never coerced

**Not verified:** the real Melbourne endpoints and real archive bodies — this
sandbox's bash has no outbound network. That is what `probe` is for.

---

## Storage policy

Per `README.md`, large reproducible public data is referenced by
`URL + retrievedAt + bytes + SHA-256`, not stored as bytes. This tool enforces
that in code rather than in prose:

- downloads go to a temp dir **outside the repository**
- the archive is SHA-256 hashed **while streaming**, so the hash exists even
  though the bytes are discarded
- the download is **deleted** on completion unless `--keep-download`
- only bounded derived artifacts are written to `--out`
- `archive-manifest.json` is written in the repository's manifest format, ready to
  paste into `manifests/`

This matters concretely: the 2014 archive alone is 1.56 GB, which on a
storage-constrained development machine is the difference between a usable
workflow and an unusable one.

`out/` is gitignored. If a particular harvest becomes evidence for a specific
finding, promote it deliberately under `sources/` or `evidence/` with a hash and a
manifest entry — do not let it accumulate by accident.
