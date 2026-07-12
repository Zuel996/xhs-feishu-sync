# CLAUDE.md — AI 助手指引

## 项目概述
**小红书 → 飞书多维表格** 数据自动统计工具。
每日自动采集小红书账号数据，统计后同步到飞书多维表格。
技术栈: Python 3.11+ / Playwright / lark-oapi / SQLite / APScheduler。

---

## 标准文件路径

所有开发必须遵循以下文档中的规范。接到任何任务时，先检查相关文档：

| 文档 | 路径 | 用途 |
|------|------|------|
| 需求文档 | [docs/requirements.md](docs/requirements.md) | 功能需求、非功能需求、约束条件 |
| 架构设计 | [docs/architecture.md](docs/architecture.md) | 系统架构、数据流、目录结构、技术栈 |
| 设计规范 | [docs/design-standards.md](docs/design-standards.md) | 代码风格、命名、异常处理、日志、错误恢复 |
| 执行计划 | [docs/implementation-plan.md](docs/implementation-plan.md) | 分阶段任务、当前进度、待验证清单 |
| API 参考 | [docs/api-reference.md](docs/api-reference.md) | 飞书API、小红书API、内部接口文档 |
| 开发日志 | [devlog/](devlog/) | 每日开发记录，命名格式 `YYYY-MM-DD.md` |

---

## 工作原则

### 1. 安全第一，逐步推进
- **不要一口气做大改动** — 每次只改一个模块，验证通过后再进入下一步
- **先验证，后推进** — 任何代码变更后必须验证，确认无误才能标记为完成
- **保持回滚能力** — 破坏性修改前，确保可以回退到已知良好状态

### 2. 开发流程
每次会话遵循以下流程：
1. **阅读开发日志** — 查看 `devlog/` 中最新的日志文件，了解当前进度
2. **对照执行计划** — 查看 `docs/implementation-plan.md` 的待验证清单
3. **选择一项任务** — 只做清单中的一个待验证项或一个模块
4. **执行 + 验证** — 完成代码修改后立即验证
5. **更新日志** — 在 `devlog/` 中记录今日完成、待办、遇到的问题

### 3. 验证优先于新功能
当前项目代码（Phase 1-5）已完成但未经验证。
**首要任务不是添加新功能，而是验证已有代码能正常工作。**
验证顺序：环境安装 → CSV路径 → 飞书连接 → SQLite → Pipeline → 浏览器采集。

### 4. 代码修改规范
- 修改前先阅读相关文件
- 遵循 `docs/design-standards.md` 中的编码规范
- 不引入与现有模块职责重复的代码
- 修改异常类时检查继承层次
- 敏感信息永远不要硬编码

### 5. 日志与文档同步
- 每天结束前更新 `devlog/YYYY-MM-DD.md`
- 如果发现文档与代码不一致，更新文档
- `implementation-plan.md` 中的勾选状态保持最新

---

## 快速参考

### 常用命令
```bash
# 安装依赖
pip install -e .

# 初始化
xhs-feishu setup

# 测试连接
xhs-feishu test-feishu
xhs-feishu test-collect

# 单次运行
xhs-feishu run
xhs-feishu run --date 2026-07-10

# 调度器
xhs-feishu start
xhs-feishu status
```

### 关键配置文件
- `config/settings.yaml` — 采集策略、调度cron、日志级别
- `config/accounts.yaml` — 自有账号 + 竞品账号列表
- `config/bitable_schema.yaml` — 飞书4张表的字段定义
- `.env` — 飞书凭证（从 `.env.example` 复制并填写）

### 关键模块入口
- 采集器工厂: `src/collectors/factory.py` → `create_collector()`
- Pipeline: `src/core/pipeline.py` → `run_pipeline()`
- 同步引擎: `src/loaders/sync_engine.py` → `SyncEngine`
- CLI: `src/cli/main.py` → `cli` group

### 飞书 Bitable 4张表
| 表名 | key | 用途 |
|------|-----|------|
| 账号概览 | account_summary | 每账号一行，当前指标+趋势 |
| 笔记数据明细 | note_metrics | 每笔记一行，互动数据+日增量 |
| 每日快照 | daily_snapshot | 账号×日期时间序列 |
| 竞品对比 | competitor_comparison | 横向排名+指标对比 |

---

## 当前状态 (2026-07-10)
- **Phase 1-5**: 代码已完成 ✅
- **Phase 6**: 集成测试与验证 ⬜ 待开始
- **下一步**: 环境验证 → CSV路径测试 → 飞书连接测试
- **具体待办**: 见 [devlog/2026-07-10.md](devlog/2026-07-10.md) 待办清单
