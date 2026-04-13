# Hermes Agent vs CoPaw 深度对比分析

> 本文档对比 Hermes Agent (NousResearch) 和 CoPaw (AgentScope) 两个开源 AI Agent 框架的设计差异。

---

## 1. 项目概述

### Hermes Agent

| 属性 | 值 |
|------|-----|
| **开发者** | Nous Research (Hermes 模型团队) |
| **发布时间** | 2026-02-26 |
| **Stars** | 64K+ |
| **许可证** | MIT |
| **底层框架** | 自研 (无依赖) |
| **核心文件** | `run_agent.py` (~532KB, ~9200 行) |

### CoPaw

| 属性 | 值 |
|------|-----|
| **开发者** | AgentScope (阿里) |
| **底层框架** | AgentScope |
| **许可证** | Apache 2.0 |
| **核心文件** | `react_agent.py` (~500 行) |

---

## 2. 核心架构对比

### 代码量对比

| 模块 | Hermes Agent | CoPaw |
|------|--------------|-------|
| **核心 Agent** | `run_agent.py` 532KB | `react_agent.py` ~15KB |
| **CLI** | `cli.py` 439KB | `cli/` 多文件 |
| **Gateway** | `gateway/run.py` 408KB | `channels/` 多文件 |
| **工具数量** | 47+ | 14 |
| **平台数量** | 15+ | 9+ |

### 设计理念

| 方面 | Hermes Agent | CoPaw |
|------|--------------|-------|
| **架构模式** | 单体大文件 (便于部署) | 模块化 (便于扩展) |
| **Agent 实现** | 自研 AIAgent 类 | 继承 ReActAgent |
| **状态管理** | SQLite + FTS5 | JSON 文件 |
| **记忆系统** | MemoryManager + 多 Provider | ReMeLightMemoryManager |
| **学习机制** | ✅ 自我学习循环 | ❌ 无自动学习 |

---

## 3. AIAgent vs CoPawAgent 对比

### Hermes AIAgent (`run_agent.py:492`)

```python
class AIAgent:
    """AI Agent with tool calling capabilities.
    
    This class manages the conversation flow, tool execution, 
    and response handling for AI models.
    """
    
    def __init__(
        self,
        base_url: str = None,
        api_key: str = None,
        provider: str = None,
        api_mode: str = None,
        model: str = "",
        max_iterations: int = 90,
        tool_delay: float = 1.0,
        enabled_toolsets: List[str] = None,
        disabled_toolsets: List[str] = None,
        save_trajectories: bool = False,
        verbose_logging: bool = False,
        quiet_mode: bool = False,
        ephemeral_system_prompt: str = None,
        platform: str = None,
        user_id: str = None,
        session_db=None,
        # ... 50+ 更多参数
    ):
        # 初始化逻辑
```

### CoPawAgent (`react_agent.py`)

```python
class CoPawAgent(ToolGuardMixin, ReActAgent):
    """CoPaw Agent with Tool Guard and Skill support."""
    
    def __init__(
        self,
        agent_config: AgentConfig,
        env_context: dict,
        mcp_clients: list,
        memory_manager: MemoryManager,
        request_context: dict,
    ):
        # 继承 AgentScope 的 ReActAgent
        super().__init__(...)
        # 注册内置工具
        self._create_toolkit()
        # 加载 Skills
        self._register_skills()
```

### 关键差异

| 特性 | Hermes AIAgent | CoPawAgent |
|------|----------------|------------|
| **继承关系** | 无继承，完全自研 | 继承 ReActAgent + ToolGuardMixin |
| **初始化参数** | 50+ 参数，高度可配置 | 5 个核心参数 |
| **工具管理** | 内置 + MCP + Skill 动态加载 | Toolkit + Skills |
| **API 模式** | 3 种 (chat_completions, codex_responses, anthropic_messages) | 1 种 (依赖 AgentScope) |
| **迭代预算** | IterationBudget 类管理 | 无显式管理 |
| **Prompt Caching** | ✅ Anthropic 支持 | ❌ 无 |

---

## 4. 状态存储对比

### Hermes Agent: SQLite + FTS5

```python
# hermes_state.py

SCHEMA_SQL = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,        -- 'cli', 'telegram', 'discord'
    user_id TEXT,
    model TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,      -- 压缩后的父子关系
    started_at REAL,
    message_count INTEGER,
    tool_call_count INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_usd REAL,
    title TEXT,
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    role TEXT,
    content TEXT,
    tool_calls TEXT,
    timestamp REAL,
);

-- FTS5 全文搜索
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content,
    content=messages,
);
"""
```

**特点：**
- WAL 模式支持并发读写
- FTS5 支持跨 Session 全文搜索
- 自动压缩触发 Session 分裂
- 详细 Token 统计和成本追踪

### CoPaw: JSON 文件

```python
# session.py

class SafeJSONSession(SessionBase):
    """JSON 文件存储，Windows 文件名安全化"""
    
    def _get_save_path(self, session_id, user_id):
        safe_sid = sanitize_filename(session_id)
        safe_uid = sanitize_filename(user_id)
        return f"{safe_uid}_{safe_sid}.json"
    
    async def save_session_state(self, session_id, user_id, **state_modules):
        state_dicts = {name: module.state_dict() for name, module in state_modules}
        with open(path, "w") as f:
            f.write(json.dumps(state_dicts))
```

**特点：**
- 无数据库依赖
- 每个 Session 独立文件
- 异步 I/O (aiofiles)
- Windows 文件名安全处理

---

## 5. 记忆系统对比

### Hermes Agent: MemoryManager + Provider 插件

```python
# agent/memory_manager.py

class MemoryManager:
    """管理内置 + 一个外部记忆 Provider"""
    
    def __init__(self):
        self._providers: List[MemoryProvider] = []
        self._has_external: bool = False
    
    def add_provider(self, provider: MemoryProvider):
        """只允许一个外部 Provider"""
        if not is_builtin and self._has_external:
            logger.warning("Rejected — only one external provider allowed")
            return
        self._providers.append(provider)
    
    def build_system_prompt(self) -> str:
        """收集所有 Provider 的系统提示"""
        return "\n".join(p.build_system_prompt() for p in self._providers)
    
    def prefetch_all(self, user_message) -> str:
        """预取所有记忆上下文"""
        return "\n".join(p.prefetch(user_message) for p in self._providers)
```

**特点：**
- 插件式 Provider 系统
- Honcho dialectic 用户建模
- 自动 Nudge 提醒记忆更新
- 支持跨 Session 搜索

### CoPaw: ReMeLightMemoryManager

```python
# 基于 AgentScope 的 ReMe 记忆系统

class ReMeLightMemoryManager:
    """长期记忆管理"""
    
    async def add_memory(self, content, metadata):
        """添加记忆"""
        await self._reme.add(content, metadata)
    
    async def search_memory(self, query):
        """搜索记忆"""
        return await self._reme.search(query)
```

---

## 6. 工具系统对比

### Hermes Agent: 47+ 工具，Toolset 分组

```python
# tools/registry.py

class ToolRegistry:
    """单例注册中心"""
    
    def register(
        self,
        name: str,
        toolset: str,      # 分组：'terminal', 'browser', 'memory', ...
        schema: dict,
        handler: Callable,
        check_fn: Callable = None,   # 可用性检查
        requires_env: list = None,   # 环境变量依赖
        is_async: bool = False,
        emoji: str = "",
    ):
        self._tools[name] = ToolEntry(...)
```

**工具列表 (tools/ 目录)：**

| 工具文件 | 大小 | 功能 |
|----------|------|------|
| `browser_tool.py` | 93KB | 浏览器自动化 |
| `terminal_tool.py` | 75KB | 终端执行 |
| `skills_hub.py` | 101KB | Skills Hub 集成 |
| `mcp_tool.py` | 84KB | MCP 服务器连接 |
| `file_operations.py` | 44KB | 文件操作 |
| `web_tools.py` | 87KB | Web 请求 |
| `memory_tool.py` | 22KB | 记忆管理 |
| `send_message_tool.py` | 44KB | 消息发送 |
| ... | ... | ... |

### CoPaw: 14 内置工具，Skill 扩展

```python
# react_agent.py

def _create_toolkit(self):
    """注册 14 个内置工具"""
    toolkit = Toolkit()
    
    toolkit.register_tool(shell_execute)
    toolkit.register_tool(file_read)
    toolkit.register_tool(file_write)
    toolkit.register_tool(edit_file)
    toolkit.register_tool(web_search)
    toolkit.register_tool(web_fetch)
    toolkit.register_tool(browser_visible)
    # ... 14 个工具
```

**Skills 扩展：**
- `pdf/`, `docx/`, `xlsx/`, `pptx/`
- `cron/`, `news/`, `browser_visible/`
- 用户自定义 Skills

---

## 7. Gateway/Channel 对比

### Hermes Gateway: 15+ 平台

```
gateway/platforms/
├── telegram.py       (121KB)
├── discord.py        (128KB)
├── slack.py          (67KB)
├── whatsapp.py       (38KB)
├── signal.py         (32KB)
├── matrix.py         (81KB)
├── feishu.py         (153KB)
├── dingtalk.py       (12KB)
├── wecom.py          (58KB)
├── weixin.py         (64KB)
├── mattermost.py     (27KB)
├── email.py          (23KB)
├── sms.py            (14KB)
├── bluebubbles.py    (33KB)
├── homeassistant.py  (16KB)
├── api_server.py     (77KB)  -- REST API
└── webhook.py        (25KB)
```

### CoPaw Channels: 9+ 平台

```
app/channels/
├── console.py        -- Web UI
├── dingtalk.py       -- 钉钉
├── feishu.py         -- 飞书
├── discord.py        -- Discord
├── telegram.py       -- Telegram
├── imessage.py       -- iMessage
├── qq.py             -- QQ
├── wechat.py         -- 微信
└── matrix.py         -- Matrix
```

---

## 8. 自我学习机制对比

### Hermes Agent: 完整学习循环

```python
# run_agent.py 中的学习逻辑

# 1. 记忆 Nudge (定期提醒)
if self._memory_nudge_interval > 0:
    self._turns_since_memory += 1
    if self._turns_since_memory >= self._memory_nudge_interval:
        _should_review_memory = True

# 2. Skill 自动创建
# agent/insights.py - 从对话提取可复用模式

# 3. 记忆持久化
# skills_tool.py - 自动保存到 MEMORY.md
```

**学习特性：**
- ✅ 自动从对话提取模式
- ✅ 自动创建/更新 Skills
- ✅ 定期 Nudge 提醒回顾记忆
- ✅ Honcho 用户建模
- ✅ 跨 Session 搜索 (FTS5)

### CoPaw: 无自动学习

- ❌ 无自动 Skill 创建
- ❌ 无自动记忆提取
- ✅ 手动编写 Skills
- ✅ ReMe 长期记忆（手动调用）

---

## 9. API 模式对比

### Hermes Agent: 3 种 API 模式

```python
# run_agent.py

if api_mode == "chat_completions":
    # OpenAI 兼容 API
    response = self._client.chat.completions.create(...)
elif api_mode == "codex_responses":
    # OpenAI Codex/Responses API
    response = self._client.responses.create(...)
elif api_mode == "anthropic_messages":
    # Anthropic Messages API
    response = self._anthropic_client.messages.create(...)
```

**自动检测：**
- OpenRouter → chat_completions
- OpenAI API → codex_responses
- Anthropic API → anthropic_messages
- 端点 URL 后缀 `/anthropic` → anthropic_messages

### CoPaw: AgentScope 模型层

```python
# model_factory.py

model, formatter = create_model_and_formatter()

# Formatter 根据模型类型选择
_CHAT_MODEL_FORMATTER_MAP = {
    OpenAIChatModel: OpenAIChatFormatter,
    AnthropicChatModel: AnthropicChatFormatter,
    GeminiChatModel: GeminiChatFormatter,
}
```

---

## 10. 总结对比表

| 方面 | Hermes Agent | CoPaw |
|------|--------------|-------|
| **架构复杂度** | 高 (单体大文件) | 低 (模块化) |
| **代码可读性** | 中 (532KB) | 高 (~500 行) |
| **扩展性** | 高 (插件系统) | 中 (继承模式) |
| **自我学习** | ✅ 完整 | ❌ 无 |
| **记忆搜索** | ✅ FTS5 | ❌ 无 |
| **用户建模** | ✅ Honcho | ❌ 无 |
| **平台支持** | 15+ | 9+ |
| **工具数量** | 47+ | 14 |
| **Prompt Caching** | ✅ | ❌ |
| **RL 训练** | ✅ Atropos | ❌ |
| **状态存储** | SQLite | JSON |
| **二次开发难度** | 高 | 中 |

---

## 11. 集成建议

### 方案 A: 完全替换

将 CoPaw 的 Agent 层替换为 Hermes AIAgent：

```python
# src/copaw/agents/hermes_adapter.py

from hermes.run_agent import AIAgent

class HermesCoPawAgent:
    """包装 Hermes AIAgent 为 CoPaw 接口"""
    
    def __init__(self, agent_config, **kwargs):
        self.hermes = AIAgent(
            model=agent_config.active_model.model,
            provider=agent_config.active_model.provider_id,
            max_iterations=90,
            enabled_toolsets=self._get_toolsets(),
        )
    
    async def __call__(self, msgs):
        result = self.hermes.run_conversation(
            user_message=self._extract_user_message(msgs),
            conversation_history=self._convert_history(msgs[:-1]),
        )
        return Msg(content=result["final_response"])
```

### 方案 B: 增强学习机制

借鉴 Hermes 的自我学习逻辑：

```python
# src/copaw/agents/learning_agent.py

class SelfLearningAgent(CoPawAgent):
    """带自我学习的 Agent"""
    
    async def reply(self, msgs):
        response = await super().reply(msgs)
        
        # 学习逻辑
        patterns = await self._extract_patterns(msgs, response)
        for pattern in patterns:
            await self._create_skill(pattern)
        
        # 记忆 Nudge
        if self._turns_since_memory >= self._nudge_interval:
            await self._nudge_memory_review()
        
        return response
```

### 方案 C: 替换状态存储

使用 SQLite + FTS5 替换 JSON：

```python
# src/copaw/app/runner/session_sqlite.py

class SQLiteSession(SessionBase):
    """SQLite 状态存储"""
    
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
    
    def save_session_state(self, session_id, user_id, **modules):
        # INSERT INTO messages ...
    
    def search_sessions(self, query):
        # SELECT * FROM messages_fts WHERE content MATCH query
```

---

## 12. 参考资源

- Hermes Agent GitHub: https://github.com/NousResearch/hermes-agent
- Hermes Agent 文档: https://hermes-agent.nousresearch.com/docs/
- CoPaw GitHub: https://github.com/agentscope-ai/CoPaw
- AgentScope 文档: https://agentscope.io/