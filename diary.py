"""日记文件：一晚一篇 Markdown，按日期命名。"""
from __future__ import annotations

from pathlib import Path


def diary_path(root, date_str: str) -> Path:
    return Path(root) / f"{date_str}.md"


def write_entry(root, date_str: str, entry: str) -> Path:
    """幂等追加：同一晚多次醒来追加到同一篇；完全相同的段落不重复追加。"""
    p = diary_path(root, date_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = p.read_text(encoding="utf-8")
        if entry.strip() in old:
            return p
        p.write_text(old.rstrip() + "\n\n---\n\n" + entry.strip() + "\n", encoding="utf-8")
    else:
        p.write_text(f"# {date_str} 的日记\n\n" + entry.strip() + "\n", encoding="utf-8")
    return p


def list_diaries(root) -> list[Path]:
    r = Path(root)
    return sorted(r.glob("????-??-??.md")) if r.exists() else []


def latest(root) -> Path | None:
    d = list_diaries(root)
    return d[-1] if d else None


def recent_text(root, n: int, max_chars: int = 1500) -> str:
    parts = []
    for p in (list_diaries(root)[-n:] if n > 0 else []):
        t = p.read_text(encoding="utf-8")
        parts.append(f"【{p.stem}】\n{t[-max_chars:]}")
    return "\n\n".join(parts)
