"""作息：时间窗内随机取时刻、跳过概率、计划持久化、安静时段。"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    from .config import parse_window
except ImportError:  # 直接运行测试时
    from config import parse_window

MISSED_GRACE = timedelta(hours=2)
# DeepSeek 高价时段按北京时间（UTC+8，无夏令时，用固定偏移最稳）：工作日（不含法定节假日）9-12、14-18。
CN_TZ = timezone(timedelta(hours=8))


def is_peak(dt: datetime, holidays=frozenset()) -> bool:
    """dt 所在时刻是否处于 DeepSeek 高价时段。holidays 为法定节假日 YYYY-MM-DD 集合（按低价算）。"""
    b = dt.astimezone(CN_TZ)
    if b.weekday() >= 5 or b.date().isoformat() in holidays:
        return False
    return 9 <= b.hour < 12 or 14 <= b.hour < 18


def next_offpeak(dt: datetime, holidays=frozenset()) -> datetime:
    t = dt
    for _ in range(24 * 60):
        if not is_peak(t, holidays):
            return t
        t += timedelta(minutes=1)
    return t


def get_tz(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def window_bounds(day: date, window: str, tz) -> tuple[datetime, datetime]:
    (h1, m1), (h2, m2) = parse_window(window)
    start = datetime.combine(day, time(h1, m1), tzinfo=tz)
    end = datetime.combine(day, time(h2, m2), tzinfo=tz)
    if end <= start:  # 跨午夜
        end += timedelta(days=1)
    return start, end


def pick_times(day: date, window: str, wakes: int, skip_prob: float, rng: random.Random, tz,
               avoid=None) -> list[datetime]:
    """在窗口内随机取 wakes 个时刻（避开整点/半点），每个以 skip_prob 概率被跳过。"""
    start, end = window_bounds(day, window, tz)
    span = int((end - start).total_seconds())
    out = []
    for _ in range(wakes):
        if rng.random() < skip_prob:
            continue
        found = None
        for _try in range(80):
            t = start + timedelta(seconds=rng.randint(0, max(0, span - 1)))
            if t.minute in (0, 30):
                continue
            if avoid and avoid(t):
                continue  # 例如高价时段
            found = t
            break
        if found:
            out.append(found)
    return sorted(out)


def ensure_plan(state, day: date, windows: list[str], wakes: int, skip_prob: float, tz, rng=None,
                avoid=None) -> dict:
    """为某天生成计划；已存在的窗口不重新生成（重启不丢、同窗口不重复）。"""
    rng = rng or random.Random()
    key = day.isoformat()
    plan = state.data["plans"].setdefault(key, {})
    changed = False
    for w in windows:
        if w not in plan:
            times = pick_times(day, w, wakes, skip_prob, rng, tz, avoid)
            plan[w] = {"times": [t.isoformat() for t in times], "done": []}
            changed = True
    # 只保留最近几天
    for old in sorted(state.data["plans"])[:-4]:
        del state.data["plans"][old]
        changed = True
    if changed:
        state.save()
    return plan


def pending_wakes(state, now: datetime) -> list[tuple[str, str, datetime]]:
    """返回 [(date_key, window, time)] 未完成的、按时间排序。"""
    out = []
    for dk, plan in state.data["plans"].items():
        for w, p in plan.items():
            for iso in p["times"]:
                if iso not in p["done"]:
                    out.append((dk, w, datetime.fromisoformat(iso)))
    return sorted(out, key=lambda x: x[2])


def due_wake(state, now: datetime):
    """取出已到点且未过期的第一个；过期太久的标记为 missed。"""
    for dk, w, t in pending_wakes(state, now):
        if t > now:
            return None
        p = state.data["plans"][dk][w]
        if now - t > MISSED_GRACE:
            p["done"].append(t.isoformat())
            state.save()
            continue
        return dk, w, t
    return None


def mark_done(state, dk: str, w: str, t: datetime):
    p = state.data["plans"][dk][w]
    iso = t.isoformat()
    if iso not in p["done"]:
        p["done"].append(iso)
        state.save()


def in_quiet(now: datetime, quiet: str) -> bool:
    pw = parse_window(quiet) if quiet else None
    if not pw:
        return False
    (h1, m1), (h2, m2) = pw
    cur = now.hour * 60 + now.minute
    a, b = h1 * 60 + m1, h2 * 60 + m2
    if a == b:
        return False
    return (a <= cur < b) if a < b else (cur >= a or cur < b)


def looks_like_deepseek(provider) -> bool:
    """AstrBot 提供商是否为 DeepSeek（看提供商 ID、api_base、模型名）；用于只对 DeepSeek 启用低价时段调度。"""
    conf = getattr(provider, "provider_config", None) or {}
    parts = [str(conf.get(k, "")) for k in ("id", "api_base", "model")]
    try:
        parts.append(str(provider.get_model()))
    except Exception:
        pass
    return "deepseek" in " ".join(parts).lower()
