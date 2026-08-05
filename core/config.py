"""
core/config.py — 全项目共享配置的单一出口

🔴 BRIEFING_AS_OF（数据世界"现在"）只在这里定义。
2026-07-08 起默认 = date.today()（真·逐日实时）：课堂网关死亡后已切用户自己的
ANTHROPIC_API_KEY，"钉死 6-25 省 token"的历史约束解除。经济性由缓存层兜住：
/dashboard 默认读该钱包**最新日期**快照（core/cachefiles.newest_dated，旧快照
零 token 秒回），只有 新钱包/用户点刷新/AI 精选保鲜 才在今天真烧。
环境变量 BRIEFING_AS_OF 仍可覆盖（回测/复现某天快照用）。
注意：值在进程启动时求值——本地 dev 常重启无感；Render 免费档闲置即休眠、
冷启动即取新日期，长驻进程跨天需重启才换日（已知边界，非 bug）。
"""
import os
from datetime import date

BRIEFING_AS_OF = os.environ.get("BRIEFING_AS_OF") or date.today().isoformat()

# ── 入站限流阈值（P1-15，core/ratelimit.py 用，api 层对 /dashboard 上闸）──
# 🔴 闸是防"额度被脚本刷空"，不是关门——「完全开放」的产品决策（2026-07-07）不变。
# 默认值对人类浏览宽松：缓存命中为主的真实用法一分钟点不了 30 次；每日全局 500 是
# 最坏情况（全部 miss 重建，~$0.05/次）≈$25/天 的硬顶。环境变量可调，改默认值走这里。
RATE_LIMIT_PER_IP         = int(os.environ.get("RATE_LIMIT_PER_IP", "30"))          # 每 IP 每窗口最多次数
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))  # 滑动窗口长（秒）
RATE_LIMIT_DAILY_GLOBAL   = int(os.environ.get("RATE_LIMIT_DAILY_GLOBAL", "500"))   # 每日（UTC）全站总量

# ── 信心分档回验（T2.5，confidence_replay.py 用）──
# 🔴 样本数低于此阈值的信心档不显示命中率百分比（显示"样本不足"）——两三个样本算出的
# 100%/0% 是误导，宁可不给数字。T2.2 落地 scoring/constants.py 时此常量一并迁走。
REPLAY_MIN_BUCKET_N = int(os.environ.get("REPLAY_MIN_BUCKET_N", "5"))               # 每档最少样本数
