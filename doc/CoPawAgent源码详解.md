# CoPawAgent 源码详解

> 本文档详细解释 `src/copaw/agents/react_agent.py` 的完整实现。

## 文件概述

**文件路径**: `src/copaw/agents/react_agent.py`

**核心职责**: 实现 CoPaw 的主 Agent 类，继承自 AgentScope 的 `ReActAgent`，集成工具、技能、记忆管理和安全拦截等功能。

---

## 1. 模块导入

```python
# 标准库
import asyncio
import logging
import os
from pathlib import Path
from typing import Any, List, Literal, Optional, Type, TYPE_CHECKING

# AgentScope 核心组件
from agentscope.agent import ReActAgent      # ReAct 推理-行动 Agent 基类
from agentscope.memory import InMemoryMemory # 内存记忆实现
from agentscope.message import Msg           # 消息对象
from agentscope.tool import Toolkit          # 工具集管理器

# 第三方库
from anyio import ClosedResourceError
from pydantic import BaseModel

# 内部模块
from ..app.mcp import HttpStatefulClient, StdIOStatefulClient  # MCP 客户端
from .command_handler import CommandHandler                     # 系统命令处理器
from .hooks import BootstrapHook, MemoryCompactionHook          # Agent 钩子
from .model_factory import create_model_and_formatter           # 模型工厂
from .prompt import ...                                         # 提示词构建
from .skills_manager import ...                                 # 技能管理
from .tool_guard_mixin import ToolGuardMixin                    # 工具安全拦截
from .tools import ...                                          # 内置工具函数
```

---

## 2. 类定义与继承关系

### 类声明

```python
NamesakeStrategy = Literal["override", "skip", "raise", "rename"]

class CoPawAgent(ToolGuardMixin, ReActAgent):
    """CoPaw Agent with integrated tools, skills, and memory management."""
```

### 继承关系 (MRO)

```
CoPawAgent
    │
    ├─ ToolGuardMixin (Mixin)
    │   └─ 重写 _acting()：工具执行前的安全检查
    │
    └─ ReActAgent (AgentScope)
        ├─ __call__() → reply()
        ├─ reply()：推理-行动循环
        ├─ _reasoning()：LLM 推理
        ├─ _acting()：工具执行
        └─ print()：发送消息到队列
```

### MRO 详解

```python
# Python 方法解析顺序 (MRO)
# CoPawAgent → ToolGuardMixin → ReActAgent → AgentBase

# 当调用 self._acting() 时：
# 1. 先找 CoPawAgent._acting（如果定义）
# 2. 再找 ToolGuardMixin._acting（安全拦截）
# 3. 最后找 ReActAgent._acting（实际执行）
```

---

## 3. `__init__` 方法

### 方法签名

```python
def __init__(
    self,
    agent_config: "AgentProfileConfig",        # Agent 配置
    env_context: Optional[str] = None,         # 环境上下文
    enable_memory_manager: bool = True,        # 是否启用记忆管理器
    mcp_clients: Optional[List[Any]] = None,   # MCP 客户端列表
    memory_manager: "BaseMemoryManager | None" = None,  # 记忆管理器实例
    request_context: Optional[dict[str, str]] = None,   # 请求上下文
    namesake_strategy: NamesakeStrategy = "skip",       # 同名工具处理策略
    workspace_dir: Path | None = None,         # 工作目录
    task_tracker: Any | None = None,           # 任务追踪器
):
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `agent_config` | AgentProfileConfig | Agent 完整配置，包含模型、运行参数等 |
| `env_context` | str | 额外的环境上下文，会追加到系统提示词 |
| `enable_memory_manager` | bool | 是否启用长期记忆管理 |
| `mcp_clients` | List | MCP 客户端实例列表 |
| `memory_manager` | BaseMemoryManager | 记忆管理器实例（从 Workspace 传入） |
| `request_context` | dict | 请求上下文，包含 session_id, user_id, channel, agent_id |
| `namesake_strategy` | str | 同名工具处理策略：override/skip/raise/rename |
| `workspace_dir` | Path | 工作目录路径 |
| `task_tracker` | Any | 后台任务追踪器 |

### 初始化流程

```python
def __init__(self, ...):
    # ─────────────────────────────────────────────────────────
    # 步骤 1: 保存配置和上下文
    # ─────────────────────────────────────────────────────────
    self._agent_config = agent_config
    self._env_context = env_context
    self._request_context = dict(request_context or {})
    self._mcp_clients = mcp_clients or []
    self._namesake_strategy = namesake_strategy
    self._workspace_dir = workspace_dir
    self._task_tracker = task_tracker

    running_config = agent_config.running
    self._language = agent_config.language

    # ─────────────────────────────────────────────────────────
    # 步骤 2: 创建 Toolkit 并注册内置工具
    # ─────────────────────────────────────────────────────────
    toolkit = self._create_toolkit(namesake_strategy=namesake_strategy)

    # ─────────────────────────────────────────────────────────
    # 步骤 3: 加载并注册 Skills
    # ─────────────────────────────────────────────────────────
    self._register_skills(toolkit)

    # ─────────────────────────────────────────────────────────
    # 步骤 4: 构建系统提示词
    # ─────────────────────────────────────────────────────────
    sys_prompt = self._build_sys_prompt()

    # ─────────────────────────────────────────────────────────
    # 步骤 5: 创建模型和格式化器
    # ─────────────────────────────────────────────────────────
    model, formatter = create_model_and_formatter(agent_id=agent_config.id)

    # ─────────────────────────────────────────────────────────
    # 步骤 6: 初始化父类 ReActAgent
    # ─────────────────────────────────────────────────────────
    super().__init__(
        name="Friday",                        # Agent 名称固定为 "Friday"
        model=model,                          # LLM 模型实例
        sys_prompt=sys_prompt,                # 系统提示词
        toolkit=toolkit,                      # 工具集
        memory=InMemoryMemory(),              # 内存记忆
        formatter=formatter,                  # 消息格式化器
        max_iters=running_config.max_iters,   # 最大推理轮数
    )

    # ─────────────────────────────────────────────────────────
    # 步骤 7: 设置记忆管理器
    # ─────────────────────────────────────────────────────────
    self._setup_memory_manager(
        enable_memory_manager,
        memory_manager,
        namesake_strategy,
    )

    # ─────────────────────────────────────────────────────────
    # 步骤 8: 创建命令处理器
    # ─────────────────────────────────────────────────────────
    self.command_handler = CommandHandler(
        agent_name=self.name,
        memory=self.memory,
        memory_manager=self.memory_manager,
        enable_memory_manager=self._enable_memory_manager,
    )

    # ─────────────────────────────────────────────────────────
    # 步骤 9: 注册 Hooks
    # ─────────────────────────────────────────────────────────
    self._register_hooks()
```

---

## 4. `_create_toolkit` 方法 — 工具注册

### 完整实现

```python
def _create_toolkit(
    self,
    namesake_strategy: NamesakeStrategy = "skip",
) -> Toolkit:
    """创建并填充工具集"""
    toolkit = Toolkit()

    # 1. 从配置读取启用的工具
    enabled_tools = {}          # {tool_name: bool}
    async_execution_tools = {}  # {tool_name: bool}

    if hasattr(self._agent_config, "tools"):
        builtin_tools = self._agent_config.tools.builtin_tools
        enabled_tools = {name: tool.enabled for name, tool in builtin_tools.items()}
        async_execution_tools = {
            "execute_shell_command": builtin_tools.get("execute_shell_command").async_execution
        }

    # 2. 工具函数映射
    tool_functions = {
        "execute_shell_command": execute_shell_command,  # Shell 命令执行
        "read_file": read_file,                          # 读取文件
        "write_file": write_file,                        # 写入文件
        "edit_file": edit_file,                          # 编辑文件
        "grep_search": grep_search,                      # 正则搜索
        "glob_search": glob_search,                      # 文件模式匹配
        "browser_use": browser_use,                      # 浏览器自动化
        "desktop_screenshot": desktop_screenshot,        # 桌面截图
        "view_image": view_image,                        # 查看图片
        "view_video": view_video,                        # 查看视频
        "send_file_to_user": send_file_to_user,          # 发送文件给用户
        "get_current_time": get_current_time,            # 获取当前时间
        "set_user_timezone": set_user_timezone,          # 设置用户时区
        "get_token_usage": get_token_usage,              # 获取 Token 使用量
    }

    # 3. 检查模型是否支持多模态
    multimodal = get_active_model_supports_multimodal()

    # 4. 注册启用的工具
    for tool_name, tool_func in tool_functions.items():
        # 跳过禁用的工具
        if not enabled_tools.get(tool_name, True):
            continue

        # 跳过多模态工具（如果模型不支持）
        if tool_name in ("view_image", "view_video") and not multimodal:
            continue

        # 注册工具
        async_exec = async_execution_tools.get(tool_name, False)
        toolkit.register_tool_function(
            tool_func,
            namesake_strategy=namesake_strategy,
            async_execution=async_exec,
        )

    # 5. 自动注册后台任务管理工具（如果有异步工具）
    has_async_tools = any(
        async_execution_tools.get(name, False)
        for name in tool_functions
        if enabled_tools.get(name, True)
    )

    if has_async_tools:
        toolkit.register_tool_function(toolkit.view_task, ...)
        toolkit.register_tool_function(toolkit.wait_task, ...)
        toolkit.register_tool_function(toolkit.cancel_task, ...)

    return toolkit
```

### 内置工具列表

| 工具名 | 功能 | 异步执行 |
|--------|------|----------|
| `execute_shell_command` | 执行 Shell 命令 | 可配置 |
| `read_file` | 读取文件内容 | 否 |
| `write_file` | 写入文件 | 否 |
| `edit_file` | 编辑文件（字符串替换） | 否 |
| `grep_search` | 正则表达式搜索文件 | 否 |
| `glob_search` | 文件模式匹配 | 否 |
| `browser_use` | 浏览器自动化操作 | 否 |
| `desktop_screenshot` | 桌面截图 | 否 |
| `view_image` | 查看图片（多模态） | 否 |
| `view_video` | 查看视频（多模态） | 否 |
| `send_file_to_user` | 发送文件给用户 | 否 |
| `get_current_time` | 获取当前时间 | 否 |
| `set_user_timezone` | 设置用户时区 | 否 |
| `get_token_usage` | 获取 Token 使用统计 | 否 |

### Namesake 策略

| 策略 | 行为 |
|------|------|
| `override` | 新工具覆盖同名旧工具 |
| `skip` | 跳过同名工具，保留旧工具 |
| `raise` | 抛出异常 |
| `rename` | 自动重命名新工具 |

---

## 5. `_register_skills` 方法 — 技能注册

```python
def _register_skills(self, toolkit: Toolkit) -> None:
    """从工作目录加载并注册 Skills"""
    workspace_dir = self._workspace_dir or WORKING_DIR

    # 1. 初始化技能池
    ensure_skills_initialized(workspace_dir)

    # 2. 获取当前通道的有效技能列表
    request_context = getattr(self, "_request_context", {})
    channel_name = request_context.get("channel", "console")

    effective_skills = resolve_effective_skills(
        workspace_dir,
        channel_name,  # 不同通道可以有不同的技能配置
    )

    # 3. 注册每个技能
    working_skills_dir = get_workspace_skills_dir(Path(workspace_dir))

    for skill_name in effective_skills:
        skill_dir = working_skills_dir / skill_name
        if skill_dir.exists():
            try:
                toolkit.register_agent_skill(str(skill_dir))
                logger.debug("Registered skill: %s", skill_name)
            except Exception as e:
                logger.error("Failed to register skill '%s': %s", skill_name, e)
```

### Skill 加载流程

```
workspace/skills/
├── pdf/
│   ├── SKILL.md          # 技能描述和指令
│   ├── references/       # 参考文档
│   └── scripts/          # 可选脚本
├── docx/
└── news/

    ↓ resolve_effective_skills(workspace_dir, channel)

根据 channel 过滤有效技能
    ↓
    ↓ toolkit.register_agent_skill(skill_dir)

解析 SKILL.md → 生成工具 Schema → 注册到 Toolkit
```

---

## 6. `_build_sys_prompt` 方法 — 系统提示词构建

```python
def _build_sys_prompt(self) -> str:
    """构建系统提示词"""
    # 1. 获取 agent_id
    agent_id = self._request_context.get("agent_id") if self._request_context else None

    # 2. 检查是否启用心跳
    heartbeat_enabled = False
    if hasattr(self._agent_config, "heartbeat"):
        heartbeat_enabled = self._agent_config.heartbeat.enabled

    # 3. 从工作目录构建基础提示词
    sys_prompt = build_system_prompt_from_working_dir(
        working_dir=self._workspace_dir,
        agent_id=agent_id,
        heartbeat_enabled=heartbeat_enabled,
    )

    # 4. 注入多模态能力提示
    multimodal_hint = build_multimodal_hint()
    if multimodal_hint:
        sys_prompt = sys_prompt + "\n\n" + multimodal_hint

    # 5. 追加环境上下文
    if self._env_context is not None:
        sys_prompt = sys_prompt + "\n\n" + self._env_context

    return sys_prompt
```

### 系统提示词来源

```
~/.copaw/agents/{agent_id}/
├── AGENTS.md      # Agent 人设和能力描述
├── SOUL.md        # Agent 价值观和灵魂
├── PROFILE.md     # Agent 个人资料
├── HEARTBEAT.md   # 心跳提示（如果启用）
└── BOOTSTRAP.md   # 首次交互引导

    ↓ build_system_prompt_from_working_dir()

组合所有 MD 文件内容
    ↓
+ 多模态提示（如果模型支持）
    ↓
+ 环境上下文（如当前时间、用户信息等）
    ↓
完整系统提示词
```

---

## 7. `_setup_memory_manager` 方法 — 记忆管理器设置

```python
def _setup_memory_manager(
    self,
    enable_memory_manager: bool,
    memory_manager: BaseMemoryManager | None,
    namesake_strategy: NamesakeStrategy,
) -> None:
    """设置记忆管理器"""
    # 1. 检查环境变量覆盖
    env_enable_mm = os.getenv("ENABLE_MEMORY_MANAGER", "")
    if env_enable_mm.lower() == "false":
        enable_memory_manager = False

    self._enable_memory_manager = enable_memory_manager
    self.memory_manager = memory_manager

    # 2. 如果启用且有实例
    if self._enable_memory_manager and self.memory_manager is not None:
        # 替换默认 memory
        self.memory = self.memory_manager.get_in_memory_memory()

        # 设置模型的引用
        self.memory_manager.chat_model = self.model
        self.memory_manager.formatter = self.formatter

        # 注册 memory_search 工具
        self.toolkit.register_tool_function(
            create_memory_search_tool(self.memory_manager),
            namesake_strategy=namesake_strategy,
        )
```

### 记忆管理器的作用

```
用户对话
    ↓
InMemoryMemory (self.memory)
├── content: [[Msg, marks], ...]  # 短期记忆（对话历史）
└── _long_term_memory: str        # 长期记忆（总结）

    ↓ 当对话过长时

MemoryCompactionHook 触发
    ↓
ReMeLightMemoryManager.summary_memory()
├── 生成对话总结
├── 存储到向量数据库
└── 压缩短期记忆

    ↓ 用户查询时

memory_search 工具
├── 向量检索相关记忆
└── 注入到 _long_term_memory
```

---

## 8. `_register_hooks` 方法 — 钩子注册

```python
def _register_hooks(self) -> None:
    """注册 Agent 钩子"""
    working_dir = self._workspace_dir if self._workspace_dir else WORKING_DIR

    # 1. Bootstrap Hook - 首次交互检查
    bootstrap_hook = BootstrapHook(
        working_dir=working_dir,
        language=self._language,
    )
    self.register_instance_hook(
        hook_type="pre_reasoning",
        hook_name="bootstrap_hook",
        hook=bootstrap_hook.__call__,
    )

    # 2. Memory Compaction Hook - 自动压缩记忆
    if self._enable_memory_manager and self.memory_manager is not None:
        memory_compact_hook = MemoryCompactionHook(
            memory_manager=self.memory_manager,
        )
        self.register_instance_hook(
            hook_type="pre_reasoning",
            hook_name="memory_compact_hook",
            hook=memory_compact_hook.__call__,
        )
```

### Hook 执行时机

```
每次推理循环（pre_reasoning）
    │
    ├─ BootstrapHook
    │   │
    │   ├─ 检查是否首次交互
    │   ├─ 读取 BOOTSTRAP.md
    │   └─ 注入引导提示
    │
    └─ MemoryCompactionHook
        │
        ├─ 检查记忆长度
        ├─ 如果超过阈值，触发压缩
        └─ 生成总结，存入长期记忆
```

---

## 9. MCP 客户端注册与恢复

### `register_mcp_clients` 方法

```python
async def register_mcp_clients(
    self,
    namesake_strategy: NamesakeStrategy = "skip",
) -> None:
    """注册 MCP 客户端到工具集"""
    for i, client in enumerate(self._mcp_clients):
        client_name = getattr(client, "name", repr(client))
        try:
            await self.toolkit.register_mcp_client(
                client,
                namesake_strategy=namesake_strategy,
            )
        except (ClosedResourceError, asyncio.CancelledError) as error:
            # 尝试恢复
            recovered_client = await self._recover_mcp_client(client)
            if recovered_client is not None:
                self._mcp_clients[i] = recovered_client
                await self.toolkit.register_mcp_client(
                    recovered_client,
                    namesake_strategy=namesake_strategy,
                )
        except Exception as e:
            logger.warning("Failed to register MCP client '%s': %s", client_name, e)
```

### MCP 客户端恢复流程

```python
async def _recover_mcp_client(self, client: Any) -> Any | None:
    """恢复断开的 MCP 客户端"""
    # 1. 尝试重连
    if await self._reconnect_mcp_client(client):
        return client

    # 2. 重建客户端
    rebuilt_client = self._rebuild_mcp_client(client)
    if rebuilt_client is None:
        return None

    # 3. 重连新客户端
    if await self._reconnect_mcp_client(rebuilt_client):
        return self._reuse_shared_client_reference(
            original_client=client,
            rebuilt_client=rebuilt_client,
        )

    return None

def _rebuild_mcp_client(self, client: Any) -> Any | None:
    """从存储的配置重建 MCP 客户端"""
    rebuild_info = getattr(client, "_copaw_rebuild_info", None)
    if not rebuild_info:
        return None

    transport = rebuild_info.get("transport")

    if transport == "stdio":
        return StdIOStatefulClient(
            name=rebuild_info.get("name"),
            command=rebuild_info.get("command"),
            args=rebuild_info.get("args", []),
            env=rebuild_info.get("env", {}),
            cwd=rebuild_info.get("cwd"),
        )

    # HTTP transport
    return HttpStatefulClient(
        name=rebuild_info.get("name"),
        transport=transport,
        url=rebuild_info.get("url"),
        headers=rebuild_info.get("headers"),
    )
```

---

## 10. 媒体块处理

### 问题背景

某些模型不支持多模态（图片、音频、视频），直接发送会导致 API 错误。

### 解决方案：主动过滤 + 被动重试

```python
async def _reasoning(self, tool_choice=None) -> Msg:
    """重写推理方法，添加媒体过滤"""

    # ─────────────────────────────────────────────
    # 主动过滤层：调用前检查
    # ─────────────────────────────────────────────
    if not get_active_model_supports_multimodal():
        n = self._proactive_strip_media_blocks()
        if n > 0:
            logger.warning("Proactively stripped %d media block(s)", n)

    # ─────────────────────────────────────────────
    # 被动重试层：调用失败后处理
    # ─────────────────────────────────────────────
    try:
        return await super()._reasoning(tool_choice=tool_choice)
    except Exception as e:
        # 检查是否是媒体相关错误
        if not self._is_bad_request_or_media_error(e):
            raise

        # 剥离媒体块并重试
        n_stripped = self._strip_media_blocks_from_memory()
        if n_stripped == 0:
            raise

        logger.warning("Stripped %d media block(s), retrying", n_stripped)
        return await super()._reasoning(tool_choice=tool_choice)
```

### 媒体块剥离实现

```python
_MEDIA_BLOCK_TYPES = {"image", "audio", "video"}
_MEDIA_PLACEHOLDER = "[Media content removed - model does not support this media type]"

def _strip_media_blocks_from_memory(self) -> int:
    """从记忆中剥离媒体块"""
    media_types = self._MEDIA_BLOCK_TYPES
    total_stripped = 0

    for msg, _marks in self.memory.content:
        if not isinstance(msg.content, list):
            continue

        new_content = []
        for block in msg.content:
            # 剥离媒体块
            if isinstance(block, dict) and block.get("type") in media_types:
                total_stripped += 1
                continue

            # 处理嵌套在 tool_result 中的媒体块
            if isinstance(block, dict) and block.get("type") == "tool_result":
                block["output"] = [
                    item for item in block["output"]
                    if not (isinstance(item, dict) and item.get("type") in media_types)
                ]

            new_content.append(block)

        # 如果剥离后内容为空，添加占位符
        if not new_content and total_stripped > 0:
            new_content.append({"type": "text", "text": self._MEDIA_PLACEHOLDER})

        msg.content = new_content

    return total_stripped
```

---

## 11. `reply` 方法 — 对话主入口

```python
async def reply(
    self,
    msg: Msg | list[Msg] | None = None,
    structured_model: Type[BaseModel] | None = None,
) -> Msg:
    """处理用户消息并返回响应"""

    # ─────────────────────────────────────────────────────────
    # 1. 设置上下文变量（供工具函数访问）
    # ─────────────────────────────────────────────────────────
    from ..config.context import (
        set_current_workspace_dir,
        set_current_recent_max_bytes,
    )

    set_current_workspace_dir(self._workspace_dir)
    set_current_recent_max_bytes(
        self._agent_config.running.tool_result_compact.recent_max_bytes,
    )

    # ─────────────────────────────────────────────────────────
    # 2. 处理文件和媒体块
    # ─────────────────────────────────────────────────────────
    if msg is not None:
        await process_file_and_media_blocks_in_message(msg)

    # ─────────────────────────────────────────────────────────
    # 3. 检查是否是系统命令
    # ─────────────────────────────────────────────────────────
    last_msg = msg[-1] if isinstance(msg, list) else msg
    query = last_msg.get_text_content() if isinstance(last_msg, Msg) else None

    if self.command_handler.is_command(query):
        logger.info(f"Received command: {query}")
        msg = await self.command_handler.handle_command(query)
        await self.print(msg)
        return msg

    # ─────────────────────────────────────────────────────────
    # 4. 强制记忆搜索（如果配置）
    # ─────────────────────────────────────────────────────────
    if hasattr(self.memory, "_long_term_memory"):
        ms = self._agent_config.running.memory_summary
        if ms.force_memory_search and self.memory_manager and query:
            result = await self.memory_manager.memory_search(
                query=query[:100],
                max_results=ms.force_max_results,
                min_score=ms.force_min_score,
            )
            self.memory._long_term_memory = "\n".join(
                block["text"] for block in result.content
            )

    # ─────────────────────────────────────────────────────────
    # 5. 调用父类 reply（进入推理-行动循环）
    # ─────────────────────────────────────────────────────────
    request_context = getattr(self, "_request_context", {}) or {}
    channel_name = request_context.get("channel", "console")
    workspace_dir = Path(self._workspace_dir or WORKING_DIR)

    with apply_skill_config_env_overrides(workspace_dir, channel_name):
        return await super().reply(
            msg=msg,
            structured_model=structured_model,
        )
```

### 系统命令处理

```python
# command_handler.py 处理的命令

/compact     # 压缩记忆
/new         # 开始新对话（总结并清空）
/clear       # 清空记忆
/history     # 查看历史
/message     # 发送消息
/dump_history  # 导出历史
/load_history  # 导入历史
```

---

## 12. `interrupt` 方法 — 中断执行

```python
async def interrupt(self, msg: Msg | list[Msg] | None = None) -> None:
    """中断当前的回复过程"""
    if self._reply_task and not self._reply_task.done():
        task = self._reply_task
        task.cancel(msg)  # 发送取消信号

        try:
            await task  # 等待任务清理
        except asyncio.CancelledError:
            if not task.cancelled():
                raise
        except Exception:
            logger.warning("Exception during interrupt cleanup", exc_info=True)
```

### 中断使用场景

```
用户点击"停止"按钮
    │
    ▼ runner 收到中断请求
    │
    ▼ await agent.interrupt()
    │
    ├─ task.cancel()
    │
    ├─ asyncio.CancelledError 在 reply() 中抛出
    │
    └─ AgentBase.__call__ 捕获 → handle_interrupt()
```

---

## 13. `_summarizing` 方法 — 达到最大轮数时的总结

当达到 `max_iters` 但没有产生最终回复时，AgentScope 会调用 `_summarizing` 生成一个总结性回复。

```python
_ROUND_END_NOTICE = (
    "\n\n---\n"
    "本轮调用已达最大次数，回复已终止，请继续输入。\n"
    "Maximum iterations reached for this round. "
    "Please send a new message to continue."
)

async def _summarizing(self) -> Msg:
    """重写总结方法"""
    # 主动媒体过滤
    if not get_active_model_supports_multimodal():
        self._proactive_strip_media_blocks()

    self._in_summarizing = True
    try:
        msg = await super()._summarizing()
    except Exception as e:
        # 被动重试...
        msg = await super()._summarizing()
    finally:
        self._in_summarizing = False

    # 剥离 tool_use 块（有些模型会在无工具时也生成）
    return self._strip_tool_use_from_msg(msg)
```

---

## 14. 实例属性总结

| 属性 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `name` | str | 固定 `"Friday"` | Agent 名称 |
| `model` | ModelBase | `create_model_and_formatter()` | LLM 模型实例 |
| `sys_prompt` | str | `_build_sys_prompt()` | 系统提示词 |
| `memory` | InMemoryMemory | 父类初始化 | 对话历史 |
| `toolkit` | Toolkit | `_create_toolkit()` | 工具集 |
| `toolkit.tools` | dict | 注册的工具 | 工具名 → 工具 Schema |
| `toolkit.skills` | dict | `_register_skills()` | 技能名 → 技能信息 |
| `memory_manager` | BaseMemoryManager | 传入参数 | 长期记忆管理器 |
| `command_handler` | CommandHandler | 初始化创建 | 系统命令处理器 |
| `max_iters` | int | agent_config.running | 最大推理轮数 |

---

## 15. 完整执行流程

```
agent = CoPawAgent(...)
    │
    │  __init__
    ├─ 保存配置
    ├─ 创建 Toolkit
    ├─ 注册内置工具（14 个）
    ├─ 注册 Skills（动态加载）
    ├─ 构建系统提示词
    ├─ 创建模型
    ├─ 初始化 ReActAgent
    ├─ 设置记忆管理器
    ├─ 创建命令处理器
    └─ 注册 Hooks
    │
    ▼
await agent(msgs)
    │
    │  __call__ (AgentBase)
    ├─ self._reply_task = current_task()
    │
    ▼ await self.reply(msgs)
    │
    │  reply (CoPawAgent)
    ├─ 设置上下文变量
    ├─ 处理文件/媒体块
    ├─ 检查系统命令
    ├─ 强制记忆搜索（可选）
    │
    ▼ await super().reply(msgs)  # ReActAgent.reply
    │
    │  ReActAgent 主循环
    ├─ await self.memory.add(msg)
    ├─ for _ in range(max_iters):
    │   │
    │   │  pre_reasoning hooks
    │   ├─ BootstrapHook（首次交互）
    │   └─ MemoryCompactionHook（记忆压缩）
    │   │
    │   ▼ await self._reasoning()
    │   │
    │   │  _reasoning (ToolGuardMixin → ReActAgent)
    │   ├─ 检查 Tool Guard 审批
    │   ├─ 构建 prompt
    │   ├─ 调用 model(prompt)
    │   ├─ 流式 yield
    │   └─ await self.print(msg)
    │   │
    │   ▼ 提取 tool_calls
    │   │
    │   ▼ await self._acting(tool_call)
    │   │
    │   │  _acting (ToolGuardMixin → ReActAgent)
    │   ├─ Tool Guard 安全检查
    │   ├─ 执行工具
    │   └─ await self.print(tool_result)
    │   │
    │   └─ 检查退出条件
    │
    └─ return final_msg
```

---

## 16. 设计模式总结

### 继承与 Mixin

```python
# Mixin 模式：在不修改继承链的情况下扩展功能
class ToolGuardMixin:
    async def _acting(self, tool_call):
        # 前置检查
        if self._needs_approval(tool_call):
            return await self._request_approval(tool_call)
        # 调用原始实现
        return await super()._acting(tool_call)
```

### 钩子模式

```python
# 在关键生命周期点插入自定义逻辑
self.register_instance_hook(
    hook_type="pre_reasoning",
    hook_name="bootstrap_hook",
    hook=bootstrap_hook.__call__,
)
```

### 工厂模式

```python
# 延迟创建模型实例
model, formatter = create_model_and_formatter(agent_id=agent_config.id)
```

### 策略模式

```python
# 同名工具处理策略
namesake_strategy: Literal["override", "skip", "raise", "rename"]
```

---

## 17. 关键设计决策

| 决策 | 原因 |
|------|------|
| Agent 名称固定为 `"Friday"` | 统一的用户体验 |
| 每次请求创建新 Agent 实例 | 状态隔离、配置热更新 |
| 使用 Mixin 实现 Tool Guard | 不污染继承链，可插拔 |
| 主动 + 被动媒体过滤 | 兼容不支持多模态的模型 |
| Hooks 在 `pre_reasoning` 执行 | 在每次 LLM 调用前处理 |
| Skills 按通道过滤 | 不同通道可启用不同技能 |