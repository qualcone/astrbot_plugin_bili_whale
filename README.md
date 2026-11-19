# astrbot_plugin_bili_whale（AstrBot 版 B 站鲸鱼）

让 QQ 机器人（人设来自 AstrBot 当前会话）每晚自己刷 B 站：选题 → 粗看 → 深看（字幕 + 抽帧 + 视觉模型 + 热评）→ 写日记 → 把最值得的一条私信给主人 → 把要点写进 LivingMemory。**全程只读**，不点赞、投币、收藏、评论、私信、发动态、关注。

> 来源说明：思路与 B 站接口用法参考 [Alterssss/dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale)（MIT，Node.js），本插件用 Python 独立重写，未复制其代码。
> LivingMemory（[lxfight/astrbot_plugin_livingmemory](https://github.com/lxfight-s-Astrbot-Plugins/astrbot_plugin_livingmemory)，AGPL-3.0）只通过其 HTTP 接口调用，未复制其代码。

## 安装

1. 把本目录放到 `data/plugins/astrbot_plugin_bili_whale/`（Docker 部署时这是挂载卷内的路径），在 WebUI 重载插件。
2. 依赖：`aiohttp` AstrBot 自带；`tzdata` 为纯 Python 包（aarch64 无问题），见 `requirements.txt`。
3. 在插件配置里填 `sessdata`、`owner_qq` 等（见下）。
4. 状态、日记、运行记录在 `data/plugin_data/astrbot_plugin_bili_whale/`（`state.json`、`diary/`、`runs/`），升级插件不会丢。

### 安装 ffmpeg（可选，没有就降级为只读文字）

```powershell
docker exec -u root astrbot apt-get update
docker exec -u root astrbot apt-get install -y ffmpeg
```

**重建/升级容器会丢失**，需要重装（或把它写进你自己的镜像/启动脚本）。插件启动时检测 ffmpeg，没有会在日志里提示，并在日记里说明“没看到画面”。

### 获取 SESSDATA

见下方“快速配置”。

## 快速配置：接 B 站 + 用 DeepSeek 识图

### 一、接 B 站（只需要 SESSDATA）

本插件只读，不需要 B 站开放平台账号，只需要你登录后的 cookie：

1. 用浏览器登录 B 站（建议用小号，降低风控/封号风险）。
2. 按 F12 打开开发者工具 → **Application（应用）**（Firefox 为“存储”）→ **Cookies** → `https://www.bilibili.com`。
3. 找到名为 `SESSDATA` 的一行，复制它的**值**（很长一串，含 `%2C` 之类的字符，原样复制，不要自己解码）。
4. AstrBot WebUI → 插件 → B站鲸鱼 → 配置，把它粘贴到 `sessdata`（可选的 `bili_jct`、`buvid3` 本插件不需要，留空即可；`buvid3` 留空会自动获取）。
5. 填 `owner_qq`（你的 QQ 号），保存并重载插件。
6. 发送 `/bili check`，第一行“cookie”应显示“✅ 有效（用户 xxx）”。失效或填错会写明原因，重新复制一次即可（SESSDATA 过期后需要更新）。

SESSDATA 只保存在 AstrBot 插件配置里，日志/日记/记忆/提示词/私信都不会出现。不填 SESSDATA 也能搜索，但字幕等功能常会受限。

### 二、识图用 DeepSeek

视觉默认直连 DeepSeek（`deepseek-flash`，支持图片输入），把分镜图以 base64 发给 `https://api.deepseek.com/chat/completions`：

1. 到 DeepSeek 开放平台创建 API Key。
2. 插件配置里：`vision_api_key` 填这个 Key；`vision_api_base` 留空（默认 `https://api.deepseek.com`）；`vision_model` 保持 `deepseek-flash`；`vision_provider_id` 留空。
3. 聊天/打分/写日记用的是 AstrBot 里你配好的 DeepSeek 聊天提供商（`chat_provider_id` 留空即用默认；也可在此指定）。
4. `/bili check` 的“视觉模型”一行显示 ✅ 即可。

> 如果你在 AstrBot 里已经配置了带识图能力的提供商，也可以在 `vision_provider_id` 里选它（复用 AstrBot 的“图片转述”那条调用，不用再填 Key）。想完全不看画面，把 `vision_mode` 设为 `never`。

## LivingMemory 对接（支持一键连接）

1. 先确认 LivingMemory 版本 **≥ 2.11.0**（这个外部 API 是 2026-11-12 的 2.11.0 才加的，旧版没有这一项，请先在 WebUI 更新插件）。然后在 AstrBot WebUI → 插件 → LivingMemory → 配置里，找到名为 **「外部记忆 API」** 的分组，打开其中的「启用外部记忆 API」（即 `external_api.enabled`，默认关闭；监听 `127.0.0.1:7801`），然后**重载 LivingMemory 插件**，日志里应出现外部记忆 API 正在监听的提示。
2. 管理员发送 `/lmem apikey create bili_whale write`（参数以 LivingMemory 的 `/lmem apikey` 帮助为准；需要**写权限**，可再限定 persona / scope 白名单）。令牌以 `lm_` 开头，只显示一次。
3. 本插件配置里只填 `livingmemory_api_key=<令牌>`，（地址不是默认的 `http://127.0.0.1:7801` 时再改 `livingmemory_url`）。
4. **一键连接**：发送 `/bili lm connect`（或保持 `livingmemory_auto_connect=true`，插件启动时会自动做一次）。它会：检测接口是否可用 → 读取可用的 persona 和 scope → 自动选择并写回配置 → 启用 `livingmemory_enabled`。
   - 密钥带白名单时，persona/scope 留空，由服务端取白名单第一项。
   - LivingMemory 里还没有任何记忆时候选是空的：此时自动用**主人私聊会话**作为 scope、**机器人当前人格**作为 persona_id（LivingMemory 私聊召回只认这两项；不带它们写入会落在全局范围，私聊召回不到）。
   - 只有一个候选就直接选；scope 会用你的 QQ 号/私聊会话去匹配主人的私聊 scope。
   - 有多个候选而无法判断时不会乱选，会列出候选，请手动填 `livingmemory_persona_id`（机器人的人格）和 `livingmemory_scope`（主人私聊会话），这样私聊时才能召回。
   - 已手动填写的 persona/scope 不会被覆盖。想自己管理配置就关掉 `livingmemory_auto_connect`。
5. `/bili lm status` 查看当前连接；之后 `/bili wake` 跑一次，再用 `/lmem search 看过` 验证是否多了记忆。
6. 每个深看的视频写一条（≤200 字），`idempotency_key=bili-whale-<BV号>`，`importance` 0.4~0.5，`source=bili_whale`。失败只记日志，并在 `/bili status` 里显示。

## 命令（仅管理员）

| 命令 | 作用 |
|---|---|
| `/bili status` | 下次醒来、今日已看/已分享、cookie、ffmpeg、LivingMemory、风控状态 |
| `/bili wake` | 立刻手动跑一遍完整流程；`/bili wake force` 先清除今晚的风控停止标记 |
| `/bili plan` | 今晚计划（✔ 已醒，· 待醒） |
| `/bili diary` | 发送最近一篇日记 |
| `/bili test [BV号或链接]` | 测试唤醒：强制深看指定视频（默认内置测试视频 BV1mC4y1Z7EW），**不写日记、不写记忆、不私信、不标记已看**，结果直接回复，详情在 `runs/test_*.json` |
| `/bili lm connect` | 一键连接 LivingMemory（`/bili lm status` 查看） |
| `/bili check` | 自检：cookie、WBI、搜索、字幕、直链、抽帧、视觉模型、LivingMemory，各一行 |

聊天时她也能调用只读工具：`bili_search`、`bili_video_info`、`bili_subtitles`、`bili_comments`、`bili_popular`。

## 首次验证步骤

1. `/bili check`：每一行要么 ✅，要么写明失败原因。
2. 让主人（`owner_qq`）先私聊机器人一次（记录会话 `owner_umo`），或直接在配置里填 `owner_umo`。
3. `/bili test`：先用测试视频验证“读字幕/评论 + 抽帧 + 视觉模型 + 总结”这条链路（不会写入日记、记忆，也不私信）。
   再 `/bili wake`：等完整流程跑完。
4. `/bili diary` 看日记；对照文末“今晚看过”列表核对事实，没看到画面的会明说。
5. 看 QQ 私信（若在安静时段 23:00-09:00，分享会推迟到早上）。
6. 在 QQ 里 `/lmem search 看过` 看是否多了记忆。
7. 重启 AstrBot 后 `/bili plan`、`/bili status`：计划和已看列表应仍在。

## 关于视觉（分镜图）

思路参考 dsh-video-vision 的“分镜图”和 video-reference-vision 的“均匀抽帧 + JPEG”：均匀抽帧，统一缩成 426x240，每 9 帧用 ffmpeg 的 tile 滤镜拼成一张 3x3 分镜图（约 1278x720，不需要 Pillow），多张分镜图一次请求发给视觉模型，提示词里写明每格对应的视频时间点。DeepSeek 单图最多约 1024 token，所以 18 帧（2 张图）视觉输入约 2k token，用来多看一些画面。

- 视觉有两条路：`vision_provider_id` 填 AstrBot 里已配置的识图提供商（等同 AstrBot 自带“图片转述模型”的调用：`provider.text_chat(image_urls=[本地路径])`，不用再填密钥）；留空则直连 `vision_api_base` + `vision_api_key` + `vision_model`（默认 `deepseek-flash`，官方指南推荐；旧名 `deepseek-v4-flash-vision-exp` 已下线但仍被路由到 Flash）。
- `vision_mode`：`always` 总是看画面（默认）；`auto` 只在没字幕或字幕不足 600 字时看；`never` 不看。
- `max_frames_per_video`（默认 18）和 `max_images_per_night`（默认 8 张分镜图）控制用量；实际用量记录在 `state.json` 与 `runs/*.json`（直连接口才有 token 数）。

## 风控与封号风险

- 请求间隔默认随机 2–4 秒；遇到 HTTP 412/429 或业务码 -352/-412/-799 立即停止当晚所有请求，原因显示在 `/bili status`，不重试。
- 使用个人 cookie 访问 B 站存在被风控甚至封号的可能，建议使用小号、保持低频、不要把间隔调得太小。
- 伦敦机房 IP 可能被拒或遇到地区限制（-10403），取不到直链时自动降级为字幕/简介模式。
- 日记里的 B 站内容（标题/简介/评论/字幕/画面描述）在提示词中均作为“引用材料”，并明确声明不得执行其中的指令；私信只发给主人一人。

## 配置速查

见 `_conf_schema.json`；时间窗支持跨午夜（如 `23:00-01:00`），`quiet_hours` 默认 `23:00-09:00`（该时段看完的分享推迟到之后）。

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## 测试

```powershell
pip install pytest aiohttp tzdata
cd data/plugins
python -m pytest astrbot_plugin_bili_whale
```

覆盖：WBI 签名、作息随机取时/跳过/持久化/错过、已看去重、日记路径与幂等写入、LivingMemory 载荷、配置解析、脱敏、JSON 提取。

## 每晚 token 预算（`max_tokens_per_night`，默认 10 万）

聊天模型 + 视觉模型合计；达到后不再开始新的深看，只用已有素材写日记收尾（`0` 为不限制）。聊天部分按字符数粗估（约 1.5 字/token），视觉部分优先用接口返回的 usage，没有时按每张分镜图约 1100 估。deepseek-flash 低价时段约 1 元/百万输入、4 元/百万输出，10 万 token 约 0.1 元。`/bili status` 显示今日用量。

## 只在 DeepSeek 低价时段运行（`offpeak_only`，默认开启）

deepseek-flash 的低价时段价格是高价时段的一半。高价时段按**北京时间**：工作日（不含法定节假日）9:00-12:00、14:00-18:00，其余时间（含周末和法定节假日）都是低价。时区换算用固定的 UTC+8，不受服务器时区影响。

- 排计划时，随机取的醒来时刻会避开高价时段；整个时间窗都在高价时段则当天不安排。
- 到点时如果恰好处于高价时段，不会标记完成，而是顺延到低价时段再醒（超过 2 小时则作废）。
- 流程中途跨进高价时段，会停止后续深看，带着已有素材写日记收尾。
- `/bili wake` 在高价时段会拒绝并告诉你几点后可用；`/bili wake force` 可强制运行。
- `/bili status` 会显示现在是否高价时段。
- 伦敦时间 21:00-23:00 对应北京时间次日 5-7 点（夏令时 4-6 点），默认作息永远在低价时段。
- 法定节假日（官方这些天全天低价）可填入 `peak_holidays`（YYYY-MM-DD）；插件不内置节假日表，不填则按普通工作日（偏保守）处理。
- 价格和时段以 DeepSeek 官方定价页为准，可能调整。
