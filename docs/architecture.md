# 技术架构设计

## 架构模式
ETL 管道架构 (Extract → Transform → Load)，采用分层设计。

## 架构图

```
配置层 (YAML + pydantic)
    │
    ▼
采集层 ─── XHS浏览器采集(Playwright/CDP) / CSV导入 / API(未来)
    │
    ▼
转换层 ─── 数据标准化 / 趋势计算(日环/周环) / 竞品排名
    │
    ▼
存储层 ─── SQLite (快照历史 + diff基准) ──► 飞书 Bitable (4张表)
    │
    ▼
通知层 ─── 飞书 Bot (成功日报卡 / 失败告警)
    │
    ▼
调度层 ─── APScheduler (每日8:00 定时 / CLI手动触发)
```

## 数据流

```
定时触发 (APScheduler 8:00 AM)
  → 加载配置 (accounts.yaml + settings.yaml)
  → 选择采集策略 (factory)
    → 遍历账号列表（自有账号优先，竞品次之）
      → 采集账号概览 (follower/following/likes)
      → 采集笔记列表 + 详情 (views/likes/favs/comments/shares)
    → 数据标准化 (中文数字解析、类型转换)
    → 存入 SQLite (account_snapshots + note_infos + note_snapshots)
    → 计算趋势 (DoD/WoW 增量、增长率、异常标记)
    → 竞品排名计算
    → Diff 对比 (新数据 vs 上次同步)
    → 批量同步到飞书 Bitable (upsert, 500条/批)
    → 飞书 Bot 推送日报 / 异常告警
```

## 目录结构

```
project/
├── CLAUDE.md                    # AI 助手指引
├── pyproject.toml               # 项目元数据 + 依赖
├── .env.example                 # 环境变量模板
├── .gitignore
│
├── docs/                        # 项目文档
│   ├── requirements.md          # 需求文档
│   ├── architecture.md          # 架构设计（本文件）
│   ├── design-standards.md      # 设计/编码规范
│   ├── implementation-plan.md   # 分步执行计划
│   └── api-reference.md         # API参考
│
├── devlog/                      # 开发日志
│   └── YYYY-MM-DD.md           # 每日开发记录
│
├── config/                      # 配置文件
│   ├── settings.yaml            # 主配置
│   ├── accounts.yaml            # 账号列表
│   └── bitable_schema.yaml      # 飞书表定义
│
├── src/                         # 源代码
│   ├── cli/                     # CLI 命令层
│   ├── core/                    # 核心：配置、异常、日志、Pipeline
│   ├── collectors/              # 采集层
│   ├── transformers/            # 转换层
│   ├── storage/                 # 本地存储层 (SQLite)
│   ├── loaders/                 # 飞书同步层
│   ├── notifiers/               # 通知层
│   └── scheduler/               # 调度层
│
├── scripts/                     # 辅助脚本
├── tests/                       # 测试
├── data/                        # SQLite 数据库文件
└── logs/                        # 运行日志
```

## 技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | ≥3.11 |
| 浏览器自动化 | Playwright (CDP) | ≥1.48 |
| 飞书SDK | lark-oapi | ≥1.4.0 |
| 配置验证 | pydantic | ≥2.0 |
| 本地存储 | SQLite + SQLAlchemy | ≥2.0 |
| 调度 | APScheduler | ≥3.10 |
| CLI | Click | ≥8.0 |
| HTTP | httpx | ≥0.27 |
| 重试 | tenacity | ≥9.0 |
| 日志 | structlog | ≥24.0 |
| 测试 | pytest + pytest-asyncio | ≥8.0 |

## 关键设计决策

### 1. CDP 模式 vs 标准 Playwright
**选择 CDP**：连接真实 Chrome 实例，绕过 Playwright 特征检测。小红书反爬能力强，标准 Playwright 的 Chromium 有可检测特征。

### 2. API 响应拦截 vs HTML 解析
**选择 API 拦截**：小红书页面大量使用 JS 渲染，HTML 结构频繁变更。拦截 XHR 响应获取 JSON 数据更稳定。

### 3. 增量同步 vs 全量覆盖
**选择增量 Diff**：对比 SQLite 中上次同步数据，仅将变更记录写入飞书。减少 API 调用次数，降低 429 风险。

### 4. SQLite 中间层 vs 直接写飞书
**选择 SQLite 中间层**：提供趋势计算的数据源、增量同步的 Diff 基准、原始数据审计轨迹。

## 数据模型

### 本地 SQLite (3张表 + 1状态表)
- `account_snapshots` — 账号每日快照
- `note_info` — 笔记基本信息（不变属性）
- `note_snapshots` — 笔记每日快照（互动数据）
- `sync_state` — 同步状态追踪

### 飞书 Bitable (4张表)
- `账号概览` — 每账号一行，当前指标 + 趋势
- `笔记数据明细` — 每笔记一行，互动数据 + 日增量
- `每日快照` — 账号×日期 时间序列
- `竞品对比` — 横向排名 + 指标对比
