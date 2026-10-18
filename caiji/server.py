#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自建采集聚合服务 - API
======================
读取 aggregator.py 同步的 SQLite，对外提供 applecms 兼容接口。
TVBox 里当 type=1 站填：{"key":"my_caiji","name":"自建聚合","type":1,
  "api":"http://你的服务器:8080/","searchable":1,"quickSearch":1}

接口：
    /?ac=videolist&pg=1              最新入库
    /?ac=videolist&wd=关键词          搜索
    /?ac=videolist&t=电影             分类（type_name 模糊匹配）
    /?ac=detail&ids=123             详情（含多线路播放地址）
    /                               状态页

多线路格式：vod_play_from 以 $$$ 分隔源名，vod_play_url 以 $$$ 分隔各源剧集串。

用法: python3 server.py --db caiji.db --port 8080
只用标准库。
"""
import argparse
import json
import os
import sqlite3
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_SIZE = 20


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def vod_row(r):
    return {
        "vod_id": r["id"], "vod_name": r["name"], "vod_pic": r["pic"],
        "vod_remarks": r["remarks"], "vod_year": r["year"],
        "type_name": r["type_name"], "vod_content": r["content"],
    }


def list_vods(pg, wd, t):
    con = get_db()
    where, args = [], []
    if wd:
        where.append("(name LIKE ?)")
        args.append(f"%{wd}%")
    if t:
        where.append("type_name LIKE ?")
        args.append(f"%{t}%")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = con.execute(f"SELECT COUNT(*) c FROM vods {w}", args).fetchone()["c"]
    pagecount = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    pg = max(1, min(pg, pagecount))
    rows = con.execute(
        f"SELECT * FROM vods {w} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        args + [PAGE_SIZE, (pg - 1) * PAGE_SIZE]).fetchall()
    con.close()
    return {
        "code": 1, "msg": "数据列表", "page": pg, "pagecount": pagecount,
        "limit": PAGE_SIZE, "total": total,
        "list": [vod_row(r) for r in rows],
    }


def detail(vid):
    con = get_db()
    r = con.execute("SELECT * FROM vods WHERE id=?", (vid,)).fetchone()
    if not r:
        con.close()
        return {"code": 0, "msg": "未找到"}
    plays = con.execute(
        "SELECT p.source,p.play_url,s.kbps FROM plays p"
        " LEFT JOIN sources s ON s.name=p.source"
        " WHERE p.vod_id=? AND p.play_url!='' ORDER BY s.kbps DESC", (vid,)).fetchall()
    con.close()
    item = vod_row(r)
    item["vod_play_from"] = "$$$".join(p["source"] for p in plays)
    item["vod_play_url"] = "$$$".join(p["play_url"] for p in plays)
    return {"code": 1, "msg": "数据详情", "list": [item]}


def status():
    con = get_db()
    n = con.execute("SELECT COUNT(*) c FROM vods").fetchone()["c"]
    srcs = con.execute("SELECT name,kbps,note,last_sync FROM sources").fetchall()
    con.close()
    rows = "".join(
        f"<tr><td>{s['name']}</td><td>{s['kbps']}KB/s</td><td>{s['note']}</td>"
        f"<td>{time.strftime('%m-%d %H:%M', time.localtime(s['last_sync'])) if s['last_sync'] else '-'}</td></tr>"
        for s in srcs)
    return (f"<html><head><meta charset=utf-8><title>自建采集聚合</title></head><body>"
            f"<h2>自建采集聚合服务</h2><p>影片 {n} 部</p>"
            f"<table border=1><tr><th>源</th><th>测速</th><th>状态</th><th>同步时间</th></tr>{rows}</table>"
            f"</body></html>").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        ac = (q.get("ac") or [""])[0]
        try:
            if ac == "videolist":
                pg = int((q.get("pg") or ["1"])[0] or 1)
                self._send(json.dumps(list_vods(pg, (q.get("wd") or [""])[0],
                                               (q.get("t") or [""])[0]), ensure_ascii=False))
            elif ac == "detail":
                self._send(json.dumps(detail((q.get("ids") or ["0"])[0]), ensure_ascii=False))
            else:
                self._send(status(), "text/html")
        except BrokenPipeError:
            pass
        except Exception as e:
            self._send(json.dumps({"code": 0, "msg": str(e)[:100]}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="自建采集聚合服务 - API")
    ap.add_argument("--db", default=os.path.join(HERE, "caiji.db"))
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    global DB_PATH
    DB_PATH = args.db
    if not os.path.exists(DB_PATH):
        print(f"库不存在：{DB_PATH}，先跑 aggregator.py 同步")
        return
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[server] http://{args.host}:{args.port}/  (Ctrl+C 停止)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
