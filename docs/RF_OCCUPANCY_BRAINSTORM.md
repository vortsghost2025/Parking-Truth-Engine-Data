# RF Occupancy Brainstorm

Status: exploratory idea, not validated

Date: 2026-09-14

## Goal

Explore a zero-infrastructure / low-cost way to infer whether a parking space or curb segment is physically occupied without identifying a vehicle, phone, driver, or device.

The desired output is intentionally simple:

- likely occupied
- likely empty / possible parking
- unknown

The system does **not** need to know what object is present or who owns it. Identity is irrelevant to the parking decision.

## Core idea

Do not depend on every parked vehicle continuously transmitting Bluetooth or Wi-Fi.

Instead, test whether a vehicle can be detected indirectly because a large metal object changes the local radio environment. A parked vehicle can alter attenuation, multipath, RSSI, SNR, and related channel measurements between known radios.

That turns the question from:

> Is this specific car/device transmitting?

into:

> Has the RF environment across this parking space or curb segment changed in a way consistent with a large physical obstruction?

This could potentially work even when the parked vehicle has no useful active radio emissions.

## Possible signal sources

### 1. Meshtastic / LoRa links

Use known trusted mesh nodes as fixed or semi-fixed radio references.

Collect simple link observations such as:

- RSSI
- SNR
- packet delivery / loss
- persistence of a changed link state
- change relative to an empty-space baseline

Meshtastic would also be useful for carrying tiny occupancy events rather than streaming raw RF telemetry.

Example event:

```text
segment=17
state=likely_occupied
confidence=0.82
timestamp=...
```

### 2. Passive Bluetooth / Wi-Fi presence

Bluetooth or Wi-Fi activity can be used only as an additional weak vote.

Do not store stable device identifiers or try to determine what device or vehicle produced a signal.

A short-lived RF spike could be a pedestrian, passing vehicle, adjacent apartment, passenger, or neighbouring parked car, so passive radio presence by itself should not decide occupancy.

A sustained local change is more useful than a single detection.

### 3. Opt-in app beacons

A future Parking Truth client could emit rotating, short-lived, application-specific beacons.

These would indicate only that a participating client is nearby. They should not expose a persistent identity.

Potentially useful events include:

- approach
- park / stop
- departure
- user reports leaving a space

These events could raise or lower occupancy confidence but should not be required for the base system.

## Transition-focused detection

Transitions may be more useful than static snapshots.

Examples:

```text
baseline RF state
-> persistent obstruction-like RF change
-> remains stable for 20+ minutes
= probable arrival / occupied state
```

and:

```text
persistent obstruction-like RF state
-> abrupt return toward baseline
-> remains clear
= probable departure / possible vacancy
```

A brief transient spike with no persistent RF change should be treated as passing traffic/noise rather than a parking event.

## Evidence fusion

RF occupancy should be only one input to the Parking Truth Engine.

Potential combined record:

```text
segment_id
legal_now
rf_obstruction_score
recent_arrival_score
recent_departure_score
mesh_votes
historical_availability_prior
municipal_live_signal
user_report_signal
confidence
state
```

Example user-facing result:

```text
Possible parking
Confidence: 84%
Legal now: yes
RF obstruction: low
Recent departure evidence: strong
Mesh corroboration: 2 nodes
Historical availability: favourable
```

The product should prefer probabilistic language unless direct ground-truth occupancy data is available.

## Trust / compromised-node handling

Reuse the same general ideas already proven in the offline-mesh work:

- signed observations
- replay protection
- short-lived events
- per-node trust scores
- independent corroboration
- anomaly detection / impossible churn
- down-weight suspicious nodes instead of allowing one node to decide truth
- optional veto / quorum for high-confidence state changes

A single node should not be able to flip a curb segment from occupied to empty with high confidence.

## Privacy posture

This concept should deliberately avoid identity-level tracking.

Useful data is physical-state evidence, not device identity.

Prefer:

- anonymous aggregate signal changes
- short-lived observations
- no persistent MAC/device storage
- no attempt to identify vehicle make, owner, phone, or person

The useful question is only whether something consistent with a vehicle appears to occupy the space.

## Cheapest validation experiment

Before building a larger system, validate the physics with one controlled curb/parking test.

Suggested experiment:

1. Place two known radios with a repeatable path crossing or bordering one parking space / small curb segment.
2. Record RSSI/SNR and packet quality with the space empty.
3. Park one vehicle in the target area.
4. Record the same measurements.
5. Remove the vehicle and repeat.
6. Repeat 30-50 arrival/departure cycles across different vehicle sizes and times if possible.
7. Compare empty vs occupied distributions.
8. Test whether a simple classifier can distinguish empty, occupied, and unknown without using any device identity.

Do not optimize the full app before this experiment shows a repeatable separation.

## Current working hypothesis

A free parking-availability system may be feasible by combining:

**anonymous physical RF presence inference + legal-parking rules + historical patterns + mesh corroboration + any municipal live data that happens to exist**

rather than depending on public cameras or city-installed parking sensors everywhere.

This would keep the architecture city-agnostic and allow stronger signals to plug in where available without making them mandatory.

## Important caveat

This is brainstorming, not a proven design.

The first engineering gate is empirical: determine whether the RF signature of an occupied curb segment is repeatable enough in real streets to be useful after accounting for passing traffic, pedestrians, nearby buildings, weather, radio orientation, and neighbouring vehicles.
