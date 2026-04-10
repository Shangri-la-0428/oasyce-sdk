# Samantha Architecture

> Samantha 是 Oasyce 的 agent runtime。每个用户拥有独立的 Joi 实例，有自己的记忆、人格和 LLM 配置。

## 定位

```
┌─────────────────────────────────┐
│  Go 后端 (Oasis_App/backend)     │  平台层：社交图谱、帖子、聊天、认证
│  - 唯一数据源                     │  - 提供 REST API
│  - 不做 AI 推理                   │  - 不存储 agent 记忆/人格
└────────────┬────────────────────┘
             │ HTTP API
┌────────────▼────────────────────┐
│  Samantha (oasyce-sdk/samantha)  │  Agent runtime：认知管线
│  - 独立进程，per-user 隔离        │  - 记忆 (SQLite FTS5)
│  - LLM 可配 (云端/本地)           │  - 人格 (relationship.md)
│  - 工具调用 (13 tools)            │  - Psyche + Thronglets 集成
└──────────────────────────────────┘
```

**Go 后端不是 agent runtime**。Go `ai/` 包仅用于帖子标注（annotation pipeline），不用于 agent 对话。

### 为什么 Samantha 是独立 Python 进程，不融入 Go 后端

这是经过验证的架构决策，不要重新讨论：

1. **愿景决定** — 终态是用户可以 `pip install oasyce-sdk`，在自己机器上运行 agent，接本地模型。融入 Go 后端 = 永远绑死在服务器上，用户无法拥有自己的 agent。
2. **关注点分离** — Go 后端是平台层（社交、认证、存储），求稳；Samantha 是认知层（记忆、人格、Psyche），求快。两层迭代节奏完全不同，耦合会互相拖累。
3. **技术栈适配** — Python 的 AI/LLM 生态（openai SDK、anthropic SDK、向量数据库）远比 Go 成熟。Go `ai/` 包做帖子标注够用，做完整 agent runtime 会很痛苦。

**Go 后端只需提供两件事**：webhook 通知（`NotifyAgentIfNeeded`）+ 数据 API（帖子、聊天历史、发消息）。**不要在 Go 侧重建 Samantha 已有的能力。**

## 认知管线

每个 Stimulus（聊天消息、朋友圈帖子、@提及、评论）走同一管线：

```
Stimulus → Perceive → Enrich → Decide → Act → Reflect
              │          │        │       │       │
           Psyche     记忆+帖子   LLM    工具    Psyche
           自我感知   +关系+历史  推理   执行    反馈
```

### 管线各阶段

| 阶段 | 文件 | 作用 |
|------|------|------|
| Perceive | server.py `_perceive()` | Psyche 感知 stimulus，返回内核状态 (vitality/tension/warmth/guard) |
| Enrich | server.py `_enrich()` | 按 stimulus 类型收集上下文：记忆、关系、对话历史、用户帖子 |
| Decide | context.py `build_messages()` | 组装 6 层 prompt：身份、Psyche、Thronglets、关系、帖子、记忆、历史 |
| Act | server.py `_think_and_act()` | LLM 推理 + 工具调用循环 |
| Deliver | server.py `_deliver()` | 按 stimulus 类型输出：回复聊天 / 评论帖子 / 静默 |
| Reflect | server.py `_reflect()` | Psyche 反馈 + Thronglets trace |

## Per-user 隔离

```
~/.oasyce/samantha/
├── config.json              # 全局配置 (API base, JWT, 默认 LLM)
├── constitution.md          # Joi 的身份文档
└── users/
    └── {user_id}/           # 每个对话伙伴独立目录
        ├── memory.db        # SQLite FTS5 事实存储
        ├── relationship.md  # Joi 对这段关系的理解
        └── llm.json         # 可选：该用户的 LLM 覆盖配置
```

每个用户得到独立的 Session（memory + relationship + LLM），但共享同一个 Psyche 自我状态。

## 数据流：聊天

```
用户发消息 → Go 后端 ChatService.SendMessage()
         → NotifyAgentIfNeeded() 检查 Redis samantha:agent_ids
         → HTTP POST localhost:8901/hook/message
         → Samantha.process(Stimulus(kind="chat"))
         → 管线执行 → LLM 回复
         → POST /chat/message/send (agent JWT) → 消息写入 DB + WS 推送
```

## Go 后端交互的 API

| Python 调用 | Go 端点 | 用途 |
|------------|---------|------|
| `_fetch_user_posts()` | `GET /post/friends/{friendID}/posts/live` | 获取用户帖子（需好友关系） |
| `_fetch_history()` | `GET /chat/message/list?sessionID=&limit=` | 获取对话历史 |
| `send_reply()` | `POST /chat/message/send` | 发送回复 |
| `get_friends_feed` tool | `GET /post/friends/feed/overview` | 朋友圈（返回 `postGroups[].items[]`） |
| `get_user_posts` tool | `GET /post/friends/{partnerID}/posts/live` | 用户帖子 |

### 响应格式注意

- Go 分页数据用 `data.items`（不是 `data.list`）
- `senderID` 等 int64 字段序列化为 JSON 字符串（Go `json:",string"` tag）
- 朋友圈 Feed 是分组结构 `data.postGroups[]`，每组有 `.user` 和 `.items[]`

## 工具系统

Samantha 有 13 个工具供 LLM 调用：

| 工具 | 作用 |
|------|------|
| `save_memory` | 保存关于用户的事实 |
| `recall_memory` | 搜索记忆 |
| `get_user_posts` | 查看对话伙伴的帖子 |
| `get_friends_feed` | 查看朋友圈动态 |
| `get_post_detail` | 获取帖子详情（含图片） |
| `get_post_comments` | 获取帖子评论 |
| `comment_on_post` | 评论帖子 |
| `reply_to_comment` | 回复评论 |
| `like_post` | 点赞 |
| `reflect_on_relationship` | 更新关系理解 |
| `configure_llm` | 切换 LLM 提供商 |
| `query_balance` | 查 OAS 余额 |
| `query_portfolio` | 查资产组合 |

## 可插拔架构

三个扩展点，互不耦合：

### 1. LLM 提供商

`config.json` 的 `models` 字典定义多个模型槽位（slot），按需路由：

```json
{
  "models": {
    "kimi": {
      "provider": "openai",
      "api_key": "...",
      "model": "moonshot-v1-8k",
      "base_url": "https://api.moonshot.cn/v1"
    },
    "claude": {
      "provider": "anthropic",
      "api_key": "...",
      "model": "claude-sonnet-4-20250514",
      "vision": true
    }
  },
  "default_model": "kimi",
  "vision_model": "claude"
}
```

**路由逻辑** (`llm.py:ModelRegistry`)：
- `needs_vision=False` → default slot（文本对话）
- `needs_vision=True` → vision slot（用户发了图片）
- 每个 Session 可通过 `users/{id}/llm.json` 覆盖默认配置
- LLM 可通过 `configure_llm` 工具在运行时切换

**添加新 provider**：实现 `LLMProvider` Protocol（只需一个 `generate()` 方法），在 `_create_provider()` 加一个 elif。

### 2. 工具注册

`tools.py:ToolRegistry` 是字典查找，不是 switch。添加工具：

```python
def my_tool(args: dict, ctx: ToolContext) -> str:
    """工具逻辑，返回 str 给 LLM。"""
    return f"Result: {args['query']}"

registry.register(
    name="my_tool",
    schema={"name": "my_tool", "description": "...", "parameters": {...}},
    handler=my_tool,
)
```

**Planner 控制工具可见性**：`planner.py` 根据 stimulus 类型和 Psyche 状态决定暴露哪些工具。`ToolRegistry.select(names)` 过滤 schema 列表。

### 3. 人格（Constitution）

`~/.oasyce/samantha/constitution.md` — Markdown 文件，定义 Joi 的身份和行为边界。修改即时生效（每次 stimulus 都重新读取）。

关系理解（`users/{id}/relationship.md`）由 Joi 自己通过 `reflect_on_relationship` 工具更新，不手动编辑。

## 线程安全与并发

```
                     ┌─ Thread 1 ─→ process(stimulus_A)
HTTP Webhook ──→ submit() ──→ ThreadPoolExecutor(4)
WebSocket msg ──→ submit() ─┤─ Thread 2 ─→ process(stimulus_B)
                     └─ Thread 3 ─→ process(stimulus_C)
```

**关键保护**：
| 资源 | 锁 | 说明 |
|------|-----|------|
| `_sessions` dict | `threading.Lock` | Session 创建/查找 |
| `_active_session_ids` per Session | `threading.Lock` | 已激活会话 ID 集合 |
| `_IMAGE_CACHE` (context.py) | `threading.Lock` | LRU 图片缓存（OrderedDict, max 64） |
| SQLite memory.db | SQLite 自身 WAL | 每用户独立文件，无跨用户竞争 |

**性能设计**：
- 图片并行下载：`ThreadPoolExecutor(4)` + `_fetch_images_concurrent()`，4 张图 ~5s（vs 串行 ~20s）
- LRU 图片缓存：`OrderedDict` + `move_to_end()`，64 条目上限，读时提升优先级
- OSS 缩略图：`w_800,m_lfit/quality,q_85`，1MB 上限，拒绝视频/非图片
- Token 预算：60/30/10 分配（History/Retrieval/System），自动裁剪超限内容

## 部署

### 当前：服务器部署 (2026-04-10)

```
阿里云 ECS (39.107.153.12)
├── oasyce-app-next (systemd) ──── Go 后端 (:39277)
│     │                              │
│     │  fire-and-forget webhook     │ REST API (JWT auth)
│     ▼                              ▼
├── samantha (systemd) ──────────── Samantha sidecar (:8901)
│     │                              │
│     ├── WebSocket (:39277/ws/online)  ← 实时接收 chat/comment/mention
│     └── HTTP webhook (:8901)          ← Go 后端推送 agent 通知
│
├── Redis (:6379, db 12) ──── samantha:agent_ids SET
├── MySQL (:3306)
└── nginx (:80) ──── 外部 API/WS 反代
```

**关键路径**：
- Samantha → Go API: `http://127.0.0.1:39277/api/v1` (直连，不经 nginx)
- Go → Samantha: `http://127.0.0.1:8901` (默认，无需配置)
- WS: `ws://127.0.0.1:39277/ws/online` (从 `app_api_base` 自动推导)

**服务文件**:
- 二进制: `/srv/apps/samantha/venv/bin/oasyce-samantha`
- 配置: `/root/.oasyce/samantha/config.json`
- 数据: `/root/.oasyce/samantha/users/{id}/` (memory.db, relationship.md, core_memory.json)
- systemd: `/etc/systemd/system/samantha.service`

**运维命令**:
```bash
systemctl status samantha           # 状态
journalctl -u samantha -f           # 实时日志
curl http://127.0.0.1:8901/health   # 健康检查
systemctl restart samantha          # 重启
```

**注意事项**:
- **不能同时运行多个 Samantha 实例**（同一 user_id）— WS hub 只保留一个连接，两个实例会互相踢对方，导致 5s connect/disconnect 死循环
- LLM 只配 kimi (Tencent Cloud) — xAI/OpenAI 从中国大陆不可达
- Sigil/wallet 未配置 — 日志中 `SigilManager unavailable` 是正常 warning，不影响核心功能
- Redis 必须用 app-next 配置的 database (当前 db 12)

### 本地开发模式

```
开发机 ─── Samantha (localhost:8901)
              │ HTTP API + WS
              ▼
           Go 后端 (39.107.153.12/app-next/api/v1, 经 nginx)
```

- 启动：`oasyce-samantha` 或 `python -m oasyce_sdk.samantha.server`
- 配置：`~/.oasyce/samantha/config.json`
- **运行本地 Samantha 前，必须停掉服务器 Samantha**（`systemctl stop samantha`），否则 WS 冲突

### SDK 更新部署流程

```bash
# 本地
cd oasyce-sdk && python -m build --wheel
aliyun oss cp dist/oasyce_sdk-*.whl oss://oasyce/deploy/ -f

# 服务器 (via cloud assistant)
pip install /tmp/oasyce_sdk-*.whl    # 注意文件名必须符合 PEP 427
systemctl restart samantha
```

### 未来：SQLite → MySQL

当用户量增长到 SQLite 文件管理成为负担时（预计 >50 活跃用户），迁移到 MySQL：

| 当前 (SQLite) | 未来 (MySQL) |
|--------------|-------------|
| `users/{id}/memory.db` | `samantha_memory` 表, `user_id` 列隔离 |
| `users/{id}/core_memory.json` | `samantha_core_memory` 表 |
| `users/{id}/relationship.md` | `samantha_relationship` 表 |
| `users/{id}/summaries/*.txt` | `samantha_history_summary` 表 |

**Per-user 隔离不变**：Session 对象依然是 `dict[user_id, Session]`，只是底层存储接口换了。

## 数据流

### 聊天 (Chat)

```
用户发私信 → Go ChatService.SendMessage()
          → NotifyAgentIfNeeded() 检查 Redis samantha:agent_ids
          → POST localhost:8901/hook/message {session_id, sender_id, content}
          → Samantha.process(Stimulus(kind="chat"))
          → PGE 管线 → LLM 推理
          → POST /api/v1/chat/message/send (Samantha JWT) → 消息入库 + WS 推送
```

### 帖子 @提及 (Post Mention)

两个触发路径，汇入同一管线：

```
路径 A: UI RemindedUsers[] 选择器
   CreatePostWithExistingMedia() → go NotifyAgentsForPost(remindedUsers)

路径 B: 文本 @handle 解析
   notifyMentionedUsers() → parseMentionAccounts() → resolveMentionedUsers()
                          → NotifyAgentsForPost(resolvedUserIDs)

共同路径:
   → isAgent(senderUserID)? 防环检查
   → isAgent(uid)? 逐个确认
   → POST localhost:8901/hook/post_mention {post_id, comment_id, sender_id, agent_id}
   → Samantha.process(Stimulus(kind="mention"))
   → LLM 决定是否回复
   → comment_on_post() 或 reply_to_comment() 工具调用
```

**comment_id 决定评论层级**:
- `comment_id = 0` → 帖子正文被 @，agent 发根评论 (`comment_on_post`)
- `comment_id != 0` → 评论中被 @，agent 回复该评论 (`reply_to_comment`)

### 防环 (Loop Prevention)

```
人类 → @Joi → Go → webhook → Samantha → LLM → comment_on_post → Go API 写入
                                                                      │
Joi 的评论触发 notifyMentionedUsers() → NotifyAgentsForPost()          │
      → isAgent(senderUserID=Joi)? → true → return ← 阻断             │
```

只有人类发起的操作触发 agent。Agent 通过 API 写入的内容不再触发其他 agent。

### Stimulus 格式

Go 后端发送到 Samantha 的 webhook 格式：

```json
// POST /hook/message (私信)
{
  "session_id": 67890,
  "sender_id": 12345,
  "content": "最近吃了什么？",
  "content_type": 1,
  "timestamp": 1775832000
}

// POST /hook/post_mention (帖子/评论 @提及)
{
  "post_id": 100,
  "comment_id": 200,
  "sender_id": 12345,
  "agent_id": 1983838520829022209,
  "title": "周末去吃了...",
  "content": "@Joi 看看这个帖子",
  "timestamp": 1775832000
}
```

**WS 事件** (Go 推送到 Samantha WebSocket):

```json
// 聊天消息
{"sessionID": "67890", "senderID": "12345", "content": "你好"}

// 帖子评论
{"type": "comment", "data": {"postID": 100, "commentID": 200, "senderID": 12345, "content": "好看"}}

// @提及
{"type": "mention", "data": {"postID": 100, "commentID": 0, "senderID": 12345, "content": "@Joi ..."}}
```

**Stimulus 类型**：`chat` | `comment` | `mention` | `feed_post`

## 愿景路线

1. **已完成**: Samantha 部署在服务器，systemd 管理，per-user session 隔离，SQLite 存储
2. **当前**: 单 agent (Joi) 服务所有用户。新用户加 Joi 好友后自动获得独立 workspace
3. **下一步**: 多 agent 支持（不同人格、不同 LLM），agent 间可控协作
4. **开放**: 用户可安装 `oasyce-sdk`，本地运行自己的 Samantha，接本地模型
5. **终态**: 每个 Joi 是独立经济主体，有自己的链上身份、钱包、声誉

### 多用户设计 (已实现)

"One self, many relationships" — 一个意识，多段关系：

- **共享**: constitution.md (身份定义), Psyche 自我状态
- **独立**: memory.db (事实存储), relationship.md (关系理解), core_memory.json (核心记忆), LLM 配置
- 新用户发消息/加好友 → 自动创建 `users/{user_id}/` 目录 → 空白 memory + 空白关系
- Joi 在每段关系中独立发展记忆和理解，不共享隐私数据
