"""Contract: the commit gate detects CJK messages and real git-commit calls.

Unit-tests the pure decision functions only. run_tests() is deliberately not
exercised here — it shells out to the whole tests/ suite and would recurse.
"""

import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import precommit_gate as gate


passed = 0
failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}: got={got!r} want={want!r}")


# --- has_cjk ---------------------------------------------------------------
check("plain English is not CJK", gate.has_cjk("fix: dedupe dashboard builds"), False)
check("empty string is not CJK", gate.has_cjk(""), False)
check("None is not CJK", gate.has_cjk(None), False)
check("Chinese message is CJK", gate.has_cjk("修复: 看板去重"), True)
check("mixed English+Chinese is CJK", gate.has_cjk("fix 看板 dedupe"), True)
check("fullwidth punctuation is CJK", gate.has_cjk("feat：redis"), True)
check("ASCII punctuation is not CJK", gate.has_cjk("feat: redis (v2) #3 -> ok!"), False)

# --- is_git_commit ---------------------------------------------------------
check("git commit -m is a commit", gate.is_git_commit("git commit -m 'x'"), True)
check("git add is not a commit", gate.is_git_commit("git add -A"), False)
check("git commit in a chain is a commit",
      gate.is_git_commit("git add -A && git commit -m 'x'"), True)
check("git commit-graph is not a commit",
      gate.is_git_commit("git commit-graph write"), False)
check("substring mygit is not a commit",
      gate.is_git_commit("mygit commit -m 'x'"), False)
check("empty command is not a commit", gate.is_git_commit(""), False)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
