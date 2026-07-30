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
