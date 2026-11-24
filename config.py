"""配置解析与校验（纯函数，便于测试）。"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

_WIN_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")

SECTION_MAP: dict[str, tuple[str, ...]] = {
    "bilibili_section": ("sessdata", "buvid3", "request_interval_seconds"),
    "model_vision_section": (
        "chat_provider_id", "vision_mode", "vision_api_key", "vision_api_base",
        "vision_model", "vision_provider_id", "max_frames_per_video",
        "max_images_per_night", "max_tokens_per_night",
    ),
    "targets_share_section": ("targets", "owner_qq", "owner_umo", "max_share_per_day", "quiet_hours"),
    "browse_diary_section": (
        "interests", "avoid", "candidates_per_round", "deep_watch_per_round",
        "subtitle_max_chars", "diary_context_count",
    ),
    "schedule_section": (
        "schedule_windows", "wakes_per_window", "skip_probability",
        "timezone", "offpeak_mode", "peak_holidays",
    ),
    "livingmemory_section": (
        "livingmemory_enabled", "livingmemory_auto_connect", "livingmemory_url",
        "livingmemory_api_key", "livingmemory_persona_id", "livingmemory_scope",
    ),
}

LEGACY_DEFAULTS: dict[str, object] = {
    "sessdata": "",
    "buvid3": "",
    "request_interval_seconds": "2-4",
    "chat_provider_id": "",
    "vision_mode": "always",
    "vision_api_key": "",
    "vision_api_base": "https://api.deepseek.com/v1",
    "vision_model": "deepseek-flash",
    "vision_provider_id": "",
    "max_frames_per_video": 18,
    "max_images_per_night": 8,
    "max_tokens_per_night": 100000,
    "targets": [],
    "owner_qq": "",
    "owner_umo": "",
    "max_share_per_day": 1,
    "quiet_hours": "23:00-09:00",
    "interests": ["科普", "纪录片", "猫", "音乐", "手工"],
    "avoid": [],
    "candidates_per_round": 5,
    "deep_watch_per_round": 2,
    "subtitle_max_chars": 4000,
    "diary_context_count": 3,
    "schedule_windows": ["21:00-23:00"],
    "wakes_per_window": 1,
    "skip_probability": 0.1,
    "timezone": "Europe/London",
    "offpeak_mode": "auto",
    "peak_holidays": [],
    "livingmemory_enabled": False,
    "livingmemory_auto_connect": True,
    "livingmemory_url": "http://127.0.0.1:7801",
    "livingmemory_api_key": "",
    "livingmemory_persona_id": "",
    "livingmemory_scope": "",
}


def migrate_legacy_config(raw_config) -> bool:
    """将旧版平铺顶层配置无损迁移到新版二级菜单分组，并重置隐藏旧键以避免覆盖后续修改。"""
    if not isinstance(raw_config, dict):
        return False
    changed = False
    for section, keys in SECTION_MAP.items():
        sec = raw_config.get(section)
        if not isinstance(sec, dict):
            continue
        for k in keys:
            if k not in raw_config:
                continue
            default = LEGACY_DEFAULTS[k]
            legacy_val = raw_config[k]
            nested_val = sec.get(k, default)
            if legacy_val != default:
                if nested_val == default:
                    sec[k] = copy.deepcopy(legacy_val)
                raw_config[k] = copy.deepcopy(default)
                changed = True
    return changed


def _flatten_config(c) -> dict:
    """同时兼容新版二级菜单嵌套结构与旧版平铺结构，返回统一字典供 parse_settings 读取。"""
    if not isinstance(c, dict):
        return {}
    flat = {k: v for k, v in c.items() if k not in SECTION_MAP}
    for section, keys in SECTION_MAP.items():
        sec = c.get(section)
        if not isinstance(sec, dict):
            continue
        for k in keys:
            if k not in sec:
                continue
            default = LEGACY_DEFAULTS[k]
            nested_val = sec[k]
            if nested_val != default or k not in flat or flat[k] == default:
                flat[k] = nested_val
    return flat


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
class TargetConfig:
    """单个目标对话（及对应人格、LivingMemory）配置。"""
    key: str = ""
    enabled: bool = True
    name: str = ""
    owner_qq: str = ""
    owner_umo: str = ""
    persona_id: str = ""
    lm_mode: str = "inherit"   # inherit | on | off
    lm_url: str = ""
    lm_key: str = ""
    lm_persona_id: str = ""
    lm_scope: str = ""


def _parse_targets(raw, warnings: list[str]) -> list[TargetConfig]:
    out: list[TargetConfig] = []
    if not isinstance(raw, list):
        return out
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        qq = str(item.get("owner_qq", "") or "").strip()
        umo = str(item.get("owner_umo", "") or "").strip()
        name = str(item.get("name", "") or "").strip()
        lm_mode = str(item.get("livingmemory_mode") or "inherit").strip().lower()
        if lm_mode not in ("inherit", "on", "off"):
            warnings.append(f"第 {idx + 1} 组目标的 livingmemory_mode 非法，已用 inherit: {lm_mode}")
            lm_mode = "inherit"
        key = umo or (f"qq:{qq}" if qq else f"idx:{idx}")
        out.append(TargetConfig(
            key=key,
            enabled=bool(item.get("enabled", True)),
            name=name or umo or (f"QQ {qq}" if qq else f"对话组{idx + 1}"),
            owner_qq=qq,
            owner_umo=umo,
            persona_id=str(item.get("persona_id", "") or "").strip(),
            lm_mode=lm_mode,
            lm_url=str(item.get("livingmemory_url") or "").strip().rstrip("/"),
            lm_key=str(item.get("livingmemory_api_key", "") or "").strip(),
            lm_persona_id=str(item.get("livingmemory_persona_id", "") or "").strip(),
            lm_scope=str(item.get("livingmemory_scope", "") or "").strip(),
        ))
    return out


@dataclass
class Settings:
    sessdata: str = ""
    bili_jct: str = ""
    buvid3: str = ""
    owner_qq: str = ""
    owner_umo: str = ""
    targets: list[TargetConfig] = field(default_factory=list)
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
    vision_api_key: str = ""
    vision_api_base: str = "https://api.deepseek.com/v1"
    vision_model: str = "deepseek-flash"
    vision_provider_id: str = ""
    vision_mode: str = "always"
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
    offpeak_mode: str = "auto"  # auto：仅在使用 DeepSeek 时按低价时段调度；off：不限制
    peak_holidays: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def effective_targets(self) -> list[TargetConfig]:
        """返回生效的目标对话列表；若同时存在旧版顶层设置且未在 targets 中重复配置，则自动保留。"""
        enabled = [t for t in self.targets if t.enabled]
        if not self.targets:
            return [TargetConfig(
                key="",
                enabled=True,
                name="默认主人会话",
                owner_qq=self.owner_qq,
                owner_umo=self.owner_umo,
                persona_id="",
                lm_mode="inherit",
            )]
        has_legacy_in_list = any(
            (self.owner_umo and t.owner_umo == self.owner_umo)
            or (self.owner_qq and t.owner_qq == self.owner_qq)
            for t in self.targets
        )
        if (self.owner_qq or self.owner_umo) and not has_legacy_in_list:
            legacy = TargetConfig(
                key="",
                enabled=True,
                name="默认主人会话",
                owner_qq=self.owner_qq,
                owner_umo=self.owner_umo,
                persona_id="",
                lm_mode="inherit",
            )
            return [legacy] + enabled
        return enabled


def parse_settings(c) -> Settings:
    c = _flatten_config(c or {})
    s = Settings()
    s.warnings = []
    s.sessdata = str(c.get("sessdata", "") or "").strip()
    s.bili_jct = str(c.get("bili_jct", "") or "").strip()
    s.buvid3 = str(c.get("buvid3", "") or "").strip()
    s.owner_qq = str(c.get("owner_qq", "") or "").strip()
    s.owner_umo = str(c.get("owner_umo", "") or "").strip()
    s.targets = _parse_targets(c.get("targets"), s.warnings)
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
    s.vision_api_key = str(c.get("vision_api_key", "") or "").strip()
    s.vision_api_base = str(c.get("vision_api_base") or "https://api.deepseek.com/v1").strip().rstrip("/")
    s.vision_model = str(c.get("vision_model") or "deepseek-flash").strip()
    s.vision_provider_id = str(c.get("vision_provider_id", "") or "").strip()
    vm = str(c.get("vision_mode") or "always").strip().lower()
    if vm not in ("always", "auto", "never"):
        s.warnings.append(f"vision_mode 非法，已用 always: {vm}")
        vm = "always"
    s.vision_mode = vm
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
    om = str(c.get("offpeak_mode") or "auto").strip().lower()
    if c.get("offpeak_only") is False:  # 兼容旧版配置项
        om = "off"
    if om not in ("auto", "off"):
        s.warnings.append(f"offpeak_mode 非法，已用 auto: {om}")
        om = "auto"
    s.offpeak_mode = om
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
