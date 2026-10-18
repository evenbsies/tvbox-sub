#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 订阅源聚合器
==================
抓取公开上游 -> 关键词过滤(含 bc 广告等低质源) -> 可达性校验 -> 输出合并订阅。

用法:
    python3 tvbox_source_collector.py                    # 全量: 抓取 + 校验
    python3 tvbox_source_collector.py --no-check         # 只抓取合并, 跳过可达性校验
    python3 tvbox_source_collector.py --live-limit 500   # 只校验前 500 个直播频道
    python3 tvbox_source_collector.py --out ./out         # 指定输出目录

输出 (默认 ./tvbox_out/):
    tvbox_merged.json   合并后的 TVBox 订阅配置 (sites / parses / lives)
    live_validated.txt  校验通过的直播频道 (txt 格式, 可直接填进 TVBox 做直播源)
    report.txt          本次抓取统计

说明:
  - 只用标准库, 无第三方依赖。
  - "bc 广告" 无法靠程序 100% 识别(广告是烧在视频流里的):
    脚本做三层过滤: ①名称关键词黑名单 ②上游来源标注(方便你追溯哪个上游质量差)
    ③可达性校验。最终是否含广告, 仍需人工抽看。
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------- 配置区 ---

# 点播源上游: 公开的 TVBox JSON 配置 (名称, raw 地址)
UPSTREAM_CONFIGS = [
    ("dxawi",  "https://dxawi.github.io/0/0.json"),
    ("jundie", "http://home.jundie.top:81/top98.json"),
]

# 直播源上游: txt / m3u 频道列表 (名称, raw 地址)
UPSTREAM_LIVES = [
    ("iptv-api", "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.txt"),
]

# 点播采集站 (applecms API, type=1)。脚本会逐个验证 ?ac=videolist, 只收录活着的
VOD_APIS = [
    ("暴风资源", "https://bfzyapi.com/api.php/provide/vod"),
    ("ikun资源", "https://ikunzyapi.com/api.php/provide/vod/from/ikm3u8/"),
    ("无尽资源", "https://api.wujinapi.com/api.php/provide/vod/from/wjm3u8/at/json"),
    ("魔都资源", "https://caiji.moduapi.cc/api.php/provide/vod/at/json"),
]

# 名称关键词黑名单: 命中则丢弃 (bc/博彩/色情/跑马灯广告源多用这类名字, 可自行增删)
AD_KEYWORDS = [
    "博彩", "菠菜", "棋牌", "彩票", "赌场", "娱乐城", "体育投注", "真人视讯",
    "六合彩", "时时彩", "百家乐", "老虎机", "捕鱼", "电子游艺",
    "bc", "bclc", "赌博", "赌球", "外围", "跑马灯",
    "皇冠", "威尼斯人", "金沙", "葡京", "永利", "美高梅",
    "成人", "午夜", "激情", "少妇",
]

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"}
FETCH_TIMEOUT = 20
CHECK_TIMEOUT = 8
CHECK_WORKERS = 24

# ---------------------------------------------------------------- 抓取 ---

def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2)
    raise last

def parse_tvbox_config(raw, src, base_url):
    """解析 TVBox JSON 配置, 返回 (sites, parses, lives, spider_jar)。"""
    from urllib.parse import urljoin
    d = json.loads(raw.decode("utf-8-sig"))
    sites, parses, lives = [], [], []
    for s in d.get("sites", []) or []:
        if isinstance(s, dict) and s.get("name"):
            s = dict(s); s["_src"] = src; sites.append(s)
    for p in d.get("parses", []) or []:
        if isinstance(p, dict) and p.get("url"):
            p = dict(p); p["_src"] = src; parses.append(p)
    for lv in d.get("lives", []) or []:
        if isinstance(lv, dict) and (lv.get("url") or lv.get("name")):
            lv = dict(lv); lv["_src"] = src; lives.append(lv)
    spider = d.get("spider")
    spider = urljoin(base_url, spider) if spider else None
    return sites, parses, lives, spider

def parse_live_txt(text, src):
    """解析 txt 格式直播列表: '#genre#' 分组 + '名称,url'。"""
    chans, group = [], "未分组"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "#genre#" in line:
            group = line.split(",")[0].strip(" #🕘️📺") or "未分组"
            continue
        if line.startswith("#"):
            continue
        if ",http" in line or ",rtmp" in line or ",rtsp" in line:
            name, url = line.split(",", 1)
            name, url = name.strip(), url.strip()
            if name and url.startswith(("http", "rtmp", "rtsp")):
                chans.append({"group": group, "name": name, "url": url, "_src": src})
    return chans

def parse_m3u(text, src):
    chans, group, pending = [], "未分组", None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            m = re.search(r'group-title="([^"]*)"', line)
            if m: group = m.group(1) or group
            pending = line.rsplit(",", 1)[-1].strip() or "未知"
        elif line and not line.startswith("#") and pending:
            if line.startswith(("http", "rtmp", "rtsp")):
                chans.append({"group": group, "name": pending, "url": line, "_src": src})
            pending = None
    return chans

# ---------------------------------------------------------------- 过滤 ---

def is_ad_junk(name):
    low = name.lower()
    return any(kw.lower() in low for kw in AD_KEYWORDS)

# ---------------------------------------------------------------- 校验 ---

def check_stream(url):
    """校验直播流可达: 取前 1KB, 看是不是 m3u8 / 正常响应。返回 (ok, 耗时ms)。"""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as r:
            body = r.read(1024)
            ct = r.headers.get("Content-Type", "")
            ok = r.status in (200, 206) and (
                "mpegurl" in ct or "octet-stream" in ct
                or body.startswith(b"#EXTM3U") or url.lower().endswith(".m3u8"))
            return ok, int((time.time() - t0) * 1000)
    except Exception:
        return False, -1

def check_http_api(url):
    for _ in range(2):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as r:
                if r.status == 200:
                    return True, int((time.time() - t0) * 1000)
        except Exception:
            time.sleep(1)
    return False, -1

def validate_all(items, checker, limit=0, label=""):
    items = items[:limit] if limit else items
    ok_items = []
    with cf.ThreadPoolExecutor(max_workers=CHECK_WORKERS) as ex:
        futs = {ex.submit(checker, it["url"]): it for it in items if it.get("url")}
        done = 0
        for f in cf.as_completed(futs):
            it, done = futs[f], done + 1
            try:
                ok, ms = f.result()
            except Exception:
                ok, ms = False, -1
            if ok:
                it["_ms"] = ms; ok_items.append(it)
            if done % 200 == 0:
                print(f"  [{label}] {done}/{len(futs)} ...", flush=True)
    return ok_items

# ---------------------------------------------------------------- 主流程 ---

def main():
    ap = argparse.ArgumentParser(description="TVBox 订阅源聚合器")
    ap.add_argument("--no-check", action="store_true", help="跳过可达性校验")
    ap.add_argument("--live-limit", type=int, default=0, help="只校验前 N 个直播频道 (0=全部)")
    ap.add_argument("--out", default="./tvbox_out", help="输出目录")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    rep = []

    # 1. 抓点播配置
    all_sites, all_parses, all_lives_cfg, spiders = [], [], [], {}
    for name, url in UPSTREAM_CONFIGS:
        try:
            s, p, lv, spider = parse_tvbox_config(fetch(url), name, url)
            all_sites += s; all_parses += p; all_lives_cfg += lv
            if spider: spiders[name] = spider
            rep.append(f"[config] {name}: sites={len(s)} parses={len(p)} lives={len(lv)}")
            print(rep[-1], flush=True)
        except Exception as e:
            rep.append(f"[config] {name}: 抓取失败 {str(e)[:80]}"); print(rep[-1], flush=True)

    # 1b. 验证采集站 API, 活着的做成 type=1 点播源
    for name, api in VOD_APIS:
        try:
            d = json.loads(fetch(api.rstrip("/") + "?ac=videolist").decode("utf-8", errors="ignore"))
            if d.get("code") == 1 and d.get("list"):
                all_sites.append({
                    "key": f"caiji_{len(all_sites)}", "name": name, "type": 1,
                    "api": api, "searchable": 1, "quickSearch": 1, "filterable": 1,
                    "_src": "vod_api", "_check": f'ok({d.get("total", "?")}部)'})
                rep.append(f"[vod] {name}: 可用 (共 {d.get('total', '?')} 部)")
            else:
                rep.append(f"[vod] {name}: 返回异常, 跳过")
        except Exception as e:
            rep.append(f"[vod] {name}: 不可用 {str(e)[:50]}")
        print(rep[-1], flush=True)

    # 2. 抓直播列表
    all_chans = []
    for name, url in UPSTREAM_LIVES:
        try:
            raw = fetch(url); text = raw.decode("utf-8-sig", errors="ignore")
            chans = parse_m3u(text, name) if text.lstrip().startswith("#EXTM3U") else parse_live_txt(text, name)
            all_chans += chans
            rep.append(f"[live] {name}: 频道={len(chans)}"); print(rep[-1], flush=True)
        except Exception as e:
            rep.append(f"[live] {name}: 抓取失败 {str(e)[:80]}"); print(rep[-1], flush=True)

    # 3. 关键词过滤
    def filt(items):
        kept, dropped = [], 0
        for it in items:
            if is_ad_junk(it.get("name", "")): dropped += 1
            else: kept.append(it)
        return kept, dropped
    all_sites, d1 = filt(all_sites)
    all_chans, d2 = filt(all_chans)
    rep.append(f"[filter] 关键词过滤掉: 点播 {d1} 个, 直播 {d2} 个"); print(rep[-1], flush=True)

    # 4. 去重
    def dedup(items, keyfn):
        seen, out = set(), []
        for it in items:
            k = keyfn(it)
            if k not in seen: seen.add(k); out.append(it)
        return out
    all_sites = dedup(all_sites, lambda s: (s.get("key") or s.get("name"), s.get("api")))
    all_parses = dedup(all_parses, lambda p: p.get("url"))
    all_chans = dedup(all_chans, lambda c: (c.get("name"), c.get("url")))
    rep.append(f"[dedup] 去重后: 点播 {len(all_sites)} 个, 解析 {len(all_parses)} 条, 直播 {len(all_chans)} 个")
    print(rep[-1], flush=True)

    # 5. 可达性校验 (只打标, 不丢弃: _check=ok/fail/unvalidated-spider)
    valid_chans = all_chans
    if not args.no_check:
        print(f"[check] 校验直播频道 (limit={args.live_limit or '全部'}) ...", flush=True)
        valid_chans = validate_all(all_chans, check_stream, args.live_limit, "live")
        rep.append(f"[check] 直播可达: {len(valid_chans)}/{len(all_chans)}"); print(rep[-1], flush=True)

        http_sites = [s for s in all_sites
                      if isinstance(s.get("api"), str) and s["api"].startswith("http")
                      and not str(s.get("_check", "")).startswith("ok(")]
        print(f"[check] 校验点播 http 接口 ({len(http_sites)} 个) ...", flush=True)
        ok_ids = {id(s) for s in validate_all(http_sites, check_http_api, label="vod")}
        for s in all_sites:
            api = s.get("api")
            if isinstance(api, str) and api.startswith("http"):
                s["_check"] = "ok" if id(s) in ok_ids else "fail"
            else:
                s["_check"] = "unvalidated-spider"
        rep.append(f"[check] 点播 http 接口可达: {len(ok_ids)}/{len(http_sites)}")
        print(rep[-1], flush=True)
    else:
        for s in all_sites: s["_check"] = "skipped"

    # 6. 输出 (_src/_check 保留: TVBox 会忽略未知字段, 方便追溯来源与质量)
    for it in all_parses + all_lives_cfg:
        it.pop("_src", None); it.pop("_ms", None)
    merged = {"spiders": spiders, "sites": all_sites,
              "parses": all_parses, "lives": all_lives_cfg}
    with open(os.path.join(args.out, "tvbox_merged.json"), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    # 纯净点播订阅: 仅自验证采集站 + 解析, 无需 jar, 开箱即用
    clean = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}
    vod_only = {"sites": [clean(s) for s in all_sites if s.get("_src") == "vod_api"],
                "parses": [clean(p) for p in all_parses]}
    with open(os.path.join(args.out, "vod_only.json"), "w", encoding="utf-8") as f:
        json.dump(vod_only, f, ensure_ascii=False, indent=1)

    with open(os.path.join(args.out, "live_validated.txt"), "w", encoding="utf-8") as f:
        last_group = None
        for c in valid_chans:
            if c["group"] != last_group:
                f.write(f"\n{c['group']},#genre#\n"); last_group = c["group"]
            f.write(f"{c['name']},{c['url']}\n")

    with open(os.path.join(args.out, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")

    print("\n==== 汇总 ====")
    print("\n".join(rep))
    print(f"\n完成: {args.out}/tvbox_merged.json / live_validated.txt / report.txt")

if __name__ == "__main__":
    main()
