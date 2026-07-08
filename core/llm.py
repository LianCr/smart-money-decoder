"""
core/llm.py — 课堂网关唯一客户端（全项目 AI 调用的单一出口）

之前 5 个模块（news/decoder/dual_catalyst/market_context/organize）各复制一份
requests.post + URL + 错误处理，改一处要改五遍；真上 Bedrock 时的迁移点也是这里一处。

🔴 课堂网关坑（实测）：只有 "claude-sonnet-4.5"（点号非横杠）能用，haiku 返 502；
maxTokens 上限 2048；结果在 resp.json()["output"]，不是 content[0].text。

调用方拿到 GatewayError 后自行换成本模块的错误类型（如 DecoderError/NewsError），
保持 api 层错误映射语义不变。
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

GATEWAY_URL = "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke"
GATEWAY_MODEL = "claude-sonnet-4.5"


class GatewayError(Exception):
    """reason ∈ NO_KEY | TIMEOUT | UNREACHABLE | RATE_LIMITED | HTTP_ERROR"""
    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(f"{reason}: {message}")


def call_gateway(prompt: str, max_tokens: int = 2000, timeout: int = 30) -> str:
    """发一次网关调用，返回 output 原文（可能为空串，空值语义由调用方裁决）。"""
    key = os.environ.get("CLASSROOM_API_KEY")
    if not key:
        raise GatewayError("NO_KEY", "缺少 CLASSROOM_API_KEY，请在 .env 配置")
    try:
        resp = requests.post(
            GATEWAY_URL,
            headers={"Content-Type": "application/json", "x-api-key": key},
            json={"model": GATEWAY_MODEL, "input": prompt, "maxTokens": max_tokens},
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise GatewayError("TIMEOUT", "课堂网关超时，请稍后重试")
    except requests.exceptions.RequestException as e:
        raise GatewayError("UNREACHABLE", f"无法连接课堂网关：{e}")

    if resp.status_code == 429:
        raise GatewayError("RATE_LIMITED", "课堂网关请求过于频繁，请稍后重试")
    if resp.status_code != 200:
        raise GatewayError("HTTP_ERROR", f"课堂网关返回 {resp.status_code}：{resp.text[:200]}")
    return resp.json().get("output", "")
