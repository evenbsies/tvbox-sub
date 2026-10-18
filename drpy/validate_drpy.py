#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drpy 规则校验器
==============
对 drpy/rules/*.js（TEMPLATE.js 除外）逐项检查：
  1. node --check 语法
  2. 必填字段 (title, host)
  3. host 可达
  4. 冒烟测试：用 node stub 宿主 API (request/post/setResult/input)，真实请求目标站，
     执行 推荐/一级/搜索 的 js: 解析代码，验证返回数组（HTML 解析类规则跳过此步）。

用法: python3 drpy/validate_drpy.py [--report path]
退出码恒为 0，结论写进报告（供每日任务提交）。
只用标准库 (+node)。
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(HERE, "rules")
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"

# 需要 TVBox 内置解析器 (pdfh/pdfa) 的规则跳过 stub 执行，只做前 3 项
STUB_BLOCKLIST = ("pdfh", "pdfa(", "request2", "fetch(")

HARNESS = r"""
const fs=require('fs'),cp=require('child_process');
const src=fs.readFileSync(process.argv[2],'utf8');
const expr=src.replace(/^[\s\S]*?var\s+rule\s*=\s*/, '').replace(/;\s*$/, '');
let rule; try{ rule=eval('('+expr+')'); }catch(e){ console.log(JSON.stringify({ok:false,error:'rule parse: '+String(e).slice(0,120)})); process.exit(0); }
const field=process.argv[3], input=process.argv[4];
const MOBILE_UA='Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36';
const PC_UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36';
let _r='@@NORESULT@@';
const setResult=d=>{_r=d}, log=()=>{};
const request=u=>cp.execSync('curl -sL --max-time 20 '+JSON.stringify(String(u)),{maxBuffer:32*1024*1024}).toString();
const post=(u,o)=>{o=o||{};const h=Object.entries(o.headers||{}).map(([k,v])=>'-H '+JSON.stringify(k+': '+v)).join(' ');
  return cp.execSync('curl -sL --max-time 20 -X POST '+h+' --data '+JSON.stringify(String(o.body||''))+' '+JSON.stringify(String(u)),{maxBuffer:32*1024*1024}).toString();};
let code=rule[field];
if(typeof code!=='string'||!code.startsWith('js:')){ console.log(JSON.stringify({ok:true,skipped:'not-js'})); process.exit(0); }
try{ eval(code.slice(3)); console.log(JSON.stringify({ok:true,result:_r})); }
catch(e){ console.log(JSON.stringify({ok:false,error:String(e&&e.message||e).slice(0,200)})); }
"""


def sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, str(e)[:200]


def get_rule_fields(path):
    """用 node 提取 rule 的元字段。"""
    js = ("const fs=require('fs');const src=fs.readFileSync(%s,'utf8');"
          "const expr=src.replace(/^[\\s\\S]*?var\\s+rule\\s*=\\s*/, '').replace(/;\\s*$/, '');"
          "const rule=eval('('+expr+')');"
          "console.log(JSON.stringify({title:rule.title||'',host:rule.host||'',"
          "homeUrl:rule.homeUrl||'',url:rule.url||'',detailUrl:rule.detailUrl||'',"
          "searchUrl:rule.searchUrl||'',class_url:rule.class_url||'',"
          "tuijian:typeof rule['推荐'],yiji:typeof rule['一级'],erji:typeof rule['二级'],"
          "sousuo:typeof rule['搜索'],lazy:typeof rule['lazy'],"
          "code_tj:String(rule['推荐']||''),code_yj:String(rule['一级']||''),"
          "code_ss:String(rule['搜索']||'')}));"
          ) % json.dumps(path)
    rc, out = sh(["node", "-e", js])
    if rc != 0:
        return None
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:
        return None


def stub_run(path, field, input_url):
    hpath = os.path.join(HERE, "_stub_tmp.js")
    open(hpath, "w", encoding="utf-8").write(HARNESS)
    try:
        rc, out = sh(["node", hpath, path, field, input_url], timeout=60)
        line = (out.strip().splitlines() or ["{}"])[-1]
        return json.loads(line)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    finally:
        try:
            os.remove(hpath)
        except OSError:
            pass


def host_ok(host):
    try:
        req = urllib.request.Request(host, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=12) as r:
            return True, r.status
    except Exception:
        try:  # 有些站禁 HEAD，改 GET
            req = urllib.request.Request(host, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=12) as r:
                r.read(64)
                return True, r.status
        except Exception as e:
            return False, str(e)[:60]


def validate_one(path):
    name = os.path.basename(path)
    rep, ok_all = [f"[{name}]"], True

    rc, out = sh(["node", "--check", path])
    rep.append(f"  语法: {'OK' if rc == 0 else 'FAIL ' + out[:120]}")
    if rc != 0:
        return rep, False

    f = get_rule_fields(path)
    if not f or not f.get("title") or not f.get("host"):
        rep.append("  字段: FAIL (缺 title/host 或 rule 解析失败)")
        return rep, False
    rep.append(f"  字段: OK (title={f['title']})")

    ok, detail = host_ok(f["host"])
    rep.append(f"  host: {'OK' if ok else 'FAIL ' + str(detail)}")
    if not ok:
        ok_all = False

    host = f["host"].rstrip("/")
    code_of = {"推荐": f["code_tj"], "一级": f["code_yj"], "搜索": f["code_ss"]}
    tests = {
        "推荐": host + f["homeUrl"],
        "一级": host + f["url"].replace("fypage", "1").replace("fyfilter", (f["class_url"].split("&")[0] if f["class_url"] else "")),
        "搜索": host + f["searchUrl"].replace("**", urllib.parse.quote("示例")),
    }
    for field, url in tests.items():
        if any(b in code_of[field] for b in STUB_BLOCKLIST):
            rep.append(f"  {field}: 跳过 (需 TVBox 内置解析器)")
            continue
        r = stub_run(path, field, url)
        if r.get("skipped"):
            rep.append(f"  {field}: 跳过 (非 js: 写法)")
        elif not r.get("ok"):
            rep.append(f"  {field}: FAIL {r.get('error', '')[:100]}")
            ok_all = False
        else:
            res = r.get("result")
            n = len(res) if isinstance(res, list) else -1
            good = isinstance(res, list) and (n == 0 or all(isinstance(x, dict) and "url" in x and "title" in x for x in res[:3]))
            rep.append(f"  {field}: {'OK' if good else 'FAIL(格式)'} ({n} 条)")
            if not good:
                ok_all = False
    rep.append(f"  => {'通过' if ok_all else '不通过'}")
    return rep, ok_all


def main():
    ap_ok = True
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    files = sorted(p for p in os.listdir(RULES_DIR)
                   if p.endswith(".js") and p != "TEMPLATE.js" and os.path.isfile(os.path.join(RULES_DIR, p)))
    lines = [f"drpy 规则校验 {__import__('datetime').date.today().isoformat()} 共 {len(files)} 个", ""]
    passed = 0
    for fn in files:
        rep, ok = validate_one(os.path.join(RULES_DIR, fn))
        lines += rep + [""]
        passed += ok
    lines.append(f"汇总: {passed}/{len(files)} 通过")
    text = "\n".join(lines)
    print(text)
    if args.report:
        open(args.report, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
