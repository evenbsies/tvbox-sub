# 自维护 drpy 规则

把以前依赖上游 jar 的点播站，逐步换成自己仓库里的规则。网站改版自己改，不用等上游。

## 目录

- `TEMPLATE.js` — 规则模板（带完整注释），抄它开新规则
- `rules/` — 规则文件，一站一个 js，`demo.js` 是可工作的示例
- `validate_drpy.py` — 每日校验器

## 写一条新规则

1. 复制 `TEMPLATE.js` 到 `rules/xxx.js`
2. 填 `title/host/url/class_name/class_url/detailUrl/searchUrl` 和五段解析代码（推荐/一级/二级/搜索/lazy）
3. 本地跑 `python3 drpy/validate_drpy.py`，看冒烟测试是否通过
4. 推到仓库，每日任务会自动复检

## 校验器做什么

`python3 drpy/validate_drpy.py [--report tvbox_out/drpy_report.txt]`

- `node --check` 语法检查
- 必填字段（title/host）+ host 可达
- **冒烟测试**：在 node 里 stub 宿主 API（request/post/setResult/input），真实请求目标站，
  执行 推荐/一级/搜索 的解析代码，验证返回条目含 url/title。
  用到 TVBox 内置 HTML 解析器（pdfh/pdfa）的规则跳过执行测试，只做前三项。

## 接入 TVBox

drpy 规则需要 drpy2 引擎。在点播配置里加：

```json
{
  "key": "my_demo",
  "name": "自维护示例",
  "type": 3,
  "api": "https://cdn.jsdelivr.net/gh/hjdhnx/hipy-server@master/app/t4/files/drpy_libs/drpy2.min.js",
  "ext": "https://cdn.jsdelivr.net/gh/evenbsies/tvbox-sub@main/drpy/rules/demo.js"
}
```

- `api` 是引擎（第三方稳定文件，可换）
- `ext` 是规则文件地址，改规则只改仓库里的 js，TVBox 端自动生效
- 规则挂了每日报告里会标出来，修仓库里的 js 即可
