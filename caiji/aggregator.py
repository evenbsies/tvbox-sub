#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自建采集聚合服务 - 同步器
从 vod_apis.json 的采集站拉取影片数据，写入本地 SQLite。
server.py 读取该库，对外提供 applecms 兼容 API。
"""
import argparse
import json
import os
import re
import sqlite3
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"}
FETCH_TIMEOUT = 20


def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))


def norm_name(n):
    n = (n or "").lower()
    n = re.sub(r"[《》「」『』【】\[\]（）()\s·・:：\-_]+", "", n)
    return n.strip()


def init_db(path):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE IF NOT EXISTS vods(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, norm TEXT NOT NULL, year TEXT DEFAULT '',
        pic TEXT DEFAULT '', remarks TEXT DEFAULT '', type_name TEXT DEFAULT '',
        content TEXT DEFAULT '', updated_at INTEGER DEFAULT 0,
        UNIQUE(norm, year))""")
    con.execute("""CREATE TABLE IF NOT EXISTS plays(
        vod_id INTEGER NOT NULL, source TEXT NOT NULL,
        play_url TEXT DEFAULT '', kbps INTEGER DEFAULT 0,
        PRIMARY KEY (vod_id, source))""")
    con.execute("""CREATE TABLE IF NOT EXISTS sources(
        name TEXT PRIMARY KEY, api TEXT, total INTEGER DEFAULT 0,
        kbps INTEGER DEFAULT 0, last_sync INTEGER DEFAULT 0, note TEXT DEFAULT '')""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_vods_norm ON vods(norm)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_vods_name ON vods(name)")
    con.commit()
    return con


def measure_kbps(api):
    try:
        base = api.rstrip("/")
        d = fetch_json(base + "?ac=videolist")
        it = (d.get("list") or [None])[0]
        if not it:
            return 0
        d2 = fetch_json(base + "?ac=detail&ids=" + str(it.get("vod_id")))
        lst = d2.get("list") or []
        if not lst:
            return 0
        play = lst[0].get("vod_play_url", "")
        m = re.search(r"https?://[^\s#$,\"']+\.m3u8[^\s#$,\"']*", play)
        if not m:
            m = re.search(r"https?://[^\s#$,\"']+", play)
        if not m:
            return 0
        url, n, t0 = m.group(0), 0, time.time()
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            if r.status != 200:
                return 0
            while n < 256 * 1024 and time.time() - t0 < 5:
                chunk = r.read(65536)
                if not chunk:
                    break
                n += len(chunk)
        dt = time.time() - t0
        return int(n / 1024 / dt) if dt > 0 else 0
    except Exception:
        return 0


def sync_source(con, name, api, incremental, max_pages):
    base = api.rstrip("/")
    added, updated, total = 0, 0, 0
    page = 1
    while page <= max_pages:
        q = "?ac=videolist&pg=" + str(page) + ("&h=24" if incremental else "")
        try:
            d = fetch_json(base + q)
        except Exception as e:
            return added, updated, "拉取失败: " + str(e)[:40]
        if d.get("code") != 1:
            return added, updated, "接口返回异常"
        lst = d.get("list") or []
        if not lst:
            break
        total = d.get("total", total)
        for it in lst:
            nm = it.get("vod_name", "")
            year = str(it.get("vod_year", "") or "")
            if not nm:
                continue
            norm = norm_name(nm)
            cur = con.execute("SELECT id FROM vods WHERE norm=? AND year=?", (norm, year)).fetchone()
            if cur:
                vid = cur[0]
                con.execute(
                    "UPDATE vods SET pic=?,remarks=?,type_name=?,content=?,updated_at=? WHERE id=?",
                    (it.get("vod_pic", ""), it.get("vod_remarks", ""), it.get("type_name", ""),
                     (it.get("vod_content", "") or "")[:500], int(time.time()), vid))
                updated += 1
            else:
                cur = con.execute(
                    "INSERT INTO vods(name,norm,year,pic,remarks,type_name,content,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (nm, norm, year, it.get("vod_pic", ""), it.get("vod_remarks", ""),
                     it.get("type_name", ""), (it.get("vod_content", "") or "")[:500], int(time.time())))
                vid = cur.lastrowid
                added += 1
            try:
                d2 = fetch_json(base + "?ac=detail&ids=" + str(it.get("vod_id")))
                l2 = d2.get("list") or []
                if l2:
                    con.execute("INSERT OR REPLACE INTO plays(vod_id,source,play_url) VALUES(?,?,?)",
                                (vid, name, l2[0].get("vod_play_url", "")))
            except Exception:
                pass
        con.commit()
        if page >= (d.get("pagecount") or page):
            break
        page += 1
        time.sleep(0.3)
    return added, updated, "ok(共" + str(total) + "部)"


def main():
    ap = argparse.ArgumentParser(description="自建采集聚合服务 - 同步器")
    ap.add_argument("--db", default=os.path.join(HERE, "caiji.db"))
    ap.add_argument("--full", action="store_true", help="全量回填（默认只同步近24小时更新）")
    ap.add_argument("--max-pages", type=int, default=60, help="每站最多拉多少页（每页20条）")
    ap.add_argument("--apis", default=os.path.join(HERE, "..", "vod_apis.json"))
    args = ap.parse_args()

    vod_list = json.load(open(args.apis, encoding="utf-8"))
    con = init_db(args.db)
    mode = "全量" if args.full else "增量(h=24)"
    print("[sync] " + mode + "，" + str(len(vod_list)) + " 个源，库：" + args.db, flush=True)

    for x in vod_list:
        name, api = x["name"], x["api"]
        kbps = measure_kbps(api)
        added, updated, note = sync_source(con, name, api, not args.full, args.max_pages)
        con.execute("INSERT OR REPLACE INTO sources(name,api,kbps,last_sync,note) VALUES(?,?,?,?,?)",
                    (name, api, kbps, int(time.time()), note))
        con.commit()
        print("[sync] " + name + ": 新增" + str(added) + " 更新" + str(updated) +
              " 测速" + str(kbps) + "KB/s " + note, flush=True)

    n = con.execute("SELECT COUNT(*) FROM vods").fetchone()[0]
    print("[sync] 完成，库内共 " + str(n) + " 部影片")


if __name__ == "__main__":
    main()
