# Render 上线操作说明书

从零到公网可访问约 15 分钟。前置条件已全部就绪：代码在 GitHub `LianCr/smart-money-decoder` 的 `v3-briefing` 分支，`render.yaml` 已钉住该分支，`seed/` 缓存快照随仓库发布。

---

## 第 0 步：准备（2 分钟）

打开本地项目的 `.env` 文件，把这三个 key 复制到一个临时记事本里（马上要填）：

```
CLASSROOM_API_KEY=...     # 老师的课堂网关 key
TAVILY_API_KEY=...        # app.tavily.com 的 key
HEISENBERG_API_KEY=...    # Heisenberg 免费 key
```

🔴 **这三个 key 只填在 Render 控制台，永远不进 git。**

## 第 1 步：注册 Render（2 分钟）

1. 打开 https://render.com → 右上角 **Get Started / Sign In**
2. 选 **Sign in with GitHub**（用你的 GitHub 账号授权，免费档不需要信用卡）
3. 首次授权时 GitHub 会问允许 Render 访问哪些仓库——选 **All repositories**，或 Only select repositories 并勾上 `smart-money-decoder`

## 第 2 步：Blueprint 一键部署（3 分钟）

1. 进入 Render Dashboard → 左上角 **New +** → 选 **Blueprint**
2. 在仓库列表里找到 `LianCr/smart-money-decoder` → **Connect**
3. Render 会自动读取仓库里的 `render.yaml`，显示将要创建的服务：
   `smart-money-decoder`（Web Service · Python · Free）
   - 分支已在 yaml 里钉死为 `v3-briefing`，不用改
4. 页面会提示填 3 个环境变量（yaml 里标了 `sync: false` 的）：
   | 变量名 | 填什么 |
   |---|---|
   | `CLASSROOM_API_KEY` | 第 0 步记事本里的值 |
   | `TAVILY_API_KEY` | 同上 |
   | `HEISENBERG_API_KEY` | 同上 |
5. 点 **Apply / Deploy Blueprint**

## 第 3 步：看构建日志（3-6 分钟，等就行）

服务页面会实时滚日志，正常顺序是：

1. `pip install -r requirements.txt` —— Python 依赖
2. `cd frontend && npm ci && npm run build` —— 前端构建（Render 的 Python 环境自带 Node）
3. `Build successful` → 启动 `uvicorn`
4. 启动日志里应出现一行：**`🌱 种子缓存恢复：seed/cache → .cache`** —— 这是缓存快照落位、访客零 token 秒回的关键信号
5. 状态变绿 **Live**，页面顶部出现你的公网地址，形如：
   `https://smart-money-decoder.onrender.com`

## 第 4 步：上线自测清单（5 分钟）

按顺序点一遍，前 6 项全部零 token：

- [ ] 打开公网 URL → 统一看板入口页正常渲染
- [ ] 右上角 `中 | EN` 切换 → 界面骨架变英文、刷新后语言记住
- [ ] 点一个「⚡ 已缓存 · 秒开」钱包 → **1 秒内**出完整看板（慢了说明种子缓存没恢复，见排查 Q3）
- [ ] 输一个乱地址（如 `0xabc`）→ 红色错误框，EN 模式下显示英文文案
- [ ] 入口页底部「🔒 这里的 AI 被怎么圈养（方法论）」能展开
- [ ] Track Record 页 → 诚实记分牌 + 历史回测都渲染
- [ ] （可选，烧 token）输一个新钱包或对缓存钱包点 `↻ 强制刷新` → 看到"AI working · Ns"计时加载条 → 1-3 分钟出结果。**这一步验证课堂网关 key 填对了**

## 常见问题排查

**Q1：构建在 npm 那步失败（`npm: command not found`）**
罕见但有后手：把本地构建产物直接提交——
```bash
cd frontend && npm run build && cd ..
git add -f frontend/dist && git commit -m "chore: commit dist for render" && git push origin v3-briefing
```
然后把 Render 服务设置里的 Build Command 改成只剩 `pip install -r requirements.txt`，Manual Deploy 重跑。

**Q2：网页打开是 `{"detail":"Not Found"}`**
说明前端 dist 没构建出来（静态挂载条件是 `frontend/dist` 存在）。回看构建日志里 npm 那段报错，或走 Q1 的后手。

**Q3：点"已缓存"钱包也要等几十秒**
启动日志里找 `🌱 种子缓存恢复` 那行；没有的话说明 seed 没随代码上去，本地跑 `git ls-files seed | head` 确认 seed 在 git 里，再 push 触发重新部署。

**Q4：强制刷新 / 新钱包报 502 `GATEWAY_ERROR` 或 403**
`CLASSROOM_API_KEY` 没填对或 pending。服务页 → **Environment** → 检查三个 key（注意别带引号和空格）→ Save 会自动重启。

**Q5：打开网页要等约 1 分钟才有响应**
免费档闲置 15 分钟后休眠，冷启动约 1 分钟，正常。demo 前 10 分钟先自己打开一次热身即可。想彻底消除可用 UptimeRobot 每 10 分钟 ping 一次你的 URL（免费）。

**Q6：以后改了代码怎么更新线上？**
什么都不用做——`git push origin v3-briefing` 后 Render 自动重新部署（Blueprint 默认 auto-deploy）。

## Demo 日操作流程（2026-07-09）

1. **前一晚**：对要展示的 3-5 个钱包各点一次 `↻ 强制刷新`（每个 ~12k token），让缓存里是最新数据
2. **刷新后想保住新缓存**（可选但推荐，否则服务一休眠重启就回到旧快照）：
   ```bash
   # 本地没法拿到线上刷新的缓存——所以推荐反过来：在本地起服务刷新，再回填 seed
   .venv/bin/uvicorn api.main:app --port 8000   # 本地起服务
   # 浏览器 localhost:5173（或直接 curl）对目标钱包 refresh=1，跑完后：
   rm -rf seed/cache seed/data && cp -r .cache seed/cache && cp -r .data seed/data
   git add seed && git commit -m "chore: refresh seed cache for demo" && git push origin v3-briefing
   # push 自动触发线上重新部署，线上冷启动即用新快照
   ```
3. **demo 前 10 分钟**：打开公网 URL 热身（消除冷启动），顺手点一遍要演示的钱包确认秒回
4. **现场讲解弹药**：加载条计时器 = "AI 真在跑全链"；方法论面板 = "AI 被怎么圈养"；⑥ 的信心来源标注 + Track Record 记分牌 = "判断可对账"

## 额度心账（老师 key 剩 ~30%）

| 动作 | 花费 |
|---|---|
| 访客点缓存钱包 / 切语言 / 看 Track Record | 0 |
| 访客输新钱包 or 强制刷新 | ~12k token/次 |
| /analyze（Decode tab）每天每钱包首次 | 数百~2k |

完全开放模式下额度消耗不可控（你已拍板接受）；如果发现被路人烧得太快，最快的止血是把 Render 环境变量里 `CLASSROOM_API_KEY` 临时清空——缓存钱包照常可看，新分析会报错但不烧钱。
