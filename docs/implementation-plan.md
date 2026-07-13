# 分步执行计划

## 总览

| Phase | 内容 | 预计周期 | 已完成 | 风险 |
|-------|------|---------|--------|------|
| 0 | **项目规范 + 文档** | 当前 | 🔄 进行中 | — |
| 1 | **基础框架** | Week 1-2 | ✅ 完成 | 低 |
| 2 | **数据采集层** | Week 2-4 | ✅ 已完成 | 🟢 低 |
| 3 | **数据转换层** | Week 4-5 | ✅ 已验证 | 🟢 低 |
| 4 | **飞书同步** | Week 5-6 | ✅ 已验证 | 🟢 低 |
| 5 | **调度与通知** | Week 6-7 | ✅ 已验证 | 🟢 低 |
| 6 | **集成测试** | Week 7-8 | ✅ 线路A+线路B 全部通过 | 🟢 低 |

> **当前状态**: Phase 1-6 核心链路全部验证通过。线路 A（Trend + Competitor + Pipeline 离线模式）38/38 通过。线路 B（飞书集成）7/7 通过，端到端已跑通。代码已推送至 GitHub。

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

### 验证结果（2026-07-13）
- [x] CDP 模式连接本地 Chrome 成功 ✅ — Chrome 150, WebSocket 直连
- [x] 账号主页数据采集正确 ✅ — fans=24, follow=298, faved=25
- [x] 笔记列表采集 ✅ — 浏览器 0 篇 + CSV fallback 22 篇
- [x] 反爬策略有效 ✅ — 延时1.5-5s，无验证码触发
- [x] 登录态过期检测 + 提示正常 ✅
- [x] CSV 导入解析正确 ✅ — Excel 中文日期"2026年01月12日"正常解析
- [x] 策略降级链按预期工作 ✅ — API→Browser→CSV 三级降级
- [ ] 笔记交互数据自动采集 — ⚠️ 仍依赖 CSV，浏览器笔记 API 待解析

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

### 在线验证（2026-07-13，7/7 通过）
- [x] 账号概览表 upsert 正确
- [x] 笔记明细表根据 note_id 匹配更新（0条，CSV无笔记数据）
- [x] 每日快照表追加无重复（同天二次run: created=0, updated=1）
- [x] 竞品对比表（无竞品数据，0条）
- [x] 批量 500 条分段正确
- [x] 幂等性：重复运行不产生脏数据
- [x] `xhs-feishu run` 端到端全链路 0 错误

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
- [x] 飞书凭证配置验证 ✅ (2026-07-13)
- [ ] Chrome CDP 模式启动脚本

### Step 6.2: 模块级验证（线路 A ✅ / 线路 B ✅）
- [x] **配置系统**: 加载 settings.yaml + .env 插值正确
- [x] **SQLite**: 建表 + CRUD 操作正确（4 张表全部通过）
- [x] **飞书 Client**: token 获取 + 表列表查询 ✅ (2026-07-13)
- [x] **Schema 管理**: 建表 + 字段幂等 ✅ (2026-07-13)
- [x] **CSV 采集器**: 加载示例 CSV 文件解析正确（13+7 项验证）
- [x] **标准化器**: 中文数字 + 日期转换
- [x] **趋势计算**: TrendCalculator 13/13 通过
- [x] **竞品分析**: CompetitorAnalyzer 13/13 通过
- [x] **Sync Engine**: 离线模式 7/7 通过 → 在线模式 ✅
- [x] **Pipeline**: 离线模式 + 在线模式 端到端 ✅

### Step 6.3: 端到端验证（线路 B — 完成 ✅）
- [x] 配置真实飞书凭证（FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BITABLE_APP_TOKEN）
- [x] `xhs-feishu setup` 初始化数据库 + 飞书表（4表51字段）
- [x] `xhs-feishu test-feishu` 飞书读写连接测试
- [x] `xhs-feishu run` CSV → SQLite → Trend → Competitor → Feishu 端到端
- [x] 验证飞书多维表格 4 张表数据正确
- [ ] 验证 Bot 通知收到（webhook 未配置）

### Step 6.4: 浏览器采集验证 ✅ (2026-07-13)
- [x] CDP 模式连接本地 Chrome 验证 ✅ — fans=24, follow=298, faved=25
- [x] `xhs-feishu test-collect` hybrid 模式通过 ✅
- [x] `xhs-feishu run` browser+CSV → Feishu 全链路通过 ✅
- [x] `platform` 字段添加（4张SQLite表 + 4张飞书表）✅
- [x] `scripts/start_chrome.bat` 一键启动 Chrome 调试模式 ✅
- [x] 历史数据导入（Excel 22篇笔记 + 21天快照覆盖1-7月）✅
- [ ] 笔记数据自动采集（浏览器拿笔记仍依赖 CSV fallback）
- [ ] `note_detail_new` API 响应结构解析（创作者中心笔记数据源已拦截）

### Step 6.5: 生产硬化
- [ ] 清理调试日志/注释代码
- [ ] 补充 README.md（搭建指南 + 故障排查）
- [ ] Windows Task Scheduler / GitHub Actions 配置指南
- [x] 提交代码到 GitHub ✅

---

## 下一步行动（按优先级）

1. ✅ **飞书凭证配置** — 已完成 (2026-07-13)
2. ✅ **`xhs-feishu setup`** — 4 表 55 字段已创建 (2026-07-13)
3. ✅ **`xhs-feishu test-feishu`** — 飞书连接通过 (2026-07-13)
4. ✅ **`xhs-feishu run`** — 端到端跑通 (2026-07-13)
5. ✅ **CDP 浏览器采集** — hybrid 模式验证通过 (2026-07-13)
6. ✅ **`platform` 字段** — 4表SQLite + 4表飞书 (2026-07-13)
7. ✅ **`scripts/start_chrome.bat`** — Chrome 一键启动 (2026-07-13)
8. ⬜ **`note_detail_new` API 解析** — 笔记数据自动采集（当前依赖CSV）
9. ⬜ **Bot 通知验证** — 配置 webhook 后测试
10. ⬜ **README 编写**
