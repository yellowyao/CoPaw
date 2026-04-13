# Hermes Agent run_agent.py 详细解析

> 本文档详细解析 Hermes Agent 的核心智能体实现脚本 `run_agent.py`，约 10000+ 行代码。

## 概览

`run_agent.py` 是 Hermes Agent 的核心文件，包含 `AIAgent` 类，负责：
- 与多种 LLM API 的交互（OpenAI、Anthropic、OpenRouter、Codex 等）
- 工具调用循环和执行
- 记忆管理（Memory Nudge）
- 技能学习（Skill Nudge）
- 上下文压缩
- 会话持久化
- 多平台适配

```
文件结构：
├── 导入和配置 (1-110)
├── 辅助类和函数 (113-490)
│   ├── _SafeWriter — 管道安全写入器
│   ├── IterationBudget — 迭代预算计数器
│   ├── 并行工具判断函数
│   ├── Surrogate 字符清洗
│   └── Qwen Portal headers
├── AIAgent 类 (492-10308)
│   ├── __init__ — 初始化 (516-1200)
│   ├── 系统提示构建 (3050-3206)
│   ├── 背景审查机制 (2050-2190)
│   ├── 工具执行 (6686-7200)
│   ├── 上下文压缩 (多处)
│   ├── run_conversation — 主循环 (7527-10292)
│   └── chat — 简化接口 (10294-10308)
└── main 函数 (10309-10450)
```

---

## 一、辅助类和函数

### 1.1 `_SafeWriter` — 管道安全写入器

```python
class _SafeWriter:
    """Transparent stdio wrapper that catches OSError/ValueError from broken pipes."""
```

**用途**：当 Hermes 作为 systemd 服务、Docker 容器或无头守护进程运行时，stdout/stderr 管道可能变得不可用（空闲超时、缓冲区耗尽、套接字重置）。任何 `print()` 调用都可能引发 `OSError: [Errno 5] Input/output error`，导致崩溃。

**机制**：
- 包装 stdout/stderr，捕获 OSError 和 ValueError
- 正常时透明传递，异常时静默忽略
- 防止子代理线程清理时的管道错误

### 1.2 `IterationBudget` — 迭代预算计数器

```python
class IterationBudget:
    """Thread-safe iteration counter for an agent."""
    
    def __init__(self, max_total: int):
        self.max_total = max_total
        self._used = 0
        self._lock = threading.Lock()
```

**用途**：每个智能体（父或子）都有自己的迭代预算。父代理上限为 `max_iterations`（默认 90），子代理有独立预算上限为 `delegation.max_iterations`（默认 50）。

**关键方法**：
- `consume()` — 消耗一次迭代，返回是否允许
- `refund()` — 返还一次迭代（用于 execute_code 免费轮次）

### 1.3 并行工具判断

```python
_NEVER_PARALLEL_TOOLS = frozenset({"clarify"})  # 交互类工具，永不并行
_PARALLEL_SAFE_TOOLS = frozenset({              # 只读工具，无共享状态
    "read_file", "search_files", "session_search", 
    "skill_view", "web_search", ...
})
_PATH_SCOPED_TOOLS = frozenset({"read_file", "write_file", "patch"})  # 文件路径工具
```

**判断逻辑**：
1. 如果包含 `_NEVER_PARALLEL_TOOLS` 中的工具 → 串行执行
2. 如果包含 `_PATH_SCOPED_TOOLS` 且路径重叠 → 串行执行
3. 否则 → 并行执行（最多 8 个线程）

---

## 二、AIAgent 类

### 2.1 初始化参数（`__init__`）

```python
def __init__(
    self,
    base_url: str = None,
    api_key: str = None,
    provider: str = None,
    api_mode: str = None,
    model: str = "",
    max_iterations: int = 90,      # 最大工具调用迭代次数
    tool_delay: float = 1.0,
    enabled_toolsets: List[str] = None,
    disabled_toolsets: List[str] = None,
    session_id: str = None,
    platform: str = None,          # "cli", "telegram", "discord", "whatsapp"
    skip_memory: bool = False,
    ...
):
```

**关键初始化流程**：

1. **API 模式检测**：
   ```python
   if self.provider == "anthropic":
       self.api_mode = "anthropic_messages"
   elif "chatgpt.com/backend-api/codex" in self._base_url_lower:
       self.api_mode = "codex_responses"
   else:
       self.api_mode = "chat_completions"
   ```

2. **记忆系统初始化**：
   ```python
   self._memory_store = None
   self._memory_enabled = False
   self._memory_nudge_interval = 10      # 每 10 轮触发记忆提醒
   self._memory_flush_min_turns = 6      # 最少 6 轮才能刷新
   
   if not skip_memory:
       self._memory_store = MemoryStore(...)
       self._memory_store.load_from_disk()
   ```

3. **技能系统初始化**：
   ```python
   self._skill_nudge_interval = 10       # 每 10 次工具迭代触发技能提醒
   self._iters_since_skill = 0
   ```

4. **迭代预算**：
   ```python
   self.iteration_budget = iteration_budget or IterationBudget(max_iterations)
   ```

---

### 2.2 系统提示构建（`_build_system_prompt`）

系统提示由多个部分组成，按优先级叠加：

```python
def _build_system_prompt(self, system_message=None):
    prompt_parts = []
    
    # 1. Agent identity — SOUL.md 或 DEFAULT_AGENT_IDENTITY
    if _soul_content := load_soul_md():
        prompt_parts.append(_soul_content)
    else:
        prompt_parts.append(DEFAULT_AGENT_IDENTITY)
    
    # 2. Tool-aware behavioral guidance
    if "memory" in self.valid_tool_names:
        prompt_parts.append(MEMORY_GUIDANCE)
    if "skill_manage" in self.valid_tool_names:
        prompt_parts.append(SKILLS_GUIDANCE)
    
    # 3. Persistent memory (MEMORY.md)
    if self._memory_store and self._memory_enabled:
        mem_block = self._memory_store.format_for_system_prompt("memory")
        prompt_parts.append(mem_block)
    
    # 4. Skills index
    if has_skills_tools:
        skills_prompt = build_skills_system_prompt(...)
        prompt_parts.append(skills_prompt)
    
    # 5. Context files (AGENTS.md, .cursorrules)
    context_files_prompt = build_context_files_prompt(...)
    prompt_parts.append(context_files_prompt)
    
    # 6. Current date & time
    prompt_parts.append(f"Conversation started: {now.strftime(...)}")
    
    # 7. Platform hints
    if platform_key in PLATFORM_HINTS:
        prompt_parts.append(PLATFORM_HINTS[platform_key])
    
    return "\n\n".join(prompt_parts)
```

**提示层次结构**：

| 优先级 | 内容 | 来源 |
|--------|------|------|
| 1 | Agent Identity | SOUL.md / DEFAULT_AGENT_IDENTITY |
| 2 | Tool Guidance | MEMORY_GUIDANCE, SKILLS_GUIDANCE |
| 3 | Memory Content | MEMORY.md (format_for_system_prompt) |
| 4 | Skills Index | build_skills_system_prompt() |
| 5 | Context Files | AGENTS.md, .cursorrules |
| 6 | Timestamp | 当前时间 |
| 7 | Platform Hint | PLATFORM_HINTS[platform] |

---

### 2.3 背景审查机制（Memory/Skill Nudge）

#### 2.3.1 触发条件

**Memory Nudge**：
```python
# 在 run_conversation 开头检查
_should_review_memory = False
if (self._memory_nudge_interval > 0
        and "memory" in self.valid_tool_names
        and self._memory_store):
    self._turns_since_memory += 1
    if self._turns_since_memory >= self._memory_nudge_interval:
        _should_review_memory = True
        self._turns_since_memory = 0
```

**Skill Nudge**：
```python
# 在 run_conversation 结尾检查
_should_review_skills = False
if (self._skill_nudge_interval > 0
        and self._iters_since_skill >= self._skill_nudge_interval
        and "skill_manage" in self.valid_tool_names):
    _should_review_skills = True
    self._iters_since_skill = 0
```

**计数器更新**：
```python
# 工具循环中每次迭代
self._iters_since_skill += 1

# 当 skill_manage 工具被实际使用时
if function_name == "skill_manage":
    self._iters_since_skill = 0
```

#### 2.3.2 背景审查提示词

```python
_MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory if appropriate.\n\n"
    "Focus on:\n"
    "1. Has the user revealed things about themselves — their persona, desires, "
    "preferences, or personal details worth remembering?\n"
    "2. Has the user expressed expectations about how you should behave, their work "
    "style, or ways they want you to operate?\n\n"
    "If something stands out, save it using the memory tool. "
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)

_SKILL_REVIEW_PROMPT = (
    "Review the conversation above and consider saving or updating a skill if appropriate.\n\n"
    "Focus on: was a non-trivial approach used to complete a task that required trial "
    "and error, or changing course due to experiential findings along the way, or did "
    "the user expect or desire a different method or outcome?\n\n"
    "If a relevant skill already exists, update it with what you learned. "
    "Otherwise, create a new skill if the approach is reusable.\n"
    "If nothing is worth saving, just say 'Nothing to save.' and stop."
)
```

#### 2.3.3 `_spawn_background_review` 实现

```python
def _spawn_background_review(
    self,
    messages_snapshot: List[Dict],
    review_memory: bool = False,
    review_skills: bool = False,
) -> None:
    """Spawn a background thread to review the conversation for memory/skill saves."""
    
    # 选择提示词
    if review_memory and review_skills:
        prompt = self._COMBINED_REVIEW_PROMPT
    elif review_memory:
        prompt = self._MEMORY_REVIEW_PROMPT
    else:
        prompt = self._SKILL_REVIEW_PROMPT
    
    def _run_review():
        # 创建审查代理（静默模式，共享记忆存储）
        review_agent = AIAgent(
            model=self.model,
            max_iterations=8,           # 最多 8 次迭代
            quiet_mode=True,            # 不输出进度
            platform=self.platform,
        )
        review_agent._memory_store = self._memory_store
        review_agent._memory_nudge_interval = 0  # 禁用递归审查
        review_agent._skill_nudge_interval = 0
        
        # 在快照对话上追加审查提示
        review_agent.run_conversation(
            user_message=prompt,
            conversation_history=messages_snapshot,
        )
        
        # 提取成功的工具动作并汇报
        actions = []
        for msg in review_agent._session_messages:
            if msg.get("role") == "tool":
                data = json.loads(msg.get("content", "{}"))
                if data.get("success"):
                    actions.append(data.get("message", ""))
        
        if actions:
            self._safe_print(f"  💾 {summary}")
    
    # 启动后台线程
    t = threading.Thread(target=_run_review, daemon=True, name="bg-review")
    t.start()
```

**关键特点**：
- 异步执行，不阻塞主对话
- 共享 `_memory_store`，直接写入
- 禁用递归审查（nudge_interval = 0）
- 静默模式，不干扰用户体验
- 最多 8 次迭代完成审查

---

### 2.4 主对话循环（`run_conversation`）

```python
def run_conversation(
    self,
    user_message: str,
    system_message: str = None,
    conversation_history: List[Dict] = None,
    task_id: str = None,
    stream_callback: Optional[callable] = None,
) -> Dict[str, Any]:
```

#### 流程概览：

```
┌─────────────────────────────────────────────────────────────┐
│  1. 初始化                                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ • 生成 session_id, task_id                               │ │
│  │ • 重置计数器 (_invalid_tool_retries, etc.)               │ │
│  │ • 重置迭代预算                                            │ │
│  │ • 检查 memory nudge 触发                                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  2. 构建消息                                                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ • 复制 conversation_history                              │ │
│  │ • 添加 user message                                       │ │
│  │ • 构建/缓存系统提示                                        │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  3. 预压缩检查                                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ • 估算 token 数                                           │ │
│  │ • 如果超阈值 → 预压缩                                      │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  4. 主循环 (while api_call_count < max_iterations)          │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ • 检查中断请求                                             │ │
│  │ • 消耗迭代预算                                             │ │
│  │ • 调用 API（流式或非流式）                                  │ │
│  │ • 处理响应：                                               │ │
│  │   ├─ 文本响应 → 可能结束                                   │ │
│  │   ├─ 工具调用 → 执行工具                                    │ │
│  │   ├─ 错误 → 分类处理                                        │ │
│  │ • 压缩检查（如果超出上下文限制）                             │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  5. 结束处理                                                  │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ • 检查 skill nudge 触发                                    │ │
│  │ • 外部记忆 provider sync                                   │ │
│  │ • 如果触发审查 → _spawn_background_review                  │ │
│  │ • 持久化会话                                               │ │
│  │ • 返回结果                                                 │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

#### 核心循环代码片段：

```python
while (api_call_count < self.max_iterations and self.iteration_budget.remaining > 0):
    
    # 1. 中断检查
    if self._interrupt_requested:
        interrupted = True
        break
    
    # 2. 消耗预算
    if not self.iteration_budget.consume():
        break
    
    # 3. 调用 API
    response = self._make_api_call(messages, tools=...)
    
    # 4. 处理响应
    if response has tool_calls:
        self._execute_tool_calls(response, messages)
    elif response has text:
        final_response = response.text
        # 检查是否需要继续（响应可能不完整）
        if should_continue(response):
            continue
        else:
            break  # 完成
    
    # 5. 压缩检查
    if context_exceeded:
        messages = self._compress_context(messages)
```

---

### 2.5 工具执行（`_execute_tool_calls`）

```python
def _execute_tool_calls(self, assistant_message, messages, task_id):
    """Execute tool calls from the assistant message."""
    
    tool_calls = assistant_message.tool_calls
    
    # 判断是否可以并行执行
    if _should_parallelize_tool_batch(tool_calls):
        self._execute_tool_calls_concurrent(tool_calls, messages)
    else:
        self._execute_tool_calls_sequential(tool_calls, messages)
```

#### 并行执行：

```python
def _execute_tool_calls_concurrent(self, tool_calls, messages):
    """Execute independent tool calls in parallel using ThreadPoolExecutor."""
    
    with ThreadPoolExecutor(max_workers=_MAX_TOOL_WORKERS) as executor:
        futures = []
        for tc in tool_calls:
            future = executor.submit(
                self._execute_single_tool,
                tc.function.name,
                tc.function.arguments,
            )
            futures.append((tc.id, future))
        
        # 收集结果
        for tc_id, future in futures:
            result = future.result(timeout=...)
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })
```

#### 单工具执行：

```python
def _execute_single_tool(self, function_name, function_args):
    """Execute a single tool and return the result."""
    
    # 内置工具处理
    if function_name == "memory":
        from tools.memory_tool import memory_tool
        result = memory_tool(action=..., content=..., store=self._memory_store)
        self._turns_since_memory = 0  # 重置计数器
    
    elif function_name == "skill_manage":
        from tools.skills_tool import skill_manage
        result = skill_manage(action=..., ...)
        self._iters_since_skill = 0  # 重置计数器
    
    # 外部记忆 provider
    elif self._memory_manager and self._memory_manager.has_tool(function_name):
        result = self._memory_manager.handle_tool_call(function_name, function_args)
    
    # 注册表工具
    else:
        result = handle_function_call(function_name, function_args)
    
    return result
```

---

### 2.6 上下文压缩

当上下文超出模型限制时触发压缩：

```python
def _compress_context(self, messages, system_message, approx_tokens):
    """Compress context by summarizing old messages."""
    
    # 压缩前先刷新记忆
    if self._memory_flush_min_turns > 0:
        self._memory_flush(messages, min_turns=self._memory_flush_min_turns)
    
    # 使用 ContextCompressor 进行压缩
    messages, new_system = self.context_compressor.compress(
        messages,
        system_prompt=system_message,
        model=self.model,
    )
    
    # 重载记忆（压缩后丢失的记忆需要从磁盘恢复）
    if self._memory_store:
        self._memory_store.load_from_disk()
    
    return messages, new_system
```

---

## 三、关键配置项

### 3.1 Memory 配置

```yaml
# config.yaml
memory:
  memory_enabled: true
  nudge_interval: 10          # 每 N 轮用户对话触发记忆提醒
  flush_min_turns: 6          # 压缩前最少保留 N 轮
  memory_char_limit: 2200     # 记忆文本上限
  provider: "honcho"          # 外部记忆提供者（可选）
```

### 3.2 Skills 配置

```yaml
# config.yaml
skills:
  creation_nudge_interval: 10  # 每 N 次工具迭代触发技能提醒
```

### 3.3 Agent 配置

```yaml
# config.yaml
agent:
  max_iterations: 90           # 最大工具调用迭代
  tool_use_enforcement: "auto" # 工具使用强制模式
```

---

## 四、与 CoPaw 的对比

| 特性 | Hermes Agent | CoPaw |
|------|--------------|-------|
| **Memory Nudge** | 基于 `turns_since_memory` 计数器，每 N 轮用户对话触发 | 基于 `memory_nudge_interval`，固定间隔触发 |
| **Skill Nudge** | 基于 `iters_since_skill` 计数器，每 N 次工具迭代触发 | 基于 `skill_nudge_interval`，固定间隔触发 |
| **背景审查** | 异步线程 + 代理实例，不阻塞主对话 | 同步调用，阻塞主流程 |
| **审查代理** | 创建独立的轻量 AIAgent（max_iterations=8, quiet_mode=True） | 无独立代理，直接调用 |
| **辅助模型** | `auxiliary_client.py` 自动选择低成本模型 | 无，使用主模型 |
| **记忆 Plugin** | `MemoryProvider` 抽象，支持 Honcho/Mem0 等 | ReMe 集成，无插件化 |
| **系统提示缓存** | Anthropic prompt caching 支持 | 无 |

---

## 五、学习要点

### 5.1 如何移植到 CoPaw

1. **添加迭代计数器**：
   ```python
   # 在 CoPawAgent.__init__ 中
   self._turns_since_memory = 0
   self._iters_since_skill = 0
   ```

2. **在 run_conversation 开头检查 memory nudge**：
   ```python
   if self._turns_since_memory >= self._memory_nudge_interval:
       _should_review_memory = True
   ```

3. **在工具循环中更新 skill 计数器**：
   ```python
   self._iters_since_skill += 1
   ```

4. **在 run_conversation 结尾检查 skill nudge 并触发背景审查**：
   ```python
   if self._iters_since_skill >= self._skill_nudge_interval:
       self._spawn_background_review(messages, review_skills=True)
   ```

5. **实现 `_spawn_background_review`**：
   - 使用 ThreadPoolExecutor
   - 创建轻量代理
   - 静默执行
   - 共享记忆存储

### 5.2 关键设计理念

- **异步审查**：不阻塞用户体验
- **计数器机制**：基于实际使用而非固定时间
- **共享存储**：背景代理直接写入主存储
- **静默执行**：不产生额外输出
- **预算限制**：防止审查代理失控

---

## 六、总结

`run_agent.py` 是一个高度模块化、功能完备的智能体实现，其核心特点：

1. **多 API 支持**：自动检测并适配 OpenAI/Anthropic/Codex 等多种 API
2. **工具并行**：智能判断工具是否可并行执行
3. **记忆/技能学习**：基于计数器的触发 + 异步背景审查
4. **上下文管理**：预压缩 + 记忆预刷新 + 动态压缩
5. **会话持久化**：SQLite + JSON 日志双轨持久化
6. **插件化记忆**：MemoryProvider 抽象支持多种后端

这些机制为 CoPaw 的 SelfLearningAgent 实现提供了重要的参考架构。