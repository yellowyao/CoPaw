#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SelfLearningAgent 启用示例。

演示如何通过配置文件或代码启用 SelfLearningAgent。
"""

import asyncio
import logging
import tempfile
from pathlib import Path

# 设置日志以观察学习过程
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

from agentscope.message import Msg


def demo_config_file_enable():
    """演示配置文件启用方式"""
    print("\n=== 配置文件启用方式 ===\n")

    config_example = '''---
name: My Agent
model: qwen-plus
max_iterations: 10
system_prompt: "You are a helpful assistant."
learning:
  enabled: true
  memory_nudge_interval: 10
  skill_nudge_interval: 5
  enable_pattern_extraction: true
  enable_skill_creation: true
  background_learning: true
  auxiliary_model: null
  max_skills: 50
  min_pattern_confidence: 0.5
---

# Agent Profile

这是一个启用了自我学习能力的 Agent。
'''

    print("PROFILE.md 配置示例:")
    print(config_example)

    print("\n配置说明:")
    print("- enabled: true          -> 启用自学习")
    print("- memory_nudge_interval: 每 N 个用户轮次回顾记忆")
    print("- skill_nudge_interval:  每 N 次工具迭代创建 Skill")
    print("- background_learning:   后台学习，不阻塞响应")


async def demo_code_enable():
    """演示代码启用方式"""
    print("\n=== 代码启用方式 ===\n")

    from copaw.agents import SelfLearningAgent, LearningConfig
    from copaw.config.config import AgentProfileConfig

    # 创建学习配置
    learning_config = LearningConfig(
        memory_nudge_interval=10,
        skill_nudge_interval=5,
        enable_pattern_extraction=True,
        enable_skill_creation=True,
        background_learning=True,
    )

    print("LearningConfig 配置:")
    print(f"  memory_nudge_interval = {learning_config.memory_nudge_interval}")
    print(f"  skill_nudge_interval = {learning_config.skill_nudge_interval}")
    print(f"  enable_pattern_extraction = {learning_config.enable_pattern_extraction}")
    print(f"  enable_skill_creation = {learning_config.enable_skill_creation}")

    # 模拟 Agent 配置 (实际使用时需要完整配置)
    print("\n创建 Agent 示例代码:")
    print("""
from copaw.agents import SelfLearningAgent, LearningConfig

agent = SelfLearningAgent(
    agent_config=config,
    learning_config=LearningConfig(
        memory_nudge_interval=10,
        skill_nudge_interval=5,
    ),
)

response = await agent(msgs)
# 学习自动在后台进行
""")


def demo_verify_running():
    """演示如何验证 Agent 是否正在运行"""
    print("\n=== 验证 Agent 运行状态 ===\n")

    print("方法 1: 查看日志输出")
    print("启动应用时设置日志级别:")
    print("  export COPAW_LOG_LEVEL=INFO")
    print("  copaw app")
    print("")
    print("日志中会显示:")
    print("  INFO: SelfLearningAgent initialized: memory_nudge=10, skill_nudge=5")
    print("  INFO: Spawned background learning: memory=True, skills=False")
    print("  INFO: Memory review completed: 2 insights extracted")
    print("  INFO: Pattern extraction: 1 patterns found")
    print("  INFO: Created new skill: tool_combo_xxx")

    print("\n方法 2: 检查自动创建的 Skills")
    print("Skills 保存在工作目录:")
    print("  ~/.copaw/skills/<skill_name>/SKILL.md")

    print("\n方法 3: 调用 get_learning_stats()")
    print("""
stats = agent.get_learning_stats()
print(stats)
# 输出:
# {
#   "user_turn_count": 15,
#   "turns_since_memory": 5,
#   "iters_since_skill": 3,
#   "background_tasks": 0,
#   "existing_skills": 2,
#   "learning_config": {...}
# }
""")


async def demo_learning_process():
    """演示学习过程"""
    print("\n=== 学习过程演示 ===\n")

    from copaw.agents.learning_agent import PatternExtractor, SkillCreator, Pattern

    # 1. 模式提取
    print("1. PatternExtractor 提取模式")
    extractor = PatternExtractor(min_confidence=0.5)

    msgs = [
        Msg(name="user", content="请帮我分析项目代码", role="user"),
        Msg(name="assistant", content="步骤如下:\n1. 首先\n2. 然后\n3. 最后", role="assistant"),
    ]

    patterns = await extractor.extract(
        conversation=msgs,
        response=msgs[-1],
        existing_skills=[],
        tool_calls=[{"name": "read_file"}, {"name": "grep_search"}],
    )

    print(f"   发现 {len(patterns)} 个模式")
    for p in patterns:
        print(f"   - {p.name} (confidence: {p.confidence})")

    # 2. Skill 创建
    print("\n2. SkillCreator 创建 Skill")
    with tempfile.TemporaryDirectory() as tmpdir:
        creator = SkillCreator(skills_dir=Path(tmpdir))

        if patterns:
            skill_path = await creator.create_skill(patterns[0])
            print(f"   创建成功: {skill_path}")

            # 显示 SKILL.md 内容
            skill_md = (skill_path / "SKILL.md").read_text()
            print(f"\n   SKILL.md 内容预览:")
            for line in skill_md.split("\n")[:15]:
                print(f"   {line}")

    # 3. 记忆洞察
    print("\n3. 提取记忆洞察")
    long_response = Msg(
        name="assistant",
        content="这是完整的分析结果，包含了详细的项目结构分析。"
                "这些信息对于后续工作非常重要。我们发现以下关键点...",
        role="assistant",
    )

    insights = await extractor.extract_insights(msgs, long_response)
    print(f"   发现 {len(insights)} 个洞察")
    for i in insights:
        print(f"   - type: {i.type}, importance: {i.importance}")


def main():
    """运行所有演示"""
    print("=" * 60)
    print("SelfLearningAgent 启用指南")
    print("=" * 60)

    # 配置文件启用
    demo_config_file_enable()

    # 代码启用
    asyncio.run(demo_code_enable())

    # 验证方法
    demo_verify_running()

    # 学习过程演示
    asyncio.run(demo_learning_process())

    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)
    print("""
启用 SelfLearningAgent 的步骤:

1. 配置文件方式 (推荐):
   - 编辑 ~/.copaw/agents/default/PROFILE.md
   - 添加 learning 配置块，设置 enabled: true
   - 启动 copaw app

2. 代码方式:
   - 创建 LearningConfig 配置对象
   - 使用 SelfLearningAgent(agent_config, learning_config)

3. 验证生效:
   - 查看日志输出 (INFO 级别)
   - 检查自动创建的 Skills 目录
   - 调用 get_learning_stats() 查看统计

学习触发条件:
   - memory_nudge_interval: 每 N 个用户轮次回顾记忆
   - skill_nudge_interval: 每 N 次工具迭代创建 Skill
""")
    print("=" * 60)


if __name__ == "__main__":
    main()