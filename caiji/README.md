# 自建采集聚合服务

不再直调别人的采集站 API，自己跑一个聚合服务：每天把 `vod_apis.json` 里的采集站拉一遍，
去重合并成多线路、按测速排序、缓存进 SQLite，对外提供 applecms 兼容接口。
单个采集站挂了，缓存还顶得住；TVBox 里只填一个地址。

## 文件

- `aggregator.py` — 同步器：拉取 → 去重入库
- `server.py` — API 服务：applecms 兼容接口
- 两个都是标准库，无第三方依赖

## 跑起来

```bash
# 1. 同步（增量：各站近24小时更新；--full 全量回填）
python3 aggregator.py
# 2. 启动 API（默认 8080 端口）
python3 server.py --port 8080
```

接口（applecms 兼容）：

- `/?ac=videolist&pg=1` 最新
- `/?ac=videolist&wd=关键词` 搜索
- `/?ac=videolist&t=电影` 分类
- `/?ac=detail&ids=123` 详情（含 `vod_play_from`/`vod_play_url` 多线路）
- `/` 状态页（各源测速、同步时间）

## TVBox 配置

```json
{"key": "my_caiji", "name": "自建聚合", "type": 1,
 "api": "http://你的服务器IP:8080/", "searchable": 1, "quickSearch": 1, "filterable": 1}
```

## 部署

- **VPS**：systemd 跑 `server.py`，cron 每天跑一次 `aggregator.py`
- **家里**：同上，TVBox 在外网访问需要公网 IP 或内网穿透
- 数据在 `caiji.db`，备份它就行
