import random
from datetime import date, datetime, timedelta, timezone

import pytest

from astrbot_plugin_bili_whale import diary, wbi
from astrbot_plugin_bili_whale.bili_client import redact
from astrbot_plugin_bili_whale.config import parse_interval, parse_settings, parse_window
from astrbot_plugin_bili_whale.livingmemory import LMClient
from astrbot_plugin_bili_whale.pipeline import contains_avoid, extract_json
from astrbot_plugin_bili_whale.scheduler import (due_wake, ensure_plan, in_quiet, mark_done,
                                                 pick_times)
from astrbot_plugin_bili_whale.state import State

UTC = timezone.utc


# ---- WBI ----
# 密钥取自 B 站社区文档示例；w_rid 期望值由独立的 md5sum 计算得出（不是官方向量）：
#   md5("bar=514&foo=114&wts=1684746387&zab=1919810" + mixin_key)
IMG, SUB = "7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45"


def test_wbi_mixin_key():
    assert wbi.get_mixin_key(IMG, SUB) == "ea1db124af3c7062474693fa704f4ff8"


def test_wbi_sign_regression():
    p = wbi.sign_params({"foo": "114", "bar": "514", "zab": 1919810}, IMG, SUB, wts=1684746387)
    assert p["w_rid"] == "a1d48f59663db6078c92dccb249618ba"
    assert str(p["wts"]) == "1684746387"


def test_wbi_strips_special_chars():
    a = wbi.sign_params({"q": "a!b'c(d)e*f"}, IMG, SUB, wts=1)
    b = wbi.sign_params({"q": "abcdef"}, IMG, SUB, wts=1)
    assert a["q"] == "abcdef" and a["w_rid"] == b["w_rid"]


def test_key_from_url():
    assert wbi.key_from_url("https://i0.hdslb.com/bfs/wbi/abc123.png") == "abc123"


# ---- 作息 ----
def test_pick_times_inside_window_and_not_round():
    tz = UTC
    for seed in range(30):
        ts = pick_times(date(2026, 1, 1), "21:00-23:00", 3, 0.0, random.Random(seed), tz)
        assert len(ts) == 3
        for t in ts:
            assert datetime(2026, 1, 1, 21, tzinfo=tz) <= t < datetime(2026, 1, 1, 23, tzinfo=tz)
            assert t.minute not in (0, 30)


def test_skip_probability():
    assert pick_times(date(2026, 1, 1), "21:00-23:00", 5, 1.0, random.Random(1), UTC) == []
    assert len(pick_times(date(2026, 1, 1), "21:00-23:00", 5, 0.0, random.Random(1), UTC)) == 5


def test_window_crossing_midnight():
    ts = pick_times(date(2026, 1, 1), "23:00-01:00", 5, 0.0, random.Random(3), UTC)
    assert all(datetime(2026, 1, 1, 23, tzinfo=UTC) <= t < datetime(2026, 1, 2, 1, tzinfo=UTC) for t in ts)


def test_plan_persists_and_not_regenerated(tmp_path):
    s = State(tmp_path / "s.json")
    p1 = ensure_plan(s, date(2026, 1, 1), ["21:00-23:00"], 1, 0.0, UTC, random.Random(1))
    t1 = list(p1["21:00-23:00"]["times"])
    s2 = State(tmp_path / "s.json")  # 模拟重启
    p2 = ensure_plan(s2, date(2026, 1, 1), ["21:00-23:00"], 1, 0.0, UTC, random.Random(999))
    assert p2["21:00-23:00"]["times"] == t1


def test_due_and_done_not_repeated(tmp_path):
    s = State(tmp_path / "s.json")
    plan = ensure_plan(s, date(2026, 1, 1), ["21:00-23:00"], 1, 0.0, UTC, random.Random(1))
    t = datetime.fromisoformat(plan["21:00-23:00"]["times"][0])
    assert due_wake(s, t - timedelta(minutes=1)) is None
    d = due_wake(s, t + timedelta(minutes=1))
    assert d and d[2] == t
    mark_done(s, *d)
    assert due_wake(s, t + timedelta(minutes=2)) is None


def test_missed_wake_expires(tmp_path):
    s = State(tmp_path / "s.json")
    plan = ensure_plan(s, date(2026, 1, 1), ["21:00-23:00"], 1, 0.0, UTC, random.Random(1))
    t = datetime.fromisoformat(plan["21:00-23:00"]["times"][0])
    assert due_wake(s, t + timedelta(hours=5)) is None


def test_quiet_hours():
    assert in_quiet(datetime(2026, 1, 1, 23, 30, tzinfo=UTC), "23:00-09:00")
    assert in_quiet(datetime(2026, 1, 1, 3, 0, tzinfo=UTC), "23:00-09:00")
    assert not in_quiet(datetime(2026, 1, 1, 9, 0, tzinfo=UTC), "23:00-09:00")
    assert not in_quiet(datetime(2026, 1, 1, 15, 0, tzinfo=UTC), "23:00-09:00")


# ---- 已看去重 / 状态 ----
def test_seen_dedup_and_persist(tmp_path):
    s = State(tmp_path / "s.json")
    assert not s.is_seen("BV1")
    s.mark_seen("BV1", "2026-01-01", "skim")
    s.mark_seen("BV1", "2026-01-01", "deep")
    s.mark_seen("BV1", "2026-01-02", "skim")  # 不能把 deep 降级
    assert State(tmp_path / "s.json").data["seen"]["BV1"]["level"] == "deep"


def test_mem_and_share_idempotent(tmp_path):
    s = State(tmp_path / "s.json")
    s.mark_mem("BV1")
    s.mark_mem("BV1")
    assert s.data["mem_done"] == ["BV1"]
    s.add_share("2026-01-01", "BV1")
    assert s.was_shared("BV1") and len(s.shares_on("2026-01-01")) == 1


def test_risk_only_today(tmp_path):
    s = State(tmp_path / "s.json")
    s.set_risk("2026-01-01", "-352")
    assert s.risk_today("2026-01-01") == "-352"
    assert s.risk_today("2026-01-02") is None


def test_corrupt_state_recovers(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    s = State(p)
    assert s.data["seen"] == {}


# ---- 日记 ----
def test_diary_path_and_idempotent_append(tmp_path):
    p = diary.write_entry(tmp_path, "2026-01-01", "## 21:10 醒来\n\n内容A")
    assert p.name == "2026-01-01.md"
    diary.write_entry(tmp_path, "2026-01-01", "## 21:10 醒来\n\n内容A")  # 同段落不重复
    assert p.read_text(encoding="utf-8").count("内容A") == 1
    diary.write_entry(tmp_path, "2026-01-01", "## 22:00 醒来\n\n内容B")
    assert "内容B" in p.read_text(encoding="utf-8")
    assert diary.latest(tmp_path) == p
    assert "内容B" in diary.recent_text(tmp_path, 3)


# ---- LivingMemory 载荷 ----
def test_lm_payload():
    c = LMClient("http://127.0.0.1:7801/", "lm_x", "p1", "s1")
    p = c.build_payload("x" * 9000, 1.7, "BV1abc")
    assert p["idempotency_key"] == "bili-whale-BV1abc"
    assert p["source"] == "bili_whale" and p["importance"] == 1.0
    assert len(p["content"]) == 8000 and p["persona_id"] == "p1" and p["scope"] == "s1"
    assert c.base == "http://127.0.0.1:7801/page/external"
    assert "persona_id" not in LMClient("http://x", "k").build_payload("a", 0.4, "BV2")


# ---- 配置解析 ----
def test_parse_window():
    assert parse_window("21:00-23:00") == ((21, 0), (23, 0))
    assert parse_window("25:00-23:00") is None
    assert parse_window("abc") is None


def test_parse_interval():
    assert parse_interval("2-4") == (2.0, 4.0)
    assert parse_interval("5-3") == (3.0, 5.0)
    assert parse_interval("garbage") == (2.0, 4.0)


def test_parse_settings_defaults_and_clamp():
    s = parse_settings({"schedule_windows": ["21:00-23:00", "bad"], "skip_probability": 9,
                        "candidates_per_round": "x", "interests": "猫, 音乐，科普",
                        "deep_watch_per_round": 99, "quiet_hours": "oops"})
    assert s.windows == ["21:00-23:00"]
    assert s.skip_probability == 1.0
    assert s.candidates == 5 and s.deep_watch == 5
    assert s.interests == ["猫", "音乐", "科普"]
    assert s.quiet_hours == "23:00-09:00"
    assert any("非法" in w for w in s.warnings)


# ---- 杂项 ----
def test_redact_secret():
    assert "abc123" not in redact("Cookie: SESSDATA=abc123; x=1", "abc123")
    assert "abc123" not in redact("failed with abc123 inside", "abc123")


def test_extract_json_and_avoid():
    assert extract_json('```json\n[{"bvid":"BV1","score":7}]\n```')[0]["score"] == 7
    assert extract_json('说明 {"a":1} 结尾') == {"a": 1}
    assert extract_json("没有json") is None
    assert contains_avoid("一个 Pua 教程", ["pua"])


# ---- 分镜图 / 视觉 ----
def test_frames_helpers():
    from astrbot_plugin_bili_whale import frames as fr
    assert fr.timestamps(100, 4) == [12.5, 37.5, 62.5, 87.5]
    assert fr.timestamps(0, 4) == []
    assert fr.fmt_ts(75) == "1:15"
    assert fr.boards_for(18, 8) == 2
    assert fr.boards_for(18, 1) == 1      # 受每晚剩余额度限制
    assert fr.boards_for(10, 8) == 2      # 10 帧 -> 2 张
    assert fr.boards_for(0, 8) == 0 and fr.boards_for(18, 0) == 0
    assert [len(c) for c in fr.chunk(list(range(20)), 9)] == [9, 9, 2]
    p = fr.board_prompt("t", [1.0, 62.0], 1, 2)
    assert "1=0:01" in p and "2=1:02" in p and "1/2" in p


def test_vision_mode_parse():
    assert parse_settings({"vision_mode": "AUTO"}).vision_mode == "auto"
    s = parse_settings({"vision_mode": "bogus"})
    assert s.vision_mode == "always" and any("vision_mode" in w for w in s.warnings)
    d = parse_settings({})
    assert d.max_frames == 18 and d.max_images_per_night == 8


# ---- DeepSeek 高价时段（北京时间）----
def test_is_peak_beijing_time():
    from astrbot_plugin_bili_whale.scheduler import is_peak, next_offpeak
    # 2026-11-18 是周三。北京 10:00 = UTC 02:00 -> 高价
    assert is_peak(datetime(2026, 11, 18, 2, 0, tzinfo=UTC))
    assert not is_peak(datetime(2026, 11, 18, 4, 30, tzinfo=UTC))   # 北京 12:30 午休
    assert is_peak(datetime(2026, 11, 18, 7, 0, tzinfo=UTC))        # 北京 15:00
    assert not is_peak(datetime(2026, 11, 18, 10, 0, tzinfo=UTC))   # 北京 18:00 起低价
    assert not is_peak(datetime(2026, 11, 21, 2, 0, tzinfo=UTC))    # 周六
    # 法定节假日（工作日）按低价
    assert not is_peak(datetime(2026, 11, 18, 2, 0, tzinfo=UTC), {"2026-11-18"})
    n = next_offpeak(datetime(2026, 11, 18, 2, 0, tzinfo=UTC))
    assert n == datetime(2026, 11, 18, 4, 0, tzinfo=UTC)            # 北京 12:00


def test_london_evening_is_offpeak():
    from astrbot_plugin_bili_whale.scheduler import get_tz, is_peak
    # 伦敦 21:00-23:00（冬令时 = UTC）每天都是北京次日凌晨 5-7 点
    for day in range(16, 23):
        for h in (21, 22):
            assert not is_peak(datetime(2026, 11, day, h, 15, tzinfo=UTC))


def test_pick_times_avoid_peak():
    from astrbot_plugin_bili_whale.scheduler import is_peak
    avoid = lambda t: is_peak(t)
    # 窗口 01:00-05:00 UTC = 北京 09:00-13:00：9-12 是高价，只有 12:00 后可取
    for seed in range(20):
        ts = pick_times(date(2026, 11, 18), "01:00-05:00", 2, 0.0, random.Random(seed), UTC, avoid)
        assert all(not is_peak(t) for t in ts)
    # 整个窗口都是高价 -> 不安排
    assert pick_times(date(2026, 11, 18), "02:00-03:30", 3, 0.0, random.Random(1), UTC, avoid) == []


def test_offpeak_settings():
    s = parse_settings({"peak_holidays": "2026-10-01, bad, 2026-10-02"})
    assert s.offpeak_mode == "auto" and s.peak_holidays == ["2026-10-01", "2026-10-02"]
    assert parse_settings({"offpeak_mode": "off"}).offpeak_mode == "off"
    assert parse_settings({"offpeak_only": False}).offpeak_mode == "off"      # 兼容旧配置
    assert parse_settings({"offpeak_mode": "x"}).offpeak_mode == "auto"


# ---- token 预算 / 边界条件 ----
def test_tokens_used_and_prune(tmp_path):
    s = State(tmp_path / "s.json")
    s.add_usage("2026-01-01", chat_tokens=1000, prompt_tokens=200, completion_tokens=50)
    assert s.tokens_used("2026-01-01") == 1250
    assert s.tokens_used("2026-01-02") == 0
    for d in range(1, 40):
        s.add_usage(f"2026-02-{d:02d}" if d < 29 else f"2026-03-{d - 28:02d}", chat_tokens=1)
    assert len(s.data["usage"]) <= 30


def test_budget_setting():
    assert parse_settings({}).max_tokens_per_night == 100000
    assert parse_settings({"max_tokens_per_night": 0}).max_tokens_per_night == 0
    assert parse_settings({"max_tokens_per_night": "x"}).max_tokens_per_night == 100000


def test_extract_json_not_fooled_by_inner_brackets():
    # 旧实现的贪婪 \[.*\] 会把字段里的 [1:20] 误当成数组
    j = extract_json('{"summary":"在 [1:20] 处提到","share_score":7}')
    assert isinstance(j, dict) and j["share_score"] == 7
    assert extract_json('结果如下：[{"bvid":"BV1","score":3}] 完毕')[0]["bvid"] == "BV1"
    assert extract_json("[") is None and extract_json("") is None


def test_cookie_only_sent_to_api_host():
    from astrbot_plugin_bili_whale.bili_client import API, BiliClient
    c = BiliClient(sessdata="SECRET")
    assert "Cookie" in c._headers_for(API + "/x/web-interface/nav")
    assert "Cookie" not in c._headers_for("https://aisubtitle.hdslb.com/bfs/x.json")
    assert "SECRET" not in str(c.safe_headers())


# ---- LivingMemory 一键连接：自动选择 ----
def test_choose_target_single_candidates():
    from astrbot_plugin_bili_whale.livingmemory import choose_target
    t = choose_target({"personas": ["bot"], "scopes": ["qq:FriendMessage:123"]})
    assert t["persona_id"] == "bot" and t["scope"] == "qq:FriendMessage:123"


def test_choose_target_scope_hint_and_ambiguity():
    from astrbot_plugin_bili_whale.livingmemory import choose_target
    data = {"personas": ["a", "b"], "scopes": ["qq:FriendMessage:123", "qq:GroupMessage:9"]}
    t = choose_target(data, ["", "123"])
    assert t["scope"] == "qq:FriendMessage:123"          # 用 owner_qq 命中私聊 scope
    assert t["persona_id"] == "" and any("手动" in n for n in t["notes"])  # persona 有歧义，不乱选


def test_choose_target_allowlist_left_empty():
    from astrbot_plugin_bili_whale.livingmemory import choose_target
    t = choose_target({"personas": ["a", "b"], "scopes": ["s1", "s2"],
                       "allowed_personas": ["a"], "allowed_scopes": ["s1"]})
    assert t["persona_id"] == "" and t["scope"] == ""    # 白名单：留空交给服务端
    assert choose_target({})["persona_id"] == ""


def test_auto_connect_setting():
    assert parse_settings({}).lm_auto_connect is True
    assert parse_settings({"livingmemory_auto_connect": False}).lm_auto_connect is False


# ---- 测试唤醒 /bili test ----
def test_parse_bvid():
    from astrbot_plugin_bili_whale.bili_client import parse_bvid
    assert parse_bvid("BV1mC4y1Z7EW") == "BV1mC4y1Z7EW"
    assert parse_bvid("https://www.bilibili.com/video/BV1mC4y1Z7EW/?spm_id_from=333") == "BV1mC4y1Z7EW"
    assert parse_bvid("av123") == "" and parse_bvid("") == ""


def test_run_test_writes_nothing(tmp_path):
    import asyncio
    import json
    from astrbot_plugin_bili_whale.pipeline import Pipeline

    class FakeBili:
        async def video_info(self, b):
            return {"bvid": b, "aid": 1, "cid": 2, "title": "T", "desc": "d", "author": "u",
                    "duration": 60, "tname": "x", "stat": {}, "tags": ["a"]}

        async def subtitles(self, *a, **k):
            return "[0:01] hi"

        async def comments(self, *a, **k):
            return [{"user": "u", "text": "c", "like": 1}]

    class FakeLM:
        writes = []

        async def write(self, *a):
            FakeLM.writes.append(a)
            return True, "ok"

    sent = []

    async def llm(prompt, system):
        return '{"summary":"s","feeling":"f","memory_note":"m","share_score":9}'

    async def persona():
        return ""

    async def send(text):
        sent.append(text)
        return True

    cfg = parse_settings({})
    st = State(tmp_path / "s.json")
    p = Pipeline(cfg, st, FakeBili(), llm, persona, lambda: None, lambda: FakeLM(), send,
                 tmp_path / "diary", tmp_path / "runs", UTC, None)
    rec = asyncio.run(p.run_test("BV1mC4y1Z7EW"))
    assert rec["note"]["title"] == "T" and rec["note"]["has_subtitle"]
    assert rec["note"]["vision"] is False and "ffmpeg" in rec["note"]["vision_note"]  # 无 ffmpeg 降级
    assert FakeLM.writes == [] and sent == []                 # 不写记忆、不私信
    assert not (tmp_path / "diary").exists()                  # 不写日记
    assert not st.is_seen("BV1mC4y1Z7EW")                     # 不标记已看
    assert st.shares_on("2026-01-01") == [] and not st.data["mem_done"]
    files = list((tmp_path / "runs").glob("test_*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8"))["test"] is True
    assert p.running is False


# ---- 412 缓解：浏览器式 cookie ----
def test_browser_like_cookies_and_headers():
    from astrbot_plugin_bili_whale.bili_client import API, BiliClient
    c = BiliClient(sessdata="SECRET", buvid3="B3")
    c.extra_cookies = {"b_nut": "123"}
    h = c._headers_for(API + "/x/web-interface/wbi/search/type")
    assert "buvid3=B3" in h["Cookie"] and "b_nut=123" in h["Cookie"] and "SECRET" in h["Cookie"]
    assert h["Origin"] == "https://www.bilibili.com" and "zh-CN" in h["Accept-Language"]
    assert "Cookie" not in c._headers_for("https://aisubtitle.hdslb.com/x.json")
    assert "SECRET" not in str(c.safe_headers())


# ---- LivingMemory：库里还没有记忆时用私聊会话/当前人格 ----
def test_choose_target_fallback_when_no_candidates():
    from astrbot_plugin_bili_whale.livingmemory import choose_target
    fb = {"scope": "qq:FriendMessage:123", "persona_id": "mybot"}
    t = choose_target({"personas": [], "scopes": []}, ["qq:FriendMessage:123"], fb)
    assert t["scope"] == "qq:FriendMessage:123" and t["persona_id"] == "mybot"


def test_choose_target_never_picks_global_scope():
    from astrbot_plugin_bili_whale.livingmemory import choose_target
    fb = {"scope": "qq:FriendMessage:123", "persona_id": ""}
    t = choose_target({"personas": [], "scopes": ["livingmemory:global"]}, [], fb)
    assert t["scope"] == "qq:FriendMessage:123"          # 不会被"唯一候选"误选成全局
    t2 = choose_target({"personas": [], "scopes": ["livingmemory:global"]}, [], {})
    assert t2["scope"] == "" and any("手动" in n for n in t2["notes"])


def test_choose_target_fallback_persona_in_candidates():
    from astrbot_plugin_bili_whale.livingmemory import choose_target
    t = choose_target({"personas": ["a", "mybot"], "scopes": []}, [], {"persona_id": "mybot"})
    assert t["persona_id"] == "mybot"
    t2 = choose_target({"personas": ["a", "b"], "scopes": []}, [], {"persona_id": "zzz"})
    assert t2["persona_id"] == ""                        # 当前人格不在候选里且候选不为空：不乱选


# ---- 记忆单条长度 ----
def test_memory_content_capped_at_500(tmp_path):
    import asyncio
    from astrbot_plugin_bili_whale.pipeline import MEMORY_MAX_CHARS, Pipeline

    class FakeLM:
        got = []

        async def write(self, content, imp, bvid):
            FakeLM.got.append((content, imp, bvid))
            return True, "已写入"

    async def llm(p, s):
        return ""

    async def persona():
        return ""

    async def send(t):
        return True

    st = State(tmp_path / "s.json")
    p = Pipeline(parse_settings({}), st, None, llm, persona, lambda: None, lambda: FakeLM(), send,
                 tmp_path / "d", tmp_path / "r", UTC, None)
    note = {"bvid": "BV1", "title": "标题", "memory_note": "字" * 900, "summary": "", "share_score": 9}
    rec = {}
    asyncio.run(p.write_memory([note], rec))
    content, imp, bvid = FakeLM.got[0]
    assert MEMORY_MAX_CHARS == 500 and len(content) <= 500 and content.startswith("看过《标题》（BV1")
    assert imp == 0.5 and bvid == "BV1" and st.mem_written("BV1")
    asyncio.run(p.write_memory([note], rec))             # 再写一次：本地去重，不重复调用
    assert len(FakeLM.got) == 1


# ---- 仅对 DeepSeek 启用低价时段 ----
def test_looks_like_deepseek():
    from types import SimpleNamespace as NS
    from astrbot_plugin_bili_whale.scheduler import looks_like_deepseek
    assert looks_like_deepseek(NS(provider_config={"id": "ds", "api_base": "https://api.deepseek.com/v1"}))
    assert looks_like_deepseek(NS(provider_config={"model": "DeepSeek-V3"}))
    assert looks_like_deepseek(NS(provider_config={}, get_model=lambda: "deepseek-flash"))
    assert not looks_like_deepseek(NS(provider_config={"id": "gpt", "api_base": "https://api.openai.com/v1"},
                                      get_model=lambda: "gpt-5"))
    assert not looks_like_deepseek(object())


def test_pipeline_peak_follows_peak_fn(tmp_path):
    from astrbot_plugin_bili_whale.pipeline import Pipeline
    st = State(tmp_path / "s.json")
    flag = {"v": True}
    p = Pipeline(parse_settings({}), st, None, None, None, None, None, None,
                 tmp_path / "d", tmp_path / "r", UTC, None, lambda: flag["v"])
    assert p.peak_blocked() is True
    p.ignore_peak = True
    assert p.peak_blocked() is False
    p.ignore_peak = False
    flag["v"] = False
    assert p.peak_blocked() is False
    assert Pipeline(parse_settings({}), st, None, None, None, None, None, None,
                    tmp_path / "d", tmp_path / "r", UTC, None).peak_blocked() is False


# ---- 多组目标配置、分对话人格与 LivingMemory ----
def test_schema_valid_and_preserves_legacy_keys():
    import json
    from pathlib import Path
    schema_path = Path(__file__).resolve().parent.parent / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for legacy_key in ("sessdata", "owner_qq", "owner_umo", "livingmemory_enabled",
                       "livingmemory_auto_connect", "livingmemory_url", "livingmemory_api_key",
                       "livingmemory_persona_id", "livingmemory_scope", "targets"):
        assert legacy_key in schema
    assert schema["targets"]["type"] == "template_list"
    items = schema["targets"]["templates"]["target_profile"]["items"]
    for k in ("owner_qq", "owner_umo", "persona_id", "livingmemory_mode",
              "livingmemory_url", "livingmemory_api_key", "livingmemory_persona_id", "livingmemory_scope"):
        assert k in items


def test_effective_targets_backward_compatible():
    # 1. 未配置 targets 时：沿用旧版单对话
    s_legacy = parse_settings({"owner_qq": "111", "owner_umo": "qq:FriendMessage:111"})
    t_legacy = s_legacy.effective_targets()
    assert len(t_legacy) == 1 and t_legacy[0].key == "" and t_legacy[0].owner_qq == "111"

    # 2. 同时配置了旧版顶层与新 targets（且未重复）：两者都保留
    s_both = parse_settings({
        "owner_qq": "111",
        "targets": [
            {"name": "群聊B", "owner_umo": "qq:GroupMessage:222", "persona_id": "毒舌", "livingmemory_mode": "on"},
            {"name": "停用C", "enabled": False, "owner_qq": "333"},
        ],
    })
    eff = s_both.effective_targets()
    assert [t.name for t in eff] == ["默认主人会话", "群聊B"]
    assert eff[1].persona_id == "毒舌" and eff[1].lm_mode == "on"


def test_multi_target_share_and_memory(tmp_path):
    import asyncio
    from astrbot_plugin_bili_whale.pipeline import Pipeline

    cfg = parse_settings({
        "quiet_hours": "23:00-09:00",
        "max_share_per_day": 1,
        "targets": [
            {"name": "A", "owner_umo": "qq:FriendMessage:1", "persona_id": "pA",
             "livingmemory_mode": "on", "livingmemory_api_key": "kA", "livingmemory_persona_id": "pA",
             "livingmemory_scope": "qq:FriendMessage:1"},
            {"name": "B", "owner_umo": "qq:GroupMessage:2", "persona_id": "pB",
             "livingmemory_mode": "on", "livingmemory_api_key": "kB", "livingmemory_persona_id": "pB",
             "livingmemory_scope": "qq:GroupMessage:2"},
        ],
    })
    st = State(tmp_path / "s.json")
    sent = []
    written = []

    class FakeLM:
        def __init__(self, key, persona_id, scope):
            self.base = "http://127.0.0.1:7801/page/external"
            self.key, self.persona_id, self.scope = key, persona_id, scope

        async def write(self, content, imp, bvid):
            written.append((self.key, self.persona_id, self.scope, bvid))
            return True, "已写入"

    async def llm(prompt, system):
        return f"以[{system}]口吻分享"

    async def persona(target=None):
        return target.persona_id if target else ""

    def memory_factory(target=None):
        return FakeLM(target.lm_key, target.lm_persona_id, target.lm_scope)

    async def send_dm(text, target=None):
        sent.append((target.owner_umo, text))
        return True

    p = Pipeline(cfg, st, None, llm, persona, lambda: None, memory_factory, send_dm,
                 tmp_path / "d", tmp_path / "r", UTC, None)
    p.now = lambda: datetime(2026, 11, 24, 15, 0, tzinfo=UTC)  # 非安静时段
    notes = [{"bvid": "BV1", "title": "好视频", "summary": "s", "feeling": "f",
              "memory_note": "m", "share_score": 8}]
    rec = {"errors": []}
    asyncio.run(p.maybe_share(notes, rec))
    asyncio.run(p.write_memory(notes, rec))

    assert len(sent) == 2
    assert sent[0][0] == "qq:FriendMessage:1" and "以[pA]口吻分享" in sent[0][1]
    assert sent[1][0] == "qq:GroupMessage:2" and "以[pB]口吻分享" in sent[1][1]
    assert written == [
        ("kA", "pA", "qq:FriendMessage:1", "BV1"),
        ("kB", "pB", "qq:GroupMessage:2", "BV1"),
    ]


def test_direct_vision_payload_disables_deepseek_thinking(tmp_path):
    from astrbot_plugin_bili_whale import frames as fr

    img = tmp_path / "board0.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")

    ds = fr.DirectVision("k", "https://api.deepseek.com/v1", "deepseek-flash")
    p_ds = ds.build_payload([(img, [1.0, 2.0])], "测试视频")
    assert p_ds["model"] == "deepseek-flash"
    assert p_ds["max_tokens"] == 4096
    assert p_ds["thinking"] == {"type": "disabled"}
    content = p_ds["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    other = fr.DirectVision("k", "https://api.openai.com/v1", "gpt-4o")
    p_other = other.build_payload([(img, [1.0])], "测试视频")
    assert "thinking" not in p_other
    assert p_other["max_tokens"] == 4096
