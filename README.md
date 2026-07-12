# SXT Cloud Dashboard

纯云端运行的 SXT 双周期监控仪表板。

## 功能边界

- 前端页面部署在 Netlify。
- 云端扫描由 GitHub Actions 定时触发。
- 股票池维护在 `config/watchlist.json`。
- 同时计算日K和15分钟K的 SXT。
- 仅当 `日K SXT = 2` 且 `15分钟K SXT = 2` 时触发 Server 酱通知。
- 运行结果写入 `data/latest_signals.json`，并同步写入 `data/latest.json` 作为排查用别名；通知去重记录写入 `data/alert_history.json`。
- 不依赖本地电脑、Windows、虚拟机、通达信或 Stage 8 Lite。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/run.py
```

没有配置 `SERVERCHAN_SEND_KEY` 时，程序不会崩溃；满足通知条件时会打印 warning 并跳过推送。

需要在非交易时间验证完整链路时，可以临时使用：

```bash
SXT_FORCE_SCAN=true python scripts/run.py
```

## 配置股票池

股票池现在以 `config/watchlist_groups.json` 为主配置，第一列“汇总”由所有分组去重生成；程序会同步维护旧格式 `config/watchlist.json`，因此扫描逻辑仍兼容原配置。旧项目首次运行时会从 `watchlist.json` 迁移到“默认分组”，并创建 `watchlist.json.bak` 备份。

网页支持新增、重命名、删除分组，以及在分组内增删股票。保存时会通过 Netlify Function 同步提交分组配置和兼容旧股票池；若兼容文件更新失败，页面会明确提示部分成功。

手动配置时编辑 `config/watchlist_groups.json`：

```json
{
  "version": 1,
  "groups": [
    { "id": "default", "name": "默认分组", "symbols": ["300607"] }
  ]
}
```

程序会按代码自动判断市场：`6` 开头为 `sh`，`0`、`2`、`3` 开头为 `sz`，`8`、`4` 开头暂标记为不支持。v1.1 仍兼容旧的对象数组格式，但网页股票池管理会保存为上面的统一格式。

## SXT Cloud v1.1

v1.1 新增网页股票池管理、云端运行状态和个股跳转到 SXT 双周期项目。

### Netlify 环境变量

网页保存股票池会调用 `netlify/functions/watchlist.js`，由 Netlify Function 通过 GitHub API 修改固定文件 `config/watchlist.json`。请在 Netlify 站点环境变量中配置：

```text
GITHUB_TOKEN=你的 GitHub fine-grained token
GITHUB_OWNER=仓库所有者
GITHUB_REPO=仓库名
GITHUB_BRANCH=main
```

如果仓库默认分支不是 `main`，请把 `GITHUB_BRANCH` 改成真实分支名。Token 只放在 Netlify 环境变量中，不要写入前端或提交到仓库。
Token 需要允许读取/写入 Contents，并允许触发 Actions workflow dispatch；页面“刷新”按钮会触发本项目 GitHub Actions 的 `force_scan=true`。

### GitHub Actions

`.github/workflows/monitor.yml` 已包含：

```yaml
permissions:
  contents: write
```

每次监控运行后会提交 `data/latest_signals.json`、`data/latest.json`、`data/alert_history.json` 和 `data/status.json`。即使没有触发信号或 K 线时间没有前进，也会更新 `status.json` 的 `last_scan_time`、`next_scan_time` 和 `message`。如果监控步骤失败，Actions 会写入一份 `workflow=failed` 的 `data/status.json`，供首页状态卡片展示。

### 本地验证

```bash
SXT_FORCE_SCAN=true python scripts/run.py
python scripts/write_status.py
```

前端可直接打开 `frontend/index.html` 验证静态展示；股票池保存功能需要部署到 Netlify 并配置上面的 GitHub 环境变量后验证。

### 回滚

如需回滚 v1.1，可恢复以下文件到升级前版本：`frontend/index.html`、`scripts/run.py`、`scripts/fetch_data.py`、`.github/workflows/monitor.yml`、`config/watchlist.json`，并删除 `netlify/functions/watchlist.js`、`scripts/write_status.py`、`.env.example`、`data/status.json`。

## Server 酱

真实 sendkey 不写入仓库。请在 GitHub 仓库的 Secrets 中新增：

```text
SERVERCHAN_SEND_KEY
```

值填写你的 Server 酱 sendkey。

## 前端

Netlify 读取 `netlify.toml` 后会发布整个项目目录，并把根路径指向 `frontend/index.html`。页面读取：

```text
../data/latest_signals.json
../data/latest.json
../data/status.json
```

因此 GitHub Actions 每次提交新的数据文件后，Netlify 可以展示最新结果；前端读取 JSON 时会追加时间戳参数，避免读取旧缓存。

## 重要文件

- `scripts/fetch_data.py`：按 `simonlin1212/a-stock-data` 的行情层取数，使用腾讯日K/15分钟K和腾讯实时行情名称。
- `scripts/calc_sxt.py`：计算 SXT 指标。
- `scripts/notifier.py`：Server 酱通知和去重记录。
- `scripts/run.py`：云端扫描主入口。
- `.github/workflows/monitor.yml`：GitHub Actions 定时任务。
- `frontend/index.html`：Netlify 页面。
