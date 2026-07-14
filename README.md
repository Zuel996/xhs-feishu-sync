# 小红书 → 飞书多维表格 数据自动同步工具

自动采集小红书创作者中心数据（粉丝、笔记互动等），经过清洗和趋势计算后，同步到飞书多维表格。

---

## 目录

- [功能特性](#功能特性)
- [系统要求](#系统要求)
- [快速安装](#快速安装)
- [配置](#配置)
  - [1. 飞书应用凭证](#1-飞书应用凭证)
  - [2. 多维表格授权](#2-多维表格授权)
  - [3. 账号列表](#3-账号列表)
- [日常使用](#日常使用)
  - [浏览器自动采集（推荐）](#浏览器自动采集推荐)
  - [CSV 文件导入（备用）](#csv-文件导入备用)
- [定时自动化](#定时自动化)
- [命令参考](#命令参考)
- [团队部署](#团队部署)
- [飞书表格结构](#飞书表格结构)
- [架构概览](#架构概览)
- [故障排查](#故障排查)

---

## 功能特性

- **浏览器自动采集**：通过 Chrome CDP 直连创作者中心，自动拦截并解析 API 数据
- **Hybrid 智能合并**：浏览器实时数据优先，CSV 补充历史笔记（按 note_id 去重）
- **趋势计算**：日环比（DoD）、周环比（WoW）、增长率、3σ 异常检测
- **竞品分析**：横向排名、多维度指标对比
- **飞书多维表格同步**：增量 Diff + 批量 Upsert，幂等无重复
- **定时调度**：APScheduler 或 Windows 任务计划，每日自动运行
- **离线兼容**：无飞书凭证时自动降级，不阻塞本地计算
- **平台扩展预留**：4 张表含 `platform` 字段，为公众号等接入做准备

---

## 系统要求

| 项目 | 要求 |
|------|------|
| Python | ≥ 3.11 |
| 操作系统 | Windows / macOS / Linux |
| 浏览器 | Google Chrome（浏览器模式） |
| 飞书 | 自建应用，或能添加"文档应用"的多维表格 |

---

## 快速安装

### 方式一：一键安装（推荐）

```batch
scripts\setup.bat
```

自动完成：Python 检测 → 依赖安装 → 配置检查 → 数据库初始化。

### 方式二：手动安装

```bash
git clone https://github.com/Zuel996/xhs-feishu-sync.git
cd xhs-feishu-sync
pip install -e .
playwright install chromium    # 仅浏览器模式需要
```

---

## 配置

### 1. 飞书应用凭证

```bash
copy .env.example .env
```

编辑 `.env` 文件：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here
FEISHU_BITABLE_APP_TOKEN=HvqUb97pqaREuXsg97ic3WoUnMf
FEISHU_BOT_WEBHOOK_URL=        # 可选，日报推送
```

**获取方式**：登录 [飞书开放平台](https://open.feishu.cn) → 创建自建应用 → 添加 `bitable:app` 权限 → 发布应用 → 凭证页面获取 App ID / Secret。

Bitable App Token 从多维表格 URL 提取：
```
https://xxxx.feishu.cn/base/HvqUb97pqaREuXsg97ic3WoUnMf
                           ^^^^^^^^^^^^^^^^^^^^^^^^
```

### 2. 多维表格授权

在飞书打开多维表格 → 右上角 `...` → `添加文档应用` → 搜索你的应用名 → 添加。

首次运行 `xhs-feishu setup` 会自动创建 4 张数据表。

### 3. 账号列表

编辑 `config/accounts.yaml`，替换占位符为真实账号：

```yaml
own_accounts:
  - account_id: "my_brand"
    xhs_user_id: "你的小红书用户ID"
    xhs_username: "你的用户名"
    display_name: "显示名称"
    competitor: false
```

---

## 日常使用

### 浏览器自动采集（推荐）

每天跑一次即可获取实时数据：

```batch
# 1. 启动 Chrome 调试模式（一次，保持运行）
scripts\start_chrome.bat

# 2. 在浏览器中确认已登录 creator.xiaohongshu.com

# 3. 执行采集同步
xhs-feishu run
```

浏览器模式自动从创作者中心 API 采集：
- **账号数据**：粉丝、关注、获赞（`personal_info` API）
- **笔记互动**：浏览、点赞、收藏、评论、分享（`note/analyze/list` API）
- **每日趋势**：7/30 天聚合数据（`note_detail_new` API）

### CSV 文件导入（备用）

如果浏览器模式不可用，可以手动从创作者中心导出 Excel：

1. 打开创作者中心 → 数据中心 → 笔记数据 → 导出
2. 将导出的文件放入 `data/csv_imports/<account_id>/`
3. 确认 `config/settings.yaml` 中 `collection.strategy: "hybrid"`
4. 运行 `xhs-feishu run`

Hybrid 模式下：浏览器数据优先（含实时互动指标），CSV 补充浏览器时间窗口外的历史笔记。

---

## 定时自动化

### Windows 任务计划程序

1. 确保 `start_chrome.bat` 已运行（Chrome 保持登录）
2. 打开 **任务计划程序**（taskschd.msc）
3. 创建基本任务：
   - 触发器：**每天 09:00**
   - 操作 → 启动程序：`C:\你的路径\xhs-feishu-sync\scripts\daily_run.bat`

`daily_run.bat` 会自动检查 Chrome CDP 是否存活，然后执行 `xhs-feishu run`。

### APScheduler 常驻进程（备选）

```bash
xhs-feishu start
```

按 `Ctrl+C` 停止。适合开发/测试环境。

---

## 命令参考

| 命令 | 用途 |
|------|------|
| `xhs-feishu setup` | 初始化数据库 + 飞书表（幂等） |
| `xhs-feishu test-feishu` | 验证飞书连接 |
| `xhs-feishu test-collect` | 干跑采集（不写飞书） |
| `xhs-feishu run` | **核心命令**：采集 → 转换 → 同步 |
| `xhs-feishu run --date 2026-07-10` | 指定日期采集 |
| `xhs-feishu start` | 启动定时调度器 |
| `xhs-feishu status` | 查看最近同步状态 |

---

## 团队部署

### 推荐模式：单机采集 + 飞书消费

```
一台电脑 (Chrome + 定时任务)
  └─ 自动采集 → 写入飞书多维表格
                    │
      ┌─────────────┼─────────────┐
      ▼             ▼             ▼
   团队成员A     团队成员B     团队成员C
   (打开飞书)    (打开飞书)    (打开飞书)
```

团队成员**零安装**，打开飞书多维表格就能看到最新数据，支持筛选、排序、评论。

### 如果其他人也需要触发采集

参考 [CSV 文件导入](#csv-文件导入备用) 章节，策略设为 `csv` 即可在无 Chrome 环境下使用。

---

## 飞书表格结构

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| **账号概览** | 每账号一行，当前指标 + 趋势 | 粉丝数/日增量/周增量/增长率/异常标记 |
| **笔记数据明细** | 每笔记一行，互动数据 | 浏览量/点赞/收藏/评论/分享/日增量 |
| **每日快照** | 账号 × 日期时间序列 | 每日粉丝/关注/获赞/笔记数/互动总量 |
| **竞品对比** | 横向排名 + 多维度对比 | 排名/粉丝/互动率/平均笔记互动量 |

---

## 架构概览

```
Chrome CDP (端口 9222)
  ├─ personal_info        → 粉丝/关注/获赞
  ├─ note/analyze/list    → 单篇笔记互动数据
  └─ note_detail_new      → 7/30天聚合趋势
       │
  CSV 文件 (历史补充)
       │
       ▼
  Hybrid 合并 (浏览器优先 + CSV 去重)
       │
       ▼
  数据标准化 → 趋势计算(DoD/WoW/3σ) → 竞品排名
       │
       ▼
  SQLite (本地持久化) → 飞书多维表格 (4张表)
       │
       ▼
  飞书 Bot 通知 (日报摘要 / 错误告警)
```

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 配置 | `src/core/config.py` | pydantic 验证 + YAML + .env |
| 浏览器采集 | `src/collectors/xhs_browser.py` | CDP 直连 + API 拦截 + 解析 |
| CSV 采集 | `src/collectors/csv_import.py` | CSV/Excel 文件导入 |
| 采集工厂 | `src/collectors/factory.py` | 策略模式：browser/api/hybrid/csv |
| 标准化 | `src/transformers/normalizer.py` | 中文数字、类型转换 |
| 趋势计算 | `src/transformers/trend_calculator.py` | DoD/WoW/3σ 异常检测 |
| 竞品分析 | `src/transformers/competitor.py` | 排名、横向对比 |
| 飞书客户端 | `src/loaders/bitable_client.py` | Token 管理、CRUD、重试 |
| 同步引擎 | `src/loaders/sync_engine.py` | Diff 增量、批量 Upsert |
| 调度器 | `src/scheduler/jobs.py` | APScheduler 定时任务 |
| Bot 通知 | `src/notifiers/feishu_bot.py` | 飞书消息卡片 |
| CLI | `src/cli/main.py` | Click 命令行入口 |

---

## 故障排查

### Chrome CDP 连接失败

```
无法连接到 Chrome CDP (http://localhost:9222)
```

1. 先运行 `scripts\start_chrome.bat`
2. 确认 Chrome 已启动且端口 9222 有响应
3. 检查 `config/settings.yaml` 中 `cdp_endpoint` 配置

### 飞书 Token 获取失败

```
✗ 获取飞书 tenant_access_token 失败
```

检查 `.env` 中的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。

### 飞书写入权限 91403 Forbidden

1. 确认应用已发布（飞书开放平台 → 应用发布）
2. 在多维表格中：`...` → `添加文档应用` → 添加你的应用
3. 确认权限包含 `bitable:app`

### 字段写入失败

运行 `xhs-feishu setup` 重新创建字段（幂等，不会重复建表）。

### 笔记数据为空

1. 检查浏览器是否已登录 `creator.xiaohongshu.com`
2. 尝试 `xhs-feishu test-collect` 看具体失败原因
3. Hybrid 模式下会降级到 CSV，确认 `data/csv_imports/` 下有文件

---

## 开发指南

### 项目结构

```
xhs-feishu-sync/
├── pyproject.toml
├── .env.example
├── README.md
├── CLAUDE.md                  # AI 助手指引
├── config/
│   ├── settings.yaml
│   ├── accounts.yaml
│   └── bitable_schema.yaml
├── src/
│   ├── cli/main.py
│   ├── core/                  # 配置、异常、日志
│   ├── collectors/            # 数据采集层
│   ├── transformers/          # 数据转换层
│   ├── storage/               # SQLite 持久化
│   ├── loaders/               # 飞书同步
│   ├── notifiers/             # Bot 通知
│   └── scheduler/             # APScheduler 定时
├── scripts/                   # setup.bat / start_chrome.bat / daily_run.bat
├── data/                      # CSV 导入 + SQLite 数据库
├── docs/                      # 设计文档
└── devlog/                    # 开发日志
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
