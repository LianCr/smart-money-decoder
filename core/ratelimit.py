"""
core/ratelimit.py — 烧 token 端点的入站闸（P1-15）：IP 滑动窗口 + 每日全局总量硬闸。

🔴 目的是防"额度被刷空"，**不是关门**——「完全开放模式」的产品决策（2026-07-07，
陌生钱包/刷新真烧 token、用户自担额度）不变：阈值对正常浏览宽松（缓存命中为主的
真实用法远够不到），拦的是脚本循环刷。阈值正本在 core/config.py（环境变量可调）。

实现取舍：进程内存、无 Redis 依赖——Render 免费档单实例，够用；将来多实例时各实例
独立计数（闸宽松 N 倍，仍是硬上限，可接受；要精确就换 coordinator，接口不用变）。

纯逻辑、时钟注入、线程安全（端点跑在 anyio 线程池，并发进闸）。返回契约对齐
services 层纯数据风格：放行 → None；拒绝 → {"error", "message", "retry_after"}，
HTTP 429 映射留在 api 层。**被拒的请求不消耗每日额度**（拒绝是免费的）。

IP 来源（api 层 _client_ip）：X-Forwarded-For 首项（Render 代理层管这个头），本地
直连退回 request.client.host。直连场景该头可伪造——所以每日**全局**硬闸不认 IP，
是刷不开的兜底。
"""

import math
import threading
import time
from collections import deque

_DAY = 86400   # 用 epoch 天（=UTC 日界）判翻天：now // 86400


class RateLimiter:
    """IP 滑动窗口 + 每日全局总量。check(ip) → None=放行（记账）/ dict=拒绝（不记账）。"""

    def __init__(self, per_ip_max: int, window_seconds: int, daily_max: int, clock=None):
        self.per_ip_max = int(per_ip_max)
        self.window = int(window_seconds)
        self.daily_max = int(daily_max)
        self.clock = clock or time.time
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}     # ip → 窗口内放行时间戳
        self._day = None                       # 当前 epoch 天
        self._day_count = 0                    # 当天全局已放行数

    def check(self, ip: str):
        now = self.clock()
        today = int(now // _DAY)
        with self._lock:
            if self._day != today:             # 翻天（UTC）：全局计数归零
                self._day, self._day_count = today, 0
            q = self._hits.get(ip)
            if q is None:
                q = self._hits[ip] = deque()
            cutoff = now - self.window
            while q and q[0] <= cutoff:        # 老记录滑出窗口
                q.popleft()
            if len(q) >= self.per_ip_max:
                # 最早那条在 q[0]+window 整点滑出（cutoff 判的是 <=），ceil 即可、不多等
                retry = max(1, math.ceil(q[0] + self.window - now))
                return {
                    "error": "RATE_LIMITED",
                    "message": f"请求太频繁：同一 IP 每 {self.window} 秒最多 "
                               f"{self.per_ip_max} 次分析请求，请稍等再试。",
                    "retry_after": retry,
                }
            if self._day_count >= self.daily_max:
                retry = max(1, int(_DAY - now % _DAY))
                return {
                    "error": "DAILY_LIMIT_REACHED",
                    "message": "今日全站分析额度已用完——这是防止 API 额度被脚本刷空的"
                               "硬闸，不是关门；明天（UTC）自动恢复。",
                    "retry_after": retry,
                }
            q.append(now)
            self._day_count += 1
            if len(self._hits) > 1024:         # 防伪造 IP 撑爆内存：清空窗口的死条目
                dead = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
                for k in dead:
                    del self._hits[k]
            return None
