# -*- coding: utf-8 -*-
"""Tests for SelfLearningAgent and related components."""

# pylint: disable=redefined-outer-name,protected-access
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Msg

from copaw.agents.learning_agent import (
    LearningConfig,
    Pattern,
    PatternExtractor,
    SkillCreator,
    MemoryInsight,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_skills_dir():
    """Create a temporary skills directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def learning_config():
    """Default learning configuration."""
    return LearningConfig(
        memory_nudge_interval=10,
        skill_nudge_interval=5,
        enable_pattern_extraction=True,
        enable_skill_creation=True,
        background_learning=True,
    )


@pytest.fixture
def pattern_extractor():
    """Pattern extractor instance."""
    return PatternExtractor(min_confidence=0.5)


@pytest.fixture
def skill_creator(temp_skills_dir):
    """Skill creator instance."""
    return SkillCreator(skills_dir=temp_skills_dir, max_skills=50)


@pytest.fixture
def sample_msgs():
    """Sample conversation messages."""
    return [
        Msg(name="user", content="请帮我分析一下项目结构", role="user"),
        Msg(name="assistant", content="好的，我来帮你分析。首先需要：\n1. 读取项目文件\n2. 搜索关键内容\n3. 整理分析结果", role="assistant"),
    ]


# ---------------------------------------------------------------------------
# LearningConfig Tests
# ---------------------------------------------------------------------------


class TestLearningConfig:
    """Tests for LearningConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = LearningConfig()
        assert config.memory_nudge_interval == 10
        assert config.skill_nudge_interval == 5
        assert config.enable_pattern_extraction is True
        assert config.enable_skill_creation is True
        assert config.background_learning is True
        assert config.auxiliary_model is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = LearningConfig(
            memory_nudge_interval=20,
            skill_nudge_interval=10,
            enable_pattern_extraction=False,
            auxiliary_model="haiku",
        )
        assert config.memory_nudge_interval == 20
        assert config.skill_nudge_interval == 10
        assert config.enable_pattern_extraction is False
        assert config.auxiliary_model == "haiku"


# ---------------------------------------------------------------------------
# Pattern Tests
# ---------------------------------------------------------------------------


class TestPattern:
    """Tests for Pattern class."""

    def test_pattern_creation(self):
        """Test creating a pattern."""
        pattern = Pattern(
            name="test_pattern",
            description="A test pattern",
            instructions="Do X then Y",
            use_cases="For X and Y tasks",
            example="Example usage",
            confidence=0.7,
        )
        assert pattern.name == "test_pattern"
        assert pattern.description == "A test pattern"
        assert pattern.confidence == 0.7

    def test_to_skill_md(self):
        """Test SKILL.md generation."""
        pattern = Pattern(
            name="test_skill",
            description="Test skill description",
            instructions="Test instructions",
            use_cases="Test use cases",
            example="Test example",
            source_session="session_123",
            confidence=0.8,
        )
        skill_md = pattern.to_skill_md()
        assert "name: test_skill" in skill_md
        assert "description: \"Test skill description\"" in skill_md
        assert "Test instructions" in skill_md
        assert "confidence: 0.8" in skill_md


# ---------------------------------------------------------------------------
# PatternExtractor Tests
# ---------------------------------------------------------------------------


class TestPatternExtractor:
    """Tests for PatternExtractor."""

    def test_init(self, pattern_extractor):
        """Test initialization."""
        assert pattern_extractor.min_confidence == 0.5

    @pytest.mark.asyncio
    async def test_extract_tool_combination_pattern(self, pattern_extractor, sample_msgs):
        """Test extracting tool combination pattern."""
        tool_calls = [
            {"name": "read_file"},
            {"name": "grep_search"},
            {"name": "write_file"},
        ]

        response = Msg(name="assistant", content="分析完成", role="assistant")

        patterns = await pattern_extractor.extract(
            conversation=sample_msgs,
            response=response,
            existing_skills=[],
            tool_calls=tool_calls,
        )

        # Should find tool combination pattern
        assert len(patterns) >= 1
        assert any("tool_combo" in p.name for p in patterns)

    @pytest.mark.asyncio
    async def test_extract_workflow_pattern(self, pattern_extractor):
        """Test extracting workflow pattern."""
        msgs = [
            Msg(name="user", content="分析代码", role="user"),
            Msg(name="assistant", content="步骤：\n1. 首先\n2. 然后\n3. 最后", role="assistant"),
        ]

        patterns = await pattern_extractor.extract(
            conversation=msgs,
            response=msgs[-1],
            existing_skills=[],
            tool_calls=None,
        )

        # Should find workflow pattern (has steps)
        assert len(patterns) >= 1

    @pytest.mark.asyncio
    async def test_filter_existing_skills(self, pattern_extractor, sample_msgs):
        """Test filtering existing skills."""
        tool_calls = [{"name": "read_file"}, {"name": "grep_search"}]

        patterns = await pattern_extractor.extract(
            conversation=sample_msgs,
            response=sample_msgs[-1],
            existing_skills=["tool_combo_read_file_grep_search"],
            tool_calls=tool_calls,
        )

        # Should filter out duplicate
        assert not any("tool_combo_read_file_grep_search" == p.name for p in patterns)

    @pytest.mark.asyncio
    async def test_extract_insights(self, pattern_extractor, sample_msgs):
        """Test extracting memory insights."""
        # Response needs to be > 100 chars to trigger knowledge insight
        long_response = """这是完整的分析结果，包含了详细的项目结构分析和代码审查内容。
这些信息对于后续工作非常重要。我们发现了以下关键点：
1. 项目结构清晰，模块划分合理
2. 代码质量良好，遵循最佳实践
3. 文档完善，易于理解和使用
这个分析过程展示了系统的设计思路和实现方法。"""
        response = Msg(
            name="assistant",
            content=long_response,
            role="assistant",
        )

        insights = await pattern_extractor.extract_insights(
            conversation=sample_msgs,
            response=response,
        )

        # Should extract at least one insight (knowledge insight for long response)
        assert len(insights) >= 1
        # Check that we got a knowledge type insight
        assert any(i.type == "knowledge" for i in insights)

    def test_generate_tool_instructions(self, pattern_extractor):
        """Test generating tool instructions."""
        tools = {"read_file", "write_file"}
        instructions = pattern_extractor._generate_tool_instructions(tools)

        assert "读取文件内容" in instructions
        assert "写入新文件" in instructions


# ---------------------------------------------------------------------------
# SkillCreator Tests
# ---------------------------------------------------------------------------


class TestSkillCreator:
    """Tests for SkillCreator."""

    def test_init(self, skill_creator, temp_skills_dir):
        """Test initialization."""
        assert skill_creator.skills_dir == temp_skills_dir
        assert skill_creator.max_skills == 50
        assert temp_skills_dir.exists()

    @pytest.mark.asyncio
    async def test_create_skill(self, skill_creator):
        """Test creating a skill."""
        pattern = Pattern(
            name="test_new_skill",
            description="New skill",
            instructions="Instructions",
            use_cases="Use cases",
            example="Example",
            confidence=0.7,
        )

        skill_path = await skill_creator.create_skill(pattern)

        assert skill_path.exists()
        assert (skill_path / "SKILL.md").exists()

        skill_content = (skill_path / "SKILL.md").read_text()
        assert "test_new_skill" in skill_content

    @pytest.mark.asyncio
    async def test_update_existing_skill(self, skill_creator):
        """Test updating existing skill."""
        # Create first
        pattern1 = Pattern(
            name="update_test_skill",
            description="Original",
            instructions="Original instructions",
            confidence=0.7,
        )
        await skill_creator.create_skill(pattern1)

        # Update
        pattern2 = Pattern(
            name="update_test_skill",
            description="Updated",
            instructions="New instructions",
            example="New example",
            confidence=0.8,
        )
        skill_path = await skill_creator.create_skill(pattern2)

        skill_content = (skill_path / "SKILL.md").read_text()
        assert "New example" in skill_content

    def test_get_existing_skills(self, skill_creator):
        """Test getting existing skills list."""
        # No skills initially
        assert skill_creator.get_existing_skills() == []

        # Create a skill
        skill_dir = skill_creator.skills_dir / "existing_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: existing_skill\n---\n")

        skills = skill_creator.get_existing_skills()
        assert "existing_skill" in skills

    def test_should_create_skill(self, skill_creator):
        """Test skill creation decision."""
        # High confidence, not duplicate
        pattern = Pattern(
            name="new_skill",
            description="New skill",
            instructions="Instructions",
            confidence=0.7,
        )
        assert skill_creator.should_create_skill(pattern) is True

        # Low confidence
        pattern_low = Pattern(
            name="low_confidence",
            description="Low confidence skill",
            instructions="Instructions",
            confidence=0.3,
        )
        assert skill_creator.should_create_skill(pattern_low) is False

        # Duplicate
        skill_dir = skill_creator.skills_dir / "duplicate_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: duplicate_skill\n---\n")
        pattern_dup = Pattern(
            name="duplicate_skill",
            description="Duplicate skill",
            instructions="Instructions",
            confidence=0.7,
        )
        assert skill_creator.should_create_skill(pattern_dup) is False


# ---------------------------------------------------------------------------
# MemoryInsight Tests
# ---------------------------------------------------------------------------


class TestMemoryInsight:
    """Tests for MemoryInsight."""

    def test_insight_creation(self):
        """Test creating an insight."""
        insight = MemoryInsight(
            content="User prefers concise responses",
            type="preference",
            importance=0.8,
        )
        assert insight.content == "User prefers concise responses"
        assert insight.type == "preference"
        assert insight.importance == 0.8

    def test_default_values(self):
        """Test default values."""
        insight = MemoryInsight(content="Some insight")
        assert insight.type == "general"
        assert insight.importance == 0.5
        assert insight.metadata == {}


# ---------------------------------------------------------------------------
# SelfLearningAgent Tests (Mocked)
# ---------------------------------------------------------------------------


class TestSelfLearningAgentMocked:
    """Tests for SelfLearningAgent with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_agent_initialization(self, learning_config):
        """Test agent initialization with mocked config."""
        # Mock AgentProfileConfig
        mock_config = MagicMock()
        mock_config.name = "test_agent"
        mock_config.workspace_dir = "/tmp/test_workspace"
        mock_config.model = "test_model"
        mock_config.max_iterations = 10
        mock_config.system_prompt = "Test prompt"
        mock_config.skills = []

        with patch("copaw.agents.learning_agent.CoPawAgent.__init__", return_value=None):
            with patch("copaw.agents.learning_agent.SkillCreator"):
                from copaw.agents.learning_agent import SelfLearningAgent

                agent = SelfLearningAgent.__new__(SelfLearningAgent)
                agent._learning_config = learning_config
                agent._turns_since_memory = 0
                agent._iters_since_skill = 0
                agent._user_turn_count = 0
                agent._background_tasks = []
                agent._learning_lock = MagicMock()

                assert agent._learning_config.memory_nudge_interval == 10
                assert agent._learning_config.skill_nudge_interval == 5

    def test_get_learning_stats(self, learning_config):
        """Test getting learning statistics."""
        from copaw.agents.learning_agent import SelfLearningAgent

        agent = SelfLearningAgent.__new__(SelfLearningAgent)
        agent._learning_config = learning_config
        agent._turns_since_memory = 5
        agent._iters_since_skill = 3
        agent._user_turn_count = 15
        agent._background_tasks = []
        agent._skill_creator = MagicMock()
        agent._skill_creator.get_existing_skills.return_value = ["skill1", "skill2"]

        stats = agent.get_learning_stats()

        assert stats["user_turn_count"] == 15
        assert stats["turns_since_memory"] == 5
        assert stats["iters_since_skill"] == 3
        assert stats["existing_skills"] == 2