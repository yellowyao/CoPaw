#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 SelfLearningAgent 是否生效的脚本。

使用方法:
    python verify_learning_agent.py
"""

import asyncio
import logging
from pathlib import Path
from datetime import datetime

# 设置日志级别
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from agentscope.message import Msg


def verify_import():
    """验证导入是否成功"""
    print("\n=== 1. 导入验证 ===")

    try:
        from copaw.agents import SelfLearningAgent, LearningConfig
        print("✅ SelfLearningAgent 导入成功")
        print(f"   - SelfLearningAgent: {SelfLearningAgent}")
        print(f"   - LearningConfig: {LearningConfig}")
        return True
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False


def verify_config():
    """验证配置类"""
    print("\n=== 2. 配置验证 ===")

    from copaw.agents import LearningConfig
    from copaw.config.config import AgentLearningConfig

    # LearningConfig (运行时配置)
    lc = LearningConfig(
        memory_nudge_interval=10,
        skill_nudge_interval=5,
    )
    print(f"✅ LearningConfig 创建成功")
    print(f"   - memory_nudge_interval: {lc.memory_nudge_interval}")
    print(f"   - skill_nudge_interval: {lc.skill_nudge_interval}")
    print(f"   - background_learning: {lc.background_learning}")

    # AgentLearningConfig (持久化配置)
    alc = AgentLearningConfig(
        enabled=True,
        memory_nudge_interval=10,
    )
    print(f"✅ AgentLearningConfig 创建成功")
    print(f"   - enabled: {alc.enabled}")
    print(f"   - max_skills: {alc.max_skills}")
    print(f"   - min_pattern_confidence: {alc.min_pattern_confidence}")

    return True


def verify_components():
    """验证组件类"""
    print("\n=== 3. 组件验证 ===")

    from copaw.agents.learning_agent import (
        Pattern,
        PatternExtractor,
        SkillCreator,
        MemoryInsight,
    )
    import tempfile

    # Pattern
    pattern = Pattern(
        name="test_pattern",
        description="测试模式",
        instructions="测试指令",
        confidence=0.7,
    )
    print(f"✅ Pattern 创建成功: {pattern.name}")
    print(f"   - SKILL.md 预览:\n{pattern.to_skill_md()[:100]}...")

    # PatternExtractor
    extractor = PatternExtractor(min_confidence=0.5)
    print(f"✅ PatternExtractor 创建成功")

    # SkillCreator (使用临时目录)
    with tempfile.TemporaryDirectory() as tmpdir:
        creator = SkillCreator(skills_dir=Path(tmpdir))
        print(f"✅ SkillCreator 创建成功")
        print(f"   - skills_dir: {creator.skills_dir}")
        print(f"   - max_skills: {creator.max_skills}")

    # MemoryInsight
    insight = MemoryInsight(
        content="测试洞察",
        type="preference",
        importance=0.8,
    )
    print(f"✅ MemoryInsight 创建成功: {insight.type}")

    return True


async def verify_extraction():
    """验证模式提取逻辑"""
    print("\n=== 4. 模式提取验证 ===")

    from copaw.agents.learning_agent import PatternExtractor, MemoryInsight

    extractor = PatternExtractor(min_confidence=0.5)

    # 创建测试对话
    msgs = [
        Msg(name="user", content="请帮我分析项目代码", role="user"),
        Msg(name="assistant", content="好的，步骤如下：\n1. 首先\n2. 然后\n3. 最后\n完成了分析", role="assistant"),
    ]

    # 提取模式
    patterns = await extractor.extract(
        conversation=msgs,
        response=msgs[-1],
        existing_skills=[],
        tool_calls=[{"name": "read_file"}, {"name": "grep_search"}],
    )

    print(f"✅ 模式提取完成，发现 {len(patterns)} 个模式")
    for p in patterns:
        print(f"   - {p.name}: confidence={p.confidence}")

    # 提取洞察
    long_response = Msg(
        name="assistant",
        content="这是完整的分析结果，包含了详细的项目结构分析和代码审查内容。这些信息对于后续工作非常重要。",
        role="assistant",
    )
    insights = await extractor.extract_insights(msgs, long_response)
    print(f"✅ 洞察提取完成，发现 {len(insights)} 个洞察")
    for i in insights:
        print(f"   - type={i.type}, importance={i.importance}")

    return True


async def verify_skill_creation():
    """验证 Skill 创建"""
    print("\n=== 5. Skill 创建验证 ===")

    from copaw.agents.learning_agent import Pattern, SkillCreator
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        creator = SkillCreator(skills_dir=Path(tmpdir), max_skills=50)

        # 创建测试 Pattern
        pattern = Pattern(
            name="verify_test_skill",
            description="验证测试 Skill",
            instructions="这是验证测试的指令内容",
            use_cases="用于验证 Skill 创建功能",
            example="示例内容",
            confidence=0.7,
        )

        # 创建 Skill
        skill_path = await creator.create_skill(pattern)
        print(f"✅ Skill 创建成功")
        print(f"   - 路径: {skill_path}")

        # 读取 SKILL.md
        skill_md = (skill_path / "SKILL.md").read_text()
        print(f"   - SKILL.md 内容:\n{skill_md[:200]}...")

        # 验证是否在现有列表中
        existing = creator.get_existing_skills()
        print(f"   - 现有 Skills: {existing}")
        assert "verify_test_skill" in existing

    return True


def verify_runner_integration():
    """验证 Runner 集成"""
    print("\n=== 6. Runner 集成验证 ===")

    # 检查 runner.py 中的导入
    from copaw.app.runner.runner import SelfLearningAgent, LearningConfig, AgentLearningConfig

    print(f"✅ Runner 导入正确")
    print(f"   - SelfLearningAgent 已导入到 runner.py")
    print(f"   - LearningConfig 已导入到 runner.py")
    print(f"   - AgentLearningConfig 已导入到 runner.py")

    # 检查 __init__.py 导出
    from copaw.agents import SelfLearningAgent, LearningConfig

    print(f"✅ __init__.py 导出正确")

    return True


def main():
    """运行所有验证"""
    print("=" * 60)
    print("SelfLearningAgent 生效验证")
    print("=" * 60)

    results = {}

    # 同步验证
    results["导入"] = verify_import()
    results["配置"] = verify_config()
    results["组件"] = verify_components()
    results["Runner集成"] = verify_runner_integration()

    # 异步验证
    results["模式提取"] = asyncio.run(verify_extraction())
    results["Skill创建"] = asyncio.run(verify_skill_creation())

    # 总结
    print("\n" + "=" * 60)
    print("验证结果总结")
    print("=" * 60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有验证通过！SelfLearningAgent 已正确集成")
    else:
        print("⚠️ 部分验证失败，请检查上述错误")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)