"""持久化状态（JSON，原子写入）。放在 AstrBot 插件数据目录。"""
from __future__ import annotations

import json
import os
from pathlib import Path


class State:
    DEFAULT = {
        "plans": {},        # "YYYY-MM-DD" -> {window: {"times": [iso], "done": [iso]}}
        "seen": {},         # bvid -> {"date":..., "level": "skim"|"deep"}
        "shares": {},       # "YYYY-MM-DD" -> [bvid]
        "target_shares": {},    # target_key -> {"YYYY-MM-DD": [bvid]}
        "mem_done": [],     # 已写入 LivingMemory 的 bvid
        "target_mem_done": {},  # target_key -> [bvid]
        "risk": {},         # {"date":..., "reason":...}
        "pending_share": None,
        "pending_shares": {},   # target_key -> {"text": ..., "bvid": ...}
        "owner_umo": "",
        "target_umos": {},      # target_key -> umo
        "usage": {},        # date -> {images, videos, prompt_tokens, completion_tokens}
        "last_run": None,
        "lm_last": "",
    }

    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(json.dumps(self.DEFAULT))
        self.load()

    def load(self):
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in d.items():
                    self.data[k] = v
        except Exception:
            # 损坏的状态文件：备份后重新开始，不让插件崩溃
            try:
                os.replace(self.path, self.path.with_suffix(".corrupt"))
            except OSError:
                pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- 已看 ----
    def is_seen(self, bvid: str) -> bool:
        return bvid in self.data["seen"]

    def mark_seen(self, bvid: str, date: str, level: str = "deep"):
        cur = self.data["seen"].get(bvid)
        if cur and cur.get("level") == "deep" and level == "skim":
            return
        self.data["seen"][bvid] = {"date": date, "level": level}
        self.save()

    # ---- 分享 ----
    def shares_on(self, date: str, target_key: str = "") -> list:
        if not target_key:
            return list(self.data["shares"].get(date, []))
        return list(self.data.setdefault("target_shares", {}).get(target_key, {}).get(date, []))

    def add_share(self, date: str, bvid: str, target_key: str = ""):
        if not target_key:
            self.data["shares"].setdefault(date, []).append(bvid)
        else:
            self.data.setdefault("target_shares", {}).setdefault(target_key, {}).setdefault(date, []).append(bvid)
        self.save()

    def was_shared(self, bvid: str, target_key: str = "") -> bool:
        if not target_key:
            return any(bvid in v for v in self.data["shares"].values())
        return any(bvid in v for v in self.data.setdefault("target_shares", {}).get(target_key, {}).values())

    # ---- 记忆 ----
    def mem_written(self, bvid: str, target_key: str = "") -> bool:
        if not target_key:
            return bvid in self.data["mem_done"]
        return bvid in self.data.setdefault("target_mem_done", {}).get(target_key, [])

    def mark_mem(self, bvid: str, target_key: str = ""):
        if not target_key:
            if bvid not in self.data["mem_done"]:
                self.data["mem_done"].append(bvid)
                self.save()
        else:
            arr = self.data.setdefault("target_mem_done", {}).setdefault(target_key, [])
            if bvid not in arr:
                arr.append(bvid)
                self.save()

    # ---- 风控 ----
    def set_risk(self, date: str, reason: str):
        self.data["risk"] = {"date": date, "reason": reason}
        self.save()

    def risk_today(self, date: str):
        r = self.data.get("risk") or {}
        return r.get("reason") if r.get("date") == date else None

    def clear_risk(self):
        self.data["risk"] = {}
        self.save()

    # ---- 用量 ----
    def usage(self, date: str) -> dict:
        return self.data["usage"].setdefault(
            date, {"images": 0, "videos": 0, "prompt_tokens": 0, "completion_tokens": 0,
                  "chat_tokens": 0}
        )

    def tokens_used(self, date: str) -> int:
        u = self.usage(date)
        return int(u.get("chat_tokens", 0) + u.get("prompt_tokens", 0) + u.get("completion_tokens", 0))

    def add_usage(self, date: str, **kw):
        u = self.usage(date)
        for k, v in kw.items():
            u[k] = u.get(k, 0) + int(v)
        for old in sorted(self.data["usage"])[:-30]:  # 只留最近 30 天
            del self.data["usage"][old]
        self.save()
