# TVBox 订阅源每日自动抓取

每天北京时间 06:00 自动抓取公开上游、过滤、校验，输出合并订阅。

## 部署（3 步）

1. 在 GitHub 建一个**公开**仓库（例如 `tvbox-sub`），把本目录所有文件推上去。
2. 仓库页面点 **Actions** 选项卡 → 左侧选 "每日抓取 TVBox 订阅源" → 点 **Enable workflow**（如有提示）。
3. 等第二天早上，或点 **Run workflow** 手动跑一次，`tvbox_out/` 目录就会生成。

## TVBox 里填这两个订阅地址

把 `<user>` `<repo>` 换成你自己的：

- 点播+解析：`https://raw.githubusercontent.com/<user>/<repo>/main/tvbox_out/tvbox_merged.json`
- 直播：`https://raw.githubusercontent.com/<user>/<repo>/main/tvbox_out/live_validated.txt`

## 本地手动跑

```bash
python3 tvbox_source_collector.py --out ./tvbox_out
```
