#!/usr/bin/env python3
"""Runs every tool test, and proves it ran every one.

    python3 tools/run_tests.py

`unittest discover` on its own is not enough for CI. It exits 0 when it
finds nothing, so a renamed directory or a changed pattern reads as a
green run with no tests in it. It also exits 0 when tests skip themselves,
which is how a missing dependency turns a gate off silently rather than
loudly. Both failure modes look exactly like success in a workflow log.

So this discovers the same way, then asserts what discovery cannot: every
tools/test_*.py on disk was actually imported and contributed tests, at
least one test ran, and nothing was skipped or left as an expected
failure. Anything unusual is reported by name.
"""

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def main():
    on_disk = sorted(p.stem for p in TOOLS.glob("test_*.py"))
    if not on_disk:
        print("no tools/test_*.py found at all", file=sys.stderr)
        return 1

    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TOOLS), pattern="test_*.py", top_level_dir=str(TOOLS))

    # Discovery reports an import failure as a synthetic test that fails
    # when run, which is honest but easy to lose in the noise. Naming the
    # modules that produced tests catches it before anything executes.
    collected = set()

    def walk(test):
        if isinstance(test, unittest.TestSuite):
            for child in test:
                walk(child)
            return
        collected.add(type(test).__module__.split(".")[-1])

    walk(suite)

    missing = [name for name in on_disk if name not in collected]
    if missing:
        print(f"these test modules produced no tests: {', '.join(missing)}",
              file=sys.stderr)
        print("(usually an import error; run the module directly to see it)",
              file=sys.stderr)
        return 1

    result = unittest.TextTestRunner(verbosity=2).run(suite)

    print()
    print(f"modules: {len(on_disk)} ({', '.join(on_disk)})")
    print(f"tests:   {result.testsRun}")

    if result.testsRun == 0:
        print("discovery found modules but ran no tests", file=sys.stderr)
        return 1

    # A skip is a test that did not check anything. In a repository whose
    # only dependency is jsonschema, the honest response to a missing one
    # is a red run, not a quiet pass.
    withheld = [(str(case), reason) for case, reason in result.skipped]
    withheld += [(str(case), "expected failure") for case, _ in result.expectedFailures]
    if withheld:
        print(f"{len(withheld)} test(s) did not run:", file=sys.stderr)
        for name, reason in withheld:
            print(f"  {name}: {reason}", file=sys.stderr)
        return 1

    if not result.wasSuccessful():
        return 1

    print("every tool test ran and passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
