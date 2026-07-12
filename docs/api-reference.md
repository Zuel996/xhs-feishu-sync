# API 参考文档

## 飞书开放平台

### 基础信息
- 官方文档: https://open.feishu.cn
- 鉴权方式: tenant_access_token（2小时有效期）
- SDK: `lark-oapi` (Python)

### Bitable API 关键端点

| 操作 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 获取token | POST | `/open-apis/auth/v3/tenant_access_token/internal` | 应用身份鉴权 |
| 列出数据表 | GET | `/open-apis/bitable/v1/apps/{app_token}/tables` | 获取所有表 |
| 创建数据表 | POST | `/open-apis/bitable/v1/apps/{app_token}/tables` | 新建表 |
| 列出记录 | GET | `/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records` | 分页查询 |
| 批量创建 | POST | `/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create` | 最多500条/次 |
| 批量更新 | POST | `/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update` | 最多500条/次 |

### 字段类型映射

| Bitable 类型 | type 代码 | Python 类型 |
|-------------|----------|-------------|
| 文本 (Text) | 1 | `str` |
| 数字 (Number) | 2 | `int` |
| 单选 (SingleSelect) | 3 | `str` |
| 多选 (MultiSelect) | 4 | `list[str]` |
| 日期 (DateTime) | 5 | `str` (isoformat) |
| 复选框 (Checkbox) | 7 | `bool` |
| 人员 (User) | 11 | `list[dict]` |
| 链接 (URL) | 15 | `dict` (含 link + text) |
| 附件 (Attachment) | 17 | `list[dict]` |

### 限制
- 单次列出记录: 最多 500 条
- 批量操作: 全成功或全失败（无部分结果）
- 单表行数: 20,000 行（可申请扩容）
- 不支持写入: 公式字段、查找引用字段、双向关联字段

---

## 小红书开放平台 (未来使用)

### 基础信息
- 官方文档: https://open.xiaohongshu.com
- 鉴权方式: OAuth2.0 (access_token, 2小时有效期)
- 申请条件: 企业资质 + 专业号蓝V认证
- 速率限制: 200次/分钟 (默认), 可申请至500次/分钟

### 关键端点（v4）

| 操作 | 路径 | 说明 |
|------|------|------|
| 获取token | `/oauth2/access_token` | client_credentials 授权 |
| 用户信息 | `/api/sns/v1/user/profile` | 粉丝数、关注数等 |
| 笔记列表 | `/api/sns/v1/user/notes` | 账号下笔记列表 |
| 笔记详情 | `/api/sns/v1/note/detail` | 单篇笔记互动数据 |

---

## 小红书浏览器采集 (CDP模式)

### Chrome DevTools Protocol
- 端口: 9222 (默认)
- 启动命令: `chrome.exe --remote-debugging-port=9222`
- 连接方式: `playwright.chromium.connect_over_cdp("http://localhost:9222")`

### 关键页面 URL
- 首页: `https://www.xiaohongshu.com/explore`
- 用户主页: `https://www.xiaohongshu.com/user/profile/{user_id}`
- 笔记详情: `https://www.xiaohongshu.com/explore/{note_id}`

### API 拦截模式
- `**/api/sns/web/v1/user/otherinfo**` — 用户信息接口
- `**/api/sns/web/v1/note/feed**` — 笔记列表接口
- `**/api/sns/web/v1/feed**` — 笔记详情接口

### 降级数据源
- `window.__INITIAL_STATE__` — 页面嵌入的初始状态 JSON
- ⚠️ 已知 Bug: `undefined` 值被替换为 `""`（空字符串），需要正则修复

---

## 内部 API (模块间接口)

### 采集器接口 (BaseCollector)
```python
class BaseCollector(ABC):
    async def collect_account_profile(account: AccountInfo) -> AccountProfile
    async def collect_notes_data(account: AccountInfo, target_date: date | None) -> list[NoteMetrics]
    async def collect_all(account: AccountInfo, target_date: date | None) -> CollectResult
    async def validate_connection() -> bool
```

### 数据模型
```python
class AccountProfile(BaseModel):
    account_id: str
    xhs_user_id: str
    username: str
    follower_count: int
    following_count: int
    total_likes: int
    total_collections: int

class NoteMetrics(BaseModel):
    note_id: str
    account_id: str
    title: str
    note_type: str  # "image" | "video"
    publish_date: date | None
    url: str
    views: int
    likes: int
    favorites: int
    comments: int
    shares: int
```

### 同步引擎接口 (SyncEngine)
```python
class SyncEngine:
    def sync_account_summary(trends, competitor_rank, rank_change) -> int
    def sync_note_metrics(notes: list[tuple[NoteInfo, NoteSnapshot, NoteTrends]]) -> int
    def sync_daily_snapshot(snapshot: AccountSnapshot) -> int
    def sync_competitor_comparison(comparison: ComparisonTable) -> int
    def sync_full_pipeline(...) -> dict[str, int]
```

### Pipeline 入口
```python
async def run_pipeline(target_date: date | None = None) -> dict
# 返回: {"total": N, "success": N, "failed": N, "details": [...]}
```
