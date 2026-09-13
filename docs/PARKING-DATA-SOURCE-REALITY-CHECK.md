# Parking Data Reality Check — where live occupancy actually comes from

**Record ID:** PTE-TEL-002
**Snapshot date:** 2026-09-13
**Extends:** [`REAL-PARKING-TELEMETRY-SOURCES.md`](REAL-PARKING-TELEMETRY-SOURCES.md) (PTE-TEL-001)
**Lane:** AVAILABILITY
**Legality claim made:** none. `legalityClaimed: false`.
**Companion:** [`AVAILABILITY-INFERENCE-HANDOFF.md`](AVAILABILITY-INFERENCE-HANDOFF.md) (PTE-INF-001)

---

## 0. The question

Field research kept hitting the same wall:

- **Hull, England** — six large off-street car parks locatable, **no on-street data at all**
- **Hong Kong** — everything available, but **six companies already do it**
- **Cameras** — cannot find enough legal cameras pointed at parking spaces
- **Conclusion reached** — *"I'm not sure I can get enough free data to build my own telemetry"*

## 1. The short answer

**That conclusion is half right, and the wrong half is the expensive half.**

Right: live on-street occupancy data does not exist for most cities, is not free
where it exists, and never will be. Searching for it city by city will keep
returning nothing. That is a fact about the world, not a failure of research.

Wrong: the inference that therefore there is not enough data. The data exists —
it is simply not called "parking occupancy data", it is not live, and it is not
free. It is a **byproduct of payment and enforcement**, it is held by councils
rather than published by them, and it is in almost exactly the record shape the
harvester already normalises.

And the Hull/Hong Kong findings are not obstacles. They are the two proof cases
for the product:

| City | What it has | What it proves |
|---|---|---|
| **Melbourne** | 246M real parking events, open licence | Ground truth exists somewhere — enough to *calibrate and validate* an inference engine |
| **Hong Kong** | full live feed, six competitors | Live relay is a **commodity**. Being seventh is not a business |
| **Hull** | no live on-street data, no competitors | The actual market. Served by inference or not served at all |

**Hong Kong is not a market, it is a training set.** So is Melbourne. You do not
need to win in either. You need their ground truth to prove the inference works,
then transfer what you learned to the places nobody has instrumented — which is
where the margin is, because there is nothing there to relay.

---

## 2. Source classes, ranked by what they are actually worth

Ranked by value to the inference stack, not by how easy they are to find. The
easy ones are worth almost nothing.

### A. Cashless parking session data — *highest value, universally present, not open*

**This is the source that has been missed.** A pay-by-phone session record is:

```
location code, start time, end time, duration, fee, vehicle category
```

That is **structurally identical to Melbourne's sensor archive** — arrival,
departure, duration, restriction — except the sensor is the payment.

Evidence it exists at scale:

- **RingGo** told MPs there were roughly **250 million cashless parking
  transactions per year across the whole UK market**, and expected that to
  "dramatically increase" (submission reported 2024).
- RingGo's own privacy notice defines the session record as *"vehicle
  registration number, parking location, parking fee and **the start and end time
  of your parking session**."*
- **RingGo Insight**, the back-office product councils buy, provides
  *"historical and real-time secure access to parking session data including:
  Volumes (total, by location, by zone), Session costs, **Session lengths**,
  Refunds, **Location-data**, End-user statistics, Transaction and communication
  audit history."* Exportable as **CSV**, with date ranges and filters.
  (Source: RingGo's G-Cloud service listing — authoritative for what the product
  does.)
- Councils are replacing pay-and-display machines with cashless outright. Bromley
  removed **all** cash machines. Coverage is therefore high and rising.
- **Hull specifically uses MiPermit** as its cashless system (per Hull City
  Council's own privacy notice).

**Why this changes the problem.** It is not a scraping problem and not an open
data problem. It is a **procurement/partnership problem with a single repeating
pattern**: RingGo Insight, MiPermit, PayByPhone and their equivalents all export
the same CSV shape to the council that owns the contract. One integration, every
city. Councils already hold it, already export it, and already have a legal basis
for sharing aggregates (the personal data is the VRN, which is not needed for
occupancy inference).

**Honest bias.** Cashless sessions undercount by the share of drivers who still
buy a paper ticket from the machine, and they miss free/waiting bays entirely.
That share is shrinking, is roughly constant per street, and is correctable with
a scale factor — but it must be modelled, never ignored.

**Routes in, in rough order of difficulty:** FOI request for aggregated exports;
a council partnership (they get demand insight they currently cannot produce);
direct commercial agreement with the payment provider; published transparency
datasets (some councils already post aggregates).

### B. Enforcement byproducts — *real occupancy evidence, biased positive-only*

A Penalty Charge Notice proves **a vehicle was parked at that location at that
time**. That is an occupancy observation, produced by someone else's camera or
officer, legally, and often already published.

Best example found — **London Borough of Camden**, OGL-licensed, transactional,
still being updated:

> *"transactional penalty charge notice data... inclusive of PCNs issued by Civil
> Enforcement Officers on street and those issued by Civil Enforcement Officers
> via CCTV. Attribution includes **contravention code, ticket type, street,
> parking restriction, vehicle category and status of case**. Where possible, the
> approximate location of the PCN has been captured. The **'Spatial Accuracy'**
> column can be used to determine what level of location has been captured:
> **Civil Enforcement Officer GPS Location** = the GPS location reported by the
> CEO's handheld device; **Fixed CCTV Camera** = the location of the CCTV camera,
> this could be many metres from the vehicle in contravention; Unknown."*

That `Spatial Accuracy` column matters: it separates GPS-grade observations from
camera-location observations, which is exactly the distinction the legality lane
already refuses to guess about. Camden publishes per financial year
(2014-15 … 2023-24 plus current year). OpenDataNI publishes PCN data as CSVs
split on-street / off-street / moving traffic. The DfT's
`findtransportdata.dft.gov.uk` indexes these nationally.

**What PCN data can give you:**
- *relative* occupancy pressure by street, hour and day type — robustly, because
  the bias is roughly constant across those comparisons
- overstay behaviour, which informs the stay distribution directly
- which restriction types are under pressure (contravention code)
- enforcement intensity by street and time — which **is** the detection
  probability you need to correct the bias

**What it cannot give you:** absolute occupancy. PCNs are positive-only biased
sampling — you see violators, never compliant parkers. `PCN rate ≈ occupancy ×
violation rate × enforcement intensity`. You cannot invert that without an
anchor. Which is what C and D are for.

### C. Static inventory and curb regulation — *the denominator, and it is widely available*

The inference engine needs bay counts before it needs anything live.
`totalSlots = bays × dates × slots_per_hour` — without `bays` there is no
probability, only a guess.

**Hull: this exists and appears to have been missed.** Hull City Council runs
**Traffweb** from Causeway Technologies at `hull.traffweb.app` — a public
map-based service publishing *"Controlled Parking Zone information, Resident and
Business Parking Bays or Parking Restrictions presently in operation in Hull City
Council"*, plus pay-and-display bays and street inventory. Causeway's own
description notes users can select *"camera sites, proposed traffic orders or pay
and display parking bays"* and that historical states are selectable by date.

Whether it exposes a machine-readable endpoint (WFS/GeoJSON/API) rather than only
a rendered map is **not yet verified** — that is the first concrete thing to
check, and it determines whether Hull's on-street inventory is a download or a
FOI request.

Also relevant: Melbourne publishes `sign-plates-located-in-each-parking-zone` and
`parking-zones-linked-to-street-segments` (see PTE-TEL-001), and Montréal has AMD
`Places.csv` / `Reglementations.csv`. Curb regulation + segment geometry yields a
bay count arithmetically (a `2P 0800-1800` restriction over a 100 m block implies
roughly 16 bays) even where nobody publishes a bay layer.

### D. Published aggregate occupancy — *rare, dated, but these are absolute anchors*

Hull City Council's own parking strategy documents state numbers that are
directly usable as calibration anchors:

- **833 on-street parking spaces**, 76 disabled bays, 17 motorcycle bays (city
  centre, 2014 document)
- *"On average a total of **110** pay and display bays are occupied each day by a
  vehicle displaying a blue badge. Of the 833 on street pay and display bays an
  average of **354** are occupied on any given day by resident permit holders."*
- off-street capacities: Albion Street 260, Blanket Row 120, Francis Street 182,
  George Street 549, History Centre 51, Hull Arena 70
- a later (2021) parking strategy gives *"over 700 on-street spaces and over 70
  for people with disabilities"* within the city centre CPZ

⚠️ **These are dated and mutually inconsistent across vintages** (833 in 2014 vs
"over 700" in 2021). Treat every such figure as a lead requiring re-verification
against the current document, not as a fact. But note what they are: an
**absolute occupancy fraction for a city with zero sensors**. Two or three
numbers like that, combined with the *relative* variation from B, is enough to
pin the scale of a model. That combination is the actual technique for
sensor-poor cities.

Hull also publishes:
- `hull.gov.uk/open-data/parking-enforcement-statistics` — on/off-street PCNs,
  bus lane PCNs, recovery by month by contravention category
- monthly **"the 10 streets that attract the most penalty charge notices"** —
  street-level, which is more granular than most councils publish
- ~20,000 parking PCNs/year (20,570 in 2023/24, obtained by FOI after the
  published series lapsed at 2020/21)

### E. Live feeds where they exist — *coarser and staleness than assumed*

**Hong Kong is not actually saturated with good data.** The consolidated feed is
`https://api.data.gov.hk/v1/carpark-info-vacancy` — REST, JSON, **no
authentication**, merging Transport Department and Energizing Kowloon East Office
with participating operators. But the specification itself shows the limits:

- `vacancy_type` **A** = availability with an actual number
- `vacancy_type` **B** = availability **without** an actual number — only `0`
  (full) / `1` (available)
- `vacancy_type` **C** = car park closed
- `vacancy = -1` = *"No data provided by the car park operator"*
- `lastupdate` per record — **staleness is exposed in the payload**

So a substantial share of HK car parks publish a **binary** signal, some publish
nothing, and every record carries its own age. On-street: the Transport
Department has sensors in new parking meters plus a trial at **about 250
non-metered on-street spaces** — small relative to HK's on-street inventory.

And the staleness is documented at legislative level. A 2017 LegCo question
records that *"some motorists have pointed out that they could hardly rely on the
real-time parking vacancy data currently provided by the TD as the data often
suffer **time lags ranging from hours to even months**."*

**This is the wedge.** Six apps relaying a feed that is binary for many car
parks, `-1` for some, and hours-to-months stale will all show the same wrong
answer at the same time. Freshness-weighted fusion of a stale feed with
climatology is a *different* product from a seventh relay — and layer 2 already
implements exactly the mechanism, discounting each reading by
`w = 0.5 ** (age / median_stay)` using the `lastupdate` field HK already
provides. Stale-feed handling is not a nice-to-have in HK; it is the
differentiator.

### F. The mesh — *the only thing that scales to every city*

Every user who parks is a sensor. "Found a space here", "no spaces on this
block", and passive dwell detection from GPS traces are all telemetry events.
This is the Waze part of the comparison and it is the only source that reaches
cities with no council partnership, no published PCN data and no inventory layer.

It is also the slowest to matter and the easiest to overstate. It needs density
before it produces anything, and it needs the inference layer to be worth using
*before* density arrives — otherwise there is no reason to open the app. That is
precisely what A–E are for: they make the product useful on day one in a city
where the mesh is empty.

### Dead end: cameras you operate

**Stop looking for these.** There is no population of legally-available cameras
pointed at parking spaces at useful scale, and standing one up creates privacy,
GDPR/UK GDPR, signage and cost obligations that a startup should not own.

Note this is consistent with the existing decision in
[`PROJECT_STATUS.md`](PROJECT_STATUS.md): the camera lane is
**FROZEN — `CAMERA_FIXED_VIEW_PARTIAL`**, restartable only with independent
labelling, balanced ground truth, a frozen pipeline and measure-don't-tune
evaluation.

The inversion is the useful part: **you do not need cameras, you need the records
other people's enforcement already produces.** Camden's dataset has a `Fixed CCTV
Camera` location category — the camera exists, is legally operated by the
council, and its output is published as records under OGL. Hull is developing
camera enforcement of bus lanes; ANPR-based parking enforcement produces
entry/exit logs. Consume the byproduct, never the lens.

---

## 3. What this means for the inference stack

Mapping each source class onto the two layers in PTE-INF-001:

| Source | Feeds | Notes |
|---|---|---|
| A. Cashless sessions | **Layer 1** (training archive) | Same record shape as Melbourne. Drop into `telemetry_harvester.py` with a column mapping |
| B. PCN / enforcement | **Layer 1** (relative pressure + overstay) | Positive-only bias; needs enforcement intensity to correct |
| C. Static inventory | **Layer 1 denominator** | Without it there is no probability. Traffweb for Hull; curb regulation + geometry as fallback |
| D. Published anchors | **Layer 1 scale calibration** | Absolute fractions for cities with no sensors. Dated — re-verify |
| E. Live feeds | **Layer 2** | HK `vacancy_type` B is binary and `-1` means absent; use `lastupdate` for freshness weighting |
| F. Mesh | **Layer 2** over time | The only source that reaches every city |

Two consequences worth stating plainly:

1. **The engine does not need redesign for this.** Layer 1 consumes a normalised
   event archive and does not care whether arrival/departure came from a
   Melbourne in-ground sensor or a RingGo session. Layer 2 already weights live
   readings by measured staleness. The work is **ingest adapters and bias
   modelling**, not new statistics.

2. **Cold start is the genuinely unsolved problem.** A city with inventory (C)
   and anchors (D) but no event history (A/B) has nothing to train on locally.
   The answer is transfer — learn the *shape* of demand from ground-truth cities
   as a function of restriction type, block character and land use, apply it with
   wide intervals, and narrow as local evidence accumulates. The
   empirical-Bayes prior/shrinkage machinery in layer 1 is already the right
   structure for this: the city-level prior is the transfer mechanism, and
   `shrinkageToPrior` already reports how much a thin street is leaning on it.
   **This is the highest-risk part of the plan and it is not yet built.**

---

## 4. Confidence and verification status

Recorded honestly, because the difference between these categories is the
difference between a plan and a hope.

**Verified from primary sources** (publisher's own documents/specifications):
- RingGo Insight's session-data contents and CSV export — RingGo's G-Cloud listing
- RingGo session record fields — RingGo privacy notice
- Hull uses MiPermit; Hull's data retention and enforcement suppliers — Hull City
  Council privacy notice
- Camden PCN dataset contents, including `Spatial Accuracy` categories and OGL
  licence — Camden / DfT Find Transport Data / data.gov.uk
- HK `carpark-info-vacancy` API, `vacancy_type` A/B/C semantics, `-1` meaning,
  no authentication — OGCIO *Parking Vacancy Data Specification* v1.2
- HK ~250 non-metered on-street sensor trial; meters with sensors — Transport
  Department
- Hull Traffweb exists and publishes CPZs, bays, restrictions — `hull.traffweb.app`
  and Causeway Technologies

**Reported secondhand, plausible, needs primary confirmation:**
- ~250M UK cashless transactions/year — RingGo's submission to MPs, via press
- HK feed lag "hours to even months" — 2017 LegCo question; **eight years old**,
  may have improved
- Hull ~20,000 PCNs/year — Hull Live FOI reporting

**Dated and internally inconsistent — re-verify before use:**
- Hull 833 on-street spaces / 354 permit-holder occupancy / 110 blue-badge —
  **2014** strategy document; a 2021 document says "over 700"
- Hull car park capacities — 2014

**Not yet checked at all:**
- Whether Hull Traffweb exposes machine-readable data (WFS/GeoJSON/API) or only a
  rendered map ← **the single highest-value next check**
- Whether MiPermit offers a council-facing analytics product equivalent to RingGo
  Insight
- Which UK councils beyond Camden publish *transactional* (as opposed to
  aggregate) PCN data
- Whether any council has published aggregated cashless session data under FOI
  precedent

---

## 5. Next actions

1. **Probe `hull.traffweb.app` for a machine-readable endpoint.** Determines
   whether Hull's on-street inventory is a download or a FOI request. Highest
   value, lowest effort.
2. **Download Camden's transactional PCN series** (2014-15 → current year) and
   run it through the harvester. It is OGL, it is real, and it is the only
   immediately-obtainable enforcement-byproduct dataset confirmed to have street
   + restriction + GPS-accuracy fields. Proves whether class B actually carries
   usable signal before asking anyone for anything.
3. **Pull the HK carpark feed** and measure the real distribution of
   `vacancy_type` and `lastupdate` ages. If a large share is type B or stale, the
   freshness-fusion wedge is quantified rather than assumed.
4. **FOI test on cashless sessions.** Request aggregated, VRN-free session data
   (location code, start, end, duration) for one council. The answer — including
   a refusal and its stated grounds — tells you whether class A is a partnership
   play or a dead end, cheaply.
5. **Re-verify Hull's published occupancy anchors** against the current strategy
   document, and log the vintage on every figure.
6. **Design the cold-start transfer experiment.** Train on Melbourne, predict
   Hull from inventory + anchors alone, and measure the interval widths honestly.
   This is the riskiest assumption in the plan and should be tested before it is
   promised to anyone.

---

## 6. The line to hold

Availability only. Nothing in this record makes an illegal, conflicted or unknown
curb legal, and no source class listed here — including enforcement records,
which are *about* illegality — may be used to infer legality. A PCN tells you a
car was there; it does not tell you a car may be there.
