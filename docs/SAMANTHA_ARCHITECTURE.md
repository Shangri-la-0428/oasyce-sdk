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

## 部署路径

### 现阶段：本地开发

```
开发机 ─── Samantha (localhost:8901)
              │ HTTP API
              ▼
           Go 后端 (39.107.153.12:39277)
```

- 记忆：SQLite per-user 文件 (`~/.oasyce/samantha/users/{id}/memory.db`)
- 配置：`~/.oasyce/samantha/config.json`
- 启动：`samantha serve`

### 目标：服务器部署

```
阿里云 ECS ─── Samantha (systemd service)
                 │
                 ├── Go 后端 (localhost:39277)
                 └── MySQL (localhost:3306)
```

**迁移清单**：
1. **记忆存储**：SQLite → MySQL 表（`samantha_memory`），per-user 用 `user_id` 列隔离
2. **Core Memory**：文件 → MySQL 表（`samantha_core_memory`），JSON 存储 blocks
3. **Relationship**：文件 → MySQL 表（`samantha_relationship`），text 字段
4. **History Summary**：文件 → MySQL 表（`samantha_history_summary`）
5. **Config**：环境变量 + 配置文件（API keys 不进数据库）
6. **LLM 覆盖**：`users/{id}/llm.json` → MySQL 表或保持文件

**Per-user 隔离不变**：无论 SQLite 还是 MySQL，每个用户的数据通过 `user_id` 严格隔离。Session 对象依然是 `dict[user_id, Session]`，只是底层存储接口换了。

### Stimulus 格式

Go 后端发送到 Samantha 的 webhook 格式：

```json
// POST /hook/message
{
  "kind": "chat",
  "content": "最近吃了什么？",
  "senderId": 12345,
  "sessionId": 67890,
  "imageUrls": ["https://cdn.oasyce.com/..."]
}

// POST /hook/comment
{
  "kind": "comment",
  "content": "好看！",
  "senderId": 12345,
  "postId": 100,
  "commentId": 200
}

// POST /hook/mention
{
  "kind": "mention",
  "content": "@Joi 看看这个",
  "senderId": 12345,
  "postId": 100
}
```

**Stimulus 类型**：`chat` | `comment` | `mention` | `feed_post`

## 愿景路线

1. **现阶段**：Samantha 跑在开发者机器上，一个实例服务一个/多个用户
2. **上线**：部署到服务器，per-user session 隔离，SQLite → MySQL
3. **开放**：用户可安装 `oasyce-sdk`，本地运行自己的 Samantha，接本地模型
4. **终态**：每个 Joi 是独立经济主体，有自己的链上身份、钱包、声誉
