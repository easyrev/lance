"""Check the issue 7207 branch pair without modifying either branch."""

import subprocess
import sys

PURE = "fix/7207-reclaim-lost-commit-indices"
REVIEW = "review/7207-reclaim-lost-commit-indices"
BASELINE = "46d7bfdda8ac303d5363c851d6883facb249cb56"


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


if len(sys.argv) not in (1, 3):
    raise SystemExit("Usage: check_separation.py [PURE_REF REVIEW_REF]")

pure, review = sys.argv[1:] if len(sys.argv) == 3 else (PURE, REVIEW)
print(f"Upstream baseline: {BASELINE}")
print(f"Pure: {pure} {git('rev-parse', pure)}")
print(f"Review: {review} {git('rev-parse', review)}")

pure_paths = git("ls-tree", "-r", "--name-only", pure).splitlines()
if any(path.startswith("review/issue-") for path in pure_paths):
    raise SystemExit("FAIL: pure branch contains review material")
print("PASS: pure has no review/issue-* paths")

subprocess.run(["git", "merge-base", "--is-ancestor", pure, review], check=True)
print("PASS: pure is an ancestor of review")

changed = git("diff", "--name-only", pure, review).splitlines()
if any(not path.startswith("review/issue-7207/") for path in changed):
    raise SystemExit("FAIL: review changes a path outside review/issue-7207/")
print(f"PASS: all {len(changed)} differing paths are under review/issue-7207/")
