"""
tests/test_backtest_finalize.py — backtest/pipeline._finalize 落盘接 jsonstore（P2-25，零网络）

背景：P0-1 收尾复查时全仓只剩这一处裸 write_text（回测结果 result.json）。
写到一半被打断=半截 JSON，/backtest 读取端虽有 try 兜底，但产物是 git 跟踪的
静态正本，坏了就得重跑烧 token 的采样——所以同样接 core/jsonstore 原子写。覆盖：
  1. _finalize 产物落盘、可解析、结构完整（wallet/overview/samples）
  2. 格式与旧裸写一致：indent=2 + ensure_ascii=False（中文原样、不转义）
  3. 空样本列表不炸（overview 全 0）
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import backtest.pipeline as bp

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


SAMPLE = {"hit": True, "bet_won": True, "t1_card": {"confidence": "high"},
          "question": "中文问题?"}

_real = bp.RESULT_PATH
try:
    with tempfile.TemporaryDirectory() as tmp:
        bp.RESULT_PATH = Path(tmp) / "nested" / "result.json"   # 父目录不存在→原语自动建
        out = bp._finalize([dict(SAMPLE)], "0xtest")
        check("返回值含 overview", "overview" in out, True)
        check("落盘文件存在（父目录自动创建）", bp.RESULT_PATH.exists(), True)
        raw = bp.RESULT_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        check("落盘可解析且 wallet 正确", data.get("wallet"), "0xtest")
        check("样本原样落盘", data.get("samples"), [SAMPLE])
        check("overview 命中数正确", data["overview"]["directional"], {"hits": 1, "total": 1})
        check("格式不变：indent=2（有缩进换行）", raw.startswith('{\n  "'), True)
        check("格式不变：ensure_ascii=False（中文原样）", "中文问题?" in raw, True)

        out = bp._finalize([], "0xempty")                        # 空样本不炸
        check("空样本 overview 全 0", out["overview"]["directional"], {"hits": 0, "total": 0})
finally:
    bp.RESULT_PATH = _real

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
