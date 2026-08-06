"""
backtest/_field_probe.py — T1 前置字段实测（下划线前缀 = 内部诊断，不入生产、可删）

一次性回答五个问题，结果进 CLAUDE.md 坑表后才许写生产代码（参数名学费只交一次）：
  1. 579 按地址查：记录里 f_score/tier 真名真值？rank 字段真名？
  2. _15d 疑云：同一钱包传 7d/15d/30d，数字变不变（不变=窗口恒 15d，展示标错窗口）
  3. 575 created_at 真格式（ISO/纯日期/epoch 秒/毫秒）
  4. 581 五个反作弊旗标真名与取值
  5. Batch Market Resolution 调用形（未验证假设：客户端无 workflow 概念，试几种 shape）
顺手：2 个已结算盘 574 winning_outcome vs 575 winning_side 交叉基线。

跑法：.venv/bin/python backtest/_field_probe.py （免费 key；402 = 额度未充，止步报告）
"""
import json
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()

from fetcher.heisenberg import call, results, HeisenbergError

KEN = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"   # ImJustKen（已验证样本）


def dump(label, rec, keys=None):
    print(f"\n—— {label} ——")
    if rec is None:
        print("  （无记录）")
        return
    for k in (keys or sorted(rec.keys())):
        print(f"  {k} = {json.dumps(rec.get(k), ensure_ascii=False)}")


def main():
    # 0) 额度探活（⚠ 实测 limit≤2 → 404 body validation，文档"1-200"是假的，最小=3）
    try:
        call(574, {"condition_id": "0x0"}, limit=10)
        print("✓ 额度探活通过（574 有响应）")
    except HeisenbergError as e:
        print(f"✗ 数据层不可用：{e.reason} —— {e.message}")
        if e.reason == "INSUFFICIENT_CREDIT":
            print("  ⛔ 额度未充，本场止步于此（计划的硬前置）")
        return 1

    # 1+2) 579 按地址 · 三窗口对比
    print("\n===== ① 579 按地址查（f_score/tier 真名） + ② _15d 疑云 =====")
    per_period = {}
    for period in ("7d", "15d", "30d"):
        try:
            rs = results(call(579, {"wallet_address": KEN, "leaderboard_period": period}))
        except HeisenbergError as e:
            print(f"  {period}: 失败 {e.reason}")
            continue
        per_period[period] = rs[0] if rs else None
        dump(f"579 period={period}", per_period.get(period))
    vals = {p: (r.get("win_rate"), r.get("total_pnl"), r.get("rank"))
            for p, r in per_period.items() if r}
    if len(vals) >= 2:
        distinct = len(set(vals.values()))
        print(f"\n  ② 裁决：三窗口取值 {'各不相同 → 窗口参数真生效' if distinct > 1 else '完全相同 → 疑似恒 15d，展示须改标注'}")
        print(f"     {vals}")

    # 3) 575 created_at 格式（拿一个活跃 cid：先从 574 抓一个未结算盘）
    print("\n===== ③ 575 created_at 真格式 =====")
    try:
        open_mkts = results(call(574, {"closed": "False"}, limit=3))
        cid = next((m.get("condition_id") for m in open_mkts if m.get("condition_id")), None)
        if cid:
            m360 = results(call(575, {"condition_id": cid}))
            rec = m360[0] if m360 else None
            dump(f"575 cid={cid[:14]}…", rec,
                 keys=["created_at", "end_date", "updated_at", "snapshot_time",
                       "winning_side", "question"]) if rec else print("  575 无记录")
    except HeisenbergError as e:
        print(f"  失败 {e.reason}: {e.message[:100]}")

    # 4) 581 五旗标
    print("\n===== ④ 581 五个反作弊旗标真名 =====")
    try:
        rs = results(call(581, {"proxy_wallet": KEN, "window_days": "15"}))
        rec = rs[0] if rs else None
        if rec:
            flag_keys = sorted(k for k in rec.keys() if "flag" in k.lower() or "sybil" in k.lower()
                               or "anomaly" in k.lower() or "suspicious" in k.lower())
            dump("581 含 flag 字样的全部字段", {k: rec.get(k) for k in flag_keys}, keys=flag_keys)
            for want in ("sybil_risk_flag", "timing_anomaly_flag", "suspicious_win_rate_flag",
                         "position_size_volatility_flag", "perfect_timing_flag"):
                print(f"  预期名 {want}: {'✓ 在' if want in rec else '✗ 不在'}（值={rec.get(want)!r}）")
    except HeisenbergError as e:
        print(f"  失败 {e.reason}: {e.message[:100]}")

    # 5) Batch Market Resolution 调用形（未验证假设，试三种 shape）
    print("\n===== ⑤ Batch Market Resolution 调用形试探 =====")
    settled = []
    try:
        settled = [m.get("condition_id") for m in results(call(574, {"closed": "True"}, limit=2))
                   if m.get("condition_id")]
    except HeisenbergError:
        pass
    if len(settled) >= 2:
        cids = ",".join(settled[:2])
        for label, params in [("agent_id=0 + condition_ids", (0, {"condition_ids": cids})),
                              ("agent_id=0 + workflow 名", (0, {"workflow": "batch_market_resolution",
                                                                "condition_ids": cids})),
                              ("574 + condition_ids 复数参数", (574, {"condition_ids": cids}))]:
            try:
                payload = call(params[0], params[1], limit=10)
                rs = results(payload)
                print(f"  {label}: HTTP 200，results={len(rs)} 条"
                      f"{'（含数据→可能可用！dump 首条）' if rs else '（空）'}")
                if rs:
                    dump(f"  首条（{label}）", rs[0])
            except HeisenbergError as e:
                print(f"  {label}: ✗ {e.reason} —— {e.message[:80]}")

        # 顺手：574/575 结算交叉基线
        print("\n===== 附：574 winning_outcome vs 575 winning_side（2 个已结算盘） =====")
        for cid in settled[:2]:
            try:
                m574 = results(call(574, {"condition_id": cid, "closed": "True"}))
                m575 = results(call(575, {"condition_id": cid}))
                wo = (m574[0].get("winning_outcome") if m574 else None)
                ws = (m575[0].get("winning_side") if m575 else None)
                print(f"  {cid[:14]}… 574={wo!r} · 575={ws!r} · "
                      f"{'一致' if wo and ws and str(wo).lower() == str(ws).lower() else '⚠不一致/缺'}")
            except HeisenbergError as e:
                print(f"  {cid[:14]}… 失败 {e.reason}")
    else:
        print("  拿不到 2 个已结算盘，跳过")

    return 0


if __name__ == "__main__":
    sys.exit(main())
