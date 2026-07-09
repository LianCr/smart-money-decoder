"""
core/llm.py — LLM 唯一客户端（全项目 AI 调用的单一出口）

之前 5 个模块（news/decoder/dual_catalyst/market_context/organize）各复制一份
requests.post + URL + 错误处理，改一处要改五遍；迁移点收口在这一处 —— 2026-07-08
课堂网关域名从 DNS 消失（NXDOMAIN，老师的 API Gateway 被删），正好只改这一个文件。

双后端（按 key 自动选，调用方零改动）：
  1. ANTHROPIC_API_KEY 存在 → 官方 Anthropic Messages API（用户自己的 key，自担费用）。
     模型默认 claude-sonnet-4-5 —— 与课堂网关同代（全部 prompt/守卫按它调教），
     可用 ANTHROPIC_MODEL 环境变量覆盖。响应文本在 content[] 的 text 块里。
  2. 否则 CLASSROOM_API_KEY 存在 → 旧课堂网关（URL 可用 GATEWAY_URL 环境变量覆盖，
     老师换了新部署只改环境变量不改代码）。
     🔴 课堂网关坑（实测）：只有 "claude-sonnet-4.5"（点号非横杠）能用；maxTokens 上限
     2048；结果在 resp.json()["output"]，不是 content[0].text。
  3. 都没有 → NO_KEY。

调用方拿到 GatewayError 后自行换成本模块的错误类型（如 DecoderError/NewsError），
保持 api 层错误映射语义不变。reason 枚举不变（NO_KEY/TIMEOUT/UNREACHABLE/
RATE_LIMITED/HTTP_ERROR），两个后端共用同一套分类。
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

# 课堂网关（旧后端；2026-07-08 起默认 URL 已 NXDOMAIN，留作老师重新部署后的回落位）
GATEWAY_URL = os.environ.get(
    "GATEWAY_URL",
    "https://4dm65e698a.execute-api.us-west-2.amazonaws.com/prod/invoke")
GATEWAY_MODEL = "claude-sonnet-4.5"

# 官方 Anthropic API（新后端）
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")


class GatewayError(Exception):
    """reason ∈ NO_KEY | TIMEOUT | UNREACHABLE | RATE_LIMITED | HTTP_ERROR"""
    def __init__(self, reason: str, message: str):
        self.reason = reason
        self.message = message
        super().__init__(f"{reason}: {message}")


def call_gateway(prompt: str, max_tokens: int = 2000, timeout: int = 30) -> str:
    """发一次 LLM 调用，返回文本原文（可能为空串，空值语义由调用方裁决）。
    按环境变量自动选后端；函数名保持 call_gateway 不动 —— 全项目调用点零改动。"""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return _call_anthropic(anthropic_key, prompt, max_tokens, timeout)
    classroom_key = os.environ.get("CLASSROOM_API_KEY")
    if classroom_key:
        return _call_classroom(classroom_key, prompt, max_tokens, timeout)
    raise GatewayError("NO_KEY", "缺少 ANTHROPIC_API_KEY（或 CLASSROOM_API_KEY），请在 .env 配置")


def _classify_and_raise(resp) -> None:
    """两后端共用的非 200 分类。529 = Anthropic overloaded，与 429 同属'稍后重试'。"""
    if resp.status_code in (429, 529):
        raise GatewayError("RATE_LIMITED", f"LLM 服务限流/过载（{resp.status_code}），请稍后重试")
    if resp.status_code != 200:
        raise GatewayError("HTTP_ERROR", f"LLM 服务返回 {resp.status_code}：{resp.text[:200]}")


def _call_anthropic(key: str, prompt: str, max_tokens: int, timeout: int) -> str:
    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        raise GatewayError("TIMEOUT", "Anthropic API 超时，请稍后重试")
    except requests.exceptions.RequestException as e:
        raise GatewayError("UNREACHABLE", f"无法连接 Anthropic API：{e}")

    if resp.status_code == 401:
        raise GatewayError("HTTP_ERROR", "401 认证失败 —— ANTHROPIC_API_KEY 无效或已撤销")
    _classify_and_raise(resp)
    # 响应文本在 content 列表的 text 块里（可能混有其他类型块，只取 text 拼接）
    blocks = resp.json().get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_classroom(key: str, prompt: str, max_tokens: int, timeout: int) -> str:
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

    _classify_and_raise(resp)
    return resp.json().get("output", "")
