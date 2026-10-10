# 抖音个人主页作品下载器

输入一个抖音个人主页链接，自动完成：**解析账号 → 抓取全部作品 → 生成 Excel 清单 → 下载全部 mp4 到本地**。

## 为什么需要浏览器

抖音 web 端接口带有 `a_bogus` / `msToken` 等动态签名参数，纯 HTTP 请求（requests/urllib）会被 403 拦截。
本项目通过 **Playwright 驱动你本机已安装的 Chrome** 打开主页，然后**在页面 JS 上下文中直接 fetch 接口**——
页面环境会自动附加 cookie 与签名，稳定、无需破解签名算法、无需额外下载浏览器内核。

## 环境要求

- macOS / Windows / Linux
- 本机已安装 Google Chrome（默认自动探测，也可用 `--chrome` 指定路径）
- Python 3.9+

## 安装

```bash
cd douyin_downloader
pip install -r requirements.txt
```

（Playwright 使用系统 Chrome 驱动，不需要执行 `playwright install` 下载浏览器。）

## 使用

```bash
# 基本用法：抓取 + Excel + 下载视频（无头模式，后台静默运行）
python3 main.py "https://www.douyin.com/user/MS4wLjABAAAA...?showSubTab=video&showTab=post"

# 显示浏览器窗口 + 等待扫码登录（推荐：能拿到完整作品列表，最长等 5 分钟）
python3 main.py "https://www.douyin.com/user/..." --headed --wait-login 300

# 支持分享短链（自动重定向解析）
python3 main.py "https://v.douyin.com/xxxx/"

# 只生成 Excel，不下载视频
python3 main.py "https://www.douyin.com/user/..." --no-download

# 指定输出目录
python3 main.py "https://www.douyin.com/user/..." --out-dir ./my_output
```

> 提示：抖音对未登录/全新浏览器会话可能只返回部分作品（尤其是合集类作品）。
> 遇到作品数比主页显示的少时，用 `--headed --wait-login 300` 运行，
> 程序会弹出浏览器窗口，你扫码登录后自动继续抓取完整列表。

## 输出结构

```
output/
├── {账号昵称}_{N}个作品清单.xlsx   # Excel 清单（账号信息 + 作品标题/时长/mp4直链/作品页链接）
└── videos/
    ├── 01_作品标题.mp4
    ├── 02_作品标题.mp4
    └── ...
```

## Excel 列说明

| 列 | 说明 |
| --- | --- |
| 作品ID(aweme_id) | 抖音视频唯一 ID |
| 标题 | 作品文案 |
| 发布时间 | 本地时间 |
| 时长(秒) | 视频时长 |
| mp4直链 | 可直接下载的 CDN 地址 |
| 作品页链接 | https://www.douyin.com/video/{id} |
| 封面图 / 全部播放地址 | 扩展信息 |

## 常见问题

- **下载 403**：mp4 直链带签名时效（数小时到一天），过期后重跑一次即可重新获取；下载时程序已自动携带 `Referer: https://www.douyin.com/`。
- **作品数比主页显示少**：抖音对未登录会话可能过滤部分作品（尤其合集）。用 `--headed --wait-login 300` 扫码登录后重跑。
- **抓不到数据**：检查链接是否为 `douyin.com/user/...` 或 `v.douyin.com` 短链；确认 Chrome 已安装。
- **SSL 证书报错**：抖音 CDN 部分节点证书链不完整，程序已内置忽略证书校验的下载逻辑，一般不会出现。

## 声明

本工具仅用于个人学习与数据研究，请遵守抖音平台规则与《著作权法》，下载内容请勿商用或二次传播。
