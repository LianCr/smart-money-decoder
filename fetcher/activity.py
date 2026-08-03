"""
fetcher/activity.py — Activity/Trades 系 API 的共享异常类型。

（2026-08-03 瘦身：v2 /analyze 解读卡链路下架，本文件的「最近一次买入时间」查询
（get_entry_time 及翻页/过滤实现）随之删除，见 git 历史。正向流程的建仓时间来自
Heisenberg 数据层（fetcher/actions.py），回测的历史翻页在 backtest/full_activity.py。
保留 ActivityAPIError：它是 backtest/full_activity.py、backtest/resolution.py
沿用的统一异常契约（reason 机器读 + message 人读）。）
"""


class ActivityAPIError(Exception):
    """网络请求失败时统一抛这个，携带机器读的 reason 和人读的 message"""
    def __init__(self, reason: str, message: str):
        self.reason  = reason
        self.message = message
        super().__init__(message)
