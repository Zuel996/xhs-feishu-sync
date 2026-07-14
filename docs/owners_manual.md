# xhs-feishu-sync — 使用手册

小红书 → 飞书多维表格 数据自动同步工具，使用手册。

---

## 目录

- [准备工作](#准备工作)
- [首次配置](#首次配置)
- [每日使用](#每日使用)
- [定时自动化](#定时自动化)
- [命令参考](#命令参考)
- [清理数据](#清理数据)
- [故障排查](#故障排查)

---

## 准备工作

| 你需要有 | 说明 |
|----------|------|
| 小红书创作者账号 | 能登录 [creator.xiaohongshu.com](https://creator.xiaohongshu.com) |
| 飞书账号 | 有创建自建应用的权限 |
| Python 3.11+ | 如果还没装：`scripts\setup.bat` 会自动检测 |
| Google Chrome | 浏览器模式采集需要 |

---

## 首次配置

### 1. 安装环境

在项目根目录打开 PowerShell，执行：

```powershell
pip install -e .
```

### 2. 配置飞书凭证

编辑 `.env` 文件（从 `.env.example` 复制一份），填入：

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here
FEISHU_BITABLE_APP_TOKEN=HvqUb97pqaREuXsg97ic3WoUnMf
```

| 变量 | 获取方式 |
|------|----------|
| `FEISHU_APP_ID` | 飞书开放平台 → 自建应用 → 凭证与基础信息 |
| `FEISHU_APP_SECRET` | 同上 |
| `FEISHU_BITABLE_APP_TOKEN` | 多维表格 URL 中 `base/` 后面的那串字符 |

### 3. 授权多维表格

1. 打开你的飞书多维表格
2. 右上角 `...` → `添加文档应用`
3. 搜索你的应用名 → 添加

### 4. 初始化表结构

```powershell
xhs-feishu setup
```

自动在飞书多维表格中创建 4 张数据表（账号概览、笔记数据明细、每日快照、竞品对比）。

### 5. 配置监控账号

编辑 `config\accounts.yaml`，把占位符替换为真实账号：

```yaml
own_accounts:
  - account_id: "my_brand"          # 唯一标识，随便起
    xhs_user_id: "5f3a2b1cxxxxx"    # 小红书用户 ID（个人主页 URL 中获取）
    xhs_username: "你的用户名"
    display_name: "显示名称"         # 飞书表格中显示的名字
    competitor: false
```

如果有竞品需要对比，在 `competitor_accounts` 中添加（`competitor: true`）。

### 6. 验证连接

```powershell
xhs-feishu test-feishu     # 验证飞书连接
xhs-feishu test-collect    # 干跑采集，确认数据源正常
```

---

## 每日使用

### 三步走

**① 启动 Chrome 调试模式**

Win+R 打开运行，粘贴以下命令并回车：

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\chrome-debug-profile" https://creator.xiaohongshu.com
```

在打开的浏览器中确认已登录创作者中心。**这个窗口不要关。**

> 提示：可以把这行命令保存为桌面快捷方式，每次双击即可。

**② 执行采集同步**

打开 PowerShell，进入项目目录：

```powershell
cd C:\Users\LingoAce\Desktop\work\auto
xhs-feishu run
```

等待执行完成，看到 `✓ 完成` 即可。

**③ 查看数据**

打开飞书多维表格，4 张表已自动更新：

| 表名 | 内容 |
|------|------|
| **账号概览** | 粉丝/关注/获赞 当前值 + 日周增量 + 异常标记 |
| **笔记数据明细** | 每篇笔记的浏览/点赞/收藏/评论/分享 + 日增量 |
| **每日快照** | 账号 × 日期的时间序列，追踪历史趋势 |
| **竞品对比** | 横向排名 + 多维度指标对比 |

### 指定日期采集

```powershell
xhs-feishu run --date 2026-07-14
```

---

## 定时自动化

### Windows 任务计划程序

让电脑每天自动跑，不用手动操作。

**前提：** Chrome 调试窗口保持运行（可最小化）。

1. 按 Win+R，输入 `taskschd.msc` 回车
2. 右侧「创建基本任务」
3. 名称：`小红书数据采集`
4. 触发器：**每天**，时间设为 `09:00`
5. 操作：**启动程序**，程序或脚本填：
   ```
   C:\Users\LingoAce\Desktop\work\auto\scripts\daily_run.bat
   ```
6. 完成

### Chrome 保持运行

为了防止 Chrome 意外关闭，可以把启动命令也加入任务计划：

1. 创建另一个任务，触发器设为「**计算机启动时**」
2. 程序或脚本填 Chrome 启动命令：
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\chrome-debug-profile" https://creator.xiaohongshu.com
   ```

> 注意：如果小红书创作者中心长时间未操作，可能需要重新登录。

---

## 命令参考

| 命令 | 用途 |
|------|------|
| `xhs-feishu setup` | 初始化数据库 + 飞书表结构 |
| `xhs-feishu test-feishu` | 验证飞书连接和权限 |
| `xhs-feishu test-collect` | 干跑采集（不写入飞书） |
| `xhs-feishu run` | **核心命令**：采集 → 转换 → 同步 |
| `xhs-feishu run --date 2026-07-14` | 指定日期采集 |
| `xhs-feishu start` | 启动 APScheduler 定时调度 |
| `xhs-feishu status` | 查看最近同步状态 |
| `xhs-feishu clear` | 清理指定账号数据 |

---

## 清理数据

如果某个账号的数据需要从飞书表格中删除：

```powershell
# 先预览（安全，不真正删除）
xhs-feishu clear --account 账号名

# 确认无误后，执行删除
xhs-feishu clear --account 账号名 --confirm
```

会同时清理飞书多维表格和本地 SQLite 中的数据。

---

## 故障排查

### Chrome 连接失败

```
无法连接到 Chrome CDP (http://localhost:9222)
```

**解决：**
1. 确认 Chrome 调试窗口已启动（Win+R 粘贴启动命令）
2. 在已打开的 Chrome 窗口中确认已登录 `creator.xiaohongshu.com`
3. 在浏览器地址栏访问 `http://localhost:9222/json/version`，如果显示 JSON 数据说明端口正常

### 飞书 Token 获取失败

```
获取飞书 tenant_access_token 失败
```

**解决：** 检查 `.env` 中的 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 是否正确。

### 飞书写入权限 91403 Forbidden

**解决：**
1. 飞书开放平台 → 应用发布 → 确认应用已发布
2. 飞书多维表格 → `...` → `添加文档应用` → 添加你的应用
3. 确认权限包含 `bitable:app`

### 字段写入失败

**解决：** 运行 `xhs-feishu setup` 重新建表（幂等，不会重复创建）。

### 笔记数据为空

**解决：**
1. 检查 Chrome 是否已登录创作者中心
2. 运行 `xhs-feishu test-collect` 查看具体失败原因
3. 如果浏览器模式一直不成功，可以改用 CSV 模式（下一条）

### 改用 CSV 模式（不需要 Chrome）

如果浏览器模式遇到问题，可以降级到 CSV 文件导入：

1. 编辑 `config\settings.yaml`，将 `strategy` 改为 `"csv"`
2. 在创作者中心手动导出 Excel（数据中心 → 笔记数据 → 导出）
3. 将导出的文件放入 `data\csv_imports\<account_id>\`
4. 运行 `xhs-feishu run`

> CSV 模式不含每篇笔记的实时互动数据，仅能做基础统计。
