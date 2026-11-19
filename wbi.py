"""B 站 WBI 签名。思路参考 dsh-bili-whale (MIT) 的 bili-api.mjs，Python 独立重写。"""
from __future__ import annotations

import hashlib
import time
import urllib.parse

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def key_from_url(url: str) -> str:
    """从 wbi_img.img_url / sub_url 取文件名（不含扩展名）作为密钥。"""
    name = url.rsplit("/", 1)[-1]
    return name.split(".", 1)[0]


def get_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_params(params: dict, img_key: str, sub_key: str, wts: int | None = None) -> dict:
    """返回带 wts 与 w_rid 的新参数字典。"""
    mixin = get_mixin_key(img_key, sub_key)
    p = dict(params)
    p["wts"] = int(time.time()) if wts is None else int(wts)
    cleaned = {}
    for k in sorted(p):
        v = "".join(ch for ch in str(p[k]) if ch not in "!'()*")
        cleaned[k] = v
    query = urllib.parse.urlencode(cleaned, quote_via=urllib.parse.quote)
    cleaned["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return cleaned
