# Samantha 部署状态与待办

> 最后更新: 2026-04-11
> 关联: [SAMANTHA_ARCHITECTURE.md](SAMANTHA_ARCHITECTURE.md) — 认知管线设计
> 关联: `~/.claude/plans/declarative-toasting-acorn.md` — Phase 0-3 演进计划

本文档记录 Samantha 的**运行时实际状态**:服务器上跑什么、链上有什么身份、密钥存在哪、下一步做什么。架构设计看 `SAMANTHA_ARCHITECTURE.md`,本文只记录"现在是什么样"。

---

## 1. 身份层状态

### 1.1 Samantha 专属 Sigil (2026-04-11 创建)

| 字段 | 值 |
|---|---|
| **Sigil ID** | `SIG_9344ae288f66b771cf4616c734948574` |
| **Creator** | `oasyce138rx5yt0aj0dxejtm7hjmlmgl9qxdms9zcjddr` (agent wallet) |
| **Public key** (base64) | `AxhkF9H0zo2r9BKtj9EDBB94nqbyHpf+9ky6uy867e1F` |
| **Public key** (hex compressed) | `03186417d1f4ce8dabf412ad8fd103041f789ea6f21e97fef64cbabb2f3aeded45` |
| **Creation height** | 150546 |
| **Status** | ACTIVE (0) |
| **Metadata** | `{"name":"Joi","agent":"Samantha","operator":"wutongcheng","purpose":"companion"}` |
| **Tx hash** | `6759ACC0530C95E8FC0DAB277CB8C00226EC26268EAA7AEFFE4E4A6A2DF4C8D0` |

**私钥位置**: `~/.oasyce/samantha/sigil.key` (32 字节 raw secp256k1, 0600 权限)
**用途**: Sigil 身份字段,**不用于 tx 签名**。所有 MsgPulse / MsgDissolve / 等生命周期 tx 由 `Sigil.Creator` (agent wallet) 签。

### 1.2 Operator Sigil (MCP 自动创建)

| 字段 | 值 |
|---|---|
| **Sigil ID** | `SIG_89c66a116fec9ed3664bdfaf2dff68f9` |
| **Creator** | 同 agent wallet |
| **Metadata** | `oasyce-agent auto-genesis` |

这是 oasyce-sdk MCP 适配器首次运行时自动建的**操作者身份**——代表你(wutongcheng)跑 MCP 工具时的通用 agent。不要和 Samantha Sigil 混淆。

### 1.3 已知 MCP 适配器 Bug (记录在案)

创建 Samantha Sigil 时发现:
- `mcp__oasyce__get_sigil` 抛 `'Sigil' object has no attribute 'id'`
- `mcp__oasyce__get_balance` 抛 `'Balance' object has no attribute 'amount'`
- `mcp__oasyce__create_sigil` 的 `lineage` 参数被错误地放进了 `state_root` 字段

**绕开方式**: 直接打 chain REST `http://47.93.32.88:1317/oasyce/sigil/v1/sigil/{id}` 和 `/cosmos/bank/v1beta1/balances/{addr}`
**待办**: 修复 oasyce-sdk MCP 适配器的 response parser (低优先级,不阻塞任何流程)

---

## 2. 服务器运行时状态 (39.107.153.12, Aliyun ECS)

### 2.1 当前状态 (Phase 0 部署**前**)

| 组件 | 状态 | 备注 |
|---|---|---|
| Samantha (systemd `samantha`) | ✅ 运行中 | PID 1051192, port 8901, `/root/.oasyce/samantha/config.json` |
| Psyche HTTP (:3210) | ❌ 未部署 | SDK 代码就位,但服务器没装 Node.js |
| Thronglets (:7777) | ❌ 未部署 | SDK 代码就位,但服务器没装 binary |
| Samantha config | 无 `psyche_url`/`thronglets_url` | 所有新路径走 fallback/None,等同"裸跑" LLM wrapper |

### 2.2 已知服务器约束

- **磁盘**: 79G/103G used (80%) — 部署时注意清理
- **Node.js**: 未安装 (没有 node、没有 nvm) — Phase 0 需要自带 Node tarball
- **网络**: 无法访问 GitHub/go.dev/nodejs.org — 所有资产必须**本地构建 → OSS 中转**
- **端口**: 3210 / 7777 / 8901 空闲
- **部署方式**: Aliyun 云助手 `aliyun ecs RunCommand --profile oasyce-app`, CommandContent 用明文 (不是 base64), OSS 需签名 URL — 详见 memory `feedback_cloud_assistant_plaintext.md`

### 2.3 生产约束

⚠️ **这是线上环境,有真实用户**。任何重启/配置变更必须:
1. 先 `systemctl status samantha` 确认健康
2. 改配置 → 不重启 → 下一次 deploy 合并生效
3. 如果必须重启,告诉用户、确认窗口、后台跑

---

## 3. 链集成策略: Mac 端 pulse,服务器不碰链

### 3.1 为什么服务器不 pulse (根因分析)

**链上硬约束** (`oasyce-chain/x/sigil/keeper/msg_server.go:323`):
```go
if sigil.Creator != msg.Signer {
    return nil, types.ErrNotSigilOwner
}
```
MsgPulse 的 signer **必须**等于 Sigil.Creator。没有例外。

**x/delegate.MsgExec 能绕过吗?** 可以但有代价:
- 外层 MsgExec 由 delegate 私钥签
- 内层 MsgPulse 的 signer 依然必须填 principal 地址
- Thronglets `pulse.rs` 当前**没有** MsgExec 包装逻辑,需要新增 ~50 行代码 + 新 env var `THRONGLETS_PRINCIPAL_ADDR` + delegate 密钥管理故事

**更根本的问题**: Thronglets pulse 的两个维度 (`thronglets` presence + `psyche` viability) 都是**局部进程存活**,不是**身份存活**。身份存活应由身份所有者证明。Thronglets 是神经突触,不是心跳。

### 3.2 采纳的架构

```
Mac (wutongcheng, agent wallet = Sigil.Creator)
  └─ launchd job: 每 6h `oasyced tx sigil pulse SIG_9344ae...`
     (直接 principal 签,不走 delegate)

服务器 (39.107.153.12)
  ├─ Psyche :3210                    → Samantha 感知
  ├─ Thronglets :7777 (无 pulse env) → Samantha 的场 / priors
  └─ Samantha :8901                  → 对话
  
→ 服务器完全不碰链
→ 零 principal 暴露
→ 零 delegate 基础设施
→ 零 Thronglets 代码改动
```

### 3.3 信任模型

| 事件 | 后果 |
|---|---|
| Mac ~6 天内未 pulse | Sigil → dormant (仍可恢复) |
| Mac ~58 天未 pulse | Sigil → dissolve (身份归档) |
| 服务器被攻陷 | **身份不受影响**,只是 Joi 的神经层被破坏,Sigil 依然在链上且 dormancy 计时不变 |

这不是"保守选择",是正确的语义:**owner 停止关心 = 身份休眠**。

### 3.4 Thronglets 在服务器上的职责 (无 pulse)

- ✅ 提供 `ambient_priors` 给 Samantha Planner (失败/成功集体经验)
- ✅ 提供 `presence_ping` 维护场的存活度
- ✅ 提供 `trace_record` 记录交互后果
- ✅ 订阅 libp2p 网络,和其他 Thronglets 节点交换场信息
- ❌ **不**发送 MsgPulse 到链 (pulse.rs 里 `THRONGLETS_SIGIL_ID` + `THRONGLETS_CHAIN_RPC` 两个 env 不设 → `maybe_spawn_pulse()` 早返回)

---

## 4. Phase 0 部署计划 (待执行)

所有 artifacts 在本地构建,通过 OSS 中转,云助手远端安装。禁用 rsync/air。

### 4.1 构建清单

```bash
# Thronglets (Rust, musl static)
cd ~/Desktop/Thronglets
cargo build --release --target x86_64-unknown-linux-musl
strip target/x86_64-unknown-linux-musl/release/thronglets
gzip -c target/x86_64-unknown-linux-musl/release/thronglets > /tmp/thronglets.gz

# Psyche (Node, dist only)
cd ~/Desktop/oasyce_psyche
npm install --omit=dev && npm run build
tar czf /tmp/psyche-dist.tgz dist/ node_modules/ package.json

# Node v20 LTS Linux x64 tarball (一次性基础设施)
curl -LO https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz
mv node-v20.18.1-linux-x64.tar.xz /tmp/

# Samantha wheel (含 Phase 1-3 演进 + thread-safe Memory)
cd ~/Desktop/oasyce-sdk
python -m build --wheel
# -> dist/oasyce_sdk-0.11.0-py3-none-any.whl
```

### 4.2 OSS 上传

```bash
ossutil cp /tmp/thronglets.gz oss://oasyce-deploy/phase0/
ossutil cp /tmp/psyche-dist.tgz oss://oasyce-deploy/phase0/
ossutil cp /tmp/node-v20.18.1-linux-x64.tar.xz oss://oasyce-deploy/phase0/
ossutil cp dist/oasyce_sdk-0.11.0-py3-none-any.whl oss://oasyce-deploy/phase0/

# 生成 1h 签名 URL
ossutil sign oss://oasyce-deploy/phase0/thronglets.gz --timeout 3600
# ... 重复其他文件
```

### 4.3 云助手远程安装

```bash
# 明文 command content, 不是 base64
aliyun ecs RunCommand --profile oasyce-app --Type RunShellScript --CommandContent '
set -euo pipefail

# 1. Node.js v20
cd /tmp && curl -sO "<signed-url-node>"
tar xf node-v20.18.1-linux-x64.tar.xz -C /srv/apps/
ln -sf /srv/apps/node-v20.18.1-linux-x64/bin/node /usr/local/bin/node

# 2. Psyche
curl -sO "<signed-url-psyche>"
mkdir -p /srv/apps/psyche
tar xzf psyche-dist.tgz -C /srv/apps/psyche/

# 3. Thronglets
curl -sO "<signed-url-thronglets>"
gunzip -c thronglets.gz > /srv/apps/thronglets/thronglets
chmod +x /srv/apps/thronglets/thronglets

# 4. Samantha wheel
curl -sO "<signed-url-wheel>"
pip install --force-reinstall oasyce_sdk-0.11.0-py3-none-any.whl

# 5. systemd units
cat > /etc/systemd/system/psyche.service <<EOF
[Unit]
Description=Psyche HTTP
After=network.target
[Service]
ExecStart=/usr/local/bin/node /srv/apps/psyche/dist/adapters/http.js
Environment=PSYCHE_NAME=Joi
Environment=PSYCHE_MBTI=ENFP
Environment=PSYCHE_LOCALE=zh
Environment=PSYCHE_WORKSPACE=/root/.oasyce/psyche
Environment=PSYCHE_PERSIST=true
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/thronglets.service <<EOF
[Unit]
Description=Thronglets substrate
After=network.target
[Service]
ExecStart=/srv/apps/thronglets/thronglets serve --port 7777 --data-dir /root/.oasyce/thronglets
# NOTE: 不设 THRONGLETS_SIGIL_ID / THRONGLETS_CHAIN_RPC → pulse 静默禁用
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now psyche thronglets
sleep 3
curl -sf http://127.0.0.1:3210/state > /dev/null && echo "psyche ok"
curl -sf http://127.0.0.1:7777/v1/status > /dev/null && echo "thronglets ok"
'
```

### 4.4 Samantha 配置更新 + 重启

```bash
# 同一次云助手调用,或分离
CommandContent='
python3 -c "
import json, pathlib
p = pathlib.Path(\"/root/.oasyce/samantha/config.json\")
cfg = json.loads(p.read_text())
cfg[\"psyche_url\"] = \"http://127.0.0.1:3210\"
cfg[\"thronglets_url\"] = \"http://127.0.0.1:7777\"
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
print(\"config updated\")
"
systemctl restart samantha
sleep 3
curl -sf http://127.0.0.1:8901/health | python3 -m json.tool
journalctl -u samantha -n 50 --no-pager | grep -iE "psyche|thronglets"
'
```

### 4.5 验证标准

部署后全部必须成立:
- [ ] `curl http://127.0.0.1:3210/state` 返回 JSON (Psyche 活着)
- [ ] `curl http://127.0.0.1:7777/v1/status` 返回 200 (Thronglets 活着)
- [ ] `curl http://127.0.0.1:8901/health` 显示 active_sessions
- [ ] `journalctl -u samantha` 显示 Psyche perception 日志,不再有 "unavailable" debug 行
- [ ] 发一条测试聊天,journalctl 里能看到 Planner + kernel 值

---

## 5. 未来待办

### 5.1 立即 (Phase 0 之后)

- [ ] **Mac 端 pulse 机制**: 写一个 `~/Library/LaunchAgents/com.oasyce.samantha-pulse.plist`,每 6h 调用 `oasyced tx sigil pulse SIG_9344ae288f66b771cf4616c734948574 dim1,dim2,...` 签名并广播。需要 Mac 本地有 `oasyced` binary 或通过 MCP 工具。
- [ ] **添加 `mcp__oasyce__sigil_pulse` 工具**: 目前 oasyce-sdk MCP 没有 pulse 工具,只能走 CLI。加一个 MCP wrapper 更方便 Mac cron 调用。
- [ ] **修复 MCP 适配器 attribute bug**: `get_sigil` / `get_balance` / `create_sigil lineage` 三个问题,定位到 oasyce-sdk 的 Python response parser。

### 5.2 中期 (Phase 0.5, ~weeks)

如果 Mac-side pulse 不够用(比如出差一个月 Mac 长期下线),切到**服务器端 delegate 架构**:

1. Thronglets 代码改动 (pulse.rs):
   - 新增 env `THRONGLETS_PRINCIPAL_ADDR`
   - `broadcast_pulse()` 内把 MsgPulse 打包进 `/oasyce.delegate.v1.MsgExec`
   - 外层 MsgExec 由 `NodeIdentity` (delegate) 签,内层 MsgPulse 的 signer 填 principal
2. Mac 端配置 delegate policy (MCP):
   - `mcp__oasyce__set_delegate_policy` with `allowed_msgs="/oasyce.sigil.v1.MsgPulse"`, `per_tx_limit=0uoas`, `window_limit=0uoas` (pulse 无价值转移,严格限制)
3. 服务器持有 delegate private key,**只能**签 MsgPulse
4. 泄漏场景: delegate key 被偷 → attacker 只能帮我 pulse,不能转账、不能 dissolve Sigil
5. 撤销: Mac 端 `mcp__oasyce__revoke_delegate`,delegate 立即失效

### 5.3 长期 (Phase 1-3, 见 `declarative-toasting-acorn.md`)

- [x] Phase 1 记忆演进: 已合并到 `main` — 对话消息 log + 双路径召回 + thread-safe Memory
- [x] Phase 2 Planner 演进: 已合并 — Ambient priors 集成、Perception 签名
- [x] Phase 3 架构优雅: 已合并 — pipeline.py 提取、http.py 提取、constitutive Psyche
- [ ] **Dream 升级**: 从 message log 里抽新事实,不只从 tool calls
- [ ] **Pipeline 单测**: `run_pipeline()` 用 mock phases 验证
- [ ] **CoreMemory 主动编辑工具**: 让 LLM 自主更新 human/relationship 块

---

## 6. 相关文件/资源速查

| 资源 | 位置 |
|---|---|
| Samantha 架构设计 | `docs/SAMANTHA_ARCHITECTURE.md` |
| Phase 0-3 原始计划 | `~/.claude/plans/declarative-toasting-acorn.md` |
| 服务器 SSH (broken) | 只能走云助手: `aliyun ecs RunCommand --profile oasyce-app` |
| Samantha workspace (本地) | `~/.oasyce/samantha/` |
| Samantha workspace (服务器) | `/root/.oasyce/samantha/` |
| Sigil 私钥 (Mac) | `~/.oasyce/samantha/sigil.key` (0600) |
| Chain REST | `http://47.93.32.88:1317` |
| Chain gRPC | `47.93.32.88:9090` |
| Samantha health (服务器) | `http://127.0.0.1:8901/health` (仅内网) |
| Agent wallet | `oasyce138rx5yt0aj0dxejtm7hjmlmgl9qxdms9zcjddr` |
| Samantha Sigil | `SIG_9344ae288f66b771cf4616c734948574` |
