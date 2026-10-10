"""视频批量下载模块。

抖音 CDN 直链需要携带 Referer: https://www.douyin.com/ 请求头才能访问（否则 403）。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

from .client import VideoItem

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"


def _sanitize_filename(name: str, max_len: int = 40) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] or "untitled"


def _ssl_context():
    """抖音 CDN 部分节点证书链不完整，下载时忽略证书校验。"""
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def download_one(
    url: str,
    save_path: str | Path,
    referer: str = REFERER,
    timeout: int = 180,
) -> int:
    """下载单个文件，返回字节数。使用标准库实现，无第三方依赖。"""
    import urllib.request

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": referer},
    )
    total = 0
    with urllib.request.urlopen(
        req, timeout=timeout, context=_ssl_context()
    ) as resp, open(save_path, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    return total


def download_videos(
    videos: list[VideoItem],
    output_dir: str | Path,
    skip_existing: bool = True,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    referer: str = REFERER,
) -> dict[str, str]:
    """批量下载作品 mp4 到 output_dir。

    返回 {aweme_id: 结果描述}，结果描述形如 "OK 12.3MB" / "FAIL ..."。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}
    total = len(videos)
    for i, v in enumerate(videos, start=1):
        fname = f"{i:02d}_{_sanitize_filename(v.desc)}.mp4"
        path = output_dir / fname
        if skip_existing and path.exists() and path.stat().st_size > 0:
            results[v.aweme_id] = "SKIP (已存在)"
            if on_progress:
                on_progress(i, total, f"跳过 {fname}")
            continue
        try:
            size = download_one(v.mp4_url, path, referer=referer)
            mb = size / 1024 / 1024
            results[v.aweme_id] = f"OK {mb:.1f}MB"
            if on_progress:
                on_progress(i, total, f"完成 {fname} ({mb:.1f}MB)")
        except Exception as e:
            results[v.aweme_id] = f"FAIL {str(e)[:60]}"
            if on_progress:
                on_progress(i, total, f"失败 {fname}: {str(e)[:60]}")
        time.sleep(0.5)  # 温和限速，避免触发风控
    return results
