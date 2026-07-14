# Today Vibecoding Review — 项目启动期 (2026-07-10 ~ 07-14)

## 一句话总结

四天，从零到全自动——一个小红书 × 飞书多维表格的数据同步工具，端到端跑通，浏览器自动采集创作者中心数据，零人工干预。

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

## 最终项目状态

```
Phase 1: 基础框架           ✅
Phase 2: 数据采集层          ✅ CDP Browser + CSV Hybrid + API 解析
Phase 3: 数据转换层          ✅ 26/26 (中文数字/趋势/竞品/异常检测)
Phase 4: 飞书同步            ✅ 在线/离线双模式
Phase 5: 调度与通知          ✅ 15/15 (APScheduler + Bot)
Phase 6: 集成测试            ✅ 线路 A+B+C 全部通过
新增: 飞书账号管理           ✅ Bitable → Pipeline 端到端
新增: 一键操作脚本           ✅ 双击采集 + 双击清空
```

| 指标 | 数值 |
|------|------|
| 修复 Bug | 23 个 |
| 验证项 | 60+ 全部通过 |
| 拦截 API | 8 个创作者中心接口 |
| 飞书表 | 5 张 × 65 字段 |
| Git 提交 | 21 个 |
| GitHub | [Zuel996/xhs-feishu-sync](https://github.com/Zuel996/xhs-feishu-sync) |

### 用户工作流（最终形态）

```
1. 飞书「账号管理」表填写账号 → 勾选「启用」
2. 双击「每日采集.bat」→ 自动采集 + 同步
3. 打开飞书多维表格查看数据
```

## 剩余事项

| 优先级 | 事项 | 说明 |
|--------|------|------|
| P2 | 🔔 Bot 通知 webhook | 飞书群配置日报推送 |
| P3 | ⏰ Windows 定时任务 | 每天 8:00 自动触发 |
| P4 | 🌐 公众号扩展 | 架构已预留 `platform` 字段 |

---

> 文档创建于 2026-07-13，更新于 2026-07-14。此文件为只读归档，仅在明确指令下可编辑。
