# -*- coding: utf-8 -*-
"""Self-Learning Agent - CoPawAgent with automatic learning capabilities.

This module extends CoPawAgent with self-learning features inspired by Hermes Agent:
- Memory Nudge: Periodic review and consolidation of important information
- Pattern Extraction: Identify reusable problem-solving patterns from conversations
- Skill Auto-Creation: Automatically create skills from extracted patterns

The learning runs in background after response delivery, never blocking user interaction.
"""

import asyncio
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from agentscope.message import Msg

from .react_agent import CoPawAgent

if TYPE_CHECKING:
    from ..config.config import AgentProfileConfig
    from ..agents.memory import BaseMemoryManager

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

class LearningConfig:
    """Configuration for self-learning behavior.

    Attributes:
        memory_nudge_interval: Number of user turns before memory review (default: 10)
        skill_nudge_interval: Number of tool iterations before skill review (default: 5)
        enable_pattern_extraction: Whether to extract patterns from conversations
        enable_skill_creation: Whether to auto-create skills from patterns
        background_learning: Whether learning runs in background (non-blocking)
        auxiliary_model: Model used for pattern extraction (default: use main model)
    """

    def __init__(
        self,
        memory_nudge_interval: int = 10,
        skill_nudge_interval: int = 5,
        enable_pattern_extraction: bool = True,
        enable_skill_creation: bool = True,
        background_learning: bool = True,
        auxiliary_model: Optional[str] = None,
    ):
        self.memory_nudge_interval = memory_nudge_interval
        self.skill_nudge_interval = skill_nudge_interval
        self.enable_pattern_extraction = enable_pattern_extraction
        self.enable_skill_creation = enable_skill_creation
        self.background_learning = background_learning
        self.auxiliary_model = auxiliary_model


# ============================================================================
# Pattern and Skill Models
# ============================================================================

class Pattern:
    """A reusable pattern extracted from conversation.

    Patterns represent problem-solving approaches that can be generalized
    into skills for future use.
    """

    def __init__(
        self,
        name: str,
        description: str,
        instructions: str,
        use_cases: str = "",
        example: str = "",
        source_session: str = "",
        created_at: datetime = None,
        confidence: float = 0.5,
    ):
        self.name = name
        self.description = description
        self.instructions = instructions
        self.use_cases = use_cases
        self.example = example
        self.source_session = source_session
        self.created_at = created_at or datetime.now()
        self.confidence = confidence  # 0.0-1.0, higher = more likely useful

    def to_skill_md(self) -> str:
        """Generate SKILL.md content."""
        return f"""---
name: {self.name}
description: "{self.description}"
version: 1.0.0
created_at: {self.created_at.isoformat()}
created_from: conversation_pattern
confidence: {self.confidence}
---

# {self.name}

{self.instructions}

## 使用场景

{self.use_cases}

## 示例

{self.example}

## 来源

此 Skill 自动从对话中提取创建。
来源 Session: {self.source_session}
"""


class MemoryInsight:
    """An insight extracted for long-term memory."""

    def __init__(
        self,
        content: str,
        type: str = "general",  # general, preference, workflow, knowledge
        importance: float = 0.5,
        metadata: Dict[str, Any] = None,
    ):
        self.content = content
        self.type = type
        self.importance = importance
        self.metadata = metadata or {}


# ============================================================================
# Pattern Extractor
# ============================================================================

class PatternExtractor:
    """Extract reusable patterns from conversations.

    Uses LLM to analyze conversations and identify:
    - Repeated problem-solving approaches
    - Novel tool combinations that work well
    - Workflows worth remembering
    - User preferences and needs
    """

    def __init__(
        self,
        model: Optional[str] = None,
        min_confidence: float = 0.6,
    ):
        self.model = model
        self.min_confidence = min_confidence

    async def extract(
        self,
        conversation: List[Msg],
        response: Msg,
        existing_skills: List[str],
        tool_calls: List[Dict] = None,
    ) -> List[Pattern]:
        """Extract patterns from a completed conversation turn.

        Args:
            conversation: Full conversation history
            response: Agent's final response
            existing_skills: List of existing skill names (to avoid duplicates)
            tool_calls: List of tool calls made during this turn

        Returns:
            List of extracted patterns (may be empty)
        """
        patterns = []

        # 1. Tool combination patterns
        if tool_calls and len(tool_calls) >= 2:
            pattern = self._extract_tool_combination_pattern(
                tool_calls, conversation, response
            )
            if pattern and pattern.confidence >= self.min_confidence:
                patterns.append(pattern)

        # 2. Workflow patterns (multi-step solutions)
        workflow_pattern = self._extract_workflow_pattern(conversation, response)
        if workflow_pattern and workflow_pattern.confidence >= self.min_confidence:
            patterns.append(workflow_pattern)

        # 3. Filter out duplicates with existing skills
        patterns = [p for p in patterns if p.name not in existing_skills]

        return patterns

    def _extract_tool_combination_pattern(
        self,
        tool_calls: List[Dict],
        conversation: List[Msg],
        response: Msg,
    ) -> Optional[Pattern]:
        """Extract pattern from tool combination."""

        # Get unique tools used
        tools_used = set()
        for tc in tool_calls:
            if isinstance(tc, dict):
                tool_name = tc.get("name", tc.get("function", {}).get("name", ""))
                if tool_name:
                    tools_used.add(tool_name)

        if len(tools_used) < 2:
            return None

        # Create pattern name from tools
        tool_str = "_".join(sorted(tools_used)[:3])
        name = f"tool_combo_{tool_str}"

        # Generate description and instructions
        description = f"Efficient combination of {', '.join(tools_used)} tools"
        instructions = f"""使用以下工具组合来高效完成任务：

1. {self._generate_tool_instructions(tools_used)}

这个组合在解决类似问题时表现出良好的效果。
"""

        # Extract example from conversation
        user_msg = ""
        for msg in reversed(conversation):
            if msg.role == "user":
                user_msg = msg.content if isinstance(msg.content, str) else ""
                break

        example = f"用户问题: {user_msg[:100]}...\n\n解决方案: 使用 {', '.join(tools_used)} 工具组合"

        return Pattern(
            name=name,
            description=description,
            instructions=instructions,
            use_cases=f"适用于需要 {', '.join(tools_used)} 的任务",
            example=example,
            confidence=0.7,  # Tool combos are usually useful
        )

    def _extract_workflow_pattern(
        self,
        conversation: List[Msg],
        response: Msg,
    ) -> Optional[Pattern]:
        """Extract workflow pattern from multi-step solution."""

        # Analyze response for structured workflow
        response_text = response.content if isinstance(response.content, str) else ""

        # Check for numbered steps, bullet points, etc.
        has_steps = any([
            "步骤" in response_text or "step" in response_text.lower(),
            "1." in response_text or "1)" in response_text,
            "首先" in response_text or "然后" in response_text,
        ])

        if not has_steps:
            return None

        # Extract workflow name from first user message
        user_msg = ""
        for msg in reversed(conversation):
            if msg.role == "user":
                user_msg = msg.content if isinstance(msg.content, str) else ""
                break

        # Create short name from user message
        name_words = user_msg.split()[:3]
        name = "workflow_" + "_".join(w.lower() for w in name_words if w)
        name = name[:50]  # Limit length

        return Pattern(
            name=name,
            description=f"Workflow for: {user_msg[:80]}",
            instructions=response_text[:500],
            use_cases="适用于类似的多步骤任务",
            example=user_msg[:200],
            confidence=0.6,
        )

    def _generate_tool_instructions(self, tools: set) -> str:
        """Generate instructions for tool usage."""
        tool_descriptions = {
            "read_file": "读取文件内容，了解当前状态",
            "write_file": "写入新文件或创建内容",
            "edit_file": "修改现有文件，进行精确更新",
            "execute_shell_command": "执行命令行操作",
            "browser_use": "浏览器自动化，获取网页内容",
            "grep_search": "搜索文件内容，定位关键信息",
            "glob_search": "搜索文件路径，找到相关文件",
        }

        lines = []
        for tool in sorted(tools):
            desc = tool_descriptions.get(tool, f"使用 {tool} 工具")
            lines.append(f"- {desc}")

        return "\n".join(lines)

    async def extract_insights(
        self,
        conversation: List[Msg],
        response: Msg,
    ) -> List[MemoryInsight]:
        """Extract insights for long-term memory."""

        insights = []

        # 1. User preference insights
        user_msg = ""
        for msg in reversed(conversation):
            if msg.role == "user":
                user_msg = msg.content if isinstance(msg.content, str) else ""
                break

        # Check for preference indicators
        preference_keywords = ["我喜欢", "我希望", "我需要", "prefer", "want", "need"]
        for kw in preference_keywords:
            if kw in user_msg.lower():
                insights.append(MemoryInsight(
                    content=f"User preference detected: {user_msg[:200]}",
                    type="preference",
                    importance=0.8,
                ))
                break

        # 2. Knowledge insights (successful solutions)
        if response.content and len(response.content) > 100:
            insights.append(MemoryInsight(
                content=f"Solution provided: {response.content[:300]}",
                type="knowledge",
                importance=0.5,
            ))

        return insights


# ============================================================================
# Skill Creator
# ============================================================================

class SkillCreator:
    """Create and manage skills from extracted patterns."""

    def __init__(
        self,
        skills_dir: Path,
        max_skills: int = 50,
    ):
        self.skills_dir = skills_dir
        self.max_skills = max_skills
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    async def create_skill(self, pattern: Pattern) -> Path:
        """Create a new skill from pattern.

        Args:
            pattern: The pattern to create skill from

        Returns:
            Path to the created skill directory
        """
        skill_dir = self.skills_dir / pattern.name

        # Check if already exists
        if skill_dir.exists():
            logger.info(f"Skill '{pattern.name}' already exists, updating")
            return await self.update_skill(skill_dir, pattern)

        # Create skill directory
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write SKILL.md
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text(pattern.to_skill_md())

        logger.info(f"Created new skill: {pattern.name} at {skill_dir}")

        return skill_dir

    async def update_skill(self, skill_dir: Path, pattern: Pattern) -> Path:
        """Update existing skill with new pattern information."""

        skill_md_path = skill_dir / "SKILL.md"

        if skill_md_path.exists():
            # Read existing content
            existing = skill_md_path.read_text()

            # Append new example/use case
            updated = existing + f"""

---

## 新增示例 (Updated {datetime.now().isoformat()})

{pattern.example}
"""
            skill_md_path.write_text(updated)
        else:
            skill_md_path.write_text(pattern.to_skill_md())

        logger.info(f"Updated skill: {pattern.name}")

        return skill_dir

    def get_existing_skills(self) -> List[str]:
        """Get list of existing skill names."""
        skills = []
        for item in self.skills_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                skills.append(item.name)
        return skills

    def should_create_skill(self, pattern: Pattern) -> bool:
        """Check if a pattern should be created as skill."""

        # Confidence threshold
        if pattern.confidence < 0.5:
            return False

        # Not duplicate
        if pattern.name in self.get_existing_skills():
            return False

        # Not too many skills
        if len(self.get_existing_skills()) >= self.max_skills:
            return False

        return True


# ============================================================================
# Self-Learning Agent
# ============================================================================

class SelfLearningAgent(CoPawAgent):
    """CoPawAgent with self-learning capabilities.

    Extends CoPawAgent with:
    - Memory Nudge: Periodic review and consolidation
    - Pattern Extraction: Identify reusable patterns
    - Skill Auto-Creation: Create skills from patterns

    All learning happens in background after response is delivered,
    never blocking user interaction.

    Usage:
        agent = SelfLearningAgent(
            agent_config=config,
            learning_config=LearningConfig(
                memory_nudge_interval=10,
                skill_nudge_interval=5,
            ),
        )

        response = await agent(msgs)  # Normal execution
        # Learning happens in background automatically
    """

    def __init__(
        self,
        agent_config: "AgentProfileConfig",
        learning_config: Optional[LearningConfig] = None,
        **kwargs,
    ):
        """Initialize self-learning agent.

        Args:
            agent_config: Agent configuration (same as CoPawAgent)
            learning_config: Learning behavior configuration
            **kwargs: Additional arguments passed to CoPawAgent
        """
        super().__init__(agent_config, **kwargs)

        # Learning configuration
        self._learning_config = learning_config or LearningConfig()

        # Learning state counters
        self._turns_since_memory = 0
        self._iters_since_skill = 0
        self._user_turn_count = 0

        # Learning components
        workspace_dir = Path(agent_config.workspace_dir or kwargs.get("workspace_dir", ""))
        self._skill_creator = SkillCreator(
            skills_dir=workspace_dir / "skills",
        )
        self._pattern_extractor = PatternExtractor(
            model=self._learning_config.auxiliary_model,
        )

        # Background task tracking
        self._background_tasks: List[asyncio.Task] = []
        self._learning_lock = threading.Lock()

        # Tool calls from current turn (for pattern extraction)
        self._current_tool_calls: List[Dict] = []

        logger.info(
            f"SelfLearningAgent initialized: "
            f"memory_nudge={self._learning_config.memory_nudge_interval}, "
            f"skill_nudge={self._learning_config.skill_nudge_interval}"
        )

    async def reply(self, msgs: List[Msg]) -> Msg:
        """Execute reply with learning hook.

        1. Execute normal reply (from CoPawAgent)
        2. Update learning counters
        3. Spawn background learning if thresholds reached
        """

        # Reset tool calls tracking
        self._current_tool_calls = []

        # 1. Normal execution
        response = await super().reply(msgs)

        # 2. Update counters
        self._user_turn_count += 1
        self._turns_since_memory += 1
        # Tool iterations tracked separately

        # 3. Check learning triggers
        should_review_memory = (
            self._learning_config.memory_nudge_interval > 0
            and self._turns_since_memory >= self._learning_config.memory_nudge_interval
        )

        should_review_skills = (
            self._learning_config.skill_nudge_interval > 0
            and self._iters_since_skill >= self._learning_config.skill_nudge_interval
        )

        # 4. Background learning (non-blocking)
        if should_review_memory or should_review_skills:
            if self._learning_config.background_learning:
                self._spawn_background_learning(
                    msgs_snapshot=list(msgs),
                    response_snapshot=response,
                    review_memory=should_review_memory,
                    review_skills=should_review_skills,
                )
            else:
                # Synchronous learning (for testing)
                await self._do_learning(
                    msgs, response, should_review_memory, should_review_skills
                )

            # Reset counters after trigger
            if should_review_memory:
                self._turns_since_memory = 0
            if should_review_skills:
                self._iters_since_skill = 0

        return response

    def _spawn_background_learning(
        self,
        msgs_snapshot: List[Msg],
        response_snapshot: Msg,
        review_memory: bool,
        review_skills: bool,
    ):
        """Spawn background learning task.

        Learning runs asynchronously without blocking the response.
        """

        async def learning_task():
            try:
                await self._do_learning(
                    msgs_snapshot, response_snapshot, review_memory, review_skills
                )
            except Exception as e:
                logger.warning(f"Background learning failed: {e}")

        task = asyncio.create_task(learning_task())
        self._background_tasks.append(task)

        # Cleanup callback
        def cleanup(t):
            with self._learning_lock:
                if t in self._background_tasks:
                    self._background_tasks.remove(t)

        task.add_done_callback(cleanup)

        logger.debug(
            f"Spawned background learning: memory={review_memory}, skills={review_skills}"
        )

    async def _do_learning(
        self,
        msgs: List[Msg],
        response: Msg,
        review_memory: bool,
        review_skills: bool,
    ):
        """Execute learning logic.

        This runs in background and should not raise exceptions.
        """

        # 1. Memory review
        if review_memory:
            await self._review_memory(msgs, response)

        # 2. Pattern extraction and skill creation
        if review_skills and self._learning_config.enable_pattern_extraction:
            patterns = await self._extract_patterns(msgs, response)

            if self._learning_config.enable_skill_creation:
                for pattern in patterns:
                    if self._skill_creator.should_create_skill(pattern):
                        await self._skill_creator.create_skill(pattern)
                        # Reload skills
                        self._register_skills()

        # 3. Sync to memory manager
        if self.memory_manager:
            await self._sync_to_memory(msgs, response)

    async def _review_memory(self, msgs: List[Msg], response: Msg):
        """Review conversation and extract memory insights."""

        insights = await self._pattern_extractor.extract_insights(msgs, response)

        if insights and self.memory_manager:
            for insight in insights:
                try:
                    await self.memory_manager.add_memory(
                        content=insight.content,
                        metadata={
                            "type": insight.type,
                            "importance": insight.importance,
                            "timestamp": datetime.now().isoformat(),
                            "session_id": self._request_context.get("session_id", ""),
                            **insight.metadata
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to add memory insight: {e}")

        logger.info(f"Memory review completed: {len(insights)} insights extracted")

    async def _extract_patterns(self, msgs: List[Msg], response: Msg) -> List[Pattern]:
        """Extract patterns from conversation."""

        existing_skills = self._skill_creator.get_existing_skills()

        patterns = await self._pattern_extractor.extract(
            conversation=msgs,
            response=response,
            existing_skills=existing_skills,
            tool_calls=self._current_tool_calls,
        )

        logger.info(f"Pattern extraction: {len(patterns)} patterns found")

        return patterns

    async def _sync_to_memory(self, msgs: List[Msg], response: Msg):
        """Sync conversation turn to memory."""

        user_msg = msgs[-1] if msgs and msgs[-1].role == "user" else None

        if user_msg and self.memory_manager:
            try:
                content = user_msg.content if isinstance(user_msg.content, str) else str(user_msg.content)

                await self.memory_manager.add_memory(
                    content=f"User: {content[:200]}\n\nAssistant: {response.content[:200] if response.content else ''}",
                    metadata={
                        "type": "conversation",
                        "timestamp": datetime.now().isoformat(),
                        "session_id": self._request_context.get("session_id", ""),
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to sync to memory: {e}")

    # Override to track tool calls
    def _acting(self, *args, **kwargs):
        """Track tool calls during acting phase."""

        # Call parent implementation
        result = super()._acting(*args, **kwargs)

        # Track iterations
        self._iters_since_skill += 1

        return result

    async def stop(self):
        """Stop agent and cleanup background tasks."""

        # Wait for background tasks to complete
        if self._background_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._background_tasks, return_exceptions=True),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("Some background learning tasks did not complete")

        await super().stop()

    def get_learning_stats(self) -> Dict[str, Any]:
        """Get learning statistics."""
        return {
            "user_turn_count": self._user_turn_count,
            "turns_since_memory": self._turns_since_memory,
            "iters_since_skill": self._iters_since_skill,
            "background_tasks": len(self._background_tasks),
            "existing_skills": len(self._skill_creator.get_existing_skills()),
            "learning_config": {
                "memory_nudge_interval": self._learning_config.memory_nudge_interval,
                "skill_nudge_interval": self._learning_config.skill_nudge_interval,
                "enable_pattern_extraction": self._learning_config.enable_pattern_extraction,
                "enable_skill_creation": self._learning_config.enable_skill_creation,
            }
        }


# ============================================================================
# Factory function
# ============================================================================

def create_learning_agent(
    agent_config: "AgentProfileConfig",
    learning_config: Optional[LearningConfig] = None,
    **kwargs,
) -> SelfLearningAgent:
    """Factory function to create self-learning agent.

    Args:
        agent_config: Agent configuration
        learning_config: Learning configuration (optional)
        **kwargs: Additional arguments

    Returns:
        SelfLearningAgent instance
    """
    return SelfLearningAgent(
        agent_config=agent_config,
        learning_config=learning_config,
        **kwargs,
    )