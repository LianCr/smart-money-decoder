"""
tests/test_llm_backend.py — core/llm.py 双后端选择与错误分类（monkeypatch，无网络）

背景（2026-07-08）：课堂网关域名 NXDOMAIN（老师的 API Gateway 被删），core/llm.py
改造成双后端：ANTHROPIC_API_KEY → 官方 Messages API；否则 CLASSROOM_API_KEY → 旧网关。
call_gateway 签名不变、reason 枚举不变 —— 全项目调用点零改动。覆盖：
  1. 有 ANTHROPIC_API_KEY → 打官方 API（URL/headers/body 形状正确），取 content[] text 块
  2. 只有 CLASSROOM_API_KEY → 打课堂网关，取 output 字段
  3. 两个都有 → 优先官方 API
  4. 都没有 → NO_KEY
  5. 错误分类：429/529→RATE_LIMITED · 401→HTTP_ERROR · 其他非200→HTTP_ERROR ·
     Timeout→TIMEOUT · 网络异常→UNREACHABLE
  6. content 混有非 text 块只拼 text；content 空返回空串（空值语义归调用方）
"""

import sys
sys.path.insert(0, ".")

import os
import requests as _requests

import core.llm as llm

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


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text="err"):
        self.status_code = status_code
        self._p = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._p


class _FakePost:
    def __init__(self, result):
        self.result = result          # _FakeResp 或 Exception
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FakeRequestsModule:
    def __init__(self, post):
        self.post = post
        self.exceptions = _requests.exceptions


def _with_env(env, fn):
    """临时替换两个 key 的环境变量，跑完恢复（不污染真实 .env 加载的值）。"""
    keys = ("ANTHROPIC_API_KEY", "CLASSROOM_API_KEY")
    saved = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        os.environ.update(env)
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_real_requests = llm.requests
try:
    # 1. 官方 API 路径：URL/headers/body 形状 + 取 text 块
    ok = _FakeResp(200, {"content": [{"type": "text", "text": "hello"}]})
    post = _FakePost(ok); llm.requests = _FakeRequestsModule(post)
    out = _with_env({"ANTHROPIC_API_KEY": "sk-test"},
                    lambda: llm.call_gateway("hi", max_tokens=123))
    check("官方路径返回文本", out, "hello")
    call = post.calls[0]
    check("官方 URL", call["url"], "https://api.anthropic.com/v1/messages")
    check("x-api-key header", call["headers"].get("x-api-key"), "sk-test")
    check("anthropic-version header", call["headers"].get("anthropic-version"), "2023-06-01")
    check("body.max_tokens 透传", call["json"].get("max_tokens"), 123)
    check("body.messages 形状", call["json"].get("messages"),
          [{"role": "user", "content": "hi"}])
    check("body.model 是官方 id", call["json"].get("model"), llm.ANTHROPIC_MODEL)

    # 2. 课堂网关路径：output 字段 + 旧 body 形状
    ok = _FakeResp(200, {"output": "from-gateway"})
    post = _FakePost(ok); llm.requests = _FakeRequestsModule(post)
    out = _with_env({"CLASSROOM_API_KEY": "ck-test"},
                    lambda: llm.call_gateway("hi", max_tokens=99))
    check("网关路径返回 output", out, "from-gateway")
    call = post.calls[0]
    check("网关 body 用 input/maxTokens", (call["json"].get("input"), call["json"].get("maxTokens")),
          ("hi", 99))

    # 3. 两个都有 → 优先官方
    ok = _FakeResp(200, {"content": [{"type": "text", "text": "official"}]})
    post = _FakePost(ok); llm.requests = _FakeRequestsModule(post)
    out = _with_env({"ANTHROPIC_API_KEY": "sk", "CLASSROOM_API_KEY": "ck"},
                    lambda: llm.call_gateway("hi"))
    check("双 key 优先官方 API", out, "official")
    check("双 key 打的是官方 URL", post.calls[0]["url"], llm.ANTHROPIC_URL)

    # 4. 都没有 → NO_KEY
    try:
        _with_env({}, lambda: llm.call_gateway("hi"))
        check("无 key → NO_KEY", "no-raise", "GatewayError")
    except llm.GatewayError as e:
        check("无 key → NO_KEY", e.reason, "NO_KEY")

    # 5. 错误分类（官方路径）
    for sc, want in ((429, "RATE_LIMITED"), (529, "RATE_LIMITED"),
                     (401, "HTTP_ERROR"), (500, "HTTP_ERROR")):
        post = _FakePost(_FakeResp(sc)); llm.requests = _FakeRequestsModule(post)
        try:
            _with_env({"ANTHROPIC_API_KEY": "sk"}, lambda: llm.call_gateway("hi"))
            check(f"{sc} → {want}", "no-raise", want)
        except llm.GatewayError as e:
            check(f"{sc} → {want}", e.reason, want)

    post = _FakePost(_requests.exceptions.Timeout()); llm.requests = _FakeRequestsModule(post)
    try:
        _with_env({"ANTHROPIC_API_KEY": "sk"}, lambda: llm.call_gateway("hi"))
        check("Timeout → TIMEOUT", "no-raise", "TIMEOUT")
    except llm.GatewayError as e:
        check("Timeout → TIMEOUT", e.reason, "TIMEOUT")

    post = _FakePost(_requests.exceptions.ConnectionError("dns"))
    llm.requests = _FakeRequestsModule(post)
    try:
        _with_env({"ANTHROPIC_API_KEY": "sk"}, lambda: llm.call_gateway("hi"))
        check("网络异常 → UNREACHABLE", "no-raise", "UNREACHABLE")
    except llm.GatewayError as e:
        check("网络异常 → UNREACHABLE", e.reason, "UNREACHABLE")

    # 6. content 块过滤与空值
    mixed = _FakeResp(200, {"content": [
        {"type": "thinking", "thinking": "内心戏"},
        {"type": "text", "text": "A"}, {"type": "text", "text": "B"},
    ]})
    post = _FakePost(mixed); llm.requests = _FakeRequestsModule(post)
    out = _with_env({"ANTHROPIC_API_KEY": "sk"}, lambda: llm.call_gateway("hi"))
    check("混合块只拼 text", out, "AB")

    post = _FakePost(_FakeResp(200, {"content": []})); llm.requests = _FakeRequestsModule(post)
    out = _with_env({"ANTHROPIC_API_KEY": "sk"}, lambda: llm.call_gateway("hi"))
    check("content 空 → 空串（语义归调用方）", out, "")
finally:
    llm.requests = _real_requests

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
