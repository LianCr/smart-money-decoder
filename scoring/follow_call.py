"""
scoring/follow_call.py — 代码版跟单判定（T2.2 从 services/dashboard_build._code_follow_call 迁入）

判定本质是价格位移数学（应归代码，红线 5）：无证据→NO BASIS；价已大幅走过→CHASED；
否则 ROOM LEFT。信心由 market_thesis 直出，这里只出 follow_call。阈值正本在 constants。
"""
from scoring.constants import CHASED_MOVED_PCT


def code_follow_call(facts: dict) -> str:
    if not (facts.get("support_catalysts") or facts.get("threat_catalysts")):
        return "NO BASIS"
    moved = facts.get("price_already_moved")
    if moved is not None and moved >= CHASED_MOVED_PCT:
        return "CHASED"
    return "ROOM LEFT"
