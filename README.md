# 小红书 → 飞书多维表格 数据自动同步工具

自动采集小红书创作者中心数据（粉丝、笔记互动等），经过清洗和趋势计算后，同步到飞书多维表格。

---

## 目录

- [功能特性](#功能特性)
- [系统要求](#系统要求)
- [方式A：Chrome 插件模式（推荐）](#方式achrome-插件模式推荐)
  - [1. 安装](#1-安装)
  - [2. 启动后端服务](#2-启动后端服务)
  - [3. 加载 Chrome 插件](#3-加载-chrome-插件)
  - [4. 配置飞书凭证](#4-配置飞书凭证)
  - [5. 添加监控账号](#5-添加监控账号)
  - [6. 开始采集](#6-开始采集)
  - [7. 诊断排查](#7-诊断排查)
- [方式B：命令行 / 脚本模式](#方式b命令行--脚本模式)
  - [安装依赖](#安装依赖)
  - [配置](#配置)
  - [浏览器 CDP 采集](#浏览器-cdp-采集)
  - [CSV 文件导入](#csv-文件导入备用)
- [定时自动化](#定时自动化)
- [飞书表格结构](#飞书表格结构)
- [架构概览](#架构概览)
- [故障排查](#故障排查)
- [开发指南](#开发指南)

---

## 功能特性

**Chrome 插件模式（推荐）**
- **零命令行**：所有操作在 Chrome 插件 Popup 中完成 — 填凭证、加账号、点按钮即可
- **API 拦截**：Content Script 注入 `creator.xiaohongshu.com`，自动拦截小红书 API 响应（三层：SW postMessage / BroadcastChannel / fetch、XHR）
- **一键采集**：点击"开始"→ 自动定位 XHS 页面 → 拦截数据 → 发送后端 → 飞书入库
- **每日自动**：`chrome.alarms` 定时触发，每天自动采集，无需手动操作
- **诊断面板**：Popup 内实时查看拦截状态（通道计数器、Hook 存活、消息结构）
- **本地存储**：飞书凭证和账号列表存于 `chrome.storage.local`，重启不丢失

**CLI / 脚本模式（备选）**
- **CDP 采集**：Chrome DevTools Protocol 直连，解析 API 数据
- **Hybrid 合并**：浏览器实时数据优先，CSV 补充历史笔记（按 note_id 去重）
- **趋势计算**：日环比（DoD）、周环比（WoW）、增长率、3σ 异常检测
- **竞品分析**：横向排名、多维度指标对比
- **幂等同步**：增量 Diff + 批量 Upsert，不重复写入飞书

---

## 系统要求

| 项目 | 插件模式 | CLI 模式 |
|------|---------|---------|
| Python | ≥ 3.11 | ≥ 3.11 |
| 浏览器 | Google Chrome | Google Chrome |
| Playwright | 不需要 | 需要 (`playwright install chromium`) |
| 操作系统 | Windows / macOS / Linux | Windows / macOS / Linux |
| 飞书 | 自建应用（`bitable:app` 权限） | 同左 |

---

## 方式A：Chrome 插件模式（推荐）

```
Chrome 插件（Popup UI）
    │  fetch localhost:9527
    ▼
Python API 后端 ──API──> 飞书多维表格
    │
 Content Script（注入 XHS 页面）
    │  拦截 API 响应
    ▼
小红书创作者中心
```

### 1. 安装

**一键安装：**

```batch
scripts\install.bat
```

自动完成：复制扩展 + 后端到 `%LOCALAPPDATA%\xhs-feishu-sync\` → 注册开机自启 → 创建开始菜单快捷方式 → 注册 Chrome 扩展策略 → 启动后端。

> 注册 Chrome 扩展策略需要**管理员权限**。如果没有，安装完成后手动加载插件即可（见步骤 3）。

**手动安装：**

```bash
git clone https://github.com/Zuel996/xhs-feishu-sync.git
cd xhs-feishu-sync
pip install -e .
```

### 2. 启动后端服务

后端是一个 Python API 服务（`localhost:9527`），负责飞书验证、数据处理和同步。**窗口不能关，关了服务就停了。**

<details>
<summary><b>方式一：双击脚本</b></summary>

在文件资源管理器中打开 `scripts\start_server.bat`，双击运行：

```
============================================================
  xhs-feishu-sync — API Server
============================================================

  Server running at http://localhost:9527
  Press Ctrl+C to stop
```

脚本会自动检测 Python 3.11+ 的位置。

</details>

<details>
<summary><b>方式二：命令行</b></summary>

```powershell
python -m uvicorn src.api.server:app --host 127.0.0.1 --port 9527 --log-level info
```

</details>

启动后验证：

```powershell
curl http://localhost:9527/health
# → {"status":"ok","feishu_configured":false}
```

### 3. 加载 Chrome 插件

1. 打开 Chrome，地址栏输入 `chrome://extensions/`
2. 打开右上角「**开发者模式**」
3. 点击「**加载已解压的扩展程序**」
4. 选择项目中的 `extension/` 文件夹（如果用 `install.bat` 安装，路径是 `%LOCALAPPDATA%\xhs-feishu-sync\extension\`）
5. 插件图标 🔴 出现在 Chrome 工具栏，加载完成

### 4. 配置飞书凭证

1. 点击 Chrome 工具栏的 🔴 插件图标
2. 状态栏应显示 **绿色圆点 + "后端运行中"**
3. 在「飞书配置」区域填入：
   - **App ID**：`cli_xxxxxxxxxxxx`
   - **App Secret**：从飞书开放平台获取
   - **Bitable Token**：从多维表格 URL 提取
4. 点击「**验证并保存**」→ 显示 ✅ 即连接成功

> **获取凭证**：登录 [飞书开放平台](https://open.feishu.cn) → 创建自建应用 → 添加 `bitable:app` 权限 → 发布应用 → 凭证页面获取 App ID / Secret。Bitable Token 从多维表格 URL 提取：
> ```
> https://xxxx.feishu.cn/base/HvqUb97pqaREuXsg97ic3WoUnMf
>                            ^^^^^^^^^^^^^^^^^^^^^^^^
> ```
> 在飞书多维表格中：右上角 `...` → `添加文档应用` → 搜索你的应用名 → 添加授权。

### 5. 添加监控账号

在插件的「监控账号」区域填入：

| 字段 | 说明 | 示例 |
|------|------|------|
| 账号ID | 自定义唯一标识 | `my_brand` |
| XHS用户ID | 小红书平台用户 ID（32 位） | `5f6c8d2e1a3b4c5d6e7f8a9b0c1d2e3f` |

点击「+ 添加」。支持添加多个账号（自有账号 + 竞品账号）。

> XHS 用户 ID 获取方式：打开 [小红书创作者中心](https://creator.xiaohongshu.com)，进入「数据中心」→ 查看任意笔记 → 浏览器 F12 → Console → 输入 `window.__INITIAL_STATE__` → 在 `creatorIndex.user_id` 中找到。

### 6. 开始采集

1. 打开 [小红书创作者中心](https://creator.xiaohongshu.com) 并确认已登录
2. 点击插件图标 → 点击「**🚀 开始**」
3. 插件自动定位到 XHS 页面 → Content Script 拦截 API 数据 → 发送后端 → Pipeline → 飞书入库
4. 采集完成后桌面弹出通知：`✅ 采集完成: 1账号, N笔记`
5. 打开飞书多维表格即可看到最新数据

> 插件每天 10:00 会自动执行采集（通过 `chrome.alarms`），无需手动操作。只要 Chrome 在运行、后端在运行、XHS 保持登录状态即可。

### 7. 诊断排查

如果采集异常，点击插件中的「🔍 诊断信息」展开面板，点击「🔄 刷新诊断」查看：

| 指标 | 正常值 | 说明 |
|------|--------|------|
| 🟢 CS 加载 | 是 | Content Script 注入成功 |
| SW Controller | ⚠️ 是 | XHS 使用 Service Worker（正常） |
| 📤 Page→SW | > 0 | 拦截到页面发给 SW 的消息 |
| 📥 SW→Page | > 0 | 拦截到 SW 返回的数据 |
| Fetch 调用 | ≥ 0 | 兜底通道计数 |
| Fetch/XHR Hook | ✅ | Hook 未被覆盖 |

详见 [故障排查](#故障排查) 章节。

---

## 方式B：命令行 / 脚本模式

适用于无 Chrome 插件环境的场景（服务器、CI/CD）、或偏好命令行的用户。

### 安装依赖

```bash
git clone https://github.com/Zuel996/xhs-feishu-sync.git
cd xhs-feishu-sync
pip install -e .
playwright install chromium
```

### 配置

**飞书凭证：**

```bash
copy .env.example .env
```

编辑 `.env`：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here
FEISHU_BITABLE_APP_TOKEN=HvqUb97pqaREuXsg97ic3WoUnMf
FEISHU_BOT_WEBHOOK_URL=        # 可选，日报推送
```

**账号列表（YAML）：**

编辑 `config/accounts.yaml`：

```yaml
own_accounts:
  - account_id: "my_brand"
    xhs_user_id: "你的小红书用户ID"
    xhs_username: "你的用户名"
    display_name: "显示名称"
    competitor: false
```

> 也可从飞书「账号管理」表加载：`xhs-feishu run --source bitable`

### 浏览器 CDP 采集

**① 启动 Chrome 调试模式**

```batch
scripts\start_chrome.bat
```

或手动：

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\chrome-debug-profile" https://creator.xiaohongshu.com
```

在打开的浏览器中确认已登录创作者中心。**这个窗口不要关。**

**② 执行采集**

```powershell
xhs-feishu run
```

**③ 打开飞书多维表格查看数据**

### CSV 文件导入（备用）

1. 创作者中心 → 数据中心 → 笔记数据 → 导出
2. 将文件放入 `data/csv_imports/<account_id>/`
3. `config/settings.yaml` 中设置 `collection.strategy: "hybrid"`
4. 运行 `xhs-feishu run`

Hybrid 模式：浏览器数据优先（含实时互动指标），CSV 补充浏览器时间窗口外的历史笔记。

---

## 定时自动化

### 插件模式（自动）

Service Worker 内置 `chrome.alarms`，安装时自动注册每日定时采集（默认 10:00）。

- 无需任何额外配置
- Chrome 和后端必须都在运行
- 到时间自动打开/定位 XHS 页面 → 采集 → 通知

### CLI 模式（Windows 任务计划）

1. 确保 Chrome 调试窗口保持运行
2. 打开 **任务计划程序**（taskschd.msc）
3. 创建基本任务 → 触发器：每天 09:00 → 操作：`scripts\daily_run.bat`

`daily_run.bat` 会检查 Chrome CDP 是否存活，然后执行 `xhs-feishu run`。

---

## 命令参考

### CLI 命令

| 命令 | 用途 |
|------|------|
| `xhs-feishu setup` | 初始化数据库 + 创建飞书表（幂等） |
| `xhs-feishu test-feishu` | 验证飞书连接 |
| `xhs-feishu test-collect` | 干跑采集（不写飞书） |
| `xhs-feishu run` | 采集 → 转换 → 同步 |
| `xhs-feishu run -s bitable` | 从飞书「账号管理」表读取账号 |
| `xhs-feishu run -s auto` | 优先飞书，失败回退 YAML |
| `xhs-feishu run --date 2026-07-10` | 指定日期 |
| `xhs-feishu start` | 启动 APScheduler 定时调度 |
| `xhs-feishu status` | 查看最近同步状态 |
| `xhs-feishu clear --all --confirm` | 清空全部数据（保留账号管理表） |
| `xhs-feishu clear --account 账号名` | 清理指定账号数据 |

### 后端 API 端点

| 端点 | 用途 |
|------|------|
| `GET /health` | 健康检查 |
| `POST /config` | 配置并验证飞书凭证 |
| `POST /collect` | 提交采集数据，触发 Pipeline |
| `GET /status` | 最近采集状态 |

### 批处理脚本

| 脚本 | 用途 |
|------|------|
| `scripts\install.bat` | 一键安装：复制文件 + 开机自启 + Chrome 策略 |
| `scripts\start_server.bat` | 启动后端 API 服务（localhost:9527） |
| `scripts\setup.bat` | 安装 Python 依赖 + 初始化 |
| `scripts\start_chrome.bat` | 启动 Chrome CDP 调试模式 |
| `scripts\daily_run.bat` | 每日采集入口（配合 Windows 任务计划） |
| `每日采集.bat` | 一键采集同步全流程 |
| `删除.bat` | 一键清空飞书数据 |

---

## 飞书表格结构

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| **账号管理** | 监控账号配置（团队协作编辑） | 账号ID / XHS用户ID / 账号类型 / 启用 |
| **账号概览** | 每账号一行，当前指标 + 趋势 | 粉丝数 / 日增量 / 周增量 / 增长率 / 异常标记 |
| **笔记数据明细** | 每笔记一行，互动数据 | 浏览量 / 点赞 / 收藏 / 评论 / 分享 / 日增量 |
| **每日快照** | 账号 × 日期时间序列 | 粉丝 / 关注 / 获赞 / 笔记数 / 互动总量 |
| **竞品对比** | 横向排名 + 多维度对比 | 排名 / 粉丝 / 互动率 / 平均笔记互动量 |

首次运行 `xhs-feishu setup` 会自动创建以上 5 张表（幂等，不会重复创建）。

---

## 架构概览

```
Chrome Extension（前端 — 浏览器中运行）
  ├─ Popup UI           → 配置飞书凭证、管理账号、触发采集
  ├─ Content Script     → 注入 XHS 页面，拦截 API 响应（三层 Hook）
  ├─ Service Worker     → 消息中转、chrome.alarms 每日定时
  └─ Background         → 与后端 API 通信
         │
         │  fetch http://localhost:9527
         ▼
Python API Server（后端 — 本地进程）
  ├─ POST /config       → 验证飞书连接
  ├─ POST /collect      → Pipeline → 飞书 Upsert
  ├─ GET  /status       → 采集状态
  └─ GET  /health       → 健康检查
         │
         │  lark-oapi SDK
         ▼
飞书多维表格（5 张表）
```

### 两种架构对比

| | Chrome 插件模式 | CLI / CDP 模式 |
|------|------|------|
| 采集方式 | Content Script 拦截 API | CDP 协议解析 |
| 配置方式 | Popup UI 填写 | 编辑 `.env` + `accounts.yaml` |
| 启动方式 | `start_server.bat` + 加载扩展 | `start_chrome.bat` + `xhs-feishu run` |
| 定时 | `chrome.alarms` 自动 | Windows 任务计划 |
| 适用场景 | 日常使用 | 服务器 / 开发 / 无插件环境 |

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 后端 API | `src/api/server.py` | FastAPI 4 端点，接收插件请求 |
| Pipeline | `src/core/pipeline.py` | 采集 → 转换 → 同步全流程 |
| 配置 | `src/core/config.py` | pydantic 验证 + YAML + .env |
| 浏览器采集 | `src/collectors/xhs_browser.py` | CDP 直连 + API 拦截 + 解析 |
| CSV 采集 | `src/collectors/csv_import.py` | CSV/Excel 文件导入 |
| 采集工厂 | `src/collectors/factory.py` | 策略模式：browser / api / hybrid / csv |
| 标准化 | `src/transformers/normalizer.py` | 中文数字、类型转换 |
| 趋势计算 | `src/transformers/trend_calculator.py` | DoD / WoW / 3σ 异常检测 |
| 竞品分析 | `src/transformers/competitor.py` | 排名、横向对比 |
| 飞书客户端 | `src/loaders/bitable_client.py` | Token 管理、CRUD、重试 |
| 账号管理 | `src/loaders/account_manager.py` | 从飞书表加载监控账号 |
| 同步引擎 | `src/loaders/sync_engine.py` | Diff 增量、批量 Upsert |
| 调度器 | `src/scheduler/jobs.py` | APScheduler 定时任务 |
| Bot 通知 | `src/notifiers/feishu_bot.py` | 飞书消息卡片 |
| CLI | `src/cli/main.py` | Click 命令行入口 |
| **Chrome 插件** | `extension/` | **MV3 插件：拦截器 + Popup + SW** |

---

## 故障排查

### 后端未启动

```
❌ 无法连接后端，请确认 xhs-feishu-server 已启动
```

运行 `scripts\start_server.bat` 启动后端，确认命令行窗口显示 `Server running at http://localhost:9527`。

或用 `curl http://localhost:9527/health` 验证——应返回 `{"status":"ok"}`。

### 飞书 Token 获取失败 / 连接失败

```
✗ 获取飞书 tenant_access_token 失败
❌ 飞书连接失败
```

1. 确认 App ID / App Secret 填写正确（无多余空格）
2. 确认应用已在飞书开放平台**发布**
3. 确认应用有 `bitable:app` 权限
4. 在多维表格中：`...` → `添加文档应用` → 添加你的应用

### 插件加载后无反应 / 诊断全为 0

1. 确认已打开 `https://creator.xiaohongshu.com` 并登录
2. 确认扩展已刷新（manifest 变更后必须到 `chrome://extensions/` 点击刷新）
3. 打开插件 Popup → 诊断信息 → 查看各项计数器
4. 如果所有通道为 0：F12 打开 Console，检查是否有 `[xhs-feishu-sync]` 开头的日志

### API 拦截数为 0

这是已知的常见问题——XHS 使用 Service Worker 通信，不走常规 fetch/XHR：

1. 确认 `manifest.json` 中 `"world": "MAIN"` 已设置（否则 Hook 对页面不可见）
2. 在 XHS 页面等待 10 秒以上，让页面完全加载
3. 在 XHS 页面点击不同菜单（账号页、数据中心等），触发 API 请求
4. 查看诊断面板「📤 Page→SW」是否 > 0

### 飞书写入权限 91403 Forbidden

1. 确认应用已发布（飞书开放平台 → 应用发布）
2. 在多维表格中：`...` → `添加文档应用` → 添加你的应用
3. 确认权限包含 `bitable:app`

### 字段写入失败

运行 `xhs-feishu setup` 重新创建字段（幂等，不会重复建表）。

### Chrome CDP 连接失败（CLI 模式）

```
无法连接到 Chrome CDP (http://localhost:9222)
```

1. 先运行 `scripts\start_chrome.bat`
2. 确认 Chrome 已启动且端口 9222 有响应
3. 检查 `config/settings.yaml` 中 `cdp_endpoint` 配置

### 笔记数据为空

1. 确认浏览器已登录 `creator.xiaohongshu.com`
2. 插件模式：查看诊断面板确认拦截到数据
3. CLI 模式：运行 `xhs-feishu test-collect` 查看错误详情
4. Hybrid 模式下降级到 CSV，确认 `data/csv_imports/` 下有文件

---

## 开发指南

### 项目结构

```
xhs-feishu-sync/
├── pyproject.toml
├── .env.example
├── README.md
├── CLAUDE.md                    # AI 助手指引
├── config/
│   ├── settings.yaml
│   ├── accounts.yaml
│   └── bitable_schema.yaml
├── extension/                   # Chrome 插件 (MV3)
│   ├── manifest.json            # 权限、content_scripts、world: MAIN
│   ├── background/
│   │   └── service-worker.js    # 消息中转 + chrome.alarms 定时
│   ├── content/
│   │   └── xhs-interceptor.js   # 三层 API 拦截 + 诊断
│   ├── popup/
│   │   ├── popup.html           # 配置 UI + 诊断面板
│   │   ├── popup.js             # 逻辑：凭证/账号/采集/诊断
│   │   └── popup.css            # 样式
│   └── icons/
├── src/
│   ├── api/
│   │   └── server.py            # FastAPI 后端 (localhost:9527)
│   ├── cli/
│   │   └── main.py              # Click 命令行入口
│   ├── core/                    # 配置、异常、日志、Pipeline
│   ├── collectors/              # 数据采集层
│   ├── transformers/            # 数据转换层
│   ├── storage/                 # SQLite 持久化
│   ├── loaders/                 # 飞书同步
│   ├── notifiers/               # Bot 通知
│   └── scheduler/               # APScheduler 定时
├── scripts/
│   ├── install.bat              # 一键安装到 %LOCALAPPDATA%
│   ├── start_server.bat         # 启动后端
│   ├── setup.bat                # 安装依赖 + 初始化
│   ├── start_chrome.bat         # 启动 Chrome CDP 调试模式
│   └── daily_run.bat            # 每日采集入口
├── 每日采集.bat                  # 一键采集同步
├── 删除.bat                      # 一键清空数据
├── data/                        # CSV 导入 + SQLite 数据库
├── docs/                        # 设计文档
└── devlog/                      # 开发日志
```

### 文档索引

| 文档 | 说明 |
|------|------|
| [需求文档](docs/requirements.md) | 功能需求、非功能需求 |
| [架构设计](docs/architecture.md) | 系统架构、数据流 |
| [设计规范](docs/design-standards.md) | 编码规范、异常处理 |
| [执行计划](docs/implementation-plan.md) | 分阶段任务、进度追踪 |
| [API 参考](docs/api-reference.md) | 飞书 API、内部接口 |
| [开发日志](devlog/) | 每日记录 |

## License

MIT
