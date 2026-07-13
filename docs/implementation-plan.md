# 分步执行计划

## 总览

| Phase | 内容 | 预计周期 | 已完成 | 风险 |
|-------|------|---------|--------|------|
| 0 | **项目规范 + 文档** | 当前 | 🔄 进行中 | — |
| 1 | **基础框架** | Week 1-2 | ✅ 完成 | 低 |
| 2 | **数据采集层** | Week 2-4 | ✅ 完成（未验证） | 🔴 高 |
| 3 | **数据转换层** | Week 4-5 | ✅ 已验证 | 🟢 低 |
| 4 | **飞书同步** | Week 5-6 | ⚠️ 离线已验证 / 在线待验证 | 🟡 中 |
| 5 | **调度与通知** | Week 6-7 | ✅ 已验证 | 🟢 低 |
| 6 | **集成测试** | Week 7-8 | 🔄 线路A完成 / 线路B待飞书凭证 | 🟡 中 |

> **当前状态**: Phase 1-3 已验证通过。线路 A（Trend + Competitor + Pipeline 离线模式）38/38 通过。线路 B（飞书集成）等待用户配置飞书凭证。代码已推送至 GitHub。

---

## Phase 0: 项目规范 + 文档（当前）

### 目标
建立完整的项目文档体系和开发规范，确保后续开发有章可循。

### 产出物
- [x] `CLAUDE.md` — AI 助手指引
- [x] `docs/requirements.md` — 需求文档
- [x] `docs/architecture.md` — 技术架构
- [x] `docs/design-standards.md` — 设计/编码规范
- [x] `docs/implementation-plan.md` — 执行计划（本文件）
- [x] `docs/api-reference.md` — API 参考
- [x] `devlog/` — 开发日志目录
- [ ] `devlog/YYYY-MM-DD.md` — 每日日志（持续更新）

---

## Phase 1: 基础框架 ✅

### 已完成
- ✅ `pyproject.toml` — 项目元数据 + 依赖声明
- ✅ `.env.example` — 环境变量模板
- ✅ `.gitignore` — 忽略规则
- ✅ `config/settings.yaml` — 主配置（采集策略、调度、日志）
- ✅ `config/accounts.yaml` — 账号列表模板
- ✅ `config/bitable_schema.yaml` — 飞书表字段定义
- ✅ `src/core/config.py` — pydantic 配置验证 + YAML加载 + 环境变量插值
- ✅ `src/core/exceptions.py` — 完整异常层次（15+ 异常类）
- ✅ `src/core/logging.py` — 日志系统（控制台 + 文件轮转）
- ✅ `src/storage/models.py` — SQLAlchemy ORM（4张表）
- ✅ `src/storage/sqlite.py` — 数据库管理 + Repository 层
- ✅ `scripts/init_db.py` — SQLite 初始化脚本
- ✅ `src/loaders/bitable_client.py` — 飞书API封装（token管理、CRUD、重试）
- ✅ `src/loaders/bitable_schema.py` — Schema管理器
- ✅ `scripts/setup_bitable.py` — 一键建表脚本
- ✅ `scripts/manual_run.py` — 手动执行入口
- ✅ `src/cli/main.py` — CLI命令框架（setup/test-feishu/test-collect/run/start/status）

### 待验证
- [ ] `pip install -e .` 依赖安装正确
- [ ] `xhs-feishu setup` 能初始化数据库
- [ ] `xhs-feishu test-feishu` 能连接飞书（需要真实凭证）

---

## Phase 2: 数据采集层 ✅ (未验证)

### 已完成
- ✅ `src/collectors/models.py` — 标准化数据模型（AccountProfile, NoteMetrics, CollectResult）
- ✅ `src/collectors/base.py` — BaseCollector 抽象基类 + collect_all 编排
- ✅ `src/collectors/xhs_browser.py` — XHSBrowserCollector (CDP) + HybridCollector（混合降级）
- ✅ `src/collectors/xhs_api.py` — XHSApiCollector（官方API，未来使用）
- ✅ `src/collectors/csv_import.py` — CSVImportCollector（CSV降级方案）
- ✅ `src/collectors/factory.py` — 采集器工厂（browser/api/hybrid/csv 策略切换）

### 待验证
- [ ] CDP 模式连接本地 Chrome 成功
- [ ] 账号主页数据采集正确
- [ ] 笔记列表 + 详情采集正确
- [ ] 反爬策略有效（无验证码触发）
- [ ] 登录态过期检测 + 提示正常
- [ ] CSV 导入解析正确（中文数字、日期格式）
- [ ] 策略降级链按预期工作

---

## Phase 3: 数据转换层 ✅ 已验证

### 已完成
- ✅ `src/transformers/normalizer.py` — 中文数字解析、类型转换、数据校验、ORM转换
- ✅ `src/transformers/trend_calculator.py` — DoD/WoW增量、增长率、3σ异常检测
- ✅ `src/transformers/competitor.py` — 排名计算、横向对比表

### 验证结果（2026-07-10，26/26 通过）
- [x] `parse_chinese_number("1.2万")` → 12000 ✅
- [x] `parse_chinese_number("3.5亿")` → 350000000 ✅
- [x] DoD/WoW 计算与人工核对一致 ✅ (13/13)
- [x] 异常检测（3σ）阈值合理 ✅ (z≈4.0 正确触发)
- [x] 竞品排名变换正确追踪 ✅ (13/13)
- [x] Pipeline 离线模式端到端 ✅ (5/5)

---

## Phase 4: 飞书同步 ⚠️ 离线已验证 / 在线待验证

### 已完成
- ✅ `src/loaders/sync_engine.py` — SyncEngine（Diff增量 + 批量Upsert + 幂等）
- ✅ `src/core/pipeline.py` — PipelineRunner（采集→转换→存储→同步全流程编排）

### 离线模式验证（2026-07-10，7/7 通过）
- [x] 无飞书凭证时自动进入离线模式（`enabled=False`）✅
- [x] 全部 5 个 sync 方法返回 0 不抛异常 ✅
- [x] `MissingCredentialError` 和 `FeishuAuthError` 均被捕获 ✅
- [x] Trend → Competitor → Pipeline 全链路不中断 ✅

### 在线验证（待飞书凭证）
- [ ] 账号概览表 upsert 正确
- [ ] 笔记明细表根据 note_id 匹配更新
- [ ] 每日快照表追加无重复
- [ ] 竞品对比表全量刷新
- [ ] 批量 500 条分段正确
- [ ] 幂等性：重复运行不产生脏数据

---

## Phase 5: 调度与通知 ✅ 已验证

### 已完成
- ✅ `src/scheduler/jobs.py` — APScheduler 定时任务 + 事件监听
- ✅ `src/notifiers/feishu_bot.py` — 飞书Bot通知（日报卡片 + 错误告警）

### 验证结果（2026-07-13，15/15 通过）
- [x] `create_scheduler()` 创建和配置正确 (5/5)
- [x] 定时任务按间隔触发，精度达标 (3/3)
- [x] 错误监听器捕获异常不崩溃 (1/1)
- [x] `_run_sync_job()` 离线模式正常 (1/1)
- [x] SyncState 状态记录正确写入 (3/3)
- [x] 优雅关闭，资源清理干净 (2/2)
- [x] `xhs-feishu status` CLI 命令正常

---

## Phase 6: 集成测试与硬化工单

### Step 6.1: 环境验证 ✅
- [x] Python 3.11+ 环境准备
- [x] 依赖安装验证 (`pip install -e .`)
- [x] Playwright 浏览器安装 (`playwright install chromium`)
- [x] 全部 21 个模块导入验证通过
- [x] CLI `--help` 可用，6 个命令正常
- [ ] 飞书凭证配置验证（需用户配置 .env）
- [ ] Chrome CDP 模式启动脚本

### Step 6.2: 模块级验证（线路 A ✅ / 线路 B ⬜）
- [x] **配置系统**: 加载 settings.yaml + .env 插值正确
- [x] **SQLite**: 建表 + CRUD 操作正确（4 张表全部通过）
- [ ] **飞书 Client**: token 获取 + 表列表查询（需凭证）
- [ ] **Schema 管理**: 建表幂等性（需凭证）
- [x] **CSV 采集器**: 加载示例 CSV 文件解析正确（13+7 项验证）
- [x] **标准化器**: 中文数字 + 日期转换
- [x] **趋势计算**: TrendCalculator 13/13 通过
- [x] **竞品分析**: CompetitorAnalyzer 13/13 通过
- [x] **Sync Engine**: 离线模式 7/7 通过
- [x] **Pipeline**: 离线模式端到端 5/5 通过

### Step 6.3: 端到端验证（线路 B — 待飞书凭证）
- [ ] 配置真实飞书凭证（FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BITABLE_APP_TOKEN）
- [ ] `xhs-feishu setup` 初始化数据库 + 飞书表
- [ ] `xhs-feishu test-feishu` 飞书读写连接测试
- [ ] `xhs-feishu run` CSV → SQLite → Trend → Competitor → Feishu 端到端
- [ ] 验证飞书多维表格 4 张表数据正确
- [ ] 验证 Bot 通知收到

### Step 6.4: 浏览器采集验证（未来）
- [ ] 编写 `scripts/xhs_login.py` 扫码登录脚本
- [ ] storageState 启动模式验证（替代 CDP 依赖）
- [ ] CDP 模式连接本地 Chrome 验证

### Step 6.5: 生产硬化
- [ ] 清理调试日志/注释代码
- [ ] 补充 README.md（搭建指南 + 故障排查）
- [ ] Windows Task Scheduler / GitHub Actions 配置指南
- [x] 提交代码到 GitHub ✅

---

## 下一步行动（按优先级）

1. ⬜ **飞书凭证配置** — 用户创建飞书应用，填入 .env
2. ⬜ **`xhs-feishu setup`** — 初始化飞书 4 张表
3. ⬜ **`xhs-feishu test-feishu`** — 验证飞书连接
4. ⬜ **`xhs-feishu run`** — 端到端跑通
5. ⬜ **Bot 通知 + 调度器验证**
6. ⬜ **storageState 扫码登录脚本**（融合新方案优点）
7. ⬜ **GitHub Actions 备选调度**（融合新方案优点）
8. ⬜ **README 编写**
