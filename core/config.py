"""
core/config.py — 全项目共享配置的单一出口

🔴 BRIEFING_AS_OF（数据世界"现在"）只在这里定义。改它会 re-key 所有 (钱包,as_of)
缓存 → 全部重烧（每钱包 ~12k token），别随手改；真上 Bedrock/有预算再切 date.today()。
之前它散落在 api/main.py、hot_traders.py、recommend.py 各写一份，fetcher 层函数
签名还残留 "2026-06-20" 旧快照默认值（忘传 as_of 会静默拿到旧世界数据）——现已全部收口到此。
"""
import os

BRIEFING_AS_OF = os.environ.get("BRIEFING_AS_OF", "2026-06-25")
