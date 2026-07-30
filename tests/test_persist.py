"""
tests/test_persist.py — GitHub 状态持久层（monkeypatch requests / tempdir，无网络）

背景：Render 免费档磁盘 ephemeral，重部署/冷启动清盘回 seed(6-25) → 用户刷新的
推荐榜每次重进网站都穿越回老版。解法=状态存 app-state 分支，冷启动拉回，谁新用谁。覆盖：
  1. restore：远端 recommendations 更新（generated_at 新）→ 覆盖 seed 旧版
  2. restore：本地更新 → 不被远端旧版覆盖（谁新用谁的另一半）
  3. restore：看板缓存（日期分 key）本地缺才补、已有不动
  4. restore：scorecard 按条 merge——updated_at 新者胜、final_result 不被 None 覆盖
  5. restore：路径穿越（../）拒绝
  6. build_bundle：跳过不存在/超大文件
  7. save_bundle：未配 token → False 不炸；有 token → 走 分支确认→取sha→PUT 三步
"""

import sys
sys.path.insert(0, ".")

import json
import os
import tempfile
from pathlib import Path

import core.persist as ps

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


# ── restore_bundle ────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / ".data").mkdir()
    # 本地（=seed 恢复后）：6-25 旧榜 + 一份已有看板缓存 + 记分牌
    (root / ".data/recommendations.json").write_text(json.dumps(
        {"generated_at": 100, "candidates": [{"wallet": "0xold"}]}), encoding="utf-8")
    (root / ".cache/dashboard").mkdir(parents=True)
    (root / ".cache/dashboard/0xaa_2026-07-09.json").write_text('{"local": true}', encoding="utf-8")
    (root / ".data/scorecard.json").write_text(json.dumps({
        "k1": {"follow_call": "CHASED", "updated_at": 50, "final_result": "Yes", "settled_at": 60},
        "k2": {"follow_call": "ROOM LEFT", "updated_at": 10, "final_result": None},
    }), encoding="utf-8")

    bundle = {"saved_at": 999, "files": {
        ".data/recommendations.json": json.dumps({"generated_at": 200, "candidates": [{"wallet": "0xnew"}]}),
        ".cache/dashboard/0xaa_2026-07-09.json": '{"remote": true}',      # 本地已有 → 不动
        ".cache/dashboard/0xbb_2026-07-09.json": '{"remote": true}',      # 本地缺 → 补
        ".data/scorecard.json": json.dumps({
            "k1": {"follow_call": "CHASED", "updated_at": 80, "final_result": None},   # 新但结果空
            "k3": {"follow_call": "NO BASIS", "updated_at": 70, "final_result": None}, # 远端独有
        }),
        "../evil.txt": "pwn",                                             # 路径穿越 → 拒绝
    }}
    n = ps.restore_bundle(bundle, root=root)

    # 1. 远端新榜覆盖
    recs = json.loads((root / ".data/recommendations.json").read_text())
    check("远端新榜覆盖 seed 旧榜", recs["generated_at"], 200)
    # 3. 看板缓存
    check("已有看板缓存不被覆盖", json.loads((root / ".cache/dashboard/0xaa_2026-07-09.json").read_text()),
          {"local": True})
    check("缺失看板缓存被补上", (root / ".cache/dashboard/0xbb_2026-07-09.json").exists(), True)
    # 4. scorecard merge
    sc = json.loads((root / ".data/scorecard.json").read_text())
    check("scorecard 新条目胜出(updated_at 80)", sc["k1"]["updated_at"], 80)
    check("final_result 不被 None 覆盖", sc["k1"]["final_result"], "Yes")
    check("远端独有条目并入", sc["k3"]["follow_call"], "NO BASIS")
    check("本地独有条目保留", sc["k2"]["follow_call"], "ROOM LEFT")
    # 5. 路径穿越
    check("路径穿越被拒绝", (root.parent / "evil.txt").exists(), False)

    # 2. 本地更新时不被远端旧版覆盖
    old_bundle = {"saved_at": 1, "files": {
        ".data/recommendations.json": json.dumps({"generated_at": 150, "candidates": []})}}
    ps.restore_bundle(old_bundle, root=root)
    recs = json.loads((root / ".data/recommendations.json").read_text())
    check("远端旧榜不覆盖本地新榜", recs["generated_at"], 200)

# ── build_bundle ──────────────────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "a.json").write_text('{"x":1}', encoding="utf-8")
    (root / "big.json").write_text("x" * (ps.MAX_FILE_BYTES + 1), encoding="utf-8")
    b = ps.build_bundle({"a.json": root / "a.json", "missing.json": root / "nope",
                         "big.json": root / "big.json"}, {})
    check("build 收录存在的文件", "a.json" in b["files"], True)
    check("build 跳过不存在", "missing.json" in b["files"], False)
    check("build 跳过超大", "big.json" in b["files"], False)

# ── save_bundle ───────────────────────────────────────────────────────────────
saved_tok = os.environ.pop("GITHUB_TOKEN", None)
try:
    check("无 token → False 不炸", ps.save_bundle({"saved_at": 1, "files": {}}), False)

    calls = []
    class _R:
        def __init__(self, sc, payload=None):
            self.status_code = sc
            self._p = payload or {}
            self.text = ""
        def json(self):
            return self._p

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls.append((method, url.replace("https://api.github.com", "")))
        if "/git/ref/heads/app-state" in url:
            return _R(200, {"object": {"sha": "abc"}})
        if "/contents/state/bundle.json" in url and method == "GET":
            return _R(200, {"sha": "oldsha"})
        if method == "PUT":
            return _R(200)
        return _R(404)

    os.environ["GITHUB_TOKEN"] = "test-token"
    _real_req = ps.requests.request
    ps.requests.request = fake_request
    try:
        ok = ps.save_bundle({"saved_at": 1, "files": {"a": "b"}})
        check("有 token → 保存成功", ok, True)
        check("走了 分支确认→取sha→PUT", [c[0] for c in calls], ["GET", "GET", "PUT"])
    finally:
        ps.requests.request = _real_req
finally:
    os.environ.pop("GITHUB_TOKEN", None)
    if saved_tok:
        os.environ["GITHUB_TOKEN"] = saved_tok

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
