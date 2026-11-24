# Changelog

## [0.4.0] - 2026-11-24

### 新增
- **多组对话配置（`targets`）**：支持配置多组目标对话（私聊或群聊），每组可独立指定目标会话（`owner_qq` / `owner_umo`）、专属人格（`persona_id`）以及独立的 LivingMemory 接口与写入策略（`livingmemory_mode`、`livingmemory_url`、`livingmemory_api_key`、`livingmemory_persona_id`、`livingmemory_scope`）。
- **AI 主动看视频工具 `bili_watch`**：在聊天中直接发给 AI 视频 BV 号、`bilibili.com` 链接或 `b23.tv` 短链时，AI 可主动调用该工具完整读取视频信息、字幕、热评并抽帧看画面。
- `/bili status` 与 `/bili lm status` 支持展示多组目标会话及 LivingMemory 连接状态；`/bili lm connect` 支持一次性为多组自动匹配并回填 `persona_id` 与 `scope`。

### 优化
- 优化配置菜单顺序：B 站账号与请求 → 多组对话配置与兼容单对话配置 → 模型与视觉预算 → LivingMemory 全局默认配置 → 作息与免打扰 → 兴趣与分享限制。
- 兼容多平台（含微信、QQ 等）：将配置说明与分享提示词从“QQ 私信”调整为通用私信描述，兼容各类 AstrBot 平台用户 ID 与会话 UMO。
- 完全兼容旧版单对话顶层配置（`owner_qq`、`owner_umo`、`livingmemory_*`），升级后原有设置自动保留。

## [0.3.0] - 2026-11-20

### 变更（不兼容）
- **识图改为直接选用 AstrBot 中已有的提供商**：新增并改用“识图模型提供商”选项（留空则使用文本模型提供商）。**移除**直连接口的 `vision_model`、`vision_api_base`、`vision_api_key` 三项，原先填写过的需要改为在 AstrBot 中添加对应提供商后在此选择。识图与文本模型可以是不同厂商。
- **低价时段调度适配所有模型**：`offpeak_only` 改为 `offpeak_mode`（自动/关闭）。自动模式下仅当当前使用 DeepSeek 时才生效，使用其他模型时不做时段限制。旧配置 `offpeak_only=false` 会被识别为“关闭”。

### 新增
- 插件图标 `logo.png`（256×256）。
- README 增加“视频内容如何传递给对话模型”一节，说明识图模型与文本模型通过文字衔接。

### 优化
- 配置项名称与说明统一为规范、简洁的表述，并补充每项的 hint；README 重新整理。
- 配置页移除不使用的 `bili_jct` 项。

## [0.2.2] - 2026-11-19

### 变更
- 每个视频的记忆上限从 200 字放宽到 500 字，并要求以人设口吻、第一人称写（前半视频要点，后半感想），写给将来的自己；一天两个视频约 1000 字。日记仍只存文件，不写入记忆。

## [0.2.1] - 2026-11-19

### 修复
- **LivingMemory 一键连接**：LivingMemory 库里还没有记忆时 `/personas` 返回空列表，导致 persona/scope 选不出来、记忆写到全局范围而私聊召回不到（召回只认「私聊会话 + 当前人格」）。现在没有候选时自动用主人私聊会话（UMO）作为 scope、机器人当前人格作为 persona_id；永远不会把全局范围 `livingmemory:global` 当成"唯一候选"选中；`/bili status` 在 scope 为空时给出警告。

## [0.2.0] - 2026-11-19

### 新增
- **`/bili test [BV号或链接]`**：测试唤醒，强制深看指定视频（默认 BV1mC4y1Z7EW），不写日记、不写记忆、不私信、不标记已看，详情落盘到 `runs/test_*.json`。
- **一键连接 LivingMemory**：`/bili lm connect` 检测接口、读取 persona/scope、自动选择并启用写入；`/bili lm status` 查看。新增配置 `livingmemory_auto_connect`（默认开，填好密钥后启动时自动连接）。已手动填写的 persona/scope 不覆盖。
- **每晚 token 预算** `max_tokens_per_night`（默认 10 万，0 不限制）：达到后停止深看，只写日记收尾；`/bili status` 显示今日用量（聊天部分为估算）。
- **只在 DeepSeek 低价时段运行** `offpeak_only`（默认开）：按北京时间（工作日 9-12、14-18 为高价），计划避开高价、到点撞上则顺延、流程中途跨入高价则停止深看；`peak_holidays` 可填法定节假日。`/bili wake force` 可强制。
- **分镜图视觉**：均匀抽帧，每 9 帧用 ffmpeg 拼成一张 3x3 分镜图，一次请求发给视觉模型；新增 `vision_mode`（always/auto/never）与 `vision_provider_id`（复用 AstrBot 识图提供商）。默认视觉模型改为 `deepseek-flash`；`max_frames_per_video` 默认 18、`max_images_per_night` 默认 8（分镜图）、`subtitle_max_chars` 默认 4000。
- README：接 B 站（获取 SESSDATA）、用 DeepSeek 识图、LivingMemory 外部 API 的开启位置（需 LivingMemory ≥ 2.11.0）。

### 修复
- **缓解 B 站 412**：首次请求前先访问首页预热 `buvid3`/`b_nut` 等 cookie，补全 `Origin`/`Accept-Language` 请求头，搜索请求补 `web_location`；412 报错现在会带上具体接口地址。
- 节假日日期校验的正则缺少转义，合法日期被全部丢弃。
- 模型输出 JSON 的提取改为逐个起点解析，避免字段里含 `[1:20]` 时被误取成数组。
- 粗看改为打分成功后才把候选标记为"已看"，模型失败时不浪费候选。
- cookie 只发给 `api.bilibili.com`，不再带给字幕 CDN 等其它域名。
- 视频缺 `aid` 时跳过评论读取；用量记录只保留最近 30 天；私聊监听函数改名，避免被当作内部函数跳过。
- 移除仓库中的个人信息。

## [0.1.0] - 2026-11-19

首个版本：
- 只读 B 站工具（`bili_search`、`bili_video_info`、`bili_subtitles`、`bili_comments`、`bili_popular`，同时注册为 AstrBot LLM 工具）。
- 夜间自主浏览：作息时间窗随机取时刻与跳过概率、计划持久化；选题 → 粗看 → 深看（字幕 + 抽帧 + 视觉模型 + 热评）→ 写日记 → 私信分享 → 写入 LivingMemory；运行记录落盘。
- 命令：`/bili status`、`wake`、`plan`、`diary`、`check`（仅管理员）。
- 风控：限速，遇 HTTP 412/429 或 -352/-412/-799 当晚停止；cookie 脱敏；B 站内容一律作为"引用材料"防提示词注入。
- 单元测试：WBI 签名、作息、已看去重、日记路径与幂等写入、配置解析等。
