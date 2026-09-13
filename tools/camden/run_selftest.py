#!/usr/bin/env python3
"""Self-test for the Camden signal harness (PTE-TEL-003 deliverable 6, part 2).

WHAT IT PROVES
--------------
A harness that claims to detect failure modes has to be shown detecting them.
This script generates a fixture from KNOWN latent processes - a demand process
and a separate enforcement-deployment process - and asserts that the harness's
verdict matches the proportions it was handed. The harness is graded against
truth it did not create.

Seven scenario assertions, five structural assertions:

  scenarios    demand-dominated -> PASS
               deployment-dominated -> FAIL on F1
               gps-biased -> FAIL on F2
               sparse-coverage -> FAIL on F3
               no-validation-route -> FAIL on F4
               drifting -> FAIL on F5
               demand-dominated without a proxy -> PARTIAL, never PASS

  structural   determinism: same seed twice -> identical file bytes
               determinism: same inputs twice -> identical report sha256
               forbidden semantics: an occupancy-shaped key raises
               no bay-level join: a cell carrying a coordinate raises
               no hour imputation: a date-only PCN yields hourKnown False and
                                   never lands in hour bucket 0

THE FIXTURE IS NOT REAL DATA. Every number here describes the fixture. A PASS in
this script means the pipeline detects what it was built to detect - it says
nothing whatsoever about Camden.

    python3 run_selftest.py
    python3 run_selftest.py --keep /tmp/camden-selftest --verbose

STDLIB ONLY. Deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import camden_aggregate                     # noqa: E402
import camden_normalize                     # noqa: E402
import camden_pressure                      # noqa: E402
import camden_signal_test as sig            # noqa: E402
import make_camden_fixture as fx            # noqa: E402
from camden_sources import load_bay_map, load_pcn_series  # noqa: E402

# scenario -> (expected verdict, expected triggered criterion key or None,
#              validation-route declaration to pass)
EXPECTATIONS = [
    ("demand-dominated",      "PASS",    None,                "supplied"),
    ("deployment-dominated",  "FAIL",    "deploymentDominance", "supplied"),
    ("gps-biased",            "FAIL",    "stratumIsolation",  "supplied"),
    ("sparse-coverage",       "FAIL",    "coverage",          "supplied"),
    ("no-validation-route",   "FAIL",    "validationRoute",   "none_known"),
    ("drifting",              "FAIL",    "splitHalfStability", "supplied"),
    ("demand-dominated-noproxy", "PARTIAL", None,             "available-but-not-supplied"),
]


class SelfTestFailure(AssertionError):
    pass


def _report_for(out_dir: str, bays: str, pcn: str, proxy: str | None,
                route: str, thresholds: dict) -> dict:
    return sig.build_report(bays, pcn, proxy, camden_aggregate.JOIN_LEVEL_STREET,
                            thresholds, route, None, field_map=None)


def _run_scenario(name: str, root: str, verbose: bool) -> dict:
    """Generate one scenario and return its report plus the manifest."""
    if name == "demand-dominated-noproxy":
        scenario, params = "demand-dominated", dict(fx.SCENARIOS["demand-dominated"])
        params["with_proxy"] = False
    else:
        scenario, params = name, dict(fx.SCENARIOS[name])

    out_dir = os.path.join(root, name)
    manifest = fx.generate(out_dir, scenario, params)
    route = "supplied" if manifest["proxyPath"] else "available_not_supplied"
    if name == "no-validation-route":
        route = "none_known"

    report = _report_for(out_dir, manifest["baysPath"], manifest["pcnPath"],
                         manifest["proxyPath"], route,
                         dict(sig.DEFAULT_THRESHOLDS))
    if verbose:
        print(f"  [{name}] {manifest['streetCount']} streets, "
              f"{manifest['distinctDates']} dates, {manifest['pcnRowCount']} PCNs "
              f"-> {report['verdict']['verdict']}", file=sys.stderr)
    return {"manifest": manifest, "report": report}


def check_scenarios(root: str, verbose: bool) -> list[dict]:
    results = []
    for name, expected_verdict, expected_criterion, route in EXPECTATIONS:
        got = _run_scenario(name, root, verbose)
        report = got["report"]
        verdict = report["verdict"]["verdict"]
        triggered = report["verdict"]["hardCriteriaTriggered"]

        ok_verdict = verdict == expected_verdict
        ok_criterion = True
        if expected_criterion is not None:
            ok_criterion = expected_criterion in triggered
        elif expected_verdict in ("PASS", "PARTIAL"):
            ok_criterion = not triggered

        results.append({
            "check": f"scenario:{name}",
            "expected": {"verdict": expected_verdict, "criterion": expected_criterion},
            "observed": {"verdict": verdict, "triggered": triggered},
            "passed": bool(ok_verdict and ok_criterion),
        })
    return results


def check_determinism_fixture(root: str) -> list[dict]:
    a = fx.generate(os.path.join(root, "det-a"), "demand-dominated",
                    dict(fx.SCENARIOS["demand-dominated"]))
    b = fx.generate(os.path.join(root, "det-b"), "demand-dominated",
                    dict(fx.SCENARIOS["demand-dominated"]))
    return [{
        "check": "structural:fixture-bytes-deterministic",
        "expected": "identical sha256 for both runs",
        "observed": {"a": a["sha256"], "b": b["sha256"]},
        "passed": a["sha256"] == b["sha256"],
    }]


def check_determinism_report(root: str) -> list[dict]:
    d = os.path.join(root, "det-report")
    m = fx.generate(d, "demand-dominated", dict(fx.SCENARIOS["demand-dominated"]))
    r1 = _report_for(d, m["baysPath"], m["pcnPath"], m["proxyPath"], "supplied",
                     dict(sig.DEFAULT_THRESHOLDS))
    r2 = _report_for(d, m["baysPath"], m["pcnPath"], m["proxyPath"], "supplied",
                     dict(sig.DEFAULT_THRESHOLDS))
    s1, s2 = sig.report_sha256(r1), sig.report_sha256(r2)
    return [{
        "check": "structural:report-sha256-deterministic",
        "expected": "identical report sha256",
        "observed": {"first": s1, "second": s2},
        "passed": s1 == s2,
    }]


def check_forbidden_semantics() -> list[dict]:
    """The lane's semantic limits must be machine-enforced, not conventional."""
    bad = {
        "street": "X",
        "relativePressureIndex": 1.4,
        "occupancyEstimate": 0.62,       # must be refused
    }
    fired = None
    try:
        camden_pressure.assert_no_forbidden_semantics(bad)
    except camden_pressure.ForbiddenSemanticsError as exc:
        fired = str(exc)[:120]

    ok_key = {"street": "X", "relativePressureIndex": 1.4,
              "semanticContract": dict(camden_pressure.SEMANTIC_CONTRACT)}
    clean_ok = True
    try:
        camden_pressure.assert_no_forbidden_semantics(ok_key)
    except camden_pressure.ForbiddenSemanticsError:
        clean_ok = False

    return [{
        "check": "structural:forbidden-semantics-guard",
        "expected": "raises on an occupancy-shaped key; permits a clean index",
        "observed": {"raised": fired is not None, "message": fired,
                     "cleanPayloadAccepted": clean_ok},
        "passed": bool(fired is not None and clean_ok),
    }]


def check_no_bay_level_join() -> list[dict]:
    """A cell carrying a coordinate must be refused, not tolerated."""
    cells = {("CA||x", "CEO_GPS", "WEEKDAY", 9): {
        "joinKey": "CA||x", "latitude": 51.54, "pcnCount": 1}}
    fired = None
    try:
        camden_aggregate.assert_no_bay_level_join(cells)
    except AssertionError as exc:
        fired = str(exc)[:120]

    clean = {("CA||x", "CEO_GPS", "WEEKDAY", 9): {
        "joinKey": "CA||x", "street": "x", "pcnCount": 1}}
    clean_ok = True
    try:
        camden_aggregate.assert_no_bay_level_join(clean)
    except AssertionError:
        clean_ok = False

    return [{
        "check": "structural:no-bay-level-join-guard",
        "expected": "raises on a coordinate-bearing cell; permits street-level cells",
        "observed": {"raised": fired is not None, "message": fired,
                     "cleanPayloadAccepted": clean_ok},
        "passed": bool(fired is not None and clean_ok),
    }]


def check_no_hour_imputation(root: str) -> list[dict]:
    """A date-only PCN must yield hourKnown False, never hour 0."""
    d = os.path.join(root, "hour-imputation")
    os.makedirs(d, exist_ok=True)
    pcn_path = os.path.join(d, "pcn.csv")
    bay_path = os.path.join(d, "bays.csv")
    with open(bay_path, "w", encoding="utf-8") as fh:
        fh.write(",".join(fx.BAY_COLUMNS) + "\n")
        fh.write("CA,Test Street,Pay and Display,Mon-Fri 08:30-18:30,2 Hours,"
                 "Tariff A,60.0,10,LINESTRING (1 1, 2 2)\n")
    with open(pcn_path, "w", encoding="utf-8") as fh:
        fh.write(",".join(fx.PCN_COLUMNS) + "\n")
        # Deliberately date-only: no time component at all.
        for i in range(5):
            fh.write(f"T{i},2025-03-0{i + 1},01,Parked without payment,"
                     f"CEO On Street,Test Street,Pay and Display,Private Car,"
                     f"Issued,Civil Enforcement Officer GPS Location,CA\n")

    bays = load_bay_map(bay_path)
    pcns = load_pcn_series(pcn_path)
    norm = camden_normalize.normalize_all(bays, pcns)

    hours = [e["temporal"]["hour"] for e in norm["pcns"]]
    known = [e["temporal"]["hourKnown"] for e in norm["pcns"]]
    statuses = {e["temporal"]["parseStatus"] for e in norm["pcns"]}
    in_bucket_zero = any(h == 0 for h in hours)

    return [{
        "check": "structural:no-hour-imputation",
        "expected": "all hours None, all hourKnown False, parseStatus DATE_ONLY, "
                    "nothing lands in hour bucket 0",
        "observed": {"hours": hours, "hourKnown": known,
                     "parseStatuses": sorted(statuses),
                     "anythingInHourZero": in_bucket_zero,
                     "hourImputationPerformed":
                         norm["missingness"]["hourImputationPerformed"]},
        "passed": bool(all(h is None for h in hours)
                       and not any(known)
                       and statuses == {"PARSED_DATE_ONLY"}
                       and not in_bucket_zero),
    }]


SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "schemas", "camden-pressure-signal-schema.json")


def _walk_consts(node, path="$", out=None):
    """Collect every `const` assertion in a schema subtree as (path, value)."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if "const" in node:
            out.append((path, node["const"]))
        for k, v in node.items():
            if k in ("properties",):
                for pk, pv in v.items():
                    _walk_consts(pv, f"{path}.{pk}", out)
            elif k == "additionalProperties" and isinstance(v, dict):
                _walk_consts(v, f"{path}.*", out)
            elif isinstance(v, (dict, list)):
                _walk_consts(v, f"{path}.{k}", out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_consts(item, f"{path}[{i}]", out)
    return out


def _resolve(instance, path: str):
    """Resolve a $-path produced by _walk_consts, tolerating the '.*' wildcard."""
    cur = instance
    for part in [p for p in path.split(".") if p and p != "$"]:
        if part == "*":
            continue
        if isinstance(cur, dict):
            if part not in cur:
                return False, None
            cur = cur[part]
        else:
            return False, None
    return True, cur


def check_schema_conformance(root: str) -> list[dict]:
    """Validate a real report against the PTE-TEL-003 schema, stdlib only.

    No jsonschema dependency exists in this repo, so the conformance check
    implements the parts of the schema that carry the lane's guarantees: every
    top-level `required` key, every `const` assertion, the `joinLevel` and
    `verdict` enums, and the required fields of each street index entry. A schema
    that nothing validates against is documentation, not a contract.
    """
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)

    d = os.path.join(root, "schema-conformance")
    m = fx.generate(d, "demand-dominated", dict(fx.SCENARIOS["demand-dominated"]))
    report = _report_for(d, m["baysPath"], m["pcnPath"], m["proxyPath"], "supplied",
                         dict(sig.DEFAULT_THRESHOLDS))

    problems: list[str] = []

    # 1. top-level required keys
    for key in schema.get("required", []):
        if key not in report:
            problems.append(f"missing required top-level key: {key}")

    # 2. every const assertion in the schema, resolved against the report
    for path, expected in _walk_consts(schema):
        if path.startswith("$.index") or ".*" in path:
            continue
        found, actual = _resolve(report, path)
        if not found:
            problems.append(f"const path not resolvable: {path}")
        elif actual != expected:
            problems.append(f"const violated at {path}: {actual!r} != {expected!r}")

    # 3. enums
    jl = schema["properties"]["joinLevel"]["enum"]
    if report["joinLevel"] not in jl:
        problems.append(f"joinLevel {report['joinLevel']!r} not in {jl}")
    ve = schema["properties"]["verdict"]["properties"]["verdict"]["enum"]
    if report["verdict"]["verdict"] not in ve:
        problems.append(f"verdict {report['verdict']['verdict']!r} not in {ve}")
    st = schema["properties"]["validation"]["properties"]["state"]["enum"]
    if report["validation"]["state"] not in st:
        problems.append(f"validation.state {report['validation']['state']!r} not in {st}")

    # 4. street index entries carry their required fields
    entry_req = schema["definitions"]["streetIndexEntry"]["required"]
    entries = report["index"]["allSuppliedStrata"]
    if not entries:
        problems.append("no street index entries emitted")
    else:
        for jk, entry in sorted(entries.items()):
            for field in entry_req:
                if field not in entry:
                    problems.append(f"street {jk}: missing required field {field}")

    # 5. the guarantee that gives this schema its purpose
    try:
        camden_pressure.assert_no_forbidden_semantics(report)
    except camden_pressure.ForbiddenSemanticsError as exc:
        problems.append(f"forbidden semantics in a conforming report: {exc}")

    return [{
        "check": "structural:report-conforms-to-schema",
        "expected": "all required keys present, all consts and enums satisfied",
        "observed": {"schemaPath": SCHEMA_PATH,
                     "problemCount": len(problems),
                     "problems": problems[:20]},
        "passed": not problems,
    }]


def check_unrecognised_spatial_accuracy(root: str) -> list[dict]:
    """Schema drift must surface, not hide inside UNKNOWN_OTHER."""
    d = os.path.join(root, "spatial-drift")
    os.makedirs(d, exist_ok=True)
    pcn_path = os.path.join(d, "pcn.csv")
    with open(pcn_path, "w", encoding="utf-8") as fh:
        fh.write(",".join(fx.PCN_COLUMNS) + "\n")
        fh.write("T0,2025-03-03T09:15:00,01,Parked without payment,CEO On Street,"
                 "Test Street,Pay and Display,Private Car,Issued,"
                 "Something Brand New,CA\n")
    pcns = load_pcn_series(pcn_path)
    norm = camden_normalize.normalize_all(_minimal_bays(d), pcns)
    unrec = norm["missingness"]["unrecognisedSpatialAccuracyValues"]
    strata = norm["missingness"]["spatialStrataCounts"]
    return [{
        "check": "structural:unrecognised-spatial-accuracy-surfaced",
        "expected": "the novel value is reported verbatim AND lands in UNKNOWN_OTHER",
        "observed": {"unrecognisedValues": unrec, "strataCounts": strata},
        "passed": bool(unrec.get("Something Brand New") == 1
                       and strata[camden_normalize.STRATUM_UNKNOWN_OTHER] == 1),
    }]


def _minimal_bays(d: str) -> dict:
    path = os.path.join(d, "bays.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(",".join(fx.BAY_COLUMNS) + "\n")
        fh.write("CA,Test Street,Pay and Display,Mon-Fri 08:30-18:30,2 Hours,"
                 "Tariff A,60.0,10,LINESTRING (1 1, 2 2)\n")
    return load_bay_map(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Self-test the Camden signal harness against fixtures built "
                    "from known latent demand and deployment processes.")
    ap.add_argument("--keep", help="keep artefacts in this directory instead of a tempdir")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", help="write the self-test result JSON here")
    args = ap.parse_args(argv)

    root = args.keep or tempfile.mkdtemp(prefix="camden-selftest-")
    os.makedirs(root, exist_ok=True)

    results: list[dict] = []
    try:
        results += check_scenarios(root, args.verbose)
        results += check_determinism_fixture(root)
        results += check_determinism_report(root)
        results += check_forbidden_semantics()
        results += check_no_bay_level_join()
        results += check_no_hour_imputation(root)
        results += check_unrecognised_spatial_accuracy(root)
        results += check_schema_conformance(root)
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)

    passed = sum(1 for r in results if r["passed"])
    summary = {
        "selfTestVersion": "1.0.0",
        "recordId": "PTE-TEL-003",
        "fixtureIsRealData": False,
        "totalChecks": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "allPassed": passed == len(results),
        "results": results,
    }
    text = json.dumps(summary, indent=2, sort_keys=True, default=str)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")

    width = max(len(r["check"]) for r in results)
    print()
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['check']:<{width}}")
        if not r["passed"]:
            print(f"         expected: {json.dumps(r['expected'], default=str)}")
            print(f"         observed: {json.dumps(r['observed'], default=str)[:400]}")
    print(f"\n  {passed}/{len(results)} checks passed"
          f"{' - ALL GREEN' if passed == len(results) else ' - FAILURES PRESENT'}")
    if args.keep:
        print(f"  artefacts kept in {root}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
