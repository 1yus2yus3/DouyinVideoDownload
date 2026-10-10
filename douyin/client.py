"""抖音作品数据抓取模块。

抖音 web 端接口带有 a_bogus / msToken 等动态签名，纯 HTTP 请求会被 403 拦截。
本项目采用「Playwright 驱动本机 Chrome 打开主页，在页面 JS 上下文中 fetch 接口」的
方式获取作品数据——页面环境会自动附加 cookie 与签名，稳定且无需破解签名算法。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .parser import extract_sec_user_id, normalize_profile_url


@dataclass
class VideoItem:
    """单个作品的结构化信息。"""

    aweme_id: str
    desc: str
    create_time: int
    duration_ms: int
    play_urls: list = field(default_factory=list)
    download_urls: list = field(default_factory=list)
    cover_urls: list = field(default_factory=list)
    mp4_url: str = ""

    @property
    def duration_seconds(self) -> int:
        return round(self.duration_ms / 1000) if self.duration_ms else 0

    @classmethod
    def from_aweme(cls, aweme: dict) -> "VideoItem":
        video = aweme.get("video") or {}
        play = video.get("play_addr") or {}
        download = video.get("download_addr") or {}
        cover = video.get("cover") or {}
        play_urls = list(play.get("url_list") or [])
        download_urls = list(download.get("url_list") or [])
        cover_urls = list(cover.get("url_list") or [])
        # 优先取明确的 mp4 直链（URL 中带 mime_type=video_mp4）
        mp4 = next(
            (u for u in play_urls if "mime_type=video_mp4" in u),
            play_urls[0] if play_urls else "",
        )
        return cls(
            aweme_id=str(aweme.get("aweme_id") or ""),
            desc=aweme.get("desc") or "",
            create_time=int(aweme.get("create_time") or 0),
            duration_ms=int(video.get("duration") or 0),
            play_urls=play_urls,
            download_urls=download_urls,
            cover_urls=cover_urls,
            mp4_url=mp4,
        )


@dataclass
class UserProfile:
    """账号信息。"""

    sec_uid: str
    nickname: str = ""
    signature: str = ""
    follower_count: int = 0
    total_favorited: int = 0
    aweme_count: int = 0
    avatar_url: str = ""


def _parse_user_info(sec_uid: str, user: dict) -> UserProfile:
    return UserProfile(
        sec_uid=sec_uid,
        nickname=user.get("nickname") or "",
        signature=user.get("signature") or "",
        follower_count=int(user.get("follower_count") or 0),
        total_favorited=int(user.get("total_favorited") or 0),
        aweme_count=int(user.get("aweme_count") or 0),
        avatar_url=((user.get("avatar_thumb") or {}).get("url_list") or [""])[0],
    )


def _default_chrome_path() -> Optional[str]:
    """定位本机 Chrome 可执行文件（macOS / Windows / Linux）。"""
    import os
    import sys

    candidates = []
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif sys.platform.startswith("win"):
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
        ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


FETCH_JS = r"""
(args) => {
    const params = new URLSearchParams({
        device_platform: 'webapp', aid: '6383', channel: 'channel_pc_web',
        sec_user_id: args.sec,
        max_cursor: String(args.maxCursor || 0), count: String(args.count || 35),
        publish_video_strategy_type: '2',
        source: 'channel_pc_web', personal_homepage_from: '', min_cursor: '0'
    });
    return fetch('https://www.douyin.com/aweme/v1/web/aweme/post/?' + params,
                 {credentials: 'include'})
        .then(r => r.text())
        .then(t => {
            try { return {ok: true, data: JSON.parse(t)}; }
            catch (e) { return {ok: false, head: t.slice(0, 300)}; }
        })
        .catch(e => ({ok: false, head: 'fetch error: ' + String(e)}));
}
"""


FETCH_PROFILE_JS = r"""
(sec) => {
    const params = new URLSearchParams({
        device_platform: 'webapp', aid: '6383', channel: 'channel_pc_web',
        publish_video_strategy_type: '2', source: 'channel_pc_web',
        sec_user_id: sec
    });
    return fetch('https://www.douyin.com/aweme/v1/web/user/profile/other/?' + params,
                 {credentials: 'include'})
        .then(r => r.text())
        .then(t => {
            try {
                const d = JSON.parse(t);
                const u = d.user || {};
                return {
                    ok: true,
                    nickname: u.nickname || '',
                    signature: u.signature || '',
                    follower_count: Number(u.follower_count || 0),
                    total_favorited: Number(u.total_favorited || 0),
                    aweme_count: Number(u.aweme_count || 0),
                    avatar: ((u.avatar_thumb || {}).url_list || [''])[0],
                };
            } catch (e) {
                return {ok: false, head: t.slice(0, 200)};
            }
        })
        .catch(e => ({ok: false, head: 'fetch error: ' + String(e)}));
}
"""


class DouyinClient:
    """通过本机 Chrome 抓取抖音个人主页作品列表。"""

    def __init__(
        self,
        chrome_path: Optional[str] = None,
        headless: bool = True,
        timeout_ms: int = 60000,
        wait_login_seconds: int = 0,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.chrome_path = chrome_path or _default_chrome_path()
        if not self.chrome_path:
            raise RuntimeError(
                "未找到本机 Chrome，请通过 chrome_path 参数指定浏览器可执行文件路径"
            )
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.wait_login_seconds = wait_login_seconds
        self.on_progress = on_progress

    def _log(self, msg: str) -> None:
        if self.on_progress:
            self.on_progress(msg)

    def _dismiss_modal(self, page) -> None:
        """关闭可能弹出的登录/引导弹窗，让作品列表区露出来（未登录也可浏览）。"""
        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception:
            pass
        try:
            close_btn = page.locator(
                "div[data-e2e='login-modal-close'], .login-modal-close, "
                "[aria-label='关闭']"
            ).first
            if close_btn.count() and close_btn.is_visible():
                close_btn.click(timeout=3000)
                time.sleep(1)
        except Exception:
            pass

    def _is_logged_in(self, page) -> bool:
        """判断当前浏览器会话是否已登录抖音。"""
        try:
            names = {c["name"] for c in page.context.cookies()}
            if "sid_guard" in names or "uid_tt" in names or "sessionid" in names:
                return True
        except Exception:
            pass
        try:
            has_login_btn = page.evaluate(
                "() => !!Array.from(document.querySelectorAll('button,a,span'))"
                ".find(el => el.textContent && el.textContent.trim() === '登录')"
            )
            return not has_login_btn
        except Exception:
            return False

    def _open_login_modal(self, page) -> None:
        """点击页面右上角『登录』按钮，弹出扫码登录窗口。"""
        try:
            btn = page.locator(
                "button:has-text('登录'), [data-e2e='user-info-login'], "
                "header button, nav button"
            ).first
            # 页面右上角登录入口
            candidates = page.get_by_role("button", name="登录")
            if candidates.count() > 0:
                candidates.first.click(timeout=5000)
                return
        except Exception:
            pass

    def _wait_for_login(self, page, wait_seconds: int) -> bool:
        """等待用户在浏览器窗口中扫码登录，返回是否成功。"""
        if wait_seconds <= 0:
            return self._is_logged_in(page)
        self._log(
            f"[提示] 检测到未登录。请在浏览器窗口中扫码登录抖音，"
            f"我将等待最多 {wait_seconds} 秒后自动继续..."
        )
        deadline = time.monotonic() + wait_seconds
        waited = 0
        while time.monotonic() < deadline:
            if self._is_logged_in(page):
                self._log("  检测到登录成功，继续抓取")
                return True
            time.sleep(3)
            waited += 3
            if waited % 30 == 0:
                remain = int(deadline - time.monotonic())
                if remain > 0:
                    self._log(f"  仍在等待登录...（剩余约 {remain} 秒）")
        self._log("[提示] 等待登录超时，将以当前会话继续（可能拿不全作品）")
        return False

    def fetch_user(self, profile_url_or_uid: str) -> tuple[UserProfile, list[VideoItem]]:
        """抓取账号信息 + 全部作品列表。

        返回 (UserProfile, [VideoItem, ...])。
        """
        sec_uid = extract_sec_user_id(profile_url_or_uid)
        if not sec_uid:
            raise ValueError(
                f"无法从链接中识别抖音 sec_user_id: {profile_url_or_uid}"
            )

        profile_url = normalize_profile_url(sec_uid)
        self._log(f"打开主页: {profile_url}")

        from playwright.sync_api import sync_playwright

        profile: Optional[UserProfile] = None
        videos: dict[str, VideoItem] = {}  # aweme_id -> item
        max_cursor: Optional[int] = 0
        has_more = True
        page_no = 0

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=self.chrome_path,
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--disable-default-apps",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
            )
            page = context.new_page()

            # 先打开主页：建立会话 cookie 与签名环境，并让页面 JS 加载完成
            page.goto(profile_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            time.sleep(3)

            # 登录处理：未登录时提示用户扫码（仅有头模式有意义）
            if not self._is_logged_in(page) and self.wait_login_seconds > 0:
                self._open_login_modal(page)
                self._wait_for_login(page, self.wait_login_seconds)

            self._dismiss_modal(page)

            # 抓取账号信息（昵称/粉丝/获赞/作品数）
            try:
                pres = page.evaluate(FETCH_PROFILE_JS, sec_uid)
                if pres.get("ok"):
                    profile = UserProfile(
                        sec_uid=sec_uid,
                        nickname=pres.get("nickname") or "",
                        signature=pres.get("signature") or "",
                        follower_count=int(pres.get("follower_count") or 0),
                        total_favorited=int(pres.get("total_favorited") or 0),
                        aweme_count=int(pres.get("aweme_count") or 0),
                        avatar_url=pres.get("avatar") or "",
                    )
            except Exception:
                pass

            # 在页面 JS 上下文中分页 fetch 作品接口
            while has_more and page_no < 50:
                page_no += 1
                result = page.evaluate(
                    FETCH_JS,
                    {"sec": sec_uid, "maxCursor": max_cursor or 0, "count": 35},
                )
                if not result.get("ok"):
                    # 偶发风控/空响应：等待后重试一次
                    time.sleep(3)
                    result = page.evaluate(
                        FETCH_JS,
                        {"sec": sec_uid, "maxCursor": max_cursor or 0, "count": 35},
                    )
                if not result.get("ok"):
                    self._log(
                        f"  第 {page_no} 页接口异常: {str(result.get('head'))[:120]}"
                    )
                    break

                data = result["data"]
                if data.get("status_code") != 0:
                    self._log(
                        f"  第 {page_no} 页 status_code={data.get('status_code')}"
                    )
                    break

                # 账号信息（通常在 user 字段）
                user = data.get("user") or {}
                if user and profile is None:
                    profile = _parse_user_info(sec_uid, user)

                for aweme in data.get("aweme_list") or []:
                    item = VideoItem.from_aweme(aweme)
                    if item.aweme_id and item.aweme_id not in videos:
                        videos[item.aweme_id] = item
                        self._log(f"  已获取 {len(videos)} 个作品...")

                max_cursor = data.get("max_cursor")
                has_more = bool(data.get("has_more")) and bool(data.get("aweme_list"))
                if has_more:
                    time.sleep(1.0)

            browser.close()

        if not videos:
            raise RuntimeError(
                "未获取到任何作品数据。可能原因：链接无效、账号作品为空、"
                "或页面需要登录/验证。请检查链接后重试。"
            )

        if profile is None:
            profile = UserProfile(sec_uid=sec_uid)

        ordered = sorted(videos.values(), key=lambda v: v.create_time, reverse=True)
        self._log(f"抓取完成，共 {len(ordered)} 个作品")
        return profile, ordered


def fetch_all(profile_url: str, **kwargs) -> tuple[UserProfile, list[VideoItem]]:
    """便捷入口：一行调用抓取账号与作品。"""
    client = DouyinClient(**kwargs)
    return client.fetch_user(profile_url)
