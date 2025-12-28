# githubhunt

githubhunt 是一个基于 AI Agent 的自然语言 Github 仓库搜索工具, 用户通过使用自然语言描述需求, 例如: "查找 golang 实现的 redis 服务器, 基于 AELoop", AI Agent 会识别用户的意图, 并结合内置的搜索工具, 不断调整输入优化搜索结果, 最终帮助用户实现 Github 仓库的精准搜索.

下面是一个简单的使用示例:

![image](./example/image.png)

![image2](./example/image2.png)

除此以外, Agent 还支持:

- 使用视觉理解模型分析仓库, 例如: "解释 xgzlucario/rotom 的流程图"
- 从用户的 starred 列表中搜索, 例如: "从我的关注列表中查找监控相关的项目, 我是 xgzlucario"
- 总结或解释仓库的功能: 例如: xgalucario/githubhunt 仓库是做什么的?

## 系统依赖

- [MeiliSearch](https://github.com/meilisearch/meilisearch)
- Python 3.13
- DeepSeek API
- Steel Browser(可选, 用于视觉分析)
- QWEN API(可选, 用于视觉分析)

## 项目结构

- `fetch_repos.py`: 拉取 Github 仓库并保存到 MeiliSearch
- `agent.py`: 使用 Agent 进行搜索
- `browser.py`: 调用浏览器截图工具, 用于视觉分析
- `db.py`: MeiliSearch 索引构建定义和 db 操作封装
- `config.toml`: 配置文件

## 使用方法

### 环境配置

1. 复制配置文件模板：

```bash
cp config.toml.example config.toml
```

2. 编辑 `config.toml` 并填写以下必需配置：

```toml
[app]
# Github Personal Access Token (必需)
# 获取地址: https://github.com/settings/tokens
github_token = "github_pat_xxxxxx"

# DeepSeek API 配置 (必需)
# 获取地址: https://platform.deepseek.com/api_keys
deepseek_api_key = "sk-xxxxxx"
deepseek_base_url = "https://api.deepseek.com/v1"  # 支持中转 API
deepseek_model = "deepseek-chat"  # 可选模型: deepseek-chat, deepseek-reasoner

# Qwen API 配置 (可选，仅视觉分析需要)
# 获取地址: https://dashscope.console.aliyun.com/apiKey
qwen_api_key = "sk-xxxxxx"
qwen_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
qwen_model = "qwen3-vl-plus"
```

**注意**: `config.toml` 包含敏感信息，已添加到 `.gitignore`，不会被提交到 Git。

### 启动 MeiliSearch

```bash
docker compose up -d
```

### 安装依赖

首先确保安装了 [uv](https://docs.astral.sh/uv/) 工具, 然后执行命令:

```bash
uv sync
```

### 拉取 Github 仓库

第一次运行时需要同步 Github 仓库到 MeiliSearch, 后续可以按需定期同步。

在本地构建索引可以大大提升搜索性能, 原因是本地使用 `frequency` 的[匹配策略](https://www.meilisearch.com/docs/reference/api/search#matching-strategy), 相比 Github API 的 `all` 策略, 每次搜索的召回率更高, 返回的结果数量更多, 更容易命中目标仓库。

```bash
uv run fetch_repos.py
```

### 使用 Agent 进行搜索

```bash
uv run agent.py --query "查找 golang 实现的 redis 服务器, 基于 AELoop"
```

如果需要使用视觉分析工具, 首先需要安装 [Steel Browser](https://github.com/steel-dev/steel-browser), 命令如下:

```bash
sudo docker run --name steel-browser-api -d -p 3000:3000 -p 9223:9223 ghcr.io/steel-dev/steel-browser-api:latest
```

然后使用视觉分析工具:

```bash
uv run agent.py --query "解释 xgzlucario/rotom 的流程图" --visual
```

## API 服务

githubhunt 提供了 OpenAI 兼容的 API 服务，可以与 OpenWebUI 等工具集成。

### 配置 API

在 `config.toml` 中添加 API 配置：

```toml
[api]
host = "0.0.0.0"
port = 7777
# API 密钥（用于鉴权，任意非空字符串即可）
# 如果不设置此字段，API 将不进行鉴权验证
api_key = "sk-your-api-key"
```

### 启动 API 服务

使用提供的脚本启动服务：

```bash
./run_api.sh
```

或者手动启动：

```bash
export PATH="$HOME/.local/bin:$PATH"
uv run uvicorn api_server:app --host 0.0.0.0 --port 7777
```

### API 端点

服务提供以下 OpenAI 兼容端点：

- `GET /health` - 健康检查
- `GET /v1/models` - 获取可用模型列表
- `POST /v1/chat/completions` - 聊天补全（支持流式和非流式）

### 测试 API

```bash
# 健康检查
curl http://localhost:7777/health

# 获取模型列表
curl http://localhost:7777/v1/models

# 发送聊天请求
curl -X POST http://localhost:7777/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "githubhunt-agent",
    "messages": [{"role": "user", "content": "查找 Python HTTP 客户端库"}],
    "stream": false
  }'
```

### 与 OpenWebUI 集成

在 OpenWebUI 中配置：

- **Base URL**: `http://localhost:7777/v1`
- **API Key**: 与 `config.toml` 中配置的 `api_key` 一致
- **Model**: 选择 `githubhunt-agent`

配置完成后即可在 OpenWebUI 中使用自然语言搜索 GitHub 仓库。

### API 功能特性

- ✅ OpenAI 兼容接口
- ✅ 流式和非流式响应
- ✅ Bearer Token 鉴权
- ✅ 混合搜索（MeiliSearch + GitHub API）
- ✅ 智能工具调用（搜索、获取 README 等）
- ✅ Cloudflare WAF 绕过（User-Agent 伪装）

