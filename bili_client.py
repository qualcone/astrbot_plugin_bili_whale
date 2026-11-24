"""B 站只读客户端。接口用法参考 dsh-bili-whale (MIT) 的思路，Python 独立重写。
只做 GET 读取；不点赞/投币/收藏/评论/私信/发动态/关注。"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time

import aiohttp

from . import wbi

log = logging.getLogger("bili_whale")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
REFERER = "https://www.bilibili.com/"
RISK_CODES = {-352, -412, -799}
API = "https://api.bilibili.com"


class BiliError(Exception):
    """可读的业务错误。"""


class BiliRisk(BiliError):
    """风控：调用方必须停止当晚后续请求。"""


def redact(text, *secrets: str) -> str:
    """从任意文本里抹掉密钥。"""
    text = str(text)
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return re.sub(r"(SESSDATA|bili_jct)=[^;\s]+", r"\1=***", text)


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&").replace("&quot;", '"').strip()


def fmt_count(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


def fmt_duration(sec) -> str:
    if isinstance(sec, str):
        return sec
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return "?"
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def explain_code(code: int, msg: str = "") -> str:
    table = {
        -101: "cookie 失效或未登录，请更新 SESSDATA",
        -352: "触发风控(-352)，请降低频率/检查 cookie",
        -412: "请求过于频繁(-412)",
        -799: "请求过于频繁(-799)",
        -403: "权限不足(-403)",
        -404: "视频不存在或已删除(-404)",
        62002: "视频不可见(稿件仅自己可见)",
        62012: "视频审核中或不可见",
        -10403: "地区限制(-10403)，该视频在当前 IP 所在地区不可看",
    }
    return table.get(code, f"B 站返回错误 {code}: {msg}")


class BiliClient:
    def __init__(self, sessdata="", bili_jct="", buvid3="", interval=(2.0, 4.0), timeout=15,
                 session: aiohttp.ClientSession | None = None):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.buvid3 = buvid3
        self.buvid4 = ""
        self.extra_cookies: dict[str, str] = {}
        self._ready = False
        self.interval = interval
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._own = session is None
        self._last = 0.0
        self._wbi: tuple[str, str] | None = None
        self._wbi_at = 0.0
        self._lock = asyncio.Lock()

    # ---------- 基础 ----------
    async def close(self):
        if self._own and self._session and not self._session.closed:
            await self._session.close()

    def _sess(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own = True
        return self._session

    def headers(self) -> dict:
        ck = []
        if self.sessdata:
            ck.append(f"SESSDATA={self.sessdata}")
        if self.buvid3:
            ck.append(f"buvid3={self.buvid3}")
        if self.buvid4:
            ck.append(f"buvid4={self.buvid4}")
        for k, v in self.extra_cookies.items():
            ck.append(f"{k}={v}")
        h = {"User-Agent": UA, "Referer": REFERER, "Origin": "https://www.bilibili.com",
             "Accept": "application/json, text/plain, */*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}
        if ck:
            h["Cookie"] = "; ".join(ck)
        return h

    def _headers_for(self, url: str) -> dict:
        """cookie 只发给 api.bilibili.com，字幕 CDN 等其它域名不带。"""
        h = self.headers()
        if not url.startswith(API):
            h.pop("Cookie", None)
        return h

    def safe_headers(self) -> dict:
        h = self.headers()
        if "Cookie" in h:
            h["Cookie"] = redact(h["Cookie"], self.sessdata)
        return h

    async def _throttle(self):
        async with self._lock:
            wait = self._last + random.uniform(*self.interval) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def _get_json(self, url: str, params: dict | None = None, throttle=True) -> dict:
        if throttle:
            await self._throttle()
        base = url.split("?")[0]
        try:
            async with self._sess().get(url, params=params, headers=self._headers_for(url),
                                        timeout=self.timeout) as r:
                if r.status in (412, 429):
                    raise BiliRisk(f"HTTP {r.status}：被风控或限流（{base}），当晚应停止")
                if r.status >= 400:
                    raise BiliError(f"HTTP {r.status}（{base}）")
                txt = await r.text()
        except asyncio.TimeoutError:
            raise BiliError(f"请求超时（{self.timeout.total}s）：{base}")
        except aiohttp.ClientError as e:
            raise BiliError(f"网络错误：{redact(e, self.sessdata)}")
        try:
            return json.loads(txt)
        except ValueError:
            raise BiliError("B 站返回了非 JSON 内容（可能被拦截）")

    async def _api(self, path: str, params: dict | None = None, use_wbi=False):
        if not self._ready and path != "/x/frontend/finger/spi":
            await self.ensure_buvid()  # 首次请求前先预热 cookie
        params = dict(params or {})
        if use_wbi:
            img, sub = await self._wbi_keys()
            params = wbi.sign_params(params, img, sub)
        data = await self._get_json(API + path, params)
        code = data.get("code", 0)
        if code in RISK_CODES:
            raise BiliRisk(explain_code(code, data.get("message", "")))
        if code != 0:
            raise BiliError(explain_code(code, data.get("message", "")))
        return data.get("data")

    async def _wbi_keys(self):
        if self._wbi and time.time() - self._wbi_at < 3600:
            return self._wbi
        data = await self._get_json(API + "/x/web-interface/nav")
        d = data.get("data") or {}
        img = d.get("wbi_img") or {}
        if not img.get("img_url"):
            raise BiliError("取不到 WBI 密钥（nav 接口无 wbi_img）")
        self._wbi = (wbi.key_from_url(img["img_url"]), wbi.key_from_url(img["sub_url"]))
        self._wbi_at = time.time()
        return self._wbi

    async def warm_up(self):
        """像浏览器一样先访问一次首页，拿到 buvid3 / b_nut 等 cookie（缺这些时搜索类接口很容易 412）。"""
        try:
            await self._throttle()
            hdr = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                   "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"}
            async with self._sess().get("https://www.bilibili.com/", headers=hdr,
                                        timeout=self.timeout) as r:
                for k, m in r.cookies.items():
                    if k == "buvid3" and not self.buvid3:
                        self.buvid3 = m.value
                    elif k == "buvid4" and not self.buvid4:
                        self.buvid4 = m.value
                    elif k in ("b_nut", "_uuid", "b_lsid", "buvid_fp"):
                        self.extra_cookies[k] = m.value
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("首页预热失败（继续）: %s", type(e).__name__)

    async def ensure_buvid(self):
        if self._ready:
            return
        self._ready = True
        if not self.buvid3:
            await self.warm_up()
        if self.buvid3:
            return
        try:
            d = await self._api("/x/frontend/finger/spi")
            self.buvid3, self.buvid4 = d.get("b_3", ""), d.get("b_4", "")
        except BiliRisk:
            raise
        except BiliError as e:
            log.warning("获取 buvid 失败（继续无 buvid）: %s", e)

    # ---------- 业务 ----------
    async def nav(self) -> dict:
        data = await self._get_json(API + "/x/web-interface/nav")
        if data.get("code") in RISK_CODES:
            raise BiliRisk(explain_code(data["code"]))
        return data.get("data") or {}

    async def cookie_status(self) -> tuple[bool, str]:
        if not self.sessdata:
            return False, "未配置 SESSDATA"
        d = await self.nav()
        if d.get("isLogin"):
            return True, f"有效（用户 {d.get('uname', '?')}）"
        return False, "已失效或不正确（isLogin=false）"

    async def search(self, keyword: str, count: int = 5) -> list[dict]:
        await self.ensure_buvid()
        d = await self._api("/x/web-interface/wbi/search/type",
                            {"search_type": "video", "keyword": keyword, "page": 1, "web_location": 1430654}, use_wbi=True)
        out = []
        for it in (d.get("result") or [])[:count]:
            out.append({
                "bvid": it.get("bvid", ""), "title": strip_html(it.get("title", "")),
                "author": it.get("author", ""), "play": it.get("play", 0),
                "duration": it.get("duration", ""), "desc": it.get("description", ""),
            })
        return out

    async def popular(self, count: int = 10) -> list[dict]:
        d = await self._api("/x/web-interface/popular", {"ps": max(1, min(count, 50)), "pn": 1})
        out = []
        for it in (d.get("list") or [])[:count]:
            out.append({
                "bvid": it.get("bvid", ""), "title": it.get("title", ""),
                "author": (it.get("owner") or {}).get("name", ""),
                "play": (it.get("stat") or {}).get("view", 0),
                "duration": it.get("duration", 0), "desc": it.get("desc", ""),
            })
        return out

    async def video_info(self, bvid: str) -> dict:
        d = await self._api("/x/web-interface/wbi/view", {"bvid": bvid}, use_wbi=True)
        tags = []
        try:
            t = await self._api("/x/web-interface/view/detail/tag", {"bvid": bvid})
            tags = [x.get("tag_name", "") for x in (t or [])][:10]
        except BiliRisk:
            raise
        except BiliError:
            pass
        return {
            "bvid": d.get("bvid", bvid), "aid": d.get("aid"), "cid": d.get("cid"),
            "title": d.get("title", ""), "desc": d.get("desc", ""),
            "author": (d.get("owner") or {}).get("name", ""),
            "duration": d.get("duration", 0), "tname": d.get("tname", ""),
            "stat": d.get("stat") or {}, "tags": tags,
        }

    async def subtitles(self, bvid: str, cid: int | None = None, max_chars: int = 3000) -> str:
        """返回带时间戳字幕文本；没有则返回空串；失败抛 BiliError。"""
        if cid is None:
            cid = (await self.video_info(bvid))["cid"]
        d = await self._api("/x/player/wbi/v2", {"bvid": bvid, "cid": cid}, use_wbi=True)
        subs = ((d or {}).get("subtitle") or {}).get("subtitles") or []
        if not subs:
            return ""
        pick = next((s for s in subs if "zh" in s.get("lan", "")), subs[0])
        url = pick.get("subtitle_url", "")
        if url.startswith("//"):
            url = "https:" + url
        if not url:
            return ""
        data = await self._get_json(url)
        lines, total = [], 0
        for it in data.get("body", []):
            t0 = int(it.get("from", 0))
            line = f"[{t0 // 60}:{t0 % 60:02d}] {it.get('content', '')}"
            total += len(line) + 1
            if total > max_chars:
                lines.append("…(字幕已截断)")
                break
            lines.append(line)
        return "\n".join(lines)

    async def comments(self, aid: int, count: int = 5) -> list[dict]:
        d = await self._api("/x/v2/reply/wbi/main",
                            {"oid": aid, "type": 1, "mode": 3, "plat": 1,
                             "pagination_str": json.dumps({"offset": ""})}, use_wbi=True)
        out = []
        for r in ((d or {}).get("replies") or [])[:count]:
            out.append({"user": (r.get("member") or {}).get("uname", ""),
                        "text": (r.get("content") or {}).get("message", ""),
                        "like": r.get("like", 0)})
        return out

    async def play_url(self, bvid: str, cid: int) -> str:
        d = await self._api("/x/player/wbi/playurl",
                            {"bvid": bvid, "cid": cid, "qn": 32, "fnval": 0, "fnver": 0,
                             "platform": "html5", "high_quality": 0}, use_wbi=True)
        durl = (d or {}).get("durl") or []
        if not durl or not durl[0].get("url"):
            raise BiliError("取不到视频直链（可能地区限制/需要登录/会员内容）")
        return durl[0]["url"]

    async def resolve_bvid(self, text: str) -> str:
        """从 BV 号、完整链接或 b23.tv 短链中解析 BV 号。"""
        bvid = parse_bvid(text)
        if bvid:
            return bvid
        m = B23_RE.search(text or "")
        if not m:
            return ""
        url = m.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        try:
            async with self._sess().get(url, headers={"User-Agent": UA},
                                        allow_redirects=True, timeout=self.timeout) as r:
                return parse_bvid(str(r.url))
        except Exception:
            return ""


# ---------- 文本格式化（供工具与流水线使用）----------
def fmt_video_line(i: int, v: dict) -> str:
    desc = (v.get("desc") or "").replace("\n", " ")[:60]
    return (f"{i}. 《{v['title']}》 {v['bvid']} UP:{v['author']} 播放:{fmt_count(v['play'])} "
            f"时长:{fmt_duration(v['duration'])} 简介:{desc}")


BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
B23_RE = re.compile(r"(?:https?://)?b23\.tv/[0-9A-Za-z]+")


def parse_bvid(s: str) -> str:
    """从 BV 号或 B 站链接里取 BV 号；取不到返回空串。"""
    m = BVID_RE.search(s or "")
    return m.group(0) if m else ""


def fmt_info(v: dict) -> str:
    s = v.get("stat", {})
    return (f"《{v['title']}》{v['bvid']}\nUP:{v['author']} 分区:{v['tname']} 时长:{fmt_duration(v['duration'])}\n"
            f"播放{fmt_count(s.get('view', 0))} 点赞{fmt_count(s.get('like', 0))} 投币{fmt_count(s.get('coin', 0))} "
            f"收藏{fmt_count(s.get('favorite', 0))} 评论{fmt_count(s.get('reply', 0))}\n"
            f"标签:{'、'.join(v.get('tags', [])) or '无'}\n简介:{(v.get('desc') or '')[:300]}")


def fmt_comments(cs: list[dict]) -> str:
    return "\n".join(f"- {c['user']}（赞{c['like']}）：{c['text'][:120]}" for c in cs) or "（没有读到评论）"
