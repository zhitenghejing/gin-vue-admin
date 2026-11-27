#!/usr/bin/env python3
"""One verification entry for local development, pre-push, Paseo and CI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def changed_files():
    base = os.environ.get("GVA_VERIFY_BASE")
    if base and not base.strip("0"):
        base = None  # GitHub's first push has an all-zero "before" SHA.
    if not base:
        result = subprocess.run(["git", "merge-base", "HEAD", "main"], cwd=ROOT, capture_output=True, text=True)
        base = result.stdout.strip() if result.returncode == 0 else "HEAD"
    tracked = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "--diff-filter=ACMR", "-z", base], cwd=ROOT)
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT)
    return sorted({os.fsdecode(p) for p in (tracked + untracked).split(b"\0") if p})


def go_tests(command):
    counts = {"pass": 0, "fail": 0, "skip": 0}
    process = subprocess.Popen(command, cwd=ROOT / "server", stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            print(line, end="", flush=True)
            continue
        if event.get("Action") in counts and event.get("Test"):
            counts[event["Action"]] += 1
        if event.get("Action") in ("output", "build-output"):
            print(event.get("Output", ""), end="", flush=True)
    process.stdout.close()
    code = process.wait()
    print(f"Go tests (including subtests): {counts['pass']} passed, {counts['fail']} failed, {counts['skip']} skipped.", flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="also run full Go vet and race checks")
    args = parser.parse_args()
    failures = []
    files = [p for p in changed_files() if p.startswith("server/") and p.endswith(".go") and (ROOT / p).is_file()]
    if files:
        result = subprocess.run(["gofmt", "-l", *files], cwd=ROOT, capture_output=True, text=True)
        if result.returncode or result.stdout:
            print("gofmt failed:\n" + result.stdout + result.stderr, flush=True)
            failures.append("format")
    checks = [
        ("workflow tests", ["python3", "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"], ROOT, False),
        ("frontend tests/build and embed staging", ["python3", "-B", "scripts/frontend.py", "verify"], ROOT, False),
        ("Go build", ["go", "build", "./..."], ROOT / "server", False),
        ("Go tests", ["go", "test", "-json", "./..."], ROOT / "server", True),
    ]
    for label, command, cwd, is_test in checks:
        print(f"\nChecking {label}: {' '.join(command)}", flush=True)
        code = go_tests(command) if is_test else subprocess.run(command, cwd=cwd).returncode
        if code:
            failures.append(label)
    # Never validate a stale dist when the frontend step failed.
    if "frontend tests/build and embed staging" not in failures:
        embedded = [
            ("embedded build", ["go", "build", "-tags", "embedweb", "./..."], False),
            ("embedded assets/routing tests", ["go", "test", "-json", "-tags", "embedweb", "./internal/webui"], True),
        ]
        if args.all:
            embedded.append(("embedded race", ["go", "test", "-json", "-race", "-tags", "embedweb", "./internal/webui"], True))
        for label, command, is_test in embedded:
            print(f"\nChecking {label}: {' '.join(command)}", flush=True)
            if (go_tests(command) if is_test else subprocess.run(command, cwd=ROOT / "server").returncode):
                failures.append(label)
    else:
        print("Embedded checks NOT RUN: current frontend build failed.", flush=True)
    if args.all:
        for label, command, is_test in [
            ("Go vet", ["go", "vet", "./..."], False),
            ("Go race", ["go", "test", "-json", "-race", "./..."], True),
        ]:
            print(f"\nChecking {label}: {' '.join(command)}", flush=True)
            if (go_tests(command) if is_test else subprocess.run(command, cwd=ROOT / "server").returncode):
                failures.append(label)
    if failures:
        print("\nFAILED: " + ", ".join(failures), file=sys.stderr)
        return 1
    print("\nRequested checks passed. Skipped tests are reported above and are not validated.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        sys.exit(1)
