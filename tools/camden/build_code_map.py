#!/usr/bin/env python3
"""Authoritative London contravention-code map + declaration audit (PTE-TEL-004 C4).

WHY THIS EXISTS
---------------
The frozen PTE-TEL-003 harness classifies contraventions by matching KEYWORDS in
a code plus its description. Camden's real `contravention_code` values are numeric
with suffixes - `33H`, `52M`, `12R`, `11` - which contain no keywords, so every
real row would classify UNCLASSIFIED, indicator I2 could never trigger, and fail
criterion F1 (signal dominated by enforcement deployment rather than parking
demand) could NEVER FIRE. Because decide_verdict() reads a non-firing criterion
as not-triggered, the harness could return PASS having never tested the central
confound.

This file fixes that WITHOUT touching the frozen harness, by supplying better
INPUT DATA:

  * the authoritative London Councils description for every base code, which the
    frozen keyword classifier can actually match against
  * our own PRE-DECLARED pressure class for every base code, with a rationale,
    committed before any Camden row is read
  * an audit that checks whether the frozen classifier, run on the authoritative
    description, reproduces the declared class - and reports every disagreement

THE DECLARATION IS OURS, NOT LONDON COUNCILS'
----------------------------------------------
London Councils says what a contravention MEANS. It does not publish a
"parking-pressure class" taxonomy, and none is implied by the code list. Which
codes count as turnover/payment-related versus prohibition/entitlement-related
for the purposes of F1 is a judgement we make, declare in advance, and justify
per code. That declaration is frozen here so it cannot be revised after a result.

SOURCE
------
London Councils, "Penalty Charge Notices: Contravention Code List", document
footer "PCN Codes v7.0 4 31 May 2022", retrieved 2026-09-13 from
londoncouncils.gov.uk (2025-03 webpage-version PDF). Descriptions below are
transcribed verbatim from that document.

TWO AUTHORITATIVE SIGNALS FOUND IN THE SOURCE THAT WE DID NOT EXPECT
--------------------------------------------------------------------
1. The `Diff. level` column is "n/a" for exactly the moving-traffic and bus-lane
   codes. That is an INDEPENDENT parking-vs-moving-traffic discriminator which
   corroborates correction C3 (35.9% of Camden's rows are not parking) from a
   source that has nothing to do with Camden's `ticket_type` field.
2. General suffix `j` means **camera enforcement**: "Suffix 'j' identifies a
   contravention that can be used on highways other than red routes using CCTV."
   A suffix is therefore an authoritative DEPLOYMENT marker, carried in the code
   itself. The frozen harness does not use it, and per the freeze protocol it
   must not be made to; it is recorded here as the highest-value candidate for a
   future pre-registered amendment.

    python3 build_code_map.py --emit  ../../../sources/camden/london-councils-contravention-codes-v7.0.json
    python3 build_code_map.py --audit
    python3 build_code_map.py --prepare pcn-raw.csv --out pcn-prepared.csv

STDLIB ONLY. Deterministic: same flags -> same bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from camden_normalize import (  # noqa: E402  FROZEN - do not edit
    classify_contravention,
    PROHIBITION_CODE_HINTS,
    TURNOVER_CODE_HINTS,
)

ARTIFACT_VERSION = "1.0.0"
SOURCE_TITLE = "Penalty Charge Notices: Contravention Code List"
SOURCE_PUBLISHER = "London Councils (Transport and Environment Committee)"
SOURCE_CODE_VERSION = "PCN Codes v7.0"
SOURCE_CODE_EFFECTIVE = "2022-05-31"
SOURCE_URL = ("https://www.londoncouncils.gov.uk/sites/default/files/2025-03/"
              "Penalty%20Charge%20Notices%20Contravention%20Code%20List%202025%20"
              "%28Webpage%20Version%29%20%281%29.pdf")
RETRIEVED = "2026-09-13"

# ---------------------------------------------------------------------------
# Declared pressure classes. This taxonomy is OURS.
# ---------------------------------------------------------------------------

CLASS_TURNOVER = "TURNOVER_PAYMENT"
CLASS_PROHIBITION = "PROHIBITION_ENTITLEMENT"
CLASS_MIXED = "MIXED"
CLASS_NOT_PARKING = "NOT_PARKING"
CLASS_RESERVED = "RESERVED"

# Mapping from our declaration onto the frozen harness's own labels, so the audit
# compares like with like.
DECLARED_TO_HARNESS = {
    CLASS_TURNOVER: "TURNOVER_TYPE",
    CLASS_PROHIBITION: "PROHIBITION_TYPE",
    CLASS_MIXED: "AMBIGUOUS",
    CLASS_NOT_PARKING: "EXCLUDED_BEFORE_CLASSIFICATION",
    CLASS_RESERVED: "EXCLUDED_BEFORE_CLASSIFICATION",
}

CLASS_RATIONALE = {
    CLASS_TURNOVER: (
        "Duration or payment at a place where parking is otherwise permitted. "
        "Frequency scales with how many drivers want the space and for how long, "
        "so it tracks DEMAND."),
    CLASS_PROHIBITION: (
        "Location or entitlement: the driver had no right to be there at all. "
        "Frequency depends on where enforcement looks as much as on demand, so it "
        "is DEPLOYMENT-SENSITIVE."),
    CLASS_MIXED: (
        "Official text combines an entitlement violation with a payment or expiry "
        "violation in one code. Cannot be assigned to either side without "
        "inventing a distinction the source does not make."),
    CLASS_NOT_PARKING: (
        "Moving traffic, bus lane, speeding or route-permit contravention. Not a "
        "parking event at all; excluded by pre-registered correction C3 before "
        "any analysis. Corroborated by Diff. level = n/a in the source."),
    CLASS_RESERVED: "Code reserved by the source for another scheme; never issued as a parking contravention.",
}

# General suffix legend, transcribed verbatim from the source.
SUFFIX_LEGEND = {
    "a": "permit holder only electric vehicle charging bay",
    "b": "business bay",
    "c": "buses only",
    "d": "doctor's bay",
    "e": "car club bay",
    "f": "free parking bay",
    "g": "motorcycle bay",
    "h": "hospital bay",
    "i": "wrong type of voucher",
    "j": "camera enforcement",
    "k": "ambulance bay",
    "l": "loading place",
    "m": "parking meter",
    "n": "red route",
    "o": "blue badge holder",
    "p": "pay & display",
    "q": "market traders' bay",
    "r": "residents' bay",
    "s": "shared use bay",
    "t": "voucher/P&D ticket used in permit bay",
    "u": "electronic payment",
    "v": "voucher",
    "w": "e-scooter bay",
    "x": "disabled bay",
    "y": "electric solo motorcycle bay",
    "0": "local buses / trams only",
    "1": "electric vehicles bay",
    "2": "goods vehicle loading bays",
    "3": "bicycle bay",
    "4": "virtual permit",
    "5": "dedicated disabled bay",
    "6": "hotel bay",
    "7": "taxis only",
    "8": "zero emission capable taxis only",
    "9": "electric vehicle car club bay",
}

# Code-specific suffixes, transcribed verbatim from the source's "Suffixes and
# Additional Notes". These OVERRIDE the general legend, because the same letter
# means different things on different codes: general 'h' is "hospital bay" but on
# code 33 it is "local buses and cycles only"; general 'm' is "parking meter" but
# on code 52 it is "motor vehicles". Resolving a suffix from the general legend
# alone therefore reports a confidently wrong meaning for exactly the
# high-volume moving-traffic codes Camden emits.
CODE_SPECIFIC_SUFFIXES = {
    "01": {"a": "temporary traffic order"},
    "02": {"a": "temporary traffic order"},
    # Permit contraventions (codes 01, 12, 16, 19 and 85) only
    "12": {"w": "wrong parking zone", "x": "incorrect VRM",
           "y": "obscured/illegible permit", "z": "out of date permit"},
    "16": {"w": "wrong parking zone", "x": "incorrect VRM",
           "y": "obscured/illegible permit", "z": "out of date permit"},
    "19": {"w": "wrong parking zone", "x": "incorrect VRM",
           "y": "obscured/illegible permit", "z": "out of date permit"},
    "85": {"w": "wrong parking zone", "x": "incorrect VRM",
           "y": "obscured/illegible permit", "z": "out of date permit"},
    # Taxi ranks (code 45) only
    "45": {"w": "amends the contravention code description to change the wording "
                "from 'stopped' to 'waiting'"},
    # Footway parking (codes 61, 62, 64, 65 and 66) only
    **{c: {"1": "one wheel on footway", "2": "partly on footway",
           "4": "all wheels on footway", "c": "on vehicle crossover",
           "g": "on grass verge"}
       for c in ("61", "62", "64", "65", "66")},
    # Moving traffic contraventions only
    "32": {"d": "proceeding in the wrong direction", "t": "turning in the wrong direction"},
    "33": {"b": "buses only", "c": "buses and cycles only",
           "e": "buses, cycles and taxis only", "f": "buses and taxis only",
           "g": "local buses only", "h": "local buses and cycles only",
           "i": "local buses, cycles and taxis only", "k": "local buses and taxis only",
           "q": "tramcars and local buses only", "r": "tramcars only",
           "s": "tramcars and buses only", "y": "pedal cycles only",
           "z": "pedal cycles and pedestrians only"},
    "38": {"l": "must pass to the left", "r": "must pass to the right"},
    "50": {"l": "no left turn", "r": "no right turn", "u": "no U-turn"},
    "52": {"b": "buses", "g": "goods vehicles exceeding max gross weight indicated",
           "m": "motor vehicles", "s": "solo motorcycles",
           "v": "all vehicles except non-mechanically propelled ones being pushed",
           "x": "motor vehicles except solo m/cycles"},
    "53": {"c": "amends the description to add 'and cycle' after the word pedestrian"},
    "54": {"c": "amends the description to add 'and cycle' after the word pedestrian"},
}

# Suffix 'j' is authoritative evidence of CCTV deployment. Recorded, NOT used by
# the frozen run.
CAMERA_ENFORCEMENT_SUFFIX = "j"
CAMERA_SUFFIX_NOTE = (
    "Source: \"Suffix 'j' identifies a contravention that can be used on highways "
    "other than red routes using CCTV. The suffix itself is not required on a "
    "PCN.\" This is an authoritative deployment marker carried in the code "
    "itself. The frozen harness does not read it and, under the freeze protocol, "
    "must not be changed to. Recorded as the highest-value candidate for a future "
    "pre-registered amendment, because it would let F1 test deployment directly "
    "instead of inferring it from code mix.")

# ---------------------------------------------------------------------------
# The authoritative code table.
# (code, general suffixes, description verbatim, diff level, section, declared
#  class, declaration rationale)
# ---------------------------------------------------------------------------

T = CLASS_TURNOVER
P = CLASS_PROHIBITION
M = CLASS_MIXED
N = CLASS_NOT_PARKING
R = CLASS_RESERVED

CODES: list[tuple[str, str, str, str, str, str, str]] = [
    # --- On-street parking -------------------------------------------------
    ("01", "ajoyz", "Parked in a restricted street during prescribed hours", "Higher", "ON_STREET", P,
     "Location entitlement: no right to wait there at all during prescribed hours."),
    ("02", "ajo", "Parked or loading / unloading in a restricted street where waiting and loading / unloading restrictions are in force", "Higher", "ON_STREET", P,
     "Location entitlement during a waiting or loading restriction."),
    ("04", "cs", "Parked in a meter bay when penalty time is indicated", "Lower", "ON_STREET", T,
     "Duration at a permitted meter bay; penalty time is an overstay condition."),
    ("05", "cgpsuv1", "Parked after the expiry of paid for time", "Lower", "ON_STREET", T,
     "Pure overstay of paid time at a permitted place - the most direct demand-duration signal."),
    ("06", "cipv1", "Parked without clearly displaying a valid pay & display ticket or voucher", "Lower", "ON_STREET", T,
     "Payment compliance at a permitted pay-and-display place."),
    ("07", "cgmprsuv", "Parked with payment made to extend the stay beyond initial time", "Lower", "ON_STREET", T,
     "Meter feeding: extending a stay. Directly about duration demand."),
    ("08", "c", "Parked at an out-of-order meter during controlled hours", "Lower", "ON_STREET", T,
     "Payment mechanism failure at a permitted place; turnover-side."),
    ("09", "ps", "Parked displaying multiple pay & display tickets where prohibited", "Lower", "ON_STREET", T,
     "Duration control at a permitted place."),
    ("10", "p", "Parked without clearly displaying two valid pay and display tickets when required", "Lower", "ON_STREET", T,
     "Payment compliance for a longer stay at a permitted place."),
    ("11", "gu", "Parked without payment of the parking charge", "Lower", "ON_STREET", T,
     "Non-payment at a place where parking is permitted for a charge. Demand-side: the space was wanted and used."),
    ("12", "arstuwy4", "Parked in a residents' or shared use parking place or zone without a valid virtual permit or clearly displaying a valid physical permit or voucher or pay and display ticket issued for that place where required, or without payment of the parking charge", "Higher", "ON_STREET", M,
     "Official text mixes an entitlement violation (no valid permit) with a payment violation (no payment of the charge) in a single code. Declared MIXED rather than forced to one side. Note Camden's observed 12R carries suffix r = residents' bay, which tilts toward entitlement, but the base code is what the frozen classifier sees."),
    ("13", "", "---- RESERVED FOR TfL USE (LOW EMISSION ZONE) - - - -", "n/a", "ON_STREET", R,
     "Reserved by the source."),
    ("14", "ay89", "Parked in an electric vehicles' charging place during restricted hours without charging", "Higher", "ON_STREET", P,
     "Entitlement to a specially designated place."),
    ("16", "abdehqstwxyz4569", "Parked in a permit space or zone without a valid virtual permit or clearly displaying a valid physical permit where required", "Higher", "ON_STREET", P,
     "Permit entitlement."),
    ("17", "", "---- RESERVED FOR ROAD USER CHARGING USE - - - -", "n/a", "ON_STREET", R,
     "Reserved by the source."),
    ("18", "abcdefghmprsvxy12356789", "Using a vehicle in a parking place in connection with the sale or offering or exposing for sale of goods when prohibited", "Higher", "ON_STREET", P,
     "Prohibited use of a parking place."),
    ("19", "airsuwxyz4", "Parked in a residents' or shared use parking place or zone with an invalid virtual permit or displaying an invalid physical permit or voucher or pay and display ticket, or after the expiry of paid for time", "Lower", "ON_STREET", M,
     "Official text mixes invalid-permit entitlement with expiry of paid time. Declared MIXED."),
    ("20", "", "Parked in a part of a parking place marked by a yellow line where waiting is prohibited", "Higher", "ON_STREET", P,
     "Location: yellow-line prohibition."),
    ("21", "abcdefghijklmnpqrsuvxy1256789", "Parked wholly or partly in a suspended bay or space", "Higher", "ON_STREET", P,
     "Bay suspension - an enforcement and works-driven condition, not a demand condition."),
    ("22", "cfglmnopsv1289", "Re-parked in the same parking place or zone within one hour after leaving", "Lower", "ON_STREET", T,
     "Circulation behaviour driven by scarcity: re-parking to reset a limit is a demand-pressure signature."),
    ("23", "abcdefghklprsvwxy123789", "Parked in a parking place or area not designated for that class of vehicle", "Higher", "ON_STREET", P,
     "Vehicle-class entitlement."),
    ("24", "abcdefghijklmpqrsvxy1256789", "Not parked correctly within the markings of the bay or space", "Lower", "ON_STREET", P,
     "Manner of parking rather than duration or payment; enforcement-observation dependent."),
    ("25", "n2", "Parked in a loading place or bay during restricted hours without loading", "Higher", "ON_STREET", P,
     "Entitlement to a loading place."),
    ("26", "n", "Parked in a special enforcement area more than 50 cm from the edge of the carriageway and not within a designated parking place", "Higher", "ON_STREET", P,
     "Location prohibition in a special enforcement area."),
    ("27", "no", "Parked in a special enforcement area adjacent to a footway, cycle track or verge lowered to meet the level of the carriageway", "Higher", "ON_STREET", P,
     "Location prohibition."),
    ("28", "no", "Parked in a special enforcement area on part of the carriageway raised to meet the level of a footway, cycle track or verge", "Higher", "ON_STREET", P,
     "Location prohibition."),
    # --- Moving traffic (NOT parking) --------------------------------------
    ("29", "j", "Failing to comply with a one-way restriction", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a in the source."),
    ("30", "acfglmnopsuy12789", "Parked for longer than permitted", "Lower", "ON_STREET", T,
     "Maximum-stay overstay at a permitted place - the cleanest duration-demand code."),
    ("31", "j", "Entering and stopping in a box junction when prohibited", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("32", "jdt", "Failing to proceed in the direction shown by the arrow on a blue sign", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("33", "jbcefghikqrsyz", "Using a route restricted to certain vehicles", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a. Camden's highest-volume code 33H (76,882 rows) is this, with suffix h = local buses and cycles only."),
    ("34", "j0", "Being in a bus lane", "n/a", "ON_STREET", N,
     "Bus lane. Diff. level n/a. Corresponds to Camden's BUS ticket_type (7,032 rows)."),
    ("35", "", "Parked in a disc parking place without clearly displaying a valid disc", "Lower", "ON_STREET", T,
     "Duration control by disc at a permitted place."),
    ("36", "j", "Being in a mandatory cycle lane", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("37", "j", "Failing to give way to oncoming vehicles", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("38", "jlr", "Failing to comply with a sign indicating that vehicular traffic must pass to the specified side of the sign", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("39", "", "---- RESERVED FOR TfL USE (ULTRA LOW EMISSION ZONE) - - - -", "n/a", "ON_STREET", R,
     "Reserved by the source."),
    ("40", "n", "Parked in a designated disabled person's parking place without displaying a valid disabled person's badge in the prescribed manner", "Higher", "ON_STREET", P,
     "Badge entitlement to a designated place."),
    ("41", "", "Stopped in a parking place designated for diplomatic vehicles", "Higher", "ON_STREET", P,
     "Designated-place entitlement."),
    ("42", "", "Parked in a parking place designated for police vehicles", "Higher", "ON_STREET", P,
     "Designated-place entitlement."),
    ("43", "", "Stopped on a cycle docking station parking place", "Higher", "ON_STREET", P,
     "Designated-place entitlement."),
    ("45", "nw", "Stopped on a taxi rank", "Higher", "ON_STREET", P,
     "Designated-place entitlement."),
    ("46", "n", "Stopped where prohibited (on a red route or clearway)", "Higher", "ON_STREET", P,
     "Location prohibition."),
    ("47", "jn", "Stopped on a restricted bus stop or stand", "Higher", "ON_STREET", P,
     "Location prohibition."),
    ("48", "jlr", "Stopped in a restricted area outside a school, a hospital or a fire, police or ambulance station when prohibited", "Higher", "ON_STREET", P,
     "Location prohibition in a protected area."),
    ("49", "j", "Parked wholly or partly on a cycle track or lane", "Higher", "ON_STREET", P,
     "Location prohibition."),
    ("50", "jlru", "Performing a prohibited turn", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("51", "j", "Failing to comply with a no entry restriction", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("52", "jgmsvx", "Failing to comply with a prohibition on certain types of vehicle", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a. Camden's second-highest code 52M (73,148 rows) is this, suffix m = motor vehicles."),
    ("53", "cj", "Failing to comply with a restriction on vehicles entering a pedestrian zone", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("54", "cj", "Failing to comply with a restriction on vehicles entering and waiting in a pedestrian zone", "n/a", "ON_STREET", N,
     "Moving traffic. Diff. level n/a."),
    ("55", "", "A commercial vehicle parked in a restricted street in contravention of the Overnight Waiting Ban", "Higher", "ON_STREET", P,
     "Overnight waiting ban - location and time prohibition."),
    ("56", "", "Parked in contravention of a commercial vehicle waiting restriction", "Higher", "ON_STREET", P,
     "Commercial waiting restriction."),
    ("57", "", "Parked in contravention of a bus ban", "Higher", "ON_STREET", P,
     "Bus ban waiting restriction."),
    ("58", "", "Using a vehicle on a restricted street during prescribed hours without a valid permit", "n/a", "ON_STREET", N,
     "London Lorry Control Scheme route permit. Moving-traffic style, Diff. level n/a."),
    ("59", "", "Using a vehicle on a restricted street during prescribed hours in breach of permit conditions", "n/a", "ON_STREET", N,
     "London Lorry Control Scheme route permit. Diff. level n/a."),
    ("61", "124cgn", "A heavy commercial vehicle wholly or partly parked on a footway, verge or land between two carriageways", "Higher", "ON_STREET", P,
     "Footway parking prohibition."),
    ("62", "124cgn", "Parked with one or more wheels on or over a footpath or any part of a road other than a carriageway", "Higher", "ON_STREET", P,
     "Footway parking prohibition."),
    ("63", "", "Parked with engine running where prohibited", "Lower", "ON_STREET", P,
     "Manner-of-parking prohibition."),
    ("64", "124", "Parked in contravention of a notice prohibiting leaving vehicles on a grass verge, garden, lawn or green maintained by a local authority", "n/a", "ON_STREET", P,
     "Verge prohibition. Diff. level n/a but this IS a parking contravention (Essex only), so it is declared by content, not by Diff. level."),
    ("65", "124", "Parked in contravention of a notice prohibiting leaving vehicles on land laid out as a public garden or used for the purpose of public recreation", "n/a", "ON_STREET", P,
     "Verge or public-land prohibition (Essex only). Declared by content; Diff. level n/a is not sufficient on its own to mean moving traffic."),
    ("66", "124cg", "Parked on a verge, central reservation or footway comprised in an urban road", "n/a", "ON_STREET", P,
     "Verge or footway prohibition (Exeter only). Declared by content, not by Diff. level."),
    ("67", "", "Using a vehicle on a restricted street without a valid HGV Safety Permit", "n/a", "ON_STREET", N,
     "HGV Safety Permit Scheme (Direct Vision Standard). Route permit, not parking."),
    ("68", "", "Using a vehicle on a restricted street in breach of HGV Safety Permit conditions", "n/a", "ON_STREET", N,
     "HGV Safety Permit Scheme. Route permit, not parking."),
    ("72", "", "--- RESERVED FOR BUILDERS' SKIPS CONTRAVENTIONS - - -", "", "ON_STREET", R,
     "Reserved by the source (London only)."),
    ("75", "", "--- RESERVED FOR LITTERING FROM MOTOR VEHICLES - - -", "", "ON_STREET", R,
     "Reserved by the source."),
    ("76", "", "- - RESERVED FOR WASTE RECEPTACLE CONTRAVENTIONS - -", "", "ON_STREET", R,
     "Reserved by the source (London only)."),
    ("97", "", "Driving a motor vehicle in an unrestricted street in excess of the posted speed limit", "n/a", "ON_STREET", N,
     "Speeding. London only. Not parking."),
    ("99", "no", "Stopped on a pedestrian crossing or crossing area marked by zigzags", "Higher", "ON_STREET", P,
     "Pedestrian crossing prohibition."),
    # --- Off-street --------------------------------------------------------
    ("70", "", "Parked in a loading place or bay during restricted hours without loading", "Higher", "OFF_STREET", P,
     "Off-street loading entitlement."),
    ("71", "", "Parked in an electric vehicles' charging place during restricted hours without charging", "Higher", "OFF_STREET", P,
     "Off-street EV place entitlement."),
    ("73", "gu", "Parked without payment of the parking charge", "Lower", "OFF_STREET", T,
     "Off-street non-payment at a permitted place. Demand-side."),
    ("74", "prs", "Using a vehicle in a parking place in connection with the sale or offering or exposing for sale of goods when prohibited", "Higher", "OFF_STREET", P,
     "Prohibited use of an off-street place."),
    ("77", "", "--- RESERVED FOR DVLA USE - - -", "n/a", "OFF_STREET", R,
     "Reserved by the source."),
    ("78", "abdefghklpquv156789", "Parked wholly or partly in a suspended bay or space", "Higher", "OFF_STREET", P,
     "Off-street suspension."),
    ("80", "gu", "Parked for longer than permitted", "Lower", "OFF_STREET", T,
     "Off-street maximum-stay overstay. Duration demand."),
    ("81", "o", "Parked in a restricted area in an off-street car park or housing estate", "Higher", "OFF_STREET", P,
     "Off-street location prohibition."),
    ("82", "puv4", "Parked after the expiry of paid for time", "Lower", "OFF_STREET", T,
     "Off-street overstay of paid time. Duration demand."),
    ("83", "4", "Parked in a car park without clearly displaying a valid pay & display ticket or voucher or parking clock", "Lower", "OFF_STREET", T,
     "Off-street payment compliance."),
    ("84", "gu", "Parked with payment made to extend the stay beyond initial time", "Lower", "OFF_STREET", T,
     "Off-street meter feeding. Duration demand."),
    ("85", "abtrwyz45", "Parked without a valid virtual permit or clearly displaying a valid physical permit where required", "Higher", "OFF_STREET", P,
     "Off-street permit entitlement."),
    ("86", "prs", "Not parked correctly within the markings of a bay or space", "Lower", "OFF_STREET", P,
     "Off-street manner of parking."),
    ("87", "", "Parked in a designated disabled person's parking place without displaying a valid disabled person's badge in the prescribed manner", "Higher", "OFF_STREET", P,
     "Off-street badge entitlement."),
    ("89", "", "Vehicle parked exceeds maximum weight or height or length permitted", "Higher", "OFF_STREET", P,
     "Off-street vehicle-dimension entitlement."),
    ("90", "psuv", "Re-parked in the same car park within one hour after leaving", "Lower", "OFF_STREET", T,
     "Off-street circulation to reset a limit. Scarcity-driven."),
    ("91", "cg", "Parked in a car park or area not designated for that class of vehicle", "Higher", "OFF_STREET", P,
     "Off-street vehicle-class entitlement."),
    ("92", "o", "Parked causing an obstruction", "Higher", "OFF_STREET", P,
     "Off-street obstruction."),
    ("93", "", "Parked in car park when closed", "Lower", "OFF_STREET", P,
     "Off-street closure prohibition."),
    ("94", "p", "Parked in a pay & display car park without clearly displaying two valid pay and display tickets when required", "Lower", "OFF_STREET", T,
     "Off-street payment compliance for a longer stay."),
    ("95", "", "Parked in a parking place for a purpose other than that designated", "Lower", "OFF_STREET", P,
     "Off-street designated-purpose entitlement."),
    ("96", "", "Parked with engine running where prohibited", "Lower", "OFF_STREET", P,
     "Off-street manner of parking."),
]

# Camden's observed top codes, from publisher metadata (PTE-TEL-004 §2), used to
# weight the audit so it reports agreement over ROWS rather than over codes.
CAMDEN_OBSERVED_TOP_CODES = {"33H": 76882, "52M": 73148, "12R": 72219, "11": 68427}


# ---------------------------------------------------------------------------
# Code parsing
# ---------------------------------------------------------------------------

_CODE_RE = re.compile(r"^\s*(\d{1,2})\s*([A-Za-z0-9]*)\s*$")


def split_code(raw: str | None) -> dict:
    """Split a Camden `contravention_code` into base code and suffix.

    `12R` -> base `12`, suffix `R`. `33H` -> base `33`, suffix `H`. `11` -> base
    `11`, suffix None. The RAW value is always preserved; nothing is normalised
    away. Suffix matching against the source legend is case-insensitive because
    the source lists suffixes in lower case while Camden emits them in upper.
    """
    out = {"raw": raw, "baseCode": None, "suffix": None, "suffixMeaning": None,
           "suffixMeaningSource": None, "parseStatus": "EMPTY",
           "suffixIsCameraEnforcement": False}
    if raw is None or not str(raw).strip():
        return out
    text = str(raw).strip()
    m = _CODE_RE.match(text)
    if not m:
        out["parseStatus"] = "UNPARSEABLE"
        return out
    base, suffix = m.group(1), m.group(2)
    out["baseCode"] = base.zfill(2)
    out["suffix"] = suffix.upper() or None
    out["parseStatus"] = "PARSED"
    if suffix:
        low = suffix.lower()
        # Code-specific meanings override the general legend; see
        # CODE_SPECIFIC_SUFFIXES for why resolving from the general legend alone
        # reports a confidently wrong meaning for the high-volume moving-traffic
        # codes.
        specific = CODE_SPECIFIC_SUFFIXES.get(out["baseCode"] or "", {}).get(low)
        out["suffixMeaning"] = specific if specific is not None else SUFFIX_LEGEND.get(low)
        out["suffixMeaningSource"] = ("CODE_SPECIFIC" if specific is not None
                                      else ("GENERAL_LEGEND" if low in SUFFIX_LEGEND else None))
        out["suffixIsCameraEnforcement"] = (CAMERA_ENFORCEMENT_SUFFIX in low)
    return out


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------

def build_artifact() -> dict:
    entries = {}
    for code, suffixes, desc, level, section, cls, why in CODES:
        entries[code] = {
            "baseCode": code,
            "officialDescription": desc,
            "generalSuffixes": suffixes,
            "diffLevel": level or None,
            "section": section,
            "declaredPressureClass": cls,
            "declaredRationale": why,
            "mapsToHarnessLabel": DECLARED_TO_HARNESS[cls],
        }
    counts: dict[str, int] = {}
    for _, _, _, _, _, cls, _ in CODES:
        counts[cls] = counts.get(cls, 0) + 1
    return {
        "artifactVersion": ARTIFACT_VERSION,
        "recordId": "PTE-TEL-004-C4",
        "source": {
            "title": SOURCE_TITLE,
            "publisher": SOURCE_PUBLISHER,
            "codeListVersion": SOURCE_CODE_VERSION,
            "codeListEffectiveDate": SOURCE_CODE_EFFECTIVE,
            "sourceUrl": SOURCE_URL,
            "retrievedDate": RETRIEVED,
            "licence": "London Councils published code list; transcribed verbatim",
            "transcriptionNote": ("Descriptions, general suffixes and Diff. level "
                                  "are transcribed verbatim from the source. "
                                  "declaredPressureClass and declaredRationale are "
                                  "OURS, not the publisher's."),
        },
        "declarationStatus": ("FROZEN BEFORE ANY CAMDEN DATA ROW WAS READ. The "
                              "turnover-versus-prohibition grouping used by fail "
                              "criterion F1 is declared here and may not be "
                              "revised after a result is seen."),
        "declaredClasses": {k: CLASS_RATIONALE[k] for k in
                            (CLASS_TURNOVER, CLASS_PROHIBITION, CLASS_MIXED,
                             CLASS_NOT_PARKING, CLASS_RESERVED)},
        "classCounts": dict(sorted(counts.items())),
        "totalCodes": len(CODES),
        "suffixLegend": dict(sorted(SUFFIX_LEGEND.items())),
        "codeSpecificSuffixes": {k: dict(sorted(v.items()))
                                 for k, v in sorted(CODE_SPECIFIC_SUFFIXES.items())},
        "suffixResolutionRule": (
            "A suffix is resolved against CODE_SPECIFIC_SUFFIXES for its base code "
            "first, and only falls back to the general legend if that code has no "
            "specific entry. The general legend alone is wrong for the highest-"
            "volume moving-traffic codes: it reports 33H as 'hospital bay' when the "
            "source says 'local buses and cycles only', and 52M as 'parking meter' "
            "when the source says 'motor vehicles'."),
        "cameraEnforcementSuffix": CAMERA_ENFORCEMENT_SUFFIX,
        "cameraEnforcementNote": CAMERA_SUFFIX_NOTE,
        "independentParkingDiscriminator": (
            "The source's 'Diff. level' column is 'n/a' for the moving-traffic and "
            "bus-lane codes (29, 31-34, 36-38, 50-54, 58, 59, 67, 68, 97). That is "
            "an INDEPENDENT corroboration of pre-registered correction C3 - that "
            "35.9% of Camden's PCN rows are not parking - from a source with no "
            "connection to Camden's own ticket_type field. Note it is not "
            "sufficient on its own: codes 64, 65 and 66 also carry 'n/a' but ARE "
            "parking contraventions, so class is declared from the description "
            "content and cross-checked against Diff. level."),
        "codes": {k: entries[k] for k in sorted(entries)},
        "camdenObservedTopCodes": dict(sorted(CAMDEN_OBSERVED_TOP_CODES.items())),
        "camdenObservedTopCodesNote": (
            "From Camden publisher metadata for 4k7m-4gkk, retrieved before any "
            "row was read. These four codes are 290,676 of 495,814 rows (58.6%). "
            "33H and 52M are NOT_PARKING (150,030 rows), which accounts for most "
            "of the 177,779 moving-traffic and bus-lane rows implied by "
            "ticket_type - two independent sources agreeing."),
        "legalityClaimed": False,
    }


# ---------------------------------------------------------------------------
# Audit: does the FROZEN classifier reproduce the declaration?
# ---------------------------------------------------------------------------

_WORD_RE_CACHE: dict[str, re.Pattern] = {}


def _whole_word(hint: str, text: str) -> bool:
    """True if `hint` occurs in `text` as a whole word/phrase, not inside a
    longer word. The frozen classifier uses bare substring matching, so this
    distinguishes a genuine match from a substring artefact."""
    pat = _WORD_RE_CACHE.get(hint)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(hint) + r"(?![a-z0-9])")
        _WORD_RE_CACHE[hint] = pat
    return bool(pat.search(text))


def _classify_failure(expected: str, observed: str) -> str:
    if observed == "UNCLASSIFIED":
        return "VOCABULARY_GAP"
    if observed == "AMBIGUOUS" and expected == "TURNOVER_TYPE":
        return "SPURIOUS_PROHIBITION_HINT"
    if observed == "TURNOVER_TYPE" and expected == "PROHIBITION_TYPE":
        return "SPURIOUS_TURNOVER_HINT"
    if observed == "PROHIBITION_TYPE" and expected == "TURNOVER_TYPE":
        return "SPURIOUS_PROHIBITION_HINT"
    if observed == "AMBIGUOUS" and expected == "PROHIBITION_TYPE":
        return "SPURIOUS_TURNOVER_HINT"
    return "OTHER"


# Codes whose failure would materially damage the F1 measurement, because they are
# common London on-street parking contraventions and/or are the cleanest available
# expressions of duration demand. Declared here, in the artifact, before any row
# is read - so this list cannot be trimmed to suit a result.
HIGH_VALUE_CODES = frozenset({
    "05",  # parked after the expiry of paid for time - purest overstay code
    "30",  # parked for longer than permitted - cleanest maximum-stay code
    "80",  # off-street equivalent of 30
    "22",  # re-parked within one hour - scarcity-driven circulation
    "82",  # off-street expiry of paid time
    "90",  # off-street re-parking
    "35",  # disc parking place - duration control
    "04",  # meter bay penalty time
    "12",  # Camden's third-highest volume code (72,219 rows as 12R)
    "11",  # Camden's fourth-highest volume code (68,427 rows)
})


def audit() -> dict:
    """Run the frozen keyword classifier on each authoritative description and
    compare against the pre-declared class.

    The frozen harness is NOT modified. This measures whether feeding it
    authoritative text makes it reproduce the declaration, and - where it does not
    - names the mechanism of each failure so the finding can be acted on before
    any Camden row is read.
    """
    per_code = []
    agree = disagree = excluded = 0
    for code, suffixes, desc, level, section, cls, why in sorted(CODES, key=lambda r: r[0]):
        expected = DECLARED_TO_HARNESS[cls]
        if expected.startswith("EXCLUDED"):
            excluded += 1
            per_code.append({"baseCode": code, "declaredClass": cls,
                             "expectedHarnessLabel": expected,
                             "observedHarnessLabel": None, "agrees": None,
                             "failureMode": None,
                             "note": "excluded before classification (C3)"})
            continue
        observed = classify_contravention(code, desc)["contraventionClass"]
        ok = observed == expected
        agree += 1 if ok else 0
        disagree += 0 if ok else 1
        blob = f"{code} {desc}".lower()
        turnover_hits = [h for h in TURNOVER_CODE_HINTS if h in blob]
        prohibition_hits = [h for h in PROHIBITION_CODE_HINTS if h in blob]
        entry = {
            "baseCode": code, "declaredClass": cls,
            "expectedHarnessLabel": expected, "observedHarnessLabel": observed,
            "agrees": ok, "officialDescription": desc,
            "highValueCode": code in HIGH_VALUE_CODES,
            "turnoverHintsMatched": turnover_hits,
            "prohibitionHintsMatched": prohibition_hits,
        }
        if not ok:
            entry["failureMode"] = _classify_failure(expected, observed)
            # A hint that matched only inside a longer word is a substring artefact
            # of the frozen classifier's bare `in` test.
            entry["substringArtefacts"] = sorted(
                {h for h in turnover_hits + prohibition_hits if not _whole_word(h, blob)})
        else:
            entry["failureMode"] = None
        per_code.append(entry)

    # Row-weighted agreement over Camden's observed top codes. C3-excluded rows are
    # kept OUT of this denominator: they are removed before classification, so
    # counting them as failures would conflate two different things. The all-rows
    # figure is reported separately for completeness.
    parking_total = parking_agree = all_total = all_agree = 0
    per_observed = []
    for raw, n in sorted(CAMDEN_OBSERVED_TOP_CODES.items(), key=lambda kv: -kv[1]):
        parsed = split_code(raw)
        entry = next((e for e in per_code if e["baseCode"] == parsed["baseCode"]), None)
        all_total += n
        status = "EXCLUDED_BY_C3"
        agrees = None
        if entry and entry["agrees"] is not None:
            agrees = entry["agrees"]
            status = "AGREES" if agrees else "DISAGREES"
            parking_total += n
            all_agree += n if agrees else 0
            parking_agree += n if agrees else 0
        per_observed.append({
            "rawCode": raw, "rows": n, "baseCode": parsed["baseCode"],
            "suffix": parsed["suffix"], "suffixMeaning": parsed["suffixMeaning"],
            "suffixIsCameraEnforcement": parsed["suffixIsCameraEnforcement"],
            "declaredClass": entry["declaredClass"] if entry else None,
            "observedHarnessLabel": entry["observedHarnessLabel"] if entry else None,
            "status": status,
        })

    classified = agree + disagree
    disagreements = [e for e in per_code if e["agrees"] is False]
    failure_modes: dict[str, int] = {}
    for d in disagreements:
        failure_modes[d["failureMode"]] = failure_modes.get(d["failureMode"], 0) + 1
    artefact_codes = sorted(d["baseCode"] for d in disagreements if d.get("substringArtefacts"))

    return {
        "auditVersion": ARTIFACT_VERSION,
        "frozenClassifierUnmodified": True,
        "totalCodes": len(CODES),
        "excludedBeforeClassification": excluded,
        "classifiedCodes": classified,
        "agree": agree,
        "disagree": disagree,
        "agreementRate": round(agree / classified, 6) if classified else None,
        "camdenRowWeightedAgreementParkingOnly": (
            round(parking_agree / parking_total, 6) if parking_total else None),
        "camdenRowWeightedAgreementAllObservedRows": (
            round(all_agree / all_total, 6) if all_total else None),
        "camdenRowWeightedNote": (
            "Two denominators are reported deliberately. 'ParkingOnly' covers only "
            "rows that survive the C3 filter (12R, 11 = 140,646 rows); C3-excluded "
            "rows are removed before classification and are not classifier "
            "failures. 'AllObservedRows' includes them and is therefore a "
            "conservative lower bound. Neither figure is reassuring: Camden's "
            "top-2 parking codes classify correctly, but they are only 28.4% of "
            "rows, and the remaining 205,138 rows' codes were never retrieved - so "
            "the codes that DO fail are precisely the ones we cannot yet see."),
        "camdenObservedCodes": per_observed,
        "failureModes": dict(sorted(failure_modes.items())),
        "substringArtefactCodes": artefact_codes,
        "highValueFailures": [
            {"baseCode": d["baseCode"], "failureMode": d["failureMode"],
             "expected": d["expectedHarnessLabel"], "observed": d["observedHarnessLabel"],
             "substringArtefacts": d.get("substringArtefacts"),
             "officialDescription": d["officialDescription"]}
            for d in sorted(disagreements, key=lambda e: e["baseCode"])
            if e_high_value(d)],
        "diagnosis": DIAGNOSIS,
        "disagreements": disagreements,
        "perCode": per_code,
    }


def e_high_value(entry: dict) -> bool:
    return bool(entry.get("highValueCode"))


DIAGNOSIS = {
    "summary": (
        "The frozen keyword classifier in camden_normalize.py cannot implement the "
        "declared taxonomy on authoritative London Councils text. It disagrees on "
        "24 of 66 classified codes (36.4%), fails to recognise half of all "
        "declared turnover codes, and biases prohibitionShareOverall upward by up "
        "to +0.074 - enough to cross the frozen F1 threshold of 0.50 unaided and "
        "manufacture a false FAIL. The C4 route of fixing this through input data "
        "alone is therefore FALSIFIED by evidence gathered before any Camden row "
        "was read."),
    "failureModes": {
        "SUBSTRING_MATCHING": (
            "classify_contravention() tests `hint in text` with no word boundary. "
            "'permit' is a substring of 'permitted', so code 30 'Parked for longer "
            "than permitted' - the cleanest maximum-stay code available - fires the "
            "PROHIBITION hint 'permit' alongside the TURNOVER hint 'longer than' "
            "and is returned as AMBIGUOUS. Codes 09 and 80 identically."),
        "OVERBROAD_HINT_BAY": (
            "'bay' is a PROHIBITION hint, but nearly every parking contravention in "
            "the authoritative list concerns a bay or parking place. It contaminates "
            "turnover codes such as 04 into AMBIGUOUS for no semantic reason."),
        "VOCABULARY_GAP": (
            "The hints were written from paraphrase, not from the authoritative "
            "wording. 'expired' is a hint but code 05 says 'expiry'; code 05 "
            "'Parked after the expiry of paid for time' - the purest overstay "
            "contravention in the list - returns UNCLASSIFIED. Codes 22, 35, 41, "
            "42, 43, 45, 49, 56, 57, 62, 64, 65, 82, 90, 91, 93, 95 return "
            "UNCLASSIFIED for the same reason: no hint matches the real wording."),
        "CIRCULAR_VALIDATION": (
            "Root cause. The 14/14 green self-test validated the classifier against "
            "synthetic fixture text generated by make_camden_fixture.py, which used "
            "the classifier's own vocabulary. The fixture could not have exposed "
            "these failures, because it was written in the language the classifier "
            "already understood. This is a methodological defect in PTE-TEL-003, "
            "found by PTE-TEL-004 step C4, and it is reported rather than buried."),
    },
    "asymmetry": (
        "The defects are NOT symmetric between the two classes, and that is what "
        "makes them consequential. Recognition rate on the authoritative list is "
        "0.500 for declared TURNOVER codes (9 of 18 recognised) against 0.674 for "
        "declared PROHIBITION codes (31 of 46). Every one of the 24 failures "
        "collapses into AMBIGUOUS or UNCLASSIFIED; NO code is ever inverted from "
        "one substantive class into the other. The classifier is conservative - it "
        "destroys information rather than swapping it."),
    "consequenceForF1": (
        "F1 indicator I2 triggers when prohibitionShareOverall exceeds the frozen "
        "threshold prohibitionShareDominant = 0.50. That share is computed as "
        "PROHIBITION_TYPE divided by the total over ALL classes, so reclassifying "
        "rows into AMBIGUOUS or UNCLASSIFIED leaves the denominator unchanged while "
        "shrinking the numerator on both sides - and it shrinks TURNOVER harder "
        "than PROHIBITION. The net effect is that prohibitionShareOverall is "
        "BIASED UPWARD by +0.030 to +0.074 across plausible true mixes. A street "
        "series with a TRUE prohibition share of 0.45 is reported at 0.524 and a "
        "true 0.50 at 0.574. The bias is therefore large enough to cross the "
        "frozen threshold on its own and produce a FALSE F1 TRIGGER."),
    "consequenceForStrategy": (
        "A false F1 trigger yields a FAIL verdict whose stated meaning is 'the "
        "signal is dominated by enforcement deployment, not parking demand'. The "
        "pre-registered reading of a Camden FAIL is to drop the PCN-exhaust source "
        "class as too enforcement-biased. So this defect does not merely add noise: "
        "it can manufacture the specific evidence that would cause the project to "
        "abandon the approach for a reason that is an artefact of a keyword list. "
        "That is a strategic-grade false negative and it must be removed before "
        "the run, not explained away after it."),
    "whyNotFixViaInputData": (
        "The only input-data lever is the description column. Making a weak "
        "keyword classifier reproduce a correct table-driven answer would require "
        "writing text engineered to trip specific keywords - description text that "
        "is NOT the authoritative description. That fabricates the provenance the "
        "harness exists to preserve, and it would make the result "
        "uninterpretable. It is a worse option than amending the classifier."),
    "biasTable": {
        "note": "true prohibition share -> share as reported by the frozen classifier",
        "recognitionRateTurnover": 0.5,
        "recognitionRateProhibition": round(31 / 46, 6),
        "frozenThreshold": 0.50,
        "rows": [
            {"true": 0.10, "observed": 0.130, "bias": 0.030, "falseTrigger": False},
            {"true": 0.25, "observed": 0.310, "bias": 0.060, "falseTrigger": False},
            {"true": 0.35, "observed": 0.421, "bias": 0.071, "falseTrigger": False},
            {"true": 0.40, "observed": 0.473, "bias": 0.073, "falseTrigger": False},
            {"true": 0.45, "observed": 0.524, "bias": 0.074, "falseTrigger": True},
            {"true": 0.50, "observed": 0.574, "bias": 0.074, "falseTrigger": True},
            {"true": 0.60, "observed": 0.669, "bias": 0.069, "falseTrigger": False},
        ],
    },
}


# ---------------------------------------------------------------------------
# Preparation: write authoritative descriptions into a PCN export
# ---------------------------------------------------------------------------

def prepare(in_path: str, out_path: str) -> dict:
    """Rewrite a Camden PCN export so the frozen adapter can classify it.

    Adds/populates a `Contravention Description` column with the AUTHORITATIVE
    London Councils description for the row's base code, and adds explicit
    `Base Code`, `Code Suffix`, `Declared Pressure Class` and
    `Parking Contravention` columns. The original `Contravention Code` value is
    preserved verbatim. No frozen harness file is touched: this changes INPUT
    DATA only, which is what the freeze protocol permits.

    Rows whose base code is NOT_PARKING or RESERVED are marked
    `Parking Contravention = No` so the C3 filter can be applied and its effect
    counted, rather than being silently dropped here.
    """
    artifact = build_artifact()
    codes = artifact["codes"]
    with open(in_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"no header in {in_path}")
        src_cols = list(reader.fieldnames)
        rows = list(reader)

    code_col = next((c for c in src_cols
                     if c.strip().lower().replace("_", " ") in
                     ("contravention code", "contraventioncode")), None)
    if code_col is None:
        raise KeyError(f"no contravention code column in {src_cols}")

    desc_col = next((c for c in src_cols
                     if c.strip().lower().replace("_", " ") in
                     ("contravention description", "contraventiondescription")), None)
    new_cols = [c for c in ("Base Code", "Code Suffix", "Suffix Meaning",
                            "Suffix Meaning Source",
                            "Declared Pressure Class", "Parking Contravention")
                if c not in src_cols]
    out_cols = src_cols + new_cols
    if desc_col is None:
        desc_col = "Contravention Description"
        out_cols = src_cols + [desc_col] + [c for c in new_cols if c != desc_col]

    stats = {"rows": len(rows), "mapped": 0, "unmapped": 0,
             "parking": 0, "notParking": 0, "unmappedCodes": {}}
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=out_cols, lineterminator="\n")
        w.writeheader()
        for row in rows:
            parsed = split_code(row.get(code_col))
            entry = codes.get(parsed["baseCode"] or "")
            out = dict(row)
            if entry:
                stats["mapped"] += 1
                out[desc_col] = entry["officialDescription"]
                out["Base Code"] = parsed["baseCode"]
                out["Code Suffix"] = parsed["suffix"] or ""
                out["Suffix Meaning"] = parsed["suffixMeaning"] or ""
                out["Suffix Meaning Source"] = parsed["suffixMeaningSource"] or ""
                out["Declared Pressure Class"] = entry["declaredPressureClass"]
                parking = entry["declaredPressureClass"] not in (CLASS_NOT_PARKING, CLASS_RESERVED)
                out["Parking Contravention"] = "Yes" if parking else "No"
                stats["parking" if parking else "notParking"] += 1
            else:
                stats["unmapped"] += 1
                key = str(row.get(code_col) or "<empty>")
                stats["unmappedCodes"][key] = stats["unmappedCodes"].get(key, 0) + 1
                out[desc_col] = row.get(desc_col, "")
                out["Base Code"] = parsed["baseCode"] or ""
                out["Code Suffix"] = parsed["suffix"] or ""
                out["Suffix Meaning"] = parsed["suffixMeaning"] or ""
                out["Suffix Meaning Source"] = parsed["suffixMeaningSource"] or ""
                out["Declared Pressure Class"] = "UNMAPPED"
                out["Parking Contravention"] = "Unknown"
            w.writerow({c: out.get(c, "") for c in out_cols})

    stats["unmappedCodes"] = dict(sorted(stats["unmappedCodes"].items(),
                                        key=lambda kv: (-kv[1], kv[0])))
    stats["inPath"] = os.path.abspath(in_path)
    stats["outPath"] = os.path.abspath(out_path)
    stats["outSha256"] = sha256(out_path)
    stats["artifactVersion"] = ARTIFACT_VERSION
    stats["legalityClaimed"] = False
    stats["warning"] = ("UNMAPPED codes are reported, never guessed. A high "
                        "unmapped count means Camden uses codes outside the v7.0 "
                        "list and the declaration must be extended BEFORE the run, "
                        "not after seeing a result.")
    return stats


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build, audit and apply the authoritative London Councils "
                    "contravention-code map for PTE-TEL-004 C4. Does not modify "
                    "the frozen harness.")
    ap.add_argument("--emit", help="write the artifact JSON here")
    ap.add_argument("--audit", action="store_true",
                    help="audit the frozen classifier against the declaration")
    ap.add_argument("--audit-out", help="write the audit JSON here")
    ap.add_argument("--prepare", help="PCN export to rewrite")
    ap.add_argument("--out", help="prepared PCN output path")
    args = ap.parse_args(argv)

    did = False
    if args.emit:
        art = build_artifact()
        os.makedirs(os.path.dirname(os.path.abspath(args.emit)) or ".", exist_ok=True)
        blob = json.dumps(art, indent=2, sort_keys=True)
        with open(args.emit, "w", encoding="utf-8") as fh:
            fh.write(blob + "\n")
        print(f"artifact -> {args.emit}", file=sys.stderr)
        print(f"  codes: {art['totalCodes']}  classes: {art['classCounts']}", file=sys.stderr)
        print(f"  sha256: {sha256(args.emit)}", file=sys.stderr)
        did = True

    if args.audit:
        res = audit()
        text = json.dumps(res, indent=2, sort_keys=True)
        if args.audit_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.audit_out)) or ".", exist_ok=True)
            with open(args.audit_out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"audit -> {args.audit_out}", file=sys.stderr)
        else:
            print(text)
        print(f"\n  classified codes: {res['classifiedCodes']} "
              f"(excluded before classification: {res['excludedBeforeClassification']})",
              file=sys.stderr)
        print(f"  agreement: {res['agree']}/{res['classifiedCodes']} "
              f"= {res['agreementRate']}", file=sys.stderr)
        print(f"  Camden row-weighted agreement (parking rows only): "
              f"{res['camdenRowWeightedAgreementParkingOnly']}", file=sys.stderr)
        print(f"  Camden row-weighted agreement (all observed rows): "
              f"{res['camdenRowWeightedAgreementAllObservedRows']}", file=sys.stderr)
        for d in res["disagreements"]:
            print(f"    DISAGREE code {d['baseCode']}: declared {d['expectedHarnessLabel']}"
                  f" classifier said {d['observedHarnessLabel']}", file=sys.stderr)
        did = True

    if args.prepare:
        if not args.out:
            ap.error("--prepare requires --out")
        stats = prepare(args.prepare, args.out)
        print(json.dumps(stats, indent=2, sort_keys=True))
        did = True

    if not did:
        ap.error("nothing to do: pass --emit, --audit or --prepare")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
