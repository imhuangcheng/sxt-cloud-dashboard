# 部署说明

## 1. 创建 GitHub 仓库

1. 在 GitHub 创建一个新仓库。
2. 把 `sxt-cloud-dashboard` 目录推送到该仓库。
3. 确认仓库中包含 `.github/workflows/monitor.yml`。

如果从本地命令行推送，可以在 `sxt-cloud-dashboard` 目录执行：

```bash
git init
git add .
git commit -m "Initial SXT cloud dashboard"
git branch -M main
git remote add origin https://github.com/你的用户名/sxt-cloud-dashboard.git
git push -u origin main
```

## 2. 配置 Server 酱密钥

在 GitHub 仓库页面进入：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

新增：

```text
Name: SERVERCHAN_SEND_KEY
Value: 你的 Server 酱 sendkey
```

不要把真实 sendkey 写入 `config/serverchan.json` 或其他仓库文件。

Netlify 侧的 `GITHUB_TOKEN` 需要允许读取/写入 Contents，并允许触发 Actions workflow dispatch；页面“刷新”按钮会触发本项目 GitHub Actions 的 `force_scan=true`。

## 3. 启用 GitHub Actions

进入仓库的 `Actions` 页面，允许 workflow 运行。定时任务使用 UTC 时间：

```text
*/15 1-3,5-7 * * 1-5
```

这覆盖 A 股交易日的主要交易时段。脚本内部还会按 `config/config.json` 的 Asia/Shanghai 交易时段再次判断，非交易时段会正常退出。

## 4. 手动触发一次扫描

进入：

```text
Actions -> SXT cloud monitor -> Run workflow
```

如果当前不是交易时段，程序会写入跳过说明。如果是交易时段，会获取股票池中每只股票的日K和15分钟K并更新 JSON。

验收完整链路时，可以在手动触发页面把 `force_scan` 设为 `true`，这样即使不在交易时段也会执行实际取数和计算。

## 5. 部署 Netlify

1. 在 Netlify 选择从 GitHub 导入该仓库。
2. Build command 留空。
3. Publish directory 使用项目根目录，或直接让 Netlify 读取 `netlify.toml`。
4. 部署后访问站点根路径即可打开 `frontend/index.html`。

页面会读取：

```text
/data/latest_signals.json
```

## 6. 修改股票池

编辑 `config/watchlist.json` 后提交到 GitHub。下次 GitHub Actions 运行时会自动按新股票池扫描。

支持字段：

```json
{
  "code": "300607",
  "name": "拓斯达",
  "market": "sz"
}
```

`name` 和 `market` 可以省略；`market` 省略时按代码前缀自动判断。

## 7. 常见问题

### 没有收到 Server 酱通知

检查 `SERVERCHAN_SEND_KEY` 是否配置在 GitHub Actions Secret 中。还要确认同一只股票同时满足 `日K SXT = 2` 和 `15分钟K SXT = 2`。

### Actions 运行了但没有提交

如果 `data/latest_signals.json` 和 `data/alert_history.json` 没有变化，workflow 会直接退出，不创建新提交。

### 非交易时间运行

这是正常情况。脚本会更新 `data/latest_signals.json` 的说明字段，并跳过实际扫描。

### 某只股票失败

单只股票失败会写入该股票的 `error` 字段，不会影响其他股票继续扫描。

### 行情源连接不稳定

程序按 `simonlin1212/a-stock-data` 的行情层取数，使用腾讯日K/15分钟K和腾讯实时行情名称。单只股票失败会把错误写入对应股票，不影响其他股票继续扫描。
