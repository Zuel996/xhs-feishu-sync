# Today Vibecoding Review — 项目启动期 (2026-07-10 ~ 07-15)

## 一句话总结

五天，从零到一键安装——一个小红书 × 飞书多维表格的数据同步工具，端到端跑通，Chrome Extension + Windows 安装包实现用户愿景闭环：「下载 → 安装 → 填凭证 → 点开始 → 数据到飞书」。

---

## Day 1: 2026-07-10（周五）— 验证地基

### 做了什么

项目代码（Phase 1-5）之前已经写好，但这天是第一次逐模块验证。

### 关键成果

| 验证线 | 内容 | 结果 |
|--------|------|------|
| 环境 | `pip install` + Playwright + 21 模块导入 | ✅ |
| CSV 采集器 | 中文数字解析（万/亿/k）+ Excel 日期 | 20/20 |
| Pipeline 离线 | CSV → Normalize → SQLite → Trend → Competitor | 38/38 |
| CLI | 6 个命令全部可用 | ✅ |

### 修复的 Bug（8 个）

- lark-oapi v1.7.1 API 变更导致 import 失败
- 飞书 Bot 源码编码损坏
- CSV 采集器代码重复（两套数字解析）
- SyncEngine 离线模式不完善
- TrendCalculator 空值崩溃

### 当日状态

```
线路 A (CSV + SQLite + 离线模式) → ✅ 跑通
线路 B (飞书在线同步)           → ⬜ 等凭证
线路 C (CDP 浏览器采集)         → ⬜ 未测
```

---

## Day 2: 2026-07-12（周日）— 架构评审 + Git

### 做了什么

做了 Node.js vs Python 两种方案的对比评审，确认现行方案在趋势计算、竞品分析、Bot 通知等方面有不可替代性。同时搭建了 Git 和 GitHub。

### 关键成果

- 方案评审：确认 Python 方案优势，设计三次融合改动（~85 行，非阻塞）
- GitHub 仓库创建：`Zuel996/xhs-feishu-sync`
- 首次提交：57 文件，6687 行
- 文档同步：implementation-plan + devlog

### 当日提交

```
fd06727 docs: sync implementation-plan + add devlog 2026-07-12
3055301 Initial commit: xhs-feishu-sync Phase 1-5 code + Line A verification
```

---

## Day 3: 2026-07-13（周日深夜~周一凌晨）— 决战飞书 + 浏览器

这是最关键的一天，从下午干到凌晨。解决了飞书写入 → CDP 浏览器采集 → API 逆向 → 端到端贯通。

### Phase A: 飞书集成（线路 B 打通）

**阻塞**: 飞书自建应用无写入权限（91403 Forbidden）。

**破局**: 在多维表格中「添加文档应用」替代管理员安装流程，获取文档级写权限。

解决了 4 个飞书 API 兼容问题：

| Bug | 错误码 | 修复 |
|-----|--------|------|
| 建表参数不兼容 | 1254001 | 移除 `default_view_name` |
| 建表后字段为空 | — | 新增 `add_field()` 幂等方法 |
| DateTime 格式错误 | 1254064 | 日期字符串 → 毫秒时间戳 |
| URL 字段格式错误 | 1254068 | 纯字符串 → `{link, text}` 对象 |

### Phase B: CDP 浏览器采集（线路 C 打通）

通过 Chrome DevTools Protocol 直连本地 Chrome，拦截网络请求获取数据。

**API 发现过程**：
1. 创作者中心首页拦截到 5 个 API（personal_info、note_detail_new 等）
2. `note_detail_new` 只是聚合统计，不是单篇笔记数据
3. 创建「API 发现模式」—— 记录全部网络请求 URL
4. 在 `statistics/data-analysis` 页面找到了关键 API：

```
/api/galaxy/creator/datacenter/note/analyze/list
```
返回每篇笔记的实时互动数据（浏览/点赞/收藏/评论/分享）。

### Phase C: 架构重构

| 旧设计 | 新设计 | 原因 |
|--------|--------|------|
| 降级链（谁先返回用谁） | 浏览器优先 + CSV 去重补充 | 浏览器数据有实时指标 |
| 单采集策略 | Hybrid 合并策略 | 浏览器覆盖不全，CSV 兜底 |
| `note_type` 仅支持字符串 | `_safe_note_type()` int/str 兼容 | 创作者中心 API 返回整数 |
| 无平台字段 | 4 表加 `platform` 字段 | 为公众号扩展预留 |

### 当日提交

```
ee3651e chore: cleanup redundant data files + finalize devlog
e172427 docs: sync implementation-plan + devlog — Phase 1-6 complete
8e03bd6 feat: 浏览器笔记数据自动采集 — 创作者中心 API 解析
d38805a feat: CDP browser collector + hybrid mode + platform field
9ecf412 fix: xhs-feishu run 不传--date时导入全部笔记
373957e feat: 支持小红书创作者中心Excel导出(.xlsx)
4f1415d feat: 飞书集成(线路B)端到端打通 + README使用说明
58374da feat: Phase 5 scheduler verification (15/15) + 4 fixes
```

---

## Day 4: 2026-07-14（周一）— 团队化 + 一键操作

### 做了什么

前三天的成果是"一个人 + 命令行"能用。这天把它变成了"团队 + 双击就能用"。

### 🆕 实现的新功能

#### 1. 飞书账号管理（核心新功能）

在飞书多维表格新增第 5 张表「账号管理」，团队可以直接在飞书中增删改监控账号，无需碰代码。

| 文件 | 说明 |
|------|------|
| `src/loaders/account_manager.py` | **新建** — `FeishuAccountManager`，从飞书分页读取→过滤启用→校验必填→转换 AccountInfo |
| `src/core/config.py` | 新增 `load_accounts_from_bitable()`，三种账号来源模式 |
| `src/core/pipeline.py` | `run_all_accounts()` + `run_pipeline()` 新增 `source` 参数 |
| `src/cli/main.py` | `run`/`test-collect` 新增 `--source/-s` 选项；`clear` 新增 `--all` 标志 |
| `src/scheduler/jobs.py` | 支持 `ACCOUNT_SOURCE` 环境变量 |
| `config/bitable_schema.yaml` | 新增 `account_manager` 表定义（10 字段） |

**三种账号来源模式：**

| 模式 | 命令 | 缓存策略 |
|------|------|---------|
| `yaml` | `xhs-feishu run` | 缓存单例 |
| `bitable` | `xhs-feishu run -s bitable` | 每次重新读取 |
| `auto` | `xhs-feishu run -s auto` | 优先飞书，失败回退 YAML |

**账号管理表过滤逻辑：**
- 「启用」Checkbox 未勾选 → 跳过
- 「账号ID」或「XHS用户ID」为空 → 跳过（打印警告日志）

#### 2. 一键操作脚本

| 文件 | 功能 | 一键操作 |
|------|------|---------|
| `每日采集.bat` | 从飞书加载账号 → 采集 → 同步 | 双击采集 |
| `删除.bat` | 清空 4 张数据表 + SQLite | 双击清空（需输入 YES） |
| `scripts/setup.bat` | Python检测 → 依赖安装 → 配置检查 → 数据库初始化 | 一键部署 |
| `scripts/daily_run.bat` | 检查 Chrome CDP 存活 → 执行采集 | Windows 定时任务入口 |

#### 3. `clear --all` 命令

一键清空全部数据表（保留「账号管理」表）：
```powershell
xhs-feishu clear --all --confirm
```

### 🔧 优化的功能

| 优化点 | 旧 | 新 |
|--------|----|----|
| 账号配置方式 | 仅 YAML 文件 | YAML + 飞书表格双模式 |
| Pipeline 账号来源 | 硬编码 YAML | `--source yaml\|bitable\|auto` |
| 调度器账号来源 | 硬编码 YAML | `ACCOUNT_SOURCE` 环境变量 |
| Chrome 路径检测 | 硬编码 `C:\Program Files\...` | 自动检测多路径 |
| README 文档 | 面向开发者 | 面向团队部署，含故障排查 |
| 代码安全 | 含测试数据 | `accounts.yaml` 占位符脱敏 |

### 🐛 修复的 Bug（4 个）

| # | 问题 | 现象 | 修复 |
|----|------|------|------|
| 20 | bat 双击找不到路径 | "系统找不到指定的路径" | `cd /d` 硬编码 → `cd /d "%~dp0"`（bat 自身目录） |
| 21 | bat 双击找不到 xhs-feishu | "'bitable' 不是内部或外部命令" | 短命令 → `C:\...\Python314\Scripts\xhs-feishu.exe` 完整路径 |
| 22 | bat 中文乱码 | CMD GBK 编码显示 `'垚锛屾寜...'` | 全部中文字符 → 英文 ASCII |
| 23 | Chrome 路径写死 | 非标准安装路径找不到 chrome.exe | 自动检测多个常见安装位置 |

### 📦 v0.1.0 发布就绪 — P1 完善项

在对项目做发布就绪度评估后，识别出 3 个 P0（阻塞项）和 6 个 P1（应该修），全部完成：

| # | P1 项目 | 说明 |
|---|---------|------|
| 1 | `print()` → `click.echo()` | `bitable_schema.py` 11 处改为 Click 标准输出 |
| 2 | `.env.example` 补充 | 新增 `ACCOUNT_SOURCE` 配置项（yaml/bitable/auto） |
| 3 | `pyproject.toml` 元数据 | +13 PyPI classifiers + 4 project.urls |
| 4 | `scripts/setup.sh` | Mac/Linux 一键安装脚本（Python 检测 + Chrome 检测 + 配置引导） |
| 5 | `scripts/start_chrome.sh` | Mac/Linux Chrome CDP 启动脚本（自动检测 macOS App Bundle / Linux 系统路径） |
| 6 | CI + 单元测试 | `.github/workflows/ci.yml`（3 Python 版本 × ruff/mypy/pytest）+ **96 项单元测试** |

### 🧪 测试体系

```
tests/test_transformers/test_normalizer.py     39 tests  (中文数字解析/校验/ORM转换/Pipeline)
tests/test_transformers/test_trend_calculator.py 19 tests  (DoD/WoW/增长率/异常检测/自定义阈值)
tests/test_transformers/test_competitor.py      13 tests  (排名变更/对比表/增量补充/排名摘要)
tests/test_storage/test_sqlite.py               25 tests  (4个Repo CRUD + 幂等性 + 多账号 + total_interactions)
──────────────────────────────────────────────────────────────────
Total                                          96 passed ✓ (0.61s)
```

测试覆盖亮点：
- SQLite 全部使用 in-memory 模式，零文件依赖
- Pydantic `Field(ge=0)` 保护层验证 → 发现模型层校验早于业务逻辑
- SQLAlchemy NOT NULL 约束 → 发现 update 时字段覆盖行为
- `datetime` 是 `date` 子类 → 发现 `isinstance` 检查顺序影响 `safe_date()` 行为

### 🌍 跨平台完善

| 文件 | 平台 | 功能 |
|------|------|------|
| `scripts/setup.sh` | Mac/Linux | 一键安装（Python 3.11+ 检测、依赖安装、.env 检查、Chrome 检测、数据库初始化） |
| `scripts/start_chrome.sh` | Mac/Linux | Chrome CDP 启动（自动检测 macOS App Bundle / Linux 系统路径，15s 等待 CDP 就绪） |
| `每日采集.sh` | Mac/Linux | 一键采集同步 |
| `删除.sh` | Mac/Linux | 一键清空数据 |

### 🔧 使用问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `删除.bat` 报 `code=10003, invalid param` | `.env` 中飞书凭证为占位符 `your_app_secret_here` | 填入飞书开放平台真实 App ID + App Secret |
| `每日采集.bat` 数据不同步到飞书 | 飞书「账号管理」表中「启用」Checkbox 未勾选 | 勾选「启用」+ 填写「账号ID」「XHS用户ID」 |
| App Secret 与 Bitable Token 混淆 | 三个字段容易搞混 | 明确三者来源：开放平台凭证页 / 多维表格 URL |

### 端到端验证

| 测试用例 | 结果 |
|----------|------|
| 飞书「账号管理」表录入测试账号 → 勾选启用 | ✅ |
| `每日采集.bat` 双击 → Pipeline 完整跑通 | ✅ fans=24, 1 account, 1 note |
| `删除.bat` 双击 → 输入 YES → 数据清空 | ✅ 3 Feishu + 4 SQLite 全删 |
| 再次双击 `每日采集.bat` → 0 账号（已清空启用） | ✅ 正确 |
| `xhs-feishu run` 无参数 → 默认 YAML 行为不变 | ✅ 回归通过 |

### 当日提交

```
3f616bb docs: 同步README至最新状态 — 5表/账号管理/一键脚本
7a31df2 feat: 飞书账号管理 + 一键操作脚本 — Phase 6 收尾
8092397 docs: merge owners_manual into README, remove duplicate
6616fa0 feat: add clear command + owners_manual + fix bat encoding — July 14 work summary
104fde8 docs: rewrite README for team deployment — current state, setup, daily use
5405798 feat: add daily_run.bat — scheduled task entry point
b212602 feat: add one-click setup script — Python check, deps, config, init
3b31112 fix: auto-detect Chrome path in start_chrome.bat instead of hardcoding
9d03e45 chore: sanitize accounts.yaml — replace test data with placeholders
```

---

```
Chrome CDP (端口 9222)
  ├─ personal_info        → 粉丝/关注/获赞      → 账号概览
  ├─ note/analyze/list    → 单篇笔记互动数据     → 笔记明细
  ├─ note_detail_new      → 7/30天聚合趋势      → 每日快照
  ├─ datacenter/account   → 账号分析数据        → (预留)
  └─ live_rooms           → 直播数据            → (预留)
       │
  CSV 文件 (历史补充)
       │
       ▼
  Hybrid 合并 (浏览器优先 + CSV 去重)
       │
       ▼
  SQLite (data/sync.db) ── 持久化 + 趋势计算 + 异常检测
       │
       ▼
  飞书多维表格 (5 张表 × 65 字段)
       │
       ├─ 账号管理 (新增) ── 团队协作编辑监控账号
       ├─ 账号概览
       ├─ 笔记明细
       ├─ 每日快照
       └─ 竞品对比
```

---

## Day 5: 2026-07-15（周二）— 愿景落地：Chrome Extension + 一键安装包

这是整个项目最具产品形态跨越的一天。从"开发者工具"变成了"对团队友好的桌面产品"。

### 🎯 用户愿景 vs 现实

| # | 差距 | Day 4 状态 | Day 5 状态 |
|---|------|-----------|-----------|
| 1 | **分发** | git clone + pip install | 单个 .zip (58MB)，解压即用 |
| 2 | **启动** | 双击 .bat 终端窗口不能关 | 开机自启，系统托盘静默运行 |
| 3 | **插件加载** | Chrome 开发者模式 + 手动加载 | 安装器自动注册扩展策略 |

### 五步实施

#### Step 1: PyInstaller 打包 ✅

Python 后端（FastAPI + Pipeline + Feishu）打包成单个 exe：

```
dist/xhs-feishu-server/
├── xhs-feishu-server.exe    # 双击运行，系统托盘图标
└── _internal/               # Python 依赖库 (~111MB)
```

- `--onedir --noconsole`：无终端窗口，静默运行
- Hidden imports：`src.api`、`pystray`、`PIL`
- 新增 `run_server.py` — PyInstaller 入口，整合系统托盘逻辑

#### Step 2: 系统托盘 ✅

```
┌─────────────────────────┐
│  🔴 xhs-feishu-sync    │
│  ───────────────────── │
│  📊 查看状态            │
│  ❌ 退出                │
└─────────────────────────┘
```

- `pystray` + `Pillow` 绘制红色圆角矩形 + 白色"S"字图标
- uvicorn 在 daemon 线程运行，main thread 跑 pystray 消息泵
- 开机自启：注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`

#### Step 3: "开始"按钮 ✅

点击「🚀 开始」后的全自动化链路：

```
点击"开始"
  ├─ 1. 检查后端是否在线 (localhost:9527)
  ├─ 2. Service Worker 自动打开/定位 creator.xiaohongshu.com
  ├─ 3. Content Script 拦截 API 数据 (poll 2s × 45s timeout)
  ├─ 4. 匹配账号 (xhs_user_id) → 发送给后端 → Pipeline → 飞书
  └─ 5. Chrome 桌面通知："采集完成: 1账号, 15笔记"
```

**状态提示链**：`检查中... → 连接后端... → 采集中...（最长等待45秒）→ ✅/⚠️/❌`

**关键代码**：
- `handleCollect()` — Service Worker 全流程编排
- `waitForData()` — 轮询 Content Script，支持动态标签页检测
- `chrome.storage.local` — 缓存采集结果，Popup 优先读 storage

#### Step 4: Windows 一键安装器 ✅

`install.bat` 以管理员身份运行，5 步完成安装：

| 步骤 | 操作 | 技术 |
|------|------|------|
| 1/5 | 复制文件 → `%LOCALAPPDATA%\xhs-feishu-sync` | robocopy |
| 2/5 | 注册开机自启 | `HKCU\Run` 注册表 |
| 3/5 | 创建开始菜单快捷方式 | PowerShell COM `WScript.Shell` |
| 4/5 | 注册 Chrome 扩展策略 | `HKLM\ExtensionInstallForcelist` + `update.xml` |
| 5/5 | 启动后端 + 打开 Chrome 扩展管理页 | `chrome://extensions/` |

**稳定扩展 ID**：`pplbaecpijioleoifnbibibegdpgabjb`（RSA 2048 密钥对 → SHA256 哈希派生）

#### Step 5: 定时自动采集 ✅

- `chrome.alarms` 每日定时（默认 10:00）
- `onInstalled` 时计算首次延迟，`onStartup` 更新时间
- Popup 显示上次采集结果 + 下次定时时间
- 采集结果持久化到 `chrome.storage.local`

### 新增文件

| 文件 | 说明 |
|------|------|
| `run_server.py` | PyInstaller 入口 + 系统托盘 |
| `extension/` (7 files) | Chrome Extension MV3 — manifest/popup/content/background/icons |
| `extension-keys/` (3 files) | RSA 密钥对 — 稳定扩展 ID |
| `scripts/install.bat` | 一键安装脚本 |
| `scripts/package.bat` | 打包分发脚本 |
| `scripts/start_server.bat` | 后端启动（开发版） |
| `src/api/` (2 files) | FastAPI 4 端点: /config /collect /status /health |
| `xhs-feishu-server.spec` | PyInstaller 配置 |
| `dist/xhs-feishu-sync-v0.1.0.zip` | 最终分发包 (58MB) |

### 分发包结构

```
xhs-feishu-sync-v0.1.0.zip (58MB)
├── xhs-feishu-server/     # 后端 exe + 依赖
├── extension/             # Chrome 插件
├── install.bat            # 一键安装
└── 安装说明.md            # 用户指南
```

### 用户最终体验

```
① 下载 xhs-feishu-sync-v0.1.0.zip (58MB)
② 解压 → 右键 install.bat → 以管理员身份运行
③ Chrome 自动打开扩展管理页 → 加载扩展
④ 点击工具栏图标 → 填飞书凭证 + XHS ID → 验证并保存
⑤ 点「🚀 开始」→ 自动打开 XHS 创作者中心 → 采集 → 通知
⑥ 飞书表格出现数据 ✓
⑦ 以后每天 10:00 自动采集，无需任何操作
```

### 架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 产品形态 | Chrome Extension + 安装包 | 3-5x 少于 Electron，复用已有插件代码 |
| 扩展安装 | 注册表策略 | 团队内部使用，无需 Chrome Web Store 审核 |
| 扩展 ID | RSA 密钥派生 | 永久稳定的扩展 ID，更新/策略注册需要 |
| 后端打包 | `--onedir` | 启动快，无每次解压开销 |
| 采集触发 | 自动 + 手动 | 日常自动化 + 特殊情况手动补采 |

### 当日提交

```
553e4ae feat: Chrome Extension + Windows 一键安装包 — 愿景落地 v0.1.0
```

22 files changed, +2,421 lines.

---

```
                            用户
                             │
              下载 .zip ──→ 双击安装 ──→ 填凭证
                             │
              ┌──────────────┴──────────────┐
              │     Chrome Extension         │
              │  ┌──────────────────────┐   │
              │  │ Popup: 凭证+账号+按钮 │   │
              │  │ Background: 编排+定时 │   │
              │  │ Content: XHS API拦截  │   │
              │  └──────┬───────────────┘   │
              │         │ fetch :9527        │
              └─────────┼───────────────────┘
                        │
              ┌─────────┴───────────────────┐
              │  Python Backend (.exe)       │
              │  FastAPI → Pipeline → 飞书   │
              │  系统托盘 — 开机自启         │
              └─────────────────────────────┘
                        │
                        ▼
              飞书多维表格 (5 张表)
```

## 最终项目状态

```
Phase 1: 基础框架           ✅
Phase 2: 数据采集层          ✅ CDP Browser + CSV Hybrid + API 解析
Phase 3: 数据转换层          ✅ 26/26 (中文数字/趋势/竞品/异常检测)
Phase 4: 飞书同步            ✅ 在线/离线双模式
Phase 5: 调度与通知          ✅ 15/15 (APScheduler + Bot)
Phase 6: 集成测试            ✅ 线路 A+B+C 全部通过
Phase 7: Chrome Extension     ✅ v0.1.0 一键安装包发布
新增: 飞书账号管理           ✅ Bitable → Pipeline 端到端
新增: 一键操作脚本           ✅ 双击采集 + 双击清空（Win/Mac/Linux）
新增: P1 发布完善            ✅ 6/6（click.echo/元数据/CI/测试/跨平台脚本）
新增: 单元测试               ✅ 96 项（normalizer/trend/competitor/sqlite）
新增: CI/CD                  ✅ GitHub Actions（Python 3.11-13 矩阵）
新增: 分发安装包             ✅ dist/xhs-feishu-sync-v0.1.0.zip (58MB)
```

| 指标 | 数值 |
|------|------|
| 修复 Bug | 23 个 |
| 验证项 | 60+ 全部通过 |
| 单元测试 | 96 项 (0.61s) |
| 拦截 API | 8 个创作者中心接口 |
| 飞书表 | 5 张 × 65 字段 |
| Chrome 扩展文件 | 7 个 (MV3) |
| 新增文件 (Day 5) | 20 个 |
| 分发包 | dist/xhs-feishu-sync-v0.1.0.zip (58MB) |
| Git 提交 | 23 个 |
| 代码行数 | ~9900+ |
| GitHub | [Zuel996/xhs-feishu-sync](https://github.com/Zuel996/xhs-feishu-sync) |
| CI 状态 | Python 3.11/12/13 × ruff/mypy/pytest |

### 用户工作流（最终形态）

```
方式一（推荐 — 日常使用）：
  ① Chrome 工具栏点击插件图标
  ② 点「🚀 开始」→ 自动打开 XHS → 采集 → 飞书有数据

方式二（自动化）：
  ① 每天 10:00 自动采集 → 桌面通知
  ② 无需任何操作
```

### 新设备上手（3 步）

```
1. 解压 xhs-feishu-sync-v0.1.0.zip
2. 右键 install.bat → 以管理员身份运行
3. Chrome 加载扩展 → 填凭证 → 点「开始」
```

## 剩余事项

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P1 | 🧪 团队内部测试 | 新电脑/虚拟机完整安装流程验证 |
| P2 | CONTRIBUTING.md / CHANGELOG.md | 开源社区规范文档 |
| P2 | Optional[...] → `\| None` 迁移 | Python 3.10+ 现代类型注解 |
| P2 | 内部文档清理 | CLAUDE.md / devlog 不适合随公开发布 |
| P3 | 🍎 Mac 安装脚本 `install.sh` | 当前仅支持 Windows |
| P3 | 🔔 Bot 通知 webhook | 飞书群配置日报推送 |
| P4 | 🌐 公众号扩展 | 架构已预留 `platform` 字段 |

---

> 文档创建于 2026-07-13，更新于 2026-07-15。此文件为只读归档，仅在明确指令下可编辑。
