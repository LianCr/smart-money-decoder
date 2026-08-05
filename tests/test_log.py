"""
tests/test_log.py — core/log 契约（P1-12：logging 外壳 + request id，零网络零 key）

覆盖：
  1. get_logger 幂等（重复调用不叠 handler → 不双打）
  2. 日志行格式：`HH:MM:SS L [rid] <原消息>`，emoji/中文消息原文保留
  3. REQUEST_ID contextvar：默认 "-"，set 后注进日志行，reset 恢复
  4. new_request_id：8 位 hex
  5. LOG_LEVEL：debug 行在默认 INFO 下不出、直调 setLevel(DEBUG) 后出
"""

import io
import logging
import re
import sys

sys.path.insert(0, ".")

from core import log as smdlog

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


def capture():
    """给 smd 根 logger 临时接一个 StringIO handler（同 formatter+filter）。"""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter(smdlog._FMT, datefmt=smdlog._DATEFMT))
    h.addFilter(smdlog._RidFilter())
    logging.getLogger("smd").addHandler(h)
    return buf, h


LOG = smdlog.get_logger("test")
root = logging.getLogger("smd")

# 1. 幂等
n = len(root.handlers)
smdlog.get_logger("again")
smdlog.setup_logging()
check("重复配置不叠 handler", len(root.handlers), n)

# 2/3. 格式 + rid 注入
buf, h = capture()
try:
    LOG.info("   ⚡ CACHE HIT 中文消息保留")
    line = buf.getvalue().strip()
    check("默认 rid 为 -", "[-]" in line, True)
    check("emoji/中文消息原文保留", line.endswith("   ⚡ CACHE HIT 中文消息保留"), True)
    check("格式 = 时间 级别 [rid] 消息", bool(re.match(r"^\d{2}:\d{2}:\d{2} I \[-\] ", line)), True)

    token = smdlog.REQUEST_ID.set("abc12345")
    buf.truncate(0); buf.seek(0)
    LOG.warning("   ✗ 出错了")
    line = buf.getvalue().strip()
    check("set 后 rid 注进日志行", "[abc12345]" in line, True)
    check("warning 级别标 W", " W [" in line, True)
    smdlog.REQUEST_ID.reset(token)
    check("reset 后恢复默认", smdlog.REQUEST_ID.get(), "-")

    # 4. request id 形状
    rid = smdlog.new_request_id()
    check("request id = 8 位 hex", bool(re.fullmatch(r"[0-9a-f]{8}", rid)), True)

    # 5. 级别过滤
    buf.truncate(0); buf.seek(0)
    LOG.debug("debug 行")
    check("默认 INFO 下 debug 不出", buf.getvalue(), "")
    old_level = root.level
    root.setLevel(logging.DEBUG)
    LOG.debug("debug 行")
    check("DEBUG 级别下 debug 出", "debug 行" in buf.getvalue(), True)
    root.setLevel(old_level)
finally:
    root.removeHandler(h)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
