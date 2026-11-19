"""配置解析与校验（纯函数，便于测试）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_WIN_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


def parse_window(s: str):
    """'21:00-23:00' -> ((21,0),(23,0))；非法返回 None。"""
    m = _WIN_RE.match(str(s))
    if not m:
        return None
    h1, m1, h2, m2 = map(int, m.groups())
    if not (0 <= h1 < 24 and 0 <= h2 < 24 and 0 <= m1 < 60 and 0 <= m2 < 60):
        return None
    return (h1, m1), (h2, m2)


def to_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = re.split(r"[,，;；\n]", v)
    return [str(x).strip() for x in v if str(x).strip()]


def _int(v, default, lo, hi):
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _float(v, default, lo, hi):
    try:
        n = float(v)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def parse_interval(s, default=(2.0, 4.0)):
    nums = re.findall(r"\d+(?:\.\d+)?", str(s or ""))
    try:
        if len(nums) >= 2:
            a, b = float(nums[0]), float(nums[1])
        elif len(nums) == 1:
            a = b = float(nums[0])
        else:
            return default
    except ValueError:
        return default
    if a > b:
        a, b = b, a
    return (max(0.5, a), max(0.5, b))


@dataclass
class Settings:
    sessdata: str = ""
    bili_jct: str = ""
    buvid3: str = ""
    owner_qq: str = ""
    owner_umo: str = ""
    windows: list[str] = field(default_factory=list)
    wakes_per_window: int = 1
    skip_probability: float = 0.1
    timezone: str = "Europe/London"
    interests: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    candidates: int = 5
    deep_watch: int = 2
    max_frames: int = 18
    max_images_per_night: int = 8
    subtitle_max_chars: int = 4000
    diary_context_count: int = 3
    vision_model: str = "deepseek-flash"
    vision_provider_id: str = ""
    vision_mode: str = "always"
    vision_api_base: str = ""
    vision_api_key: str = ""
    chat_provider_id: str = ""
    max_share_per_day: int = 1
    lm_enabled: bool = False
    lm_auto_connect: bool = True
    lm_url: str = "http://127.0.0.1:7801"
    lm_key: str = ""
    lm_persona_id: str = ""
    lm_scope: str = ""
    interval: tuple = (2.0, 4.0)
    quiet_hours: str = "23:00-09:00"
    max_tokens_per_night: int = 100000
    offpeak_only: bool = True
    peak_holidays: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_settings(c) -> Settings:
    c = c or {}
    s = Settings()
    s.warnings = []
    s.sessdata = str(c.get("sessdata", "") or "").strip()
    s.bili_jct = str(c.get("bili_jct", "") or "").strip()
    s.buvid3 = str(c.get("buvid3", "") or "").strip()
    s.owner_qq = str(c.get("owner_qq", "") or "").strip()
    s.owner_umo = str(c.get("owner_umo", "") or "").strip()
    wins = []
    for w in to_list(c.get("schedule_windows", ["21:00-23:00"])):
        if parse_window(w):
            wins.append(w)
        else:
            s.warnings.append(f"忽略非法时间窗: {w}")
    s.windows = wins
    s.wakes_per_window = _int(c.get("wakes_per_window", 1), 1, 1, 10)
    s.skip_probability = _float(c.get("skip_probability", 0.1), 0.1, 0.0, 1.0)
    s.timezone = str(c.get("timezone") or "Europe/London").strip()
    s.interests = to_list(c.get("interests"))
    s.avoid = to_list(c.get("avoid"))
    s.candidates = _int(c.get("candidates_per_round", 5), 5, 1, 20)
    s.deep_watch = _int(c.get("deep_watch_per_round", 2), 2, 0, 5)
    s.deep_watch = min(s.deep_watch, s.candidates)
    s.max_frames = _int(c.get("max_frames_per_video", 18), 18, 0, 45)
    s.max_images_per_night = _int(c.get("max_images_per_night", 8), 8, 0, 100)
    s.subtitle_max_chars = _int(c.get("subtitle_max_chars", 4000), 4000, 200, 20000)
    s.diary_context_count = _int(c.get("diary_context_count", 3), 3, 0, 10)
    s.vision_model = str(c.get("vision_model") or "deepseek-flash").strip()
    s.vision_provider_id = str(c.get("vision_provider_id", "") or "").strip()
    vm = str(c.get("vision_mode") or "always").strip().lower()
    if vm not in ("always", "auto", "never"):
        s.warnings.append(f"vision_mode 非法，已用 always: {vm}")
        vm = "always"
    s.vision_mode = vm
    s.vision_api_base = str(c.get("vision_api_base", "") or "").strip().rstrip("/")
    s.vision_api_key = str(c.get("vision_api_key", "") or "").strip()
    s.chat_provider_id = str(c.get("chat_provider_id", "") or "").strip()
    s.max_share_per_day = _int(c.get("max_share_per_day", 1), 1, 0, 10)
    s.lm_enabled = bool(c.get("livingmemory_enabled", False))
    s.lm_auto_connect = bool(c.get("livingmemory_auto_connect", True))
    s.lm_url = str(c.get("livingmemory_url") or "http://127.0.0.1:7801").strip().rstrip("/")
    s.lm_key = str(c.get("livingmemory_api_key", "") or "").strip()
    s.lm_persona_id = str(c.get("livingmemory_persona_id", "") or "").strip()
    s.lm_scope = str(c.get("livingmemory_scope", "") or "").strip()
    s.interval = parse_interval(c.get("request_interval_seconds", "2-4"))
    q = str(c.get("quiet_hours") or "23:00-09:00")
    if q and not parse_window(q):
        s.warnings.append(f"quiet_hours 非法，已用默认: {q}")
        q = "23:00-09:00"
    s.quiet_hours = q
    s.max_tokens_per_night = _int(c.get("max_tokens_per_night", 100000), 100000, 0, 5000000)
    s.offpeak_only = bool(c.get("offpeak_only", True))
    hol = []
    for d in to_list(c.get("peak_holidays")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            hol.append(d)
        else:
            s.warnings.append(f"忽略非法节假日日期: {d}")
    s.peak_holidays = hol
    if not s.sessdata:
        s.warnings.append("未配置 sessdata：搜索可用，字幕等多数功能可能受限")
    if not s.windows:
        s.warnings.append("没有有效的 schedule_windows，不会自动醒来")
    return s
