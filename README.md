<div align="center">

# QwenPaw

[![GitHub Repo](https://img.shields.io/badge/GitHub-Repo-black.svg?logo=github)](https://github.com/yellowyao/CoPaw)
[![Python Version](https://img.shields.io/badge/python-3.10%20~%20%3C3.14-blue.svg?logo=python&label=Python)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-red.svg?logo=apache&label=License)](LICENSE)

[[中文](README_zh.md)] [[日本語](README_ja.md)] [[Русский](README_ru.md)]

<p align="center"><b>Works for you, grows with you — and learns with you.</b></p>

</div>

## 🆕 v1.1.0 - SelfLearningAgent

**SelfLearningAgent** 自主学习能力已添加：

- **Memory Nudge** — 自动从对话中提取重要信息并存储到记忆
- **Pattern Extraction** — 从成功任务中识别可复用的模式
- **Skill Auto-Creation** — 从学习到的模式自动创建新技能
- **Background Learning** — 异步学习，不干扰用户交互

### 配置方式

在 `agent.json` 中添加 `learning` 配置：

```json
{
  "learning": {
    "enabled": true,
    "max_history": 100,
    "min_similarity": 0.3,
    "auto_save_threshold": 5,
    "max_iterations": 10
  }
}
```

或在 Console UI 的 **Settings → Agent Config → Self Learning** 中启用。

### 技术文档

- [SelfLearningAgent 实现文档](doc/SelfLearningAgent实现文档.md)

---

## 快速开始

### pip 安装

```bash
pip install copaw
copaw init --defaults
copaw app
```

打开浏览器访问 **http://127.0.0.1:8088/** 配置模型。

### Docker

```bash
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 \
  -v copaw-data:/app/working \
  -v copaw-secrets:/app/working.secret \
  agentscope/copaw:latest
```

### 源码安装

```bash
git clone https://github.com/yellowyao/CoPaw.git
cd CoPaw

# 构建前端
cd console && npm ci && npm run build
cd ..

# 复制前端构建产物
mkdir -p src/copaw/console
cp -R console/dist/. src/copaw/console/

# 安装 Python 包
pip install -e ".[full]"
copaw init --defaults
copaw app
```

---

## API Key 配置

如果使用云端 LLM API（如 Qwen、Gemini、OpenAI），需要配置 API Key：

1. **Console** — 打开 **http://127.0.0.1:8088/** → **Settings** → **Models**，输入 API Key
2. **环境变量** — 设置 `DASHSCOPE_API_KEY` 等环境变量

使用本地模型（llama.cpp / Ollama / LM Studio）无需 API Key。

---

## 安全特性

- **Tool Guard** — 自动拦截危险 shell 命令
- **File Access Guard** — 限制访问敏感路径
- **Skill Security Scanning** — 安装技能前自动扫描风险
- **Web Authentication** — 可选的登录保护

启用 Web 认证：
```bash
export COPAW_AUTH_ENABLED=true
export COPAW_AUTH_USERNAME=your@email.com
export COPAW_AUTH_PASSWORD=your_password
```

---

## 文档

完整文档请参考上游 [CoPaw 官方文档](https://copaw.agentscope.io/docs/intro)。

---

## 关于

本仓库是 [CoPaw](https://github.com/agentscope-ai/CoPaw) 的个人 fork，主要添加了 SelfLearningAgent 自主学习功能。

CoPaw 正式更名为 **QwenPaw**：

- **Qwen** — 代表与 Qwen 开源生态的融合
- **Paw** — 初心的延续，陪伴用户的个人助手

---

## License

[Apache License 2.0](LICENSE)