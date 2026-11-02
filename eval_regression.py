#!/usr/bin/env python3
"""A labeled regression suite for the scanner, in the spirit of an
agentevals-style trajectory check: each case says what the scanner SHOULD
decide, and the suite fails loudly the moment a code change silently stops
catching a known hiding technique.

This is deliberately a plain asserts harness, not a dependency on the
agentevals package -- the point this demo makes is the discipline (label
expected outcomes, assert on them, fail the build), which is exactly what
an eval harness like agentevals formalizes for an agent's full trajectory.
"""
import sys

from scanner import scan_pdf

CASES = [
    ("samples/clean_filing.pdf", False, "ordinary filing, no hidden text"),
    ("samples/malicious_filing.pdf", True, "white-on-white + microscopic-text payload"),
]


def main():
    failures = []
    for path, expect_flagged, description in CASES:
        findings = scan_pdf(path)
        got_flagged = bool(findings)
        status = "ok" if got_flagged == expect_flagged else "FAIL"
        print(f"[{status}] {path}: expected_flagged={expect_flagged} got_flagged={got_flagged} ({description})")
        if status == "FAIL":
            failures.append(path)

    if failures:
        print(f"\n{len(failures)} case(s) regressed: {failures}")
        sys.exit(1)
    print(f"\nall {len(CASES)} cases passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
