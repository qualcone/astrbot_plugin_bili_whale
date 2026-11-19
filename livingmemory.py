"""LivingMemory 外部 HTTP 接口客户端（AGPL-3.0 项目，仅调用接口，不复制代码）。
接口依据其 docs/external-api.md：
  POST /page/external/memories  {content<=8000, importance 0..1, idempotency_key, source<=200,
                                 persona_id, scope, topics[], key_facts[]}
  GET  /page/external/personas  GET /page/external/health
  Authorization: Bearer lm_xxx
任何失败都只返回 (False, 原因)，绝不抛出。"""
from __future__ import annotations

import asyncio

import aiohttp


class LMClient:
    def __init__(self, url: str, key: str, persona_id: str = "", scope: str = "", timeout: float = 10):
        self.base = url.rstrip("/") + "/page/external"
        self.key = key
        self.persona_id = persona_id
        self.scope = scope
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    def _h(self):
        return {"Authorization": f"Bearer {self.key}"}

    async def _req(self, method, path, body=None):
        if not self.key:
            return False, "未配置 livingmemory_api_key", None
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as s:
                async with s.request(method, self.base + path, json=body, headers=self._h()) as r:
                    try:
                        data = await r.json(content_type=None)
                    except Exception:
                        data = {}
                    if not isinstance(data, dict):
                        data = {}
                    if r.status == 200 and data.get("status") == "ok":
                        return True, "ok", data
                    msg = data.get("message") or f"HTTP {r.status}"
                    if r.status == 404:
                        msg = "404：LivingMemory 的 external_api 可能未开启（需 external_api.enabled=true 并重载）"
                    return False, f"{data.get('code', r.status)}: {msg}", data
        except asyncio.TimeoutError:
            return False, "连接 LivingMemory 超时", None
        except aiohttp.ClientError as e:
            return False, f"连接 LivingMemory 失败：{type(e).__name__}", None

    async def health(self):
        ok, msg, d = await self._req("GET", "/health")
        if ok:
            msg = f"ready={d.get('ready')} v{d.get('plugin_version', '?')}"
        return ok, msg

    async def discover(self):
        """GET /personas，返回 (ok, msg, data)；用于一键连接。"""
        return await self._req("GET", "/personas")

    async def personas(self):
        ok, msg, d = await self._req("GET", "/personas")
        if ok:
            return True, f"personas={d.get('personas')} scopes={d.get('scopes')}"
        return False, msg

    def build_payload(self, content: str, importance: float, bvid: str) -> dict:
        p = {
            "content": content[:8000],
            "importance": max(0.0, min(1.0, importance)),
            "idempotency_key": f"bili-whale-{bvid}",
            "source": "bili_whale",
        }
        if self.persona_id:
            p["persona_id"] = self.persona_id
        if self.scope:
            p["scope"] = self.scope
        return p

    async def write(self, content: str, importance: float, bvid: str):
        ok, msg, d = await self._req("POST", "/memories", self.build_payload(content, importance, bvid))
        if ok:
            return True, ("已写入" if d.get("created") else "已存在(幂等跳过)")
        return False, msg


GLOBAL_SCOPE = "livingmemory:global"


def choose_target(data: dict, hints: list[str] | None = None, fallback: dict | None = None) -> dict:
    """根据 /personas 返回的数据自动选 persona_id / scope（纯函数，便于测试）。

    背景（LivingMemory 源码）：私聊召回只认 scope==私聊会话(UMO) 且 persona_id==当前人格；
    不带 scope/persona 写入会落到全局范围(livingmemory:global)且无人格，私聊召回不到。

    规则：
    - 密钥有白名单(allowed_*)：留空，由服务端取白名单第一项。
    - 无白名单：hint 精确命中（或以 ':hint' 结尾）优先；其次 fallback（机器人当前的私聊会话/人格）
      在候选里或候选为空时采用；否则只有一个候选就选它（scope 不会选全局范围）；有歧义则提示手动选择。
    返回 {"persona_id", "scope", "notes": [...]}。
    """
    hints = [h for h in (hints or []) if h]
    fallback = fallback or {}
    notes: list[str] = []
    out = {"persona_id": "", "scope": "", "notes": notes}
    for key, field, allowed_key in (("persona_id", "personas", "allowed_personas"),
                                    ("scope", "scopes", "allowed_scopes")):
        cands = [c for c in (data.get(field) or []) if c]
        if key == "scope":
            cands = [c for c in cands if c != GLOBAL_SCOPE]
        allowed = [c for c in (data.get(allowed_key) or []) if c]
        if allowed:
            notes.append(f"{field}: 密钥有白名单 {allowed}，留空由服务端取第一项")
            continue
        pick = ""
        for h in hints:
            hit = [c for c in cands if c == h or c.endswith(":" + h)]
            if len(hit) == 1:
                pick = hit[0]
                break
        fb = fallback.get(key, "")
        if not pick and fb and (not cands or fb in cands):
            pick = fb
        if not pick and len(cands) == 1:
            pick = cands[0]
        if pick:
            out[key] = pick
            notes.append(f"{field}: 自动选择 {pick}")
        elif len(cands) > 1:
            notes.append(f"{field}: 有多个候选 {cands[:10]}，请手动填 livingmemory_{key}")
        else:
            notes.append(f"{field}: 暂无候选且取不到当前值，请手动填 livingmemory_{key}")
    return out
