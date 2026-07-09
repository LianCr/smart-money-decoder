"""
core/persist.py — GitHub 状态持久层（Render 免费档磁盘 ephemeral 的解法）

问题（2026-07-09 用户实测）：线上刷新扫榜后，重新部署/闲置冷启动都会清空磁盘并从
seed/（git 里的 6-25 快照）恢复 → 用户每次重进网站推荐榜都穿越回 6-25。

解法：磁盘靠不住，状态存回 GitHub 仓库本身——
- 保存：扫榜成功后，把 推荐榜 + 精选钱包的看板缓存 + 记分牌档案 打成一个 bundle，
  经 GitHub Contents API 写到独立分支 STATE_BRANCH（🔴 不是部署分支，绝不触发重部署）。
  需要 GITHUB_TOKEN（fine-grained PAT，仅本仓库 Contents 读写）；没配则静默跳过（只打一行提示）。
- 恢复：冷启动时（seed 恢复之后）从 raw.githubusercontent.com 拉 bundle——仓库公开，
  恢复端**不需要 token**。谁新用谁：
    · recommendations/hot_traders：比 generated_at/saved_at，远端新才覆盖
    · 看板缓存：按日期分 key 文件，本地没有才写（绝不覆盖更新的本地构建）
    · scorecard：按条 merge（updated_at 新者胜、final_result 永不被 None 覆盖——诚实档案不丢也不篡改）

🔴 全程 best-effort：任何失败只打日志，绝不阻塞启动/扫榜。
"""
import base64
import json
import os
import time
from pathlib import Path

import requests

STATE_BRANCH = os.environ.get("STATE_BRANCH", "app-state")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "LianCr/smart-money-decoder")
BUNDLE_PATH = "state/bundle.json"
API = "https://api.github.com"
TIMEOUT = 20
MAX_FILE_BYTES = 400_000       # 单文件超此不入 bundle（防失控；看板缓存实测 ~50-150KB）


def _token():
    return os.environ.get("GITHUB_TOKEN")


def _log(msg):
    print(f"   [persist] {msg}", flush=True)


# ── 保存端（需 GITHUB_TOKEN）──────────────────────────────────────────────────

def _gh(method, path, token, **kw):
    return requests.request(
        method, f"{API}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=TIMEOUT, **kw)


def _ensure_branch(token):
    """STATE_BRANCH 不存在则从默认分支 HEAD 创建。"""
    r = _gh("GET", f"/repos/{GITHUB_REPO}/git/ref/heads/{STATE_BRANCH}", token)
    if r.status_code == 200:
        return True
    base = _gh("GET", f"/repos/{GITHUB_REPO}", token).json().get("default_branch", "master")
    r = _gh("GET", f"/repos/{GITHUB_REPO}/git/ref/heads/{base}", token)
    if r.status_code != 200:
        return False
    sha = r.json()["object"]["sha"]
    r = _gh("POST", f"/repos/{GITHUB_REPO}/git/refs", token,
            json={"ref": f"refs/heads/{STATE_BRANCH}", "sha": sha})
    return r.status_code in (200, 201)


def build_bundle(data_files, cache_files):
    """打包：data_files/cache_files 均为 {bundle内相对路径: 本地Path}。跳过不存在/超大的。"""
    files = {}
    for rel, p in {**data_files, **cache_files}.items():
        try:
            p = Path(p)
            if not p.exists() or p.stat().st_size > MAX_FILE_BYTES:
                continue
            files[rel] = p.read_text(encoding="utf-8")
        except Exception:
            continue
    return {"saved_at": int(time.time()), "files": files}


def save_bundle(bundle):
    """bundle 写到 STATE_BRANCH（一次 API PUT，一个 commit）。返回是否成功。"""
    token = _token()
    if not token:
        _log("未配 GITHUB_TOKEN——刷新结果只活到下次冷启动（配上即可跨部署持久）")
        return False
    try:
        if not _ensure_branch(token):
            _log(f"状态分支 {STATE_BRANCH} 创建失败")
            return False
        # 取现有文件 sha（更新必带；不存在则是创建）
        r = _gh("GET", f"/repos/{GITHUB_REPO}/contents/{BUNDLE_PATH}", token,
                params={"ref": STATE_BRANCH})
        sha = r.json().get("sha") if r.status_code == 200 else None
        body = {
            "message": f"state: {len(bundle.get('files', {}))} files @ {bundle.get('saved_at')}",
            "content": base64.b64encode(
                json.dumps(bundle, ensure_ascii=False).encode("utf-8")).decode("ascii"),
            "branch": STATE_BRANCH,
        }
        if sha:
            body["sha"] = sha
        r = _gh("PUT", f"/repos/{GITHUB_REPO}/contents/{BUNDLE_PATH}", token, json=body)
        ok = r.status_code in (200, 201)
        _log(f"状态已存 GitHub（{len(bundle.get('files', {}))} 文件）" if ok
             else f"保存失败 HTTP {r.status_code}：{r.text[:120]}")
        return ok
    except Exception as e:
        _log(f"保存异常（不阻塞）：{type(e).__name__}: {e}")
        return False


# ── 恢复端（公开仓库，无需 token）─────────────────────────────────────────────

def fetch_bundle():
    """从 raw 链接拉 bundle；拿不到返回 None。"""
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{STATE_BRANCH}/{BUNDLE_PATH}"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _gen_at(text):
    try:
        return json.loads(text).get("generated_at") or 0
    except Exception:
        return 0


def _merge_scorecard(local_text, remote_text):
    """按条 merge：updated_at 新者胜；final_result（历史事实）永不被 None 覆盖。"""
    try:
        loc = json.loads(local_text) if local_text else {}
    except Exception:
        loc = {}
    try:
        rem = json.loads(remote_text) if remote_text else {}
    except Exception:
        rem = {}
    out = dict(loc)
    for k, rv in rem.items():
        lv = out.get(k)
        if lv is None:
            out[k] = rv
            continue
        newer = rv if (rv.get("updated_at") or 0) >= (lv.get("updated_at") or 0) else lv
        older = lv if newer is rv else rv
        merged = dict(newer)
        if not merged.get("final_result") and older.get("final_result"):
            merged["final_result"] = older["final_result"]      # 已结算事实不丢
            merged["settled_at"] = merged.get("settled_at") or older.get("settled_at")
        out[k] = merged
    return out


def restore_bundle(bundle, root="."):
    """按"谁新用谁"落盘。返回恢复的文件数。root 供测试注入临时目录。"""
    if not bundle or not isinstance(bundle.get("files"), dict):
        return 0
    root = Path(root)
    saved_at = bundle.get("saved_at") or 0
    n = 0
    for rel, content in bundle["files"].items():
        try:
            if ".." in rel or rel.startswith("/"):
                continue                                        # bundle 来自公网，路径必须干净
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            name = dst.name
            if name == "scorecard.json":                        # 档案：merge，绝不整体覆盖
                local = dst.read_text(encoding="utf-8") if dst.exists() else ""
                merged = _merge_scorecard(local, content)
                dst.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
                n += 1
            elif name in ("recommendations.json", "hot_traders.json"):
                local_gen = _gen_at(dst.read_text(encoding="utf-8")) if dst.exists() else 0
                remote_gen = _gen_at(content) or saved_at
                if remote_gen > local_gen:                      # 远端新才覆盖（seed 6-25 必输给新刷新）
                    dst.write_text(content, encoding="utf-8")
                    n += 1
            else:                                               # 看板缓存等日期分 key 文件：缺才补
                if not dst.exists():
                    dst.write_text(content, encoding="utf-8")
                    n += 1
        except Exception:
            continue
    return n
