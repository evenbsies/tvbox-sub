# TVBox 订阅源每日自动抓取

每天北京时间 06:00 自动运行，输出提交到 `tvbox_out/`。

## 两个脚本

| 脚本 | 功能 |
|---|---|
| `tvbox_source_collector.py` | 聚合公开点播配置+采集站深度健康检查(列表→详情→播放地址测速)+每日直播测活 |
| `live_scanner.py` | 全球直播自发现：iptv-org 13国索引 → 测活 → 测速分级 → 同频道保留最快3条 |

## 输出 (`tvbox_out/`)

- `tvbox_merged.json` — 点播/解析/直播合并配置（spider 站所需 jar 见 `spiders` 字段）
- `live_validated.txt` — 每日测活通过的直播频道
- `vod_only.json` — 纯净点播订阅：采集站按播放测速排序，真死的自动下架，无需 jar
- `vod_apis.json` — 采集站清单（数据驱动，加新站只改这个文件）
- `live_global/` — 全球扫描结果：`live_global.txt` / `live_global.m3u`（带台标）/ `scan_report.txt` / `live_history.json`（30天趋势）

## TVBox 订阅地址

把 `<repo>` 换成仓库名：

- 点播+解析：`https://raw.githubusercontent.com/evenbsies/<repo>/main/tvbox_out/tvbox_merged.json`
- 纯净点播（推荐）：`https://raw.githubusercontent.com/evenbsies/<repo>/main/tvbox_out/vod_only.json`
- 直播：`https://raw.githubusercontent.com/evenbsies/<repo>/main/tvbox_out/live_validated.txt`
- 全球直播：`https://raw.githubusercontent.com/evenbsies/<repo>/main/tvbox_out/live_global/live_global.txt`
- 全球直播(m3u)：`https://raw.githubusercontent.com/evenbsies/<repo>/main/tvbox_out/live_global/live_global.m3u`

国内建议把 `raw.githubusercontent.com/evenbsies/<repo>/main` 换成
`cdn.jsdelivr.net/gh/evenbsies/<repo>@main`。

## EPG 节目单

TVBox 直播设置 → EPG 地址填：

```
http://epg.51zmt.top:8000/api/diyp/?ch={name}&date={date}
```

## 自维护 drpy 规则

`drpy/` 目录：规则模板 + 校验器 + 示例规则，详见 `drpy/README.md`。
每日任务自动校验所有规则，报告在 `tvbox_out/drpy_report.txt`。

## 本地手动跑

```bash
python3 tvbox_source_collector.py --out ./tvbox_out
python3 live_scanner.py --out ./tvbox_out/live_global
python3 drpy/validate_drpy.py
# 只扫指定国家: python3 live_scanner.py --countries cn hk tw
```

## 说明

- 只用 Python 标准库，无第三方依赖。
- 关键词黑名单（过滤 bc/博彩类名字）在 `tvbox_source_collector.py` 顶部 `AD_KEYWORDS`，自行增删。
- 烧在视频流里的广告程序无法识别，需人工抽看。
- 部分台有地域限制，从哪跑就只能测出哪能看。
