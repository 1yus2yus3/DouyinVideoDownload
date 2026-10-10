"""抖音个人主页链接解析模块。

支持两种输入：
1. 桌面端主页链接：https://www.douyin.com/user/{sec_user_id}?showSubTab=video
2. 分享短链：https://v.douyin.com/xxxxx/ （需要浏览器重定向后提取）
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

# 抖音 sec_user_id 特征：以 MS4wLjABAAAA 开头的一串 base64 风格字符
SEC_UID_RE = re.compile(r"MS4wLjAB[A-Za-z0-9_\-]+")


def extract_sec_user_id(url: str) -> str | None:
    """从 URL 中直接提取 sec_user_id（无需打开页面）。"""
    # 1) /user/{sec_uid} 路径形式
    m = re.search(r"/user/(MS4wLjAB[A-Za-z0-9_\-]+)", url)
    if m:
        return m.group(1)

    # 2) query 参数 sec_user_id=...
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "sec_user_id" in qs and qs["sec_user_id"]:
        return qs["sec_user_id"][0]

    # 3) 其它路径中出现的 sec_uid 片段
    m = SEC_UID_RE.search(url)
    if m:
        return m.group(0)

    return None


def extract_sec_user_id_from_final_url(final_url: str) -> str | None:
    """从重定向后的最终 URL 提取 sec_user_id（用于分享短链场景）。"""
    return extract_sec_user_id(final_url)


def is_share_shortlink(url: str) -> bool:
    """判断是否为 v.douyin.com 分享短链。"""
    host = (urlparse(url).hostname or "").lower()
    return host == "v.douyin.com" or "v.douyin.com" in url


def normalize_profile_url(sec_user_id: str) -> str:
    """由 sec_user_id 构造桌面端主页 URL。"""
    return (
        f"https://www.douyin.com/user/{sec_user_id}"
        "?showSubTab=video&showTab=post"
    )
