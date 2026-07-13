# 小红书 → 飞书多维表格 数据自动同步工具

自动采集小红书账号数据（粉丝、笔记互动等），经过清洗、趋势计算和竞品排名后，同步到飞书多维表格。

---

## 目录

- [功能特性](#功能特性)
- [系统要求](#系统要求)
- [安装](#安装)
- [配置](#配置)
  - [1. 飞书应用凭证](#1-飞书应用凭证)
  - [2. 飞书多维表格权限](#2-飞书多维表格权限)
  - [3. 监控账号列表](#3-监控账号列表)
  - [4. 采集策略](#4-采集策略)
  - [5. 调度时间](#5-调度时间)
- [快速开始](#快速开始)
- [命令参考](#命令参考)
- [数据文件格式](#数据文件格式)
- [飞书表格结构](#飞书表格结构)
- [架构概览](#架构概览)
- [定时运行](#定时运行)
  - [方案A：APScheduler 常驻进程](#方案aapscheduler-常驻进程)
  - [方案B：Windows 任务计划程序](#方案bwindows-任务计划程序)
  - [方案C：GitHub Actions（未来）](#方案cgithub-actions未来)
- [故障排查](#故障排查)
- [开发指南](#开发指南)

---

## 功能特性

- **多策略数据采集**：CSV 导入（当前）/ 浏览器自动化（Playwright CDP）/ 开放 API（未来）
- **自动趋势计算**：日环比（DoD）、周环比（WoW）、增长率、3σ 异常检测
- **竞品分析**：横向排名、多维度指标对比
- **飞书多维表格同步**：增量 Diff + 批量 Upsert，幂等无重复
- **定时调度**：APScheduler + Cron 表达式，每日自动运行
- **Bot 通知**：飞书消息卡片推送日报摘要 / 错误告警
- **离线兼容**：无飞书凭证时自动降级为离线模式，不阻塞本地计算

---

## 系统要求

| 项目 | 要求 |
|------|------|
| Python | ≥ 3.11 |
| 操作系统 | Windows / macOS / Linux |
| 飞书 | 自建应用（或能添加"文档应用"的多维表格） |
| 浏览器（可选） | Chrome（用于 CDP 自动化采集） |

---

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/Zuel996/xhs-feishu-sync.git
cd xhs-feishu-sync

# 2. 安装依赖
pip install -e .

# 3. （可选）安装浏览器自动化依赖
playwright install chromium
```

---

## 配置

### 1. 飞书应用凭证

```bash
# 复制配置模板
copy .env.example .env   # Windows
cp .env.example .env     # macOS/Linux
```

编辑 `.env` 文件：

```bash
# 飞书应用凭证（必填，除非跑离线模式）
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here

# 飞书多维表格 App Token（从 URL 提取）
# https://xxxx.feishu.cn/base/HvqUb97pqaREuXsg97ic3WoUnMf
#                              ^^^^^^^^^^^^^^^^^^^^^^^^
FEISHU_BITABLE_APP_TOKEN=HvqUb97pqaREuXsg97ic3WoUnMf

# 飞书 Bot Webhook（可选，日报推送用）
FEISHU_BOT_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
```

> **获取凭证**：登录 [飞书开放平台](https://open.feishu.cn) → 创建自建应用 → 开通 `bitable:app` 权限 → 发布应用 → 在「凭证与基础信息」页获取 App ID / App Secret。

### 2. 飞书多维表格权限

应用需要对目标多维表格有写入权限。两种方式任选其一：

| 方式 | 步骤 | 适用场景 |
|------|------|---------|
| **添加文档应用**（推荐） | 在飞书打开多维表格 → 右上角 `...` → `添加文档应用` → 搜索你的应用名 → 添加 | 最快，无需管理员 |
| **管理员安装** | 管理后台 → 应用管理 → 自建应用 → 找到应用 → 安装 | 企业级正式部署 |

### 3. 监控账号列表

编辑 `config/accounts.yaml`：

```yaml
own_accounts:
  - account_id: "my_brand"              # 唯一标识（英文/数字）
    xhs_user_id: "5f3a2b1c0000000001001234"  # 小红书用户ID
    xhs_username: "品牌官方号"            # 小红书用户名
    display_name: "我的品牌"              # 飞书表格中显示的名称
    competitor: false                    # false = 自有账号

competitor_accounts:
  - account_id: "competitor_a"
    xhs_user_id: "5f3a2b1c0000000001005678"
    xhs_username: "竞品A"
    display_name: "竞品A"
    competitor: true                     # true = 竞品账号
```

### 4. 采集策略

编辑 `config/settings.yaml`：

```yaml
collection:
  strategy: "csv"          # 当前策略（从CSV文件读取）
  # 可选值: "browser" | "api" | "hybrid" | "csv"

  browser:                 # 浏览器采集配置（strategy=browser 时生效）
    cdp_endpoint: "http://localhost:9222"
    headless: false
    min_delay_seconds: 1.5
    max_delay_seconds: 5.0
    max_notes_per_account: 100
```

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| `csv` | 从 CSV 文件导入数据 | 无 API 权限、追求稳定 |
| `browser` | Playwright CDP 连接 Chrome 自动化采集 | 需要实时数据 |
| `api` | 小红书开放平台 API | 有官方 API 权限 |
| `hybrid` | API → Browser → CSV 三级降级 | 生产环境高可用 |

### 5. 调度时间

```yaml
schedule:
  cron: "0 8 * * *"           # 每天 8:00（中国时间）
  timezone: "Asia/Shanghai"
  retry_count: 3               # 失败重试次数
  retry_delay_seconds: 300     # 重试间隔（秒）
```

---

## 快速开始

```bash
# 第一步：初始化
xhs-feishu setup
# 将创建 SQLite 数据库 + 飞书多维表格 4 张表（含 51 个字段）

# 第二步：测试连接
xhs-feishu test-feishu
# 输出 ✓ 表示飞书连接正常

# 第三步：准备数据文件（CSV 模式）
# 将小红书创作者中心导出的 CSV 放入：
#   data/csv_imports/<account_id>/YYYY-MM-DD_export.csv
# 示例：data/csv_imports/test_brand/2026-07-10_export.csv

# 第四步：执行一次完整同步
xhs-feishu run --date 2026-07-13
# 输出 ✓ 完成 表示数据已写入飞书表格

# 第五步：查看状态
xhs-feishu status
```

---

## 命令参考

### `xhs-feishu setup`

一次性初始化。创建本地 SQLite 数据库和飞书多维表格 4 张表。**幂等**，重复运行不会重复建表。

```bash
xhs-feishu setup
```

### `xhs-feishu test-feishu`

测试飞书多维表格连接和权限。验证 App ID / Secret / App Token 是否配置正确。

```bash
xhs-feishu test-feishu
```

输出示例：
```
✓ Token 获取成功 (前8位: t-g1047d...)
✓ 多维表格访问成功，共 8 张表
✓ 飞书连接测试通过！
```

### `xhs-feishu test-collect`

测试数据采集（干跑模式）。加载配置的账号，采集数据并输出到日志，**不写入飞书**。

```bash
xhs-feishu test-collect                    # 采集所有账号
xhs-feishu test-collect --account my_brand  # 仅采集指定账号
```

### `xhs-feishu run`

执行一次完整的 采集 → 转换 → 同步 流程。这是核心命令。

```bash
xhs-feishu run                    # 使用今天的日期
xhs-feishu run --date 2026-07-13 # 指定日期
```

执行流程：
```
CSV 文件 → 数据标准化 → 趋势计算 → 竞品排名 → SQLite 存储 → 飞书同步
```

### `xhs-feishu start`

启动定时调度器，每日按配置的 cron 时间自动运行。

```bash
xhs-feishu start
# 按 Ctrl+C 停止
```

### `xhs-feishu status`

查看上次同步状态。

```bash
xhs-feishu status
```

---

## 数据文件格式

### CSV 文件路径规范

```
data/csv_imports/
  └── <account_id>/                    # 对应 accounts.yaml 中的 account_id
      └── YYYY-MM-DD_export.csv        # 创作者中心导出的原始 CSV
```

### CSV 列要求

CSV 文件为小红书创作者中心导出的原始格式。程序会自动解析以下列：

| CSV 列名 | 用途 | 格式要求 |
|----------|------|---------|
| 粉丝数 | 账号粉丝总数 | 数字，支持中文单位（"1.2万"、"3.5亿"）|
| 关注数 | 账号关注数 | 数字 |
| 获赞与收藏 | 累计获赞+收藏 | 数字 |
| 笔记标题 | 笔记标题 | 文本 |
| 笔记类型 | 图文/视频 | "图文" 或 "视频" |
| 发布日期 | 笔记发布日期 | YYYY-MM-DD |
| 笔记链接 | 笔记URL | https://... |
| 浏览量 | 笔记浏览量 | 数字 |
| 点赞数 | 点赞数 | 数字 |
| 收藏数 | 收藏数 | 数字 |
| 评论数 | 评论数 | 数字 |
| 分享数 | 分享数 | 数字 |

---

## 飞书表格结构

初始化后，多维表格中将创建 4 张数据表：

### 表 1：账号概览（account_summary）

每行一个监控账号，包含当前指标、趋势和异常标记。

| 字段 | 类型 | 说明 |
|------|------|------|
| 账号名称 | 文本 | 账号唯一标识 |
| 账号类型 | 单选 | 自有账号 / 竞品账号 |
| 粉丝数 | 数字 | 当前粉丝数 |
| 粉丝日增量 | 数字 | 与昨天的差值 |
| 粉丝周增量 | 数字 | 与上周的差值 |
| 粉丝增长率(%) | 数字 | 日增长率 |
| 竞品排名 | 数字 | 在同组中的排名 |
| 异常标记 | 复选框 | 是否触发 3σ 异常检测 |

### 表 2：笔记数据明细（note_metrics）

每行一篇笔记，包含互动数据和日增量。

### 表 3：每日快照（daily_snapshot）

每行 = 账号 × 日期。记录时间序列数据，用于趋势计算。

### 表 4：竞品对比（competitor_comparison）

每行一个竞品账号，含排名和多维度对比指标。

---

## 架构概览

```
配置层 (YAML + pydantic + .env)
    │
    ▼
采集层 ─── CSV导入 / Browser(Playwright/CDP) / API(未来)
    │
    ▼
转换层 ─── 数据标准化 / 趋势计算(DoD/WoW) / 竞品排名
    │
    ▼
存储层 ─── SQLite (本地历史) ──► 飞书 Bitable (4张表)
    │
    ▼
通知层 ─── 飞书 Bot (日报卡片 / 失败告警)
    │
    ▼
调度层 ─── APScheduler (每日定时 / CLI手动触发)
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 配置 | `src/core/config.py` | pydantic 配置验证 + YAML + .env 加载 |
| CSV 采集 | `src/collectors/csv_import.py` | 解析创作者中心导出的 CSV |
| 浏览器采集 | `src/collectors/xhs_browser.py` | Playwright CDP 自动化采集（待验证）|
| 标准化 | `src/transformers/normalizer.py` | 中文数字、类型转换、异常值处理 |
| 趋势计算 | `src/transformers/trend_calculator.py` | 日环/周环、增长率、3σ 异常 |
| 竞品分析 | `src/transformers/competitor.py` | 排名计算、横向对比 |
| 飞书客户端 | `src/loaders/bitable_client.py` | Token 管理、CRUD、重试 |
| 同步引擎 | `src/loaders/sync_engine.py` | Diff 增量、批量 Upsert、幂等 |
| 调度器 | `src/scheduler/jobs.py` | APScheduler 定时任务 |
| Bot 通知 | `src/notifiers/feishu_bot.py` | 飞书消息卡片 |
| CLI | `src/cli/main.py` | Click 命令行入口 |

---

## 定时运行

### 方案A：APScheduler 常驻进程

```bash
xhs-feishu start
```

进程常驻后台（终端保持打开）。适合开发/测试环境。

### 方案B：Windows 任务计划程序

1. 打开 **任务计划程序**（Task Scheduler）
2. 创建基本任务 → 触发器：**每天 8:00**
3. 操作 → 启动程序：
   - 程序：`C:\Users\<用户名>\AppData\Local\Programs\Python\Python311\python.exe`
   - 参数：`-m src.cli.main run`
   - 起始于：`C:\path\to\xhs-feishu-sync`

### 方案C：GitHub Actions（未来）

使用 GitHub Actions 的 `schedule` 触发器每日运行（需配置浏览器/CSV 自动化环境）。

---

## 故障排查

### `xhs-feishu` 命令找不到

```bash
pip install -e .     # 重新安装
```

### `ModuleNotFoundError`

```bash
# 确保在项目根目录下运行
cd xhs-feishu-sync
```

### 飞书 Token 获取失败

```
✗ 获取飞书 tenant_access_token 失败: code=...
```

检查 `.env` 中的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 是否正确。

### 飞书写入权限 91403 Forbidden

1. 检查应用是否已发布（开发者后台 → 应用发布 → 发布）
2. 在多维表格中：`...` → `添加文档应用` → 搜索并添加你的应用
3. 确认权限 scope 包含 `bitable:app`

### 字段写入失败 FieldNameNotFound

运行一次 `xhs-feishu setup` 确保所有字段已创建。

### CSV 文件找不到

确保文件路径为：`data/csv_imports/<account_id>/YYYY-MM-DD_export.csv`

其中 `<account_id>` 对应 `accounts.yaml` 中的 `account_id` 字段。

### 中文显示乱码（Windows Terminal）

在终端设置中将编码改为 UTF-8，或使用 Windows Terminal（非 cmd.exe）。

---

## 开发指南

### 项目结构

```
xhs-feishu-sync/
├── pyproject.toml              # 项目元数据 + 依赖
├── .env.example                # 环境变量模板
├── README.md
├── config/
│   ├── settings.yaml           # 主配置
│   ├── accounts.yaml           # 监控账号列表
│   └── bitable_schema.yaml    # 飞书表/字段定义
├── src/
│   ├── cli/main.py             # CLI 入口
│   ├── core/                   # 配置、异常、日志
│   ├── collectors/             # 数据采集层
│   ├── transformers/           # 数据转换层
│   ├── storage/                # SQLite 存储
│   ├── loaders/                # 飞书同步
│   ├── notifiers/              # Bot 通知
│   └── scheduler/              # 定时任务
├── scripts/                    # 辅助脚本
├── data/                       # 数据文件（CSV、SQLite）
├── logs/                       # 日志文件
├── docs/                       # 设计文档
│   ├── requirements.md
│   ├── architecture.md
│   ├── design-standards.md
│   ├── implementation-plan.md
│   └── api-reference.md
├── devlog/                     # 开发日志
└── tests/                      # 测试
```

### 开发命令

```bash
# 代码检查
pip install -e ".[dev]"
ruff check src/

# 类型检查
mypy src/

# 运行测试
pytest
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

### 运行验证脚本

```bash
python scripts/verify_trend_competitor.py    # 趋势 + 竞品模块验证（26项）
python scripts/verify_scheduler.py            # 调度器验证（15项）
```

---

## License

MIT
