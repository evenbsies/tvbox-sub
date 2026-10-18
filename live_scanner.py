#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全球直播源自发现扫描器 v2
==========================
从 iptv-org 的全球公开索引按国家拉取种子 -> 测活 -> 测速分级 ->
同频道保留最快 3 条线路 -> 输出 txt/m3u -> 可用性日报(含趋势)。

用法:
    python3 live_scanner.py                        # 扫描 COUNTRIES 里的国家
    python3 live_scanner.py --countries cn hk tw   # 只扫指定国家(小写 ISO 代码)
    python3 live_scanner.py --out ./live_out        # 指定输出目录
    python3 live_scanner.py --no-check              # 只拉取不测活(调试用)
    python3 live_scanner.py --lines 2               # 同频道保留几条线路(默认3)

输出:
    live_global.txt   按"国家-分类"分组的可用频道, TVBox 直播源直接用
    live_global.m3u   同上, 带台标(tvg-logo)与频道ID, EPG 匹配用
    scan_report.txt   各国统计 + 新增/失效趋势
    live_history.json 近30天可用URL集合, 用于算趋势(自动提交)

EPG:
    TVBox 直播设置里填 EPG 地址即可按频道名匹配节目单:
        http://epg.51zmt.top:8000/api/diyp/?ch={name}&date={date}

说明:
  - 只用标准库, 无第三方依赖。
  - 部分台有地域限制, 从哪里跑就只能测出哪里能看的, 正常。
  - 局域网组播源扫描需跑在家庭网络内, 云上收不到组播, 本脚本不做。
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import time
import urllib.request

# ---------------------------------------------------------------- 配置 ---

COUNTRIES = [
    "cn", "hk", "tw", "mo",
    "us", "uk", "ca", "au",
    "jp", "kr", "sg",
    "de", "fr",
]

BASE = "https://iptv-org.github.io/iptv/countries/{code}.m3u"
EPG_URL = "http://epg.51zmt.top:8000/api/diyp/?ch={name}&date={date}"
UA_DEFAULT = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"
FETCH_TIMEOUT = 20
CHECK_TIMEOUT = 10
SPEED_BYTES = 512 * 1024   # 测速最多下多少
SPEED_CAP_S = 6            # 测速最多几秒
CHECK_WORKERS = 24
HISTORY_DAYS = 30

# ---------------------------------------------------------------- 抓取 ---

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA_DEFAULT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        return r.read().decode("utf-8", errors="ignore")

def parse_m3u(text, country):
    chans, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            cur = {
                "country": country,
                "name": line.rsplit(",", 1)[-1].strip() or "未知",
                "group": (re.search(r'group-title="([^"]*)"', line) or [None, "综合"])[1],
                "tvg_id": (re.search(r'tvg-id="([^"]*)"', line) or [None, ""])[1],
                "logo": (re.search(r'tvg-logo="([^"]*)"', line) or [None, ""])[1],
                "ua": (re.match(r"#EXTVLCOPT:http-user-agent=(.+)", line) or [None, None])[1],
            }
            # UA 可能在下一行的 EXTVLCOPT
        elif line.startswith("#EXTVLCOPT:") and cur:
            m = re.match(r"#EXTVLCOPT:http-user-agent=(.+)", line)
            if m: cur["ua"] = m.group(1).strip()
        elif line and not line.startswith("#") and cur:
            if line.startswith(("http", "rtmp", "rtsp")):
                cur["url"] = line
                chans.append(cur)
            cur = None
    return chans

# ---------------------------------------------------------------- 测活+测速 ---

def check_stream(ch):
    """返回 (ok, kbps)。先取头 2KB 验格式, 通过再测速。"""
    headers = {"User-Agent": ch["ua"] or UA_DEFAULT, "Range": "bytes=0-2047"}
    try:
        req = urllib.request.Request(ch["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as r:
            if r.status not in (200, 206):
                return False, 0
            ct = r.headers.get("Content-Type", "").lower()
            body = r.read(2048)
            if body.lstrip().startswith(b"<"):
                return False, 0
            if not ("mpegurl" in ct or "mpegts" in ct or "video/" in ct
                    or "octet-stream" in ct or body.startswith(b"#EXTM3U")):
                return False, 0
    except Exception:
        return False, 0
    # 测速: 下一段算 KB/s
    kbps, n, t0 = 0, 0, time.time()
    try:
        req = urllib.request.Request(ch["url"], headers={"User-Agent": ch["ua"] or UA_DEFAULT})
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as r:
            if r.status != 200:
                return True, 0
            while n < SPEED_BYTES and time.time() - t0 < SPEED_CAP_S:
                chunk = r.read(65536)
                if not chunk:
                    break
                n += len(chunk)
        dt = time.time() - t0
        kbps = int(n / 1024 / dt) if dt > 0 else 0
    except Exception:
        pass
    return True, kbps

def norm_name(n):
    n = n.lower()
    n = re.sub(r"\(?\d{3,4}[pi]\)?", "", n)   # 去 (720p)/(1080p)/576i
    n = re.sub(r"\[.*?\]", "", n)
    return re.sub(r"\s+", "", n).strip()

# ---------------------------------------------------------------- 主流程 ---

def main():
    ap = argparse.ArgumentParser(description="全球直播源自发现扫描器 v2")
    ap.add_argument("--countries", nargs="*", default=None)
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--lines", type=int, default=3, help="同频道保留几条最快线路")
    ap.add_argument("--out", default="./live_out")
    args = ap.parse_args()

    countries = args.countries or COUNTRIES
    os.makedirs(args.out, exist_ok=True)
    rep, all_chans = [], []

    for code in countries:
        try:
            chans = parse_m3u(fetch(BASE.format(code=code)), code.upper())
            all_chans += chans
            line = f"[{code}] 拉取 {len(chans)} 个"
        except Exception as e:
            line = f"[{code}] 拉取失败 {str(e)[:60]}"
        rep.append(line); print(line, flush=True)

    seen, uniq = set(), []
    for c in all_chans:
        k = (c["name"], c["url"])
        if k not in seen:
            seen.add(k); uniq.append(c)
    rep.append(f"[dedup] 去重后 {len(uniq)} 个"); print(rep[-1], flush=True)

    valid = uniq
    if not args.no_check:
        print(f"[check] 测活+测速 {len(uniq)} 个 ...", flush=True)
        valid = []
        with cf.ThreadPoolExecutor(max_workers=CHECK_WORKERS) as ex:
            futs = {ex.submit(check_stream, c): c for c in uniq}
            done = 0
            for f in cf.as_completed(futs):
                done += 1
                try:
                    ok, kbps = f.result()
                    if ok:
                        futs[f]["_kbps"] = kbps
                        valid.append(futs[f])
                except Exception:
                    pass
                if done % 300 == 0:
                    print(f"  {done}/{len(futs)} ...", flush=True)
        rep.append(f"[check] 可用 {len(valid)}/{len(uniq)}"); print(rep[-1], flush=True)

        # 同频道保留最快的 N 条
        groups = {}
        for c in valid:
            groups.setdefault((c["country"], norm_name(c["name"])), []).append(c)
        kept = []
        for g in groups.values():
            g.sort(key=lambda c: c.get("_kbps", 0), reverse=True)
            kept += g[:args.lines]
        rep.append(f"[lines] 同频道保留最快{args.lines}条 -> {len(kept)} 条")
        print(rep[-1], flush=True)
        valid = kept

    # 趋势: 与历史比新增/失效
    today = datetime.date.today().isoformat()
    hist_path = os.path.join(args.out, "live_history.json")
    hist = {}
    if os.path.exists(hist_path):
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = {}
    urls_now = {c["url"] for c in valid}
    prev_days = sorted(hist.keys())
    if prev_days:
        urls_prev = set(hist[prev_days[-1]].get("urls", []))
        new, dead = len(urls_now - urls_prev), len(urls_prev - urls_now)
        rep.append(f"[trend] vs {prev_days[-1]}: 新增 {new} 条, 失效 {dead} 条")
        print(rep[-1], flush=True)
    hist[today] = {"total": len(valid), "urls": sorted(urls_now)}
    for d in sorted(hist.keys())[:-HISTORY_DAYS]:
        del hist[d]
    json.dump(hist, open(hist_path, "w", encoding="utf-8"))

    # 输出 txt
    valid.sort(key=lambda c: (c["country"], c["group"], -c.get("_kbps", 0), c["name"]))
    with open(os.path.join(args.out, "live_global.txt"), "w", encoding="utf-8") as f:
        last = None
        for c in valid:
            g = f'{c["country"]}-{c["group"]}'
            if g != last:
                f.write(f"\n{g},#genre#\n"); last = g
            f.write(f'{c["name"]},{c["url"]}\n')

    # 输出 m3u (带台标, EPG 用 tvg-id 匹配)
    with open(os.path.join(args.out, "live_global.m3u"), "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in valid:
            f.write(f'#EXTINF:-1 tvg-id="{c["tvg_id"]}" tvg-logo="{c["logo"]}" '
                    f'group-title="{c["country"]}-{c["group"]}",{c["name"]}\n{c["url"]}\n')

    with open(os.path.join(args.out, "scan_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + f"\n\nEPG: {EPG_URL}\n")

    print("\n==== 汇总 ===="); print("\n".join(rep))
    print(f"\n完成: {args.out}/ (txt {len(valid)} 条 / m3u / report / history)")
    print(f"EPG: {EPG_URL}")

if __name__ == "__main__":
    main()
