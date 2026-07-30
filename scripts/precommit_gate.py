#!/usr/bin/env python3
"""Claude Code PreToolUse gate for `git commit` — mechanical enforcement of the
CLAUDE.md collaboration discipline (this is the "teeth", not just prose).

Reads the hook payload as JSON on stdin. When the tool call is a `git commit`,
it enforces two rules and, on violation, prints a PreToolUse deny decision so
the commit is blocked:

  1. English-only commit messages (CLAUDE.md 协作纪律 #9 / AGENTS.md): a message
     containing CJK characters is rejected.
  2. Tests green before commit (CLAUDE.md 协作纪律 #1, TDD): every `tests/test_*.py`
     must pass; a failing test blocks the commit.

Pure decision functions (`has_cjk`, `is_git_commit`) are unit-tested in
`tests/test_precommit_gate.py`. `run_tests` is intentionally not called from tests
(it would recurse into the suite).

Fail-open on infrastructure errors: if the gate itself cannot run (bad JSON,
missing interpreter), it allows the commit and surfaces a warning, so a broken
gate never wedges every commit.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

# CJK Unified Ideographs + CJK symbols/punctuation + fullwidth/halfwidth forms.
_CJK = re.compile(r"[　-〿㐀-䶿一-鿿豈-﫿＀-￯]")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def has_cjk(text: str) -> bool:
    """True if the text contains any CJK character (i.e. not English-only)."""
    return bool(_CJK.search(text or ""))


def is_git_commit(command: str) -> bool:
    """True if the shell command invokes `git commit` (not `git commit-graph`,
    not a substring like `mygit commit`)."""
    if not command:
        return False
    # Match `git commit` as a standalone invocation, allowing a leading path or
    # env assignment and requiring a word boundary after `commit`.
    return bool(re.search(r"(^|[\s;&|(])git\s+commit(\s|$)", command))


def _python_bin() -> str:
    venv = os.path.join(REPO_ROOT, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


def run_tests() -> tuple[bool, list[str]]:
    """Run every tests/test_*.py as a standalone script (the project's convention).
    Returns (all_passed, [failed_file, ...])."""
    py = _python_bin()
    failed: list[str] = []
    for test_file in sorted(glob.glob(os.path.join(REPO_ROOT, "tests", "test_*.py"))):
        try:
            proc = subprocess.run(
                [py, test_file], cwd=REPO_ROOT,
                capture_output=True, text=True, timeout=120)
        except Exception as exc:  # noqa: BLE001 — infra failure, treat as failure
            failed.append(f"{os.path.basename(test_file)} ({type(exc).__name__})")
            continue
        if proc.returncode != 0:
            failed.append(os.path.basename(test_file))
    return (not failed, failed)


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = (payload.get("tool_input") or {}).get("command", "")
    except Exception:
        # Can't parse the hook input — fail open (allow), don't wedge commits.
        return

    if not is_git_commit(command):
        return

    if has_cjk(command):
        _deny("Commit message contains non-English (CJK) characters. Per "
              "CLAUDE.md 协作纪律 #9 / AGENTS.md, every commit message must be "
              "written in English. Rewrite the message in English and retry.")
        return

    ok, failed = run_tests()
    if not ok:
        _deny("Tests are not green — commit blocked (CLAUDE.md 协作纪律 #1, TDD: "
              "'完成' = 测试全绿). Failing: " + ", ".join(failed) +
              ". Fix the tests, then retry the commit.")
        return

    # Allowed: no output = no decision = normal permission flow proceeds.


if __name__ == "__main__":
    main()
