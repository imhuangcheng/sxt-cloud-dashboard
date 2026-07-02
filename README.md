# SXT Cloud Dashboard

纯云端运行的 SXT 双周期监控仪表板。

## 功能边界

- 前端页面部署在 Netlify。
- 云端扫描由 GitHub Actions 定时触发。
- 股票池维护在 `config/watchlist.json`。
- 同时计算日K和15分钟K的 SXT。
- 仅当 `日K SXT = 2` 且 `15分钟K SXT = 2` 时触发 Server 酱通知。
- 运行结果写入 `data/latest_signals.json`，通知去重记录写入 `data/alert_history.json`。
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

编辑 `config/watchlist.json`：

```json
[
  {
    "code": "300607",
    "name": "拓斯达",
    "market": "sz"
  }
]
```

`market` 可省略。程序会按代码自动判断：`6` 开头为 `sh`，`0`、`2`、`3` 开头为 `sz`，`8`、`4` 开头暂标记为不支持。

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
```

因此 GitHub Actions 每次提交新的 `data/latest_signals.json` 后，Netlify 可以展示最新结果。

## 重要文件

- `scripts/fetch_data.py`：获取腾讯日K/15分钟K，东方财富作为兜底。
- `scripts/calc_sxt.py`：计算 SXT 指标。
- `scripts/notifier.py`：Server 酱通知和去重记录。
- `scripts/run.py`：云端扫描主入口。
- `.github/workflows/monitor.yml`：GitHub Actions 定时任务。
- `frontend/index.html`：Netlify 页面。
