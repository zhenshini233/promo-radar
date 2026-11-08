# 部署（单用户 / 每日访问）

> 目标：推一次，云端每天自动更新，你只负责打开页面看。
> 不做推送通知。

## 前提

- 仓库：`github.com/zhenshini233/promo-radar`
- Pages：public 仓库免费；private 仓库需要 Pro 才能开 Pages
- Actions：私有仓库每月有免费分钟数，本工作流约 3–5 分钟/天

## 1. 推主分支

```powershell
git push origin main
```

## 2. 把本地库作为种子推到 data 分支

否则云端首轮从空库抓 366 页，容易撞 25 分钟超时。

```powershell
python -c "import sqlite3;c=sqlite3.connect('data/radar.db');c.execute('PRAGMA wal_checkpoint(TRUNCATE)');c.close()"
$tmp="$env:TEMP\radar-data"; New-Item -ItemType Directory -Force $tmp | Out-Null
Copy-Item data/radar.db "$tmp\radar.db"
Push-Location $tmp
git init -q; git checkout -q -b data
git add radar.db; git commit -q -m "seed radar db"
git push --force https://github.com/zhenshini233/promo-radar.git data
Pop-Location
```

## 3. 开 Pages

仓库 Settings → Pages → Source 选 `gh-pages`，目录 `/ (root)`。

首次需要工作流跑过一次，`gh-pages` 分支才会存在。

## 4. 手动跑一次

Actions → radar → Run workflow。

检查：

- `Run radar` 成功（采集 + 建站）
- `Rebuild entities` 成功（宇宙 → 标注 → Provider → Offer → 重发站点）
- `Persist database to data branch` 成功
- `Deploy dashboard to GitHub Pages` 成功

## 5. 验收

1. 打开 `https://zhenshini233.github.io/promo-radar/`
2. 首页显示：今天新增 / 最近 7 天 / 本周漏抓
3. 活动页每条能点回来源
4. 厂商页 370 家，可查最近抓取
5. 次日 UTC 02:37 自动更新，无需操作

## 6. 回滚

- 站点：Actions 里重跑上一次成功的 workflow；
- 数据库：`data` 分支只保留最新快照，回滚需从本地备份
  `data/backup/radar-pre-provider-import.db` 恢复后重新推送；
- 代码：`git revert <commit>`。

## 7. 已知限制（不阻塞）

- 推送通知未启用（按需求关闭）；
- 反馈与核实写入只在本地 `radar serve` 可用，静态站只展示核实状态；
- 32 条无官网、2 个未关联来源站、1 个 Wandb 域名冲突仍待处理。