# 设计规范与编码标准

## 代码风格

### 通用规则
- **Python 版本**: 3.11+，使用新语法特性（`str | None` 替代 `Optional[str]`）
- **行宽**: 100 字符
- **缩进**: 4 空格（不使用 Tab）
- **引号**: 双引号 `"` 用于字符串，单引号 `'` 用于字符/键名
- **编码**: UTF-8，文件头不需要 `# -*- coding: utf-8 -*-`

### 命名规范
```python
# 模块/文件: snake_case
#   例: xhs_browser.py, trend_calculator.py

# 类: PascalCase
#   例: XHSBrowserCollector, TrendCalculator

# 函数/方法: snake_case
#   例: collect_account_profile(), parse_chinese_number()

# 变量: snake_case
#   例: account_id, follower_count

# 常量: UPPER_SNAKE_CASE
#   例: XHS_BASE_URL, DEFAULT_TIMEOUT

# 私有属性: _prefix
#   例: self._browser, self._token

# 布尔变量: is_ / has_ 前缀
#   例: is_logged_in, has_anomaly
```

### 导入顺序
```python
# 1. 标准库
import asyncio
import logging
from datetime import date

# 2. 第三方库
import httpx
from pydantic import BaseModel

# 3. 本地模块
from src.core.config import load_config
from src.core.exceptions import CollectorError
```

### 类型注解
- **必须使用**: 所有公共函数/方法参数和返回值
- **可选**: 内部辅助函数
- **格式**: 使用 `| None` 替代 `Optional[...]`，使用 `list[dict]` 替代 `List[dict]`

## 异常处理

### 异常层次
```
XHSFeishuSyncError (base)
├── ConfigError
│   └── MissingCredentialError
├── CollectorError
│   ├── BrowserConnectionError
│   ├── LoginSessionExpiredError
│   ├── CaptchaDetectedError
│   ├── RateLimitError
│   ├── AccountNotFoundError
│   └── XHSApiError
├── TransformerError
├── StorageError
├── LoaderError
│   ├── FeishuAuthError
│   ├── FeishuApiError
│   └── SyncEngineError
├── NotifierError
└── SchedulerError
```

### 使用规则
1. **不吞异常**: 捕获具体异常，记录日志后重新抛出或优雅降级
2. **不使用裸 except**: 总是指定异常类型
3. **单账号隔离**: 一个账号采集失败不影响其他账号
4. **用户友好**: 异常消息使用中文，技术细节存日志

## 日志规范

### 级别使用
- **DEBUG**: 详细调试信息（API 请求/响应内容、页面元素查找过程）
- **INFO**: 关键流程节点（账号开始采集、同步完成、N条记录写入）
- **WARNING**: 可恢复的问题（CSV 行解析失败、API 响应部分缺失）
- **ERROR**: 需要关注的错误（账号采集失败、飞书同步失败）
- **CRITICAL**: 系统级崩溃（数据库损坏、配置丢失）

### 格式
```
YYYY-MM-DD HH:MM:SS | LEVEL    | module_name | message
2026-07-10 08:00:15 | INFO     | xhs_browser | 开始采集账号: 主品牌官方号
2026-07-10 08:00:20 | INFO     | xhs_browser |   ✓ 账号概览: 粉丝=12,345, 关注=89
2026-07-10 08:00:35 | INFO     | xhs_browser |   ✓ 笔记数据: 23 篇
```

### 规则
- 进度信息使用 INFO
- 采集到的数据值包含在日志中
- 错误必须包含足够的上下文用于排查

## 错误恢复策略

### 层级恢复
| 层级 | 策略 | 示例 |
|------|------|------|
| API调用 | 指数退避重试 (tenacity, 3次) | 飞书429、网络超时 |
| 账号采集 | 失败继续下一个 | 账号A反爬拦截 → 跳过，处理账号B |
| 采集策略 | 自动降级 (API→Browser→CSV) | CDP连接失败 → 尝试CSV导入 |
| 定时任务 | 失败重试 (3次, 间隔5分钟) | 8:00失败 → 8:05重试 |

## 文件组织

### 模块职责单一
- 每个 `.py` 文件只负责一个明确的职责
- 文件不超过 500 行（超过则拆分）
- 公共接口用 `__all__` 声明

### 配置外部化
- 敏感信息：环境变量（`.env`）
- 可调参数：`config/settings.yaml`
- 账号信息：`config/accounts.yaml`
- 不硬编码任何URL、密钥、阈值

### 测试覆盖
- 核心逻辑必须有单元测试
- Mock 外部依赖（浏览器、飞书API）
- 测试文件镜像 src/ 目录结构
