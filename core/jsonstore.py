"""
core/jsonstore.py — 崩不坏的 JSON 落盘（原子写 + 损坏隔离）

为什么需要它（真实事故路径，不是假想）：
`.data/scorecard.json` 是产品唯一能回答"我的判断后来被现实证明对了多少"的档案，
而它同时踩了两个坑 ——
  ① **写入非原子**：`write_text` 直写，进程被 Render 冷启动/OOM 打断就留下半截 JSON；
  ② **读取把解析失败当空档案**：于是下一次写入直接覆盖掉全部历史。
两者叠加 = 一条静默、不可逆的数据丢失路径。而红线是「**绝不造假回填**」——
丢了就永远补不回来，所以只能从源头上让它丢不掉。

两个原语，纯标准库、零网络、可单测（风格对齐 core/cachefiles.py）：

  atomic_write_json(path, data)
      先在内存里 json.dumps（序列化要炸就炸在这一步，**此时还没碰目标文件**），
      再写同目录临时文件 → flush + fsync → os.replace 原子替换。
      任何一步失败，目标文件保持原样，临时文件被清掉。

  load_json(path, default=None) -> (status, data)
      status ∈ {"ok", "missing", "corrupt"}。
      🔴 corrupt 时**隔离而不销毁**：把损坏文件改名成 `<name>.corrupt-<时间戳>`
      （原始字节一字不动地留在备份里，事后可人工抢救），原路径空出，返回 default
      让服务继续跑。这比"拒绝写入直接瘫痪"更符合本项目 best-effort 的一贯风格，
      而数据保全的目标已经达到 —— 没有任何一条真实记录被覆盖掉。

为什么返回 (status, data) 而不是只返回 data：调用方必须能区分
"档案本来就是空的（第一天，正常）" 和 "档案读不出来（出事了，该报警）"。
把这两件事混成同一个 `{}`，正是原来那条 bug 的根源。
"""

import json
import os
import time

from core.log import get_logger

_LOG = get_logger("jsonstore")
from pathlib import Path

# status 枚举（调用方按它决定要不要报警）
OK = "ok"
MISSING = "missing"
CORRUPT = "corrupt"


def atomic_write_json(path, data, indent: int | None = 2) -> None:
    """把 data 以 JSON 写到 path，要么完整生效、要么完全没发生（无中间态）。

    父目录不存在会自动创建。序列化失败原样抛出（TypeError 等），
    此时目标文件**一字未动** —— 因为序列化发生在碰文件之前。

    `indent`：默认 2（人可读，与既有落盘格式一致）。传 None 写紧凑格式 ——
    给那种"体积比可读性重要"的大缓存用（如 event_structure 全量扫描结果）。
    """
    # 🔴 顺序关键：先序列化再碰文件。反过来（边写边序列化）就会在写到一半时抛错，
    #    留下半截文件 —— 那正是本模块要根治的病。
    blob = json.dumps(data, ensure_ascii=False, indent=indent)
    atomic_write_text(path, blob)


def atomic_write_text(path, text: str) -> None:
    """把纯文本原子写到 path：要么完整生效、要么完全没发生。

    JSON 之外也需要它 —— 例如恢复备份时写的是原始文本，而一次写到一半的
    "恢复"比不恢复更糟（本来还有个完整的旧文件，现在两头空）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件必须和目标**同目录**：os.replace 只在同一文件系统内保证原子性，
    # 放 /tmp 再 move 跨设备就退化成"复制+删除"，原子性没了。
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())        # 落到磁盘，不只是进 page cache
        os.replace(tmp, path)           # 原子替换：读者要么看到旧的、要么看到新的
    except Exception:
        try:
            tmp.unlink()                # 不留残骸
        except OSError:
            pass
        raise


def quarantine(path) -> Path | None:
    """把文件挪到 `<name>.corrupt-<ts>`，返回备份路径（失败返回 None）。

    load_json 在解析失败时自动调用它。**也对外暴露**：调用方有时能看出
    "JSON 合法但结构不对"（比如档案该是 dict 却读出个 list），那同样不该直接
    覆盖，走同一条隔离路径。

    同秒内多次隔离用序号避让 —— 撞名就等于第一份证据被第二份盖掉，那还是丢数据。
    """
    path = Path(path)
    stamp = int(time.time())
    for n in range(100):
        suffix = f".corrupt-{stamp}" + (f"-{n}" if n else "")
        target = path.with_name(path.name + suffix)
        if target.exists():
            continue
        try:
            os.replace(path, target)
            return target
        except OSError:
            return None
    return None


def load_json(path, default=None):
    """读 JSON，返回 (status, data)。

    - 文件不存在        → (MISSING, default)
    - 解析成功          → (OK, data)
    - 解析失败/读不动   → (CORRUPT, default)，且损坏文件已被隔离到 .corrupt-* 备份
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return MISSING, default
    except OSError:
        # 权限/IO 问题：读不出来但文件还在，别乱动它（隔离只针对"内容坏了"）
        return CORRUPT, default

    try:
        return OK, json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        backup = quarantine(path)
        if backup is not None:
            _LOG.warning(f"⚠ JSON 档案损坏，已隔离原件到 {backup}（内容未销毁，可人工抢救）")
        return CORRUPT, default
