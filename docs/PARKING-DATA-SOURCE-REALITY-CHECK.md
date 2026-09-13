# Parking Data Reality Check — where live occupancy actually comes from

**Record ID:** PTE-TEL-002
**Snapshot date:** 2026-09-13
**Extends:** [`REAL-PARKING-TELEMETRY-SOURCES.md`](REAL-PARKING-TELEMETRY-SOURCES.md) (PTE-TEL-001)
**Lane:** AVAILABILITY
**Legality claim made:** none. `legalityClaimed: false`.
**Companion:** [`AVAILABILITY-INFERENCE-HANDOFF.md`](AVAILABILITY-INFERENCE-HANDOFF.md) (PTE-INF-001)
**Revision:** 2 — corrected after external review. See [§7](#7-review-corrections-applied-rev-2).
**Commits:** `f6adcf0` (rev 1 research), `45ea555` (INF-001 rollback recipes, *not* research).
Rev 2 is a separate commit; `45ea555` contains only handoff-doc changes.

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
rather than published by them, and it is in a record shape close enough to the
harvester's normalised event to reuse the ingest path — **though it is not the
same measurement**, which is the most important correction in rev 2 (§2A).

And the Hull/Hong Kong findings are not obstacles. They are the two proof cases
for the product:

| City | What it has | What it proves |
|---|---|---|
| **Melbourne** | 246M real parking events, open licence | Ground truth exists somewhere — enough to *calibrate and validate* an inference engine |
| **Hong Kong** | live feed (coarse for many car parks), six competitors | Live relay is a **commodity**. Being seventh is not a business |
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
location code, start time, expiry time, fee paid, vehicle category
```

Note what that list does **not** contain: a departure. Payment data records the
session the driver *paid for*, whose end is the **expiry time implied by the
amount paid** — not the moment the car left.

It is close enough in shape to Melbourne's sensor archive (location, arrival,
departure, duration, restriction) that the same ingest and normalisation path can
carry it. **It is not the same measurement.** A ground sensor observes
*occupancy*; a payment record observes *paid sessions*. Those differ by every
vehicle that parks without paying through the app — resident and business permit
holders, free and waiting bays, paper-ticket buyers, Blue Badge users,
overstayers who have already gone, and anyone who does not pay at all. That is
**systematic missingness, not random noise**, and it varies by street and by
restriction type, which are precisely the dimensions the model is trying to
resolve. Calling it "structurally identical" to sensor data (as rev 1 did) is
**withdrawn**.

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
- **Hull confirms MiPermit on-street, not only in car parks.** Hull's own page
  (`hull.gov.uk/parking/mipermitcashless-parking`) states MiPermit is used for
  cashless parking at most council car parks **and on-street**; the council's
  privacy notice separately confirms MiPermit and Chipside as part of its parking
  system. This upgrades Hull from "inferred from a privacy notice" (rev 1) to
  **officially stated**.

#### It is not one integration, and it is not real-time

Rev 1 claimed *"one integration, every city."* That is **too strong and is
withdrawn.** What is evidenced is **one vendor** — RingGo — exposing a useful
common shape. Nothing yet establishes that MiPermit or PayByPhone produce the
same schema, the same contractual access model, the same retention, the same
granularity, or a compatible licence. The correct framing is a promising
**adapter family** of two or three integrations, not one universal adapter.

A specific reason to expect per-city work: RingGo's listing states *"Clients can
access data from **their parking locations only**."* Contractual scope is the
individual council's. There is no national aggregation available from any single
deal, so coverage is assembled council by council no matter how uniform the file
format turns out to be.

Nor is the feed live. RingGo's marketing says *"real-time"* about the **Insight
dashboards**. The documented feed into a council's own platform is a **daily
batch**: Hackney's published data-platform playbook describes RingGo uploading a
CSV of the **previous day's** data to an SFTP server, the file drop happening
*every afternoon*, named `data_warehouse_-YYYY-MM-DD.csv`, copied to a landing
zone by a scheduled lambda and converted to parquet by a Glue job.

That is exactly the right shape for the **climatological layer**, which is built
from historical sessions anyway — and it is **not a live occupancy sensor**. The
only live signal in RingGo's own materials is the **RingGo Enforcement API**,
which gives Civil Enforcement Officers *"complete, accurate and real time parking
session information enabling them to verify active parking rights"*. That is an
enforcement tool, not a general data API.

#### The idea is published and measured

Assemi, Paz & Baker (2021), *"On-Street Parking Occupancy Inference based on
Payment Transactions"*, **IEEE Transactions on Intelligent Transportation
Systems**, DOI [10.1109/TITS.2021.3095277](https://doi.org/10.1109/TITS.2021.3095277)
(QUT eprints 212460). They integrated bay-level occupancy snapshots captured with
simple cameras against transactions from a conventional parking payment
management system, then developed, calibrated and validated an occupancy
estimator **using payment data only**:

- data-integration accuracy **76%** (bay occupancy matched to the correct
  transaction)
- best occupancy model **R² above 94%**, **RMSE 1.2 occupied bays**
- relative occupancy computed at **15-minute intervals as accumulation ÷
  capacity**, per location

Two details in that paper matter more than the headline accuracy:

1. It independently confirms the expiry≠departure limit: their payment data
   carried *"parking session start and **expiry times (determined by the amount
   paid)**."*
2. **They needed cameras to obtain ground truth.** The occupancy snapshots used
   to integrate, calibrate and validate came from camera capture. That is the
   published method's dependency, and it is the same dependency that makes
   cold start (§3) the central risk rather than a footnote.

So class A is **evidenced, not speculative** — and the evidence simultaneously
shows what it cannot do alone.

**Routes in, in rough order of difficulty:** FOI request for aggregated exports;
a council partnership (they get demand insight they currently cannot produce);
direct commercial agreement with the payment provider; published transparency
datasets (some councils already post aggregates). Hackney's playbook is the
worked example of the SFTP/CSV pattern already operating in a UK council.

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

**Camden also publishes the bay inventory, which makes the test self-contained.**
`opendata.camden.gov.uk/d/t4s2-xa5a` ("Parking Bay Map") gives per bay:
approximate **length in metres**, approximate **number of spaces**, **restriction
type**, **times of operation**, **maximum stay**, **tariff**, **road name**,
**CPZ**, and **WKT polyline geometry**. Camden states its catalogue is
OGL-licensed and API-enabled.

So PCN events *and* capacity *and* restriction *and* tariff all come from one
publisher under one licence with **no procurement step at all**. That is what
makes the Camden experiment (§5, action 1) the right first test.

⚠️ Two geometry limits that constrain the experiment design: a "bay" is a run of
spaces and **individual parking spaces cannot be identified**; and the
lon/lat/easting/northing are *"automatically calculated based on an **arbitrary
node** along the polyline geometry"*. A spatial join between a PCN's CEO GPS point
and a bay is therefore imprecise at bay level — the join must be made at
**street / CPZ** level, not bay level.

### C. Static inventory and curb regulation — *the denominator, and it is widely available*

The inference engine needs bay counts before it needs anything live.
`totalSlots = bays × dates × slots_per_hour` — without `bays` there is no
probability, only a guess.

**Hull: the inventory exists, but Traffweb is not a lawful source for it.** Hull
City Council runs **Traffweb** (Causeway Technologies) at `hull.traffweb.app`,
publishing *"Controlled Parking Zone information, Resident and Business Parking
Bays or Parking Restrictions presently in operation in Hull City Council"*.
Causeway's own material adds camera sites, proposed traffic orders and
pay-and-display bays, with historical states selectable by date.

**Action 1 of §5 was run this turn. Result: negative.** The rendered page exposes
two button-driven sections (`/traffweb/1/TrafficOrders`,
`/traffweb/2/PublicConsultation`) and advertises no WFS/GeoJSON/API. Fetching
renders with scripts stripped, so an XHR endpoint cannot be ruled out from
outside — but none is discoverable without instrumenting the app in a browser,
and the site's own terms make that the wrong move:

> *"**PLEASE NOTE THIS SITE IS IN BETA MODE AND ALL DATA IS FOR TESTING PURPOSES
> ONLY**"*
>
> *"The restrictions and information shown on TraffWeb are based upon confirmed
> Traffic Orders. This information is regularly updated, but some temporary,
> experimental or other orders may not be shown. Any new restrictions, or notices
> of new restrictions displayed on-street, may supersede the information shown
> here. TraffWeb shows a **representation** of the legal orders, but it is the
> **order documents themselves** that provide the legal basis by which regulatory
> measures on the highway are enforced."*

These warnings must be retained wherever Traffweb is mentioned. **Traffweb cannot
be used as the denominator.** Its value is evidential: it shows Hull *holds* a
structured on-street bay and restriction inventory, and it is a convenient visual
reference for where things are. It is not citable bay data.

**The redirect that follows from the disclaimer:** the legally authoritative
inventory is Hull's **Traffic Order documents**. That is where the denominator
has to come from — via the council's traffic orders register, or an FOI request
for it. Slower than rev 1 hoped, but authoritative rather than beta. No scraping
workaround is to be attempted.

**Verified exemplar of what "good" looks like:** Camden's Parking Bay Map (§B) —
OGL, API-enabled, with capacity, restriction, operating times, maximum stay,
tariff, CPZ and geometry. Where a publisher does that, the denominator is free.

Also relevant: Melbourne publishes `sign-plates-located-in-each-parking-zone` and
`parking-zones-linked-to-street-segments` (see PTE-TEL-001), and Montréal has AMD
`Places.csv` / `Reglementations.csv`. Curb regulation plus segment geometry
yields a bay count arithmetically (a `2P 0800-1800` restriction over a 100 m
block implies roughly 16 bays) even where nobody publishes a bay layer. Camden
publishes bay length and space count directly, which removes the need to guess —
and wherever an arithmetic estimate *is* used it must be carried as an estimate,
never as an inventory.

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
with participating operators. But the official specification itself shows the
limits:

- `vacancy_type` **A** = availability with an actual number
- `vacancy_type` **B** = availability **without** an actual number — only `0`
  (full) / `1` (available)
- `vacancy_type` **C** = car park closed
- `vacancy = -1` = *"No data provided by the car park operator"*
- `lastupdate` **per record** — staleness is exposed in the payload

So a substantial share of HK car parks publish a **binary** signal, some publish
nothing, and every record carries its own age. On-street: the Transport
Department has sensors in new parking meters plus a trial at **about 250
non-metered on-street spaces** — small relative to HK's on-street inventory.

**The staleness claim needs correct attribution, and it is weaker than rev 1
stated.** The *"time lags ranging from hours to even months"* line comes from
LegCo question **LCQ22, 2017-12-13** (Innovation, Technology and Industry
Bureau), and it appears in the **question**, framed as *"some motorists have
pointed out"*. It is a legislator relaying a complaint — **not a government
finding** — and it is eight years old. It must not be quoted as a characterisation
of the current feed. Rev 1 did exactly that; **withdrawn.**

What the government's **reply** did establish is stronger evidence:

> *"The access control system and vehicle recognition system for the car parks
> managed by the TD have been in use for over ten years. As these systems could
> not support the function of automatic feeding of real-time parking space
> information, the car park operators **have to update manually** the car park
> information for the Hong Kong eRouting **on an hourly basis**."*

TD-managed car parks were **manually updated hourly** as of 2017, with a phased
replacement programme from 2018 requiring the supplier to feed parking space
information automatically in a prescribed format. So the historical weakness is
documented and admitted — but whether it survives that replacement programme is
**unknown from this source**.

**Therefore: measure it, do not cite it.** `lastupdate` is per-record and the API
needs no authentication, so current staleness is directly observable. Pulling the
feed and reporting the real distribution of `vacancy_type` and of `lastupdate`
ages replaces a 2017 complaint with a 2026 measurement (§5, action 3). That is
the only way this claim should be made.

**This is still the wedge — on evidence rather than anecdote.** Six apps relaying
a feed that is binary for some car parks, `-1` for others, and of unmeasured age
will agree with each other precisely when they are wrong. Freshness-weighted
fusion of that feed with climatology is a *different* product from a seventh
relay, and layer 2 already implements the mechanism, discounting each reading by
`w = 0.5 ** (age / median_stay)` using the `lastupdate` field HK already
provides. Whether stale-feed handling is *the* HK differentiator depends on the
measurement in action 3, not on a 2017 quotation.

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
| A. Cashless sessions | **Layer 1** (training archive) | Reuses the ingest path via a column mapping, but observes **paid sessions, not occupancy** — missingness must be modelled (§2A). Daily batch, not live |
| B. PCN / enforcement | **Layer 1** (relative pressure + overstay) | Positive-only bias; needs enforcement intensity to correct |
| C. Static inventory | **Layer 1 denominator** | Without it there is no probability. **Traffweb is beta/testing-only — not usable (§2C)**; Hull's Traffic Orders are authoritative. Camden's bay map is the OGL exemplar |
| D. Published anchors | **Layer 1 scale calibration** | Absolute fractions for cities with no sensors. Dated — re-verify |
| E. Live feeds | **Layer 2** | HK `vacancy_type` B is binary and `-1` means absent; use `lastupdate` for freshness weighting |
| F. Mesh | **Layer 2** over time | The only source that reaches every city |

Two consequences worth stating plainly:

1. **The engine does not need redesign for this.** Layer 1 consumes a normalised
   event archive and does not care whether arrival/departure came from a
   Melbourne in-ground sensor or a payment session; layer 2 already weights live
   readings by measured staleness. The work is **ingest adapters and bias
   modelling**, not new statistics. But "does not need redesign" is weaker than
   rev 1 implied: the *statistics* survive, the *measurement semantics* do not.
   A session expiry is not a departure, and a paid-session count is not an
   occupancy count, so the bias layer is new work rather than a column mapping.

2. **Cold start is the genuinely unsolved problem.** A city with inventory (C)
   and anchors (D) but no event history (A/B) has nothing to train on locally.
   The answer is transfer — learn the *shape* of demand from ground-truth cities
   as a function of restriction type, block character and land use, apply it with
   wide intervals, and narrow as local evidence accumulates. The
   empirical-Bayes prior/shrinkage machinery in layer 1 is already the right
   structure for this: the city-level prior is the transfer mechanism, and
   `shrinkageToPrior` already reports how much a thin street is leaning on it.
   **This is the highest-risk part of the plan and it is not yet built.**

   The published precedent makes the dependency explicit rather than
   hypothetical. Assemi et al. (§2A) achieved R² > 94% from payment data alone —
   **but only after calibrating against camera-captured bay-level occupancy.**
   The peer-reviewed version of this idea does not bootstrap from payments by
   itself; it needs an occupancy truth set to fit and validate against. A
   sensor-poor city with no truth set has no local way to calibrate the
   payment→occupancy mapping.

   So the split in §1 is load-bearing, not rhetorical:

   > **Melbourne and Hong Kong are calibration laboratories. Sensor-poor cities
   > are the actual inference problem.**

   And the consequence is commercial, not just technical. **If useful demand
   shape cannot be transferred from a ground-truth city to a sensor-poor city
   while still producing honest wide uncertainty bounds, this becomes a
   city-by-city data-procurement business rather than a generally transferable
   Parking Truth Engine.** That is the fork this experiment decides, and it
   should be decided before anything is promised to anyone.

---

## 4. Confidence and verification status

Recorded honestly, because the difference between these categories is the
difference between a plan and a hope. Rev 2 moved several items between them.

**Verified from primary sources** (publisher's own documents/specifications):
- RingGo Insight's session-data contents and CSV export; the **Enforcement API**
  description; and *"Clients can access data from their parking locations only"*
  — RingGo's G-Cloud listing
- **RingGo's feed to a council platform is a daily SFTP CSV batch of the previous
  day**, `data_warehouse_-YYYY-MM-DD.csv`, afternoon drop — Hackney Data Platform
  Playbook, "RingGo data ingestion"
- RingGo session record fields — RingGo privacy notice
- **Hull uses MiPermit for cashless parking at most council car parks *and
  on-street*** — `hull.gov.uk/parking/mipermitcashless-parking`
- Hull's data retention and enforcement suppliers (MiPermit, Chipside, SEA) —
  Hull City Council privacy notice
- **Hull Traffweb is explicitly beta and testing-only; Traffic Order documents are
  legally authoritative** — disclaimer text on `hull.traffweb.app` itself
- Camden PCN dataset contents, including `Spatial Accuracy` categories
  ("Civil Enforcement Officer GPS Location", "Fixed CCTV Camera", "Unknown") and
  OGL licence — Camden open data portal
- **Camden Parking Bay Map (`t4s2-xa5a`)**: bay length, approximate space count,
  restriction type, times of operation, maximum stay, tariff, road name, CPZ,
  WKT geometry; individual spaces not identifiable; coordinates from an
  *arbitrary node* on the polyline — Camden open data portal
- HK `carpark-info-vacancy` API, `vacancy_type` A/B/C semantics, `-1` meaning,
  per-record `lastupdate`, no authentication — TD *Parking Vacancy Data
  Specification*
- **TD-managed HK car parks were updated manually on an hourly basis as of 2017**
  because the access-control systems could not auto-feed; phased replacement from
  2018 — LegCo LCQ22 reply, 2017-12-13
- HK ~250 non-metered on-street sensor trial; meters with sensors — Transport
  Department
- **Payment-only occupancy inference is published and measured**: R² > 94%,
  RMSE 1.2 bays, 76% integration accuracy, requiring camera-captured ground
  truth — Assemi, Paz & Baker (2021), IEEE TITS, DOI 10.1109/TITS.2021.3095277

**Reported secondhand, plausible, needs primary confirmation:**
- ~250M UK cashless transactions/year — RingGo's submission to MPs, via press
- Hull ~20,000 PCNs/year (20,570 in 2023/24) — Hull Live FOI reporting
- **Whether MiPermit or PayByPhone match RingGo's schema, access model, retention,
  granularity or licensing** — nothing checked. This is what decides whether
  class A is an adapter family or three separate procurements

**Correctly attributed but *not* a finding — do not cite as evidence:**
- HK *"time lags ranging from hours to even months"* — a **motorist complaint
  relayed in a legislator's question** (LCQ22, 2017-12-13), eight years old. Not
  a government finding. Measure current staleness from `lastupdate` instead

**Dated and internally inconsistent — re-verify before use:**
- Hull 833 on-street spaces / 354 permit-holder occupancy / 110 blue-badge —
  **2014** strategy document; a 2021 document says "over 700"
- Hull car park capacities — 2014
- The 2017 HK manual-update position — superseded in principle by the 2018
  replacement programme; current state unknown

**Checked this turn, negative result:**
- **Hull Traffweb exposes no advertised machine-readable endpoint.** Rendered
  page offers only two button-driven sections; scripts are stripped so an XHR
  endpoint cannot be ruled out from outside, but none is discoverable without
  instrumenting the app — which the beta/testing-only disclaimer makes the wrong
  move. Redirect: Hull's Traffic Orders register

**Not yet checked at all:**
- Whether MiPermit offers a council-facing analytics product equivalent to RingGo
  Insight
- Which UK councils beyond Camden publish *transactional* (as opposed to
  aggregate) PCN data
- Whether any council has published aggregated cashless session data under FOI
  precedent
- The current HK `vacancy_type` distribution and real `lastupdate` ages

---

## 5. Next actions

Two experiments are **approved and deliberately bounded**. Both are stated with
their scope limits, because the limits are the point.

### Action 1 — Hull Traffweb probe · ✅ run this turn, negative

*Scope: determine whether the visible bay/restriction layer has a **lawful
machine-readable endpoint**. No scraping workaround.*

**Result:** no endpoint advertised; the site is explicitly beta with all data for
testing purposes only, and it defers legal authority to the Traffic Order
documents (§2C, §4). Recorded as a negative result rather than left open.

**Redirect:** Hull's on-street denominator must come from the **Traffic Orders
register** or an FOI request for it. Do not attempt to instrument Traffweb.

### Action 2 — Camden signal test · ⏳ approved, not yet run

*Scope: take **PCN events plus the Camden bay inventory** and test whether
street/time patterns correlate with an **independent parking-pressure proxy**.
**Do not call it occupancy until calibrated.***

Why Camden: PCN transactions and bay inventory (capacity, restriction, times,
max stay, tariff, CPZ, geometry) are both OGL and API-enabled from one publisher,
so the test needs no procurement. It is the cheapest available check on whether
class B carries real signal.

Design constraints that follow from the data, not from preference:
- join at **street / CPZ** level, not bay level — bay coordinates come from an
  *arbitrary node* on the polyline, and individual spaces are not identifiable
- use `Spatial Accuracy` to separate CEO-GPS observations from fixed-CCTV
  locations; report them **separately**, never pooled
- the output is a **relative pressure index**, and it stays one until an
  independent absolute anchor calibrates it
- the proxy must be genuinely independent of the PCN series, or the test is
  circular

### Remaining actions

3. **Measure HK staleness directly.** Pull `carpark-info-vacancy` and report the
   real distribution of `vacancy_type` and of `lastupdate` ages. Replaces the
   2017 complaint with a 2026 measurement and decides whether the
   freshness-fusion wedge is real.
4. **Test the adapter-family hypothesis.** Find MiPermit's and PayByPhone's
   council-facing data products and export schemas. Until this is done, class A
   is one evidenced vendor plus two assumptions.
5. **FOI test on cashless sessions.** Request aggregated, VRN-free session data
   (location code, start, expiry, fee) for one council. A refusal and its stated
   grounds are as informative as a yes, and cost nothing.
6. **Re-verify Hull's published occupancy anchors** against the current strategy
   document, logging the vintage on every figure.
7. **Design the cold-start transfer experiment** (§3, consequence 2). Train on
   Melbourne, predict Hull from inventory plus anchors alone, and report interval
   widths honestly. This decides whether the product is a transferable engine or
   a procurement business, so it should run before either experiment above is
   allowed to imply more than it shows.

---

## 6. The line to hold

Availability only. Nothing in this record makes an illegal, conflicted or unknown
curb legal, and no source class listed here — including enforcement records,
which are *about* illegality — may be used to infer legality. A PCN tells you a
car was there; it does not tell you a car may be there.

---

## 7. Review corrections applied (rev 2)

Rev 1 got ahead of its evidence in four places. Each is recorded here with what
replaced it, because the pattern is more useful than the individual fixes.

| # | Rev 1 claim | Status | Rev 2 position |
|---|---|---|---|
| 1 | *"One integration, every city"* — RingGo/MiPermit/PayByPhone all export the same CSV shape | **Withdrawn — too strong** | One *evidenced* vendor. A promising **adapter family**, not a universal adapter. RingGo's own *"clients can access data from their parking locations only"* guarantees per-council scope regardless of format uniformity |
| 2 | Payment sessions are *"structurally identical to Melbourne's sensor archive"* | **Withdrawn — overstates** | Payment observes **paid sessions, not physical occupancy**. Permits, free bays, cash tickets, Blue Badge, overstays and unpaid cars create **systematic missingness** that varies by street and restriction type. Modellable, but it **requires calibration**; session *expiry* is not *departure* |
| 3 | HK lags of *"hours to even months"* presented as fact | **Downgraded — misattributed** | A **motorist complaint relayed in a legislator's question** (LCQ22, 2017-12-13), not a government finding, eight years old. The verified admission is weaker and better: **manual hourly updates** for TD-managed car parks in 2017. Current staleness must be **measured** from `lastupdate` |
| 4 | Hull Traffweb listed as the on-street inventory source | **Downgraded — beta data** | Traffweb is *"IN BETA MODE AND ALL DATA IS FOR TESTING PURPOSES ONLY"* and defers authority to the **Traffic Order documents**. Useful as evidence that Hull holds the inventory; **not usable as the denominator** |

One reporting error, outside this document but worth recording: rev 1's summary
cited commit `45ea555` as the TEL-002 research commit. It is not. `45ea555`
changes only `docs/AVAILABILITY-INFERENCE-HANDOFF.md` (git-rollback recovery
recipes). **The research is `f6adcf0`.** Citing the tip of the branch instead of
the commit that contains the work makes a push look like proof it is not.

Also **added** in rev 2, on primary sources rev 1 had not found:

- **Hackney's RingGo ingestion playbook** — a UK council already running the
  SFTP/CSV pattern in production, which converts class A from hypothesis to
  precedent *and* establishes that the feed is **daily batch, not real-time**
- **Assemi, Paz & Baker (2021), IEEE TITS** — payment-only occupancy inference is
  published and measured (R² > 94%, RMSE 1.2 bays), and it **required
  camera-captured ground truth** to calibrate. This is the strongest single
  support for class A and simultaneously the strongest evidence that cold start
  (§3) is the central risk
- **Camden's Parking Bay Map (`t4s2-xa5a`)** — capacity, restriction, times,
  maximum stay, tariff, CPZ and geometry under OGL, which makes the enforcement
  test self-contained with no procurement
- **Hull's official confirmation that MiPermit covers on-street**, not only car
  parks — upgrading Hull from privacy-notice inference to a published statement

**The strategic conclusion survives review unchanged, and is now better
supported:** Melbourne and Hong Kong are calibration laboratories; sensor-poor
cities are the actual inference problem. If demand shape cannot transfer with
honest wide bounds, this is a city-by-city procurement business rather than a
transferable engine — and §5 action 7 is what decides it.

If action 2 shows signal, this record may have found the route around the problem
that repeatedly blocked Montréal: **historical inference from administrative
exhaust, instead of waiting for cities to install live sensors.** That is a
conditional, not a claim, and it stays conditional until the test is run.
