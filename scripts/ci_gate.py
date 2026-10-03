"""The `ci-success` job: pass only when every job it waits on succeeded.

GitHub reports a job that failed, was cancelled or was skipped as a result other than "success". Branch protection
requires this one check, so a job that stops running (a renamed job, a bad `if:`) turns the PR red instead of
silently dropping out. Reads the `needs` context as JSON from NEEDS_JSON. Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys


def failures(needs: dict[str, dict[str, str]]) -> dict[str, str]:
    """Each job whose result is not "success", with its result; a missing result counts as a failure."""
    return {job: info.get("result") or "missing" for job, info in needs.items() if info.get("result") != "success"}


def main(environ: dict[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    try:
        needs = json.loads(env.get("NEEDS_JSON") or "")
    except ValueError:
        print("NEEDS_JSON is missing or is not JSON", file=sys.stderr)
        return 1
    if not isinstance(needs, dict) or not needs:
        print("ci-success waits on no jobs; it must need every job in ci.yml", file=sys.stderr)
        return 1
    for job, info in sorted(needs.items()):
        print(f"{job}: {info.get('result')}")
    bad = failures(needs)
    if bad:
        print(f"\nNot green: {', '.join(f'{job} ({result})' for job, result in sorted(bad.items()))}", file=sys.stderr)
        return 1
    print(f"\nAll {len(needs)} jobs succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
