#!/usr/bin/env python3
"""抖音个人主页作品抓取工具。

用法:
    python3 main.py <主页链接> [--out-dir DIR] [--headless] [--no-download] [--no-excel]

示例:
    python3 main.py "https://www.douyin.com/user/MS4wLjABAAAA..."
    python3 main.py "https://v.douyin.com/xxxx/" --out-dir ./output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from douyin.client import DouyinClient
from douyin.downloader import download_videos
from douyin.excel_writer import build_excel
from douyin.parser import extract_sec_user_id, is_share_shortlink


def main() -> int:
    parser = argparse.ArgumentParser(
        description="抓取抖音个人主页作品，生成 Excel 清单并下载 mp4 到本地"
    )
    parser.add_argument("profile_url", help="抖音个人主页链接（桌面端 /user/... 或分享短链）")
    parser.add_argument("--out-dir", default="output", help="输出目录（默认 ./output）")
    parser.add_argument("--chrome", default=None, help="Chrome 可执行文件路径（默认自动探测）")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口（默认无头模式）")
    parser.add_argument(
        "--wait-login",
        type=int,
        default=0,
        metavar="SECONDS",
        help="检测到未登录时等待扫码登录的秒数（如 300，需配合 --headed 使用）",
    )
    parser.add_argument("--no-download", action="store_true", help="只生成 Excel，不下载视频")
    parser.add_argument("--no-excel", action="store_true", help="只下载视频，不生成 Excel")
    args = parser.parse_args()

    url = args.profile_url.strip()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 短链需要浏览器重定向后才能拿到 sec_user_id，先提示
    if is_share_shortlink(url):
        print("[提示] 检测到分享短链，将通过浏览器重定向解析真实主页地址")

    if not extract_sec_user_id(url) and not is_share_shortlink(url):
        print(f"[错误] 无法从链接中识别抖音账号: {url}")
        print("支持的格式：")
        print("  https://www.douyin.com/user/{sec_user_id}")
        print("  https://v.douyin.com/xxxx/  （分享短链）")
        return 1

    def progress(msg: str, *extra) -> None:
        # 同时兼容单参数（抓取阶段）与三参数（下载阶段）的回调
        if extra:
            total = extra[0]
            detail = extra[1] if len(extra) > 1 else ""
            print(f"  [{msg}/{total}] {detail}", flush=True)
        else:
            print(msg, flush=True)

    client = DouyinClient(
        chrome_path=args.chrome,
        headless=not args.headed,
        wait_login_seconds=args.wait_login,
        on_progress=progress,
    )

    print(f"[1/3] 抓取作品数据...")
    try:
        profile, videos = client.fetch_user(url)
    except Exception as e:
        print(f"[错误] 抓取失败: {e}")
        return 1

    print(
        f"  账号: {profile.nickname} | 粉丝 {profile.follower_count} | "
        f"获赞 {profile.total_favorited} | 作品 {len(videos)} 个"
    )

    if not args.no_excel:
        print(f"[2/3] 生成 Excel 清单...")
        xlsx_path = out_dir / f"{profile.nickname or 'douyin'}_{len(videos)}个作品清单.xlsx"
        build_excel(profile, videos, xlsx_path)
        print(f"  Excel 已生成: {xlsx_path}")

    if not args.no_download:
        print(f"[3/3] 下载视频到 {out_dir / 'videos'} ...")
        video_dir = out_dir / "videos"
        results = download_videos(videos, video_dir, on_progress=progress)
        ok = sum(1 for r in results.values() if r.startswith("OK"))
        fail = sum(1 for r in results.values() if r.startswith("FAIL"))
        print(f"  下载完成: 成功 {ok} 个, 失败 {fail} 个")
        if fail:
            for aweme_id, r in results.items():
                if r.startswith("FAIL"):
                    print(f"    - {aweme_id}: {r}")

    print("\n全部完成 ✅")
    print(f"输出目录: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
