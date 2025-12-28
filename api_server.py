import asyncio
import json
import time
from typing import Optional, Union

import toml
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# 复用 agent.py 中的工具和配置
from agent import SYSTEM_PROMPT, get_repo_readme, get_user_starred, search_repositories

# 加载配置
config = toml.load("config.toml")

app = FastAPI(
    title="GitHubHunt API",
    description="OpenAI-compatible API for GitHub repository search using AI Agent",
    version="1.0.0",
)


# ===== Pydantic 模型定义 =====


class Message(BaseModel):
    role: str
    content: Union[str, list]  # 支持字符串或多模态（但后续会拒绝多模态）


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2000
    stream: Optional[bool] = False
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0

    class Config:
        extra = "allow"  # 宽松解析，允许额外字段


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = int(time.time())
    owned_by: str = "githubhunt"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


# ===== 鉴权 =====


async def verify_api_key(authorization: Optional[str] = Header(None)):
    """验证 API Key"""
    expected_key = config.get("api", {}).get("api_key", "")

    if not expected_key:
        # 如果没有配置 api_key，则不进行验证
        return

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = authorization.replace("Bearer ", "")
    if token != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ===== Agent 创建 =====


def create_agent(enable_visual: bool = False) -> Agent:
    """创建 GitHub Agent 实例"""
    tools = [search_repositories, get_user_starred, get_repo_readme]

    # 视觉分析暂不支持（Phase 1）
    # if enable_visual:
    #     from agent import view_repo_readme
    #     tools.append(view_repo_readme)

    return Agent(
        name="Github Agent",
        instructions=SYSTEM_PROMPT,
        model=DeepSeek(
            id=config["app"].get("deepseek_model", "deepseek-chat"),
            api_key=config["app"]["deepseek_api_key"],
            base_url=config["app"].get("deepseek_base_url", "https://api.deepseek.com/v1"),
            default_headers={"User-Agent": "curl/7.74.0"},  # CF 绕过
        ),
        markdown=True,
        tools=tools,
        debug_mode=False,
    )


# ===== 消息处理 =====


def messages_to_query(messages: list[Message]) -> str:
    """
    将 OpenAI 消息格式转换为 Agent query
    Phase 1: 简单策略，只取最后一条 user 消息
    """
    user_messages = [m for m in messages if m.role == "user"]

    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found in conversation")

    last_message = user_messages[-1]

    # 检查是否为多模态输入
    if isinstance(last_message.content, list):
        raise HTTPException(
            status_code=400,
            detail="Multimodal input (text+image) is not supported yet. Please use text-only queries.",
        )

    return last_message.content


# ===== Agent 执行 =====


async def run_agent_sync(agent: Agent, query: str) -> str:
    """
    执行 Agent 并收集完整输出（非流式）

    注意: agno 的 Agent.arun() 返回异步生成器
    需要收集所有 chunk 并合并
    """
    response_parts = []

    async for event in agent.arun(query, stream=True):
        # 根据 agno 实际 API 调整
        # 可能的属性: content, delta, type 等
        if hasattr(event, "content") and event.content:
            response_parts.append(event.content)
        elif isinstance(event, str):
            response_parts.append(event)

    result = "".join(response_parts).strip()
    return result if result else "No response generated from agent."


async def generate_stream(agent: Agent, query: str, model_name: str):
    """SSE 流式生成器（Phase 2）"""
    try:
        async for event in agent.arun(query, stream=True):
            content = None

            # 提取内容
            if hasattr(event, "content") and event.content:
                content = event.content
            elif isinstance(event, str):
                content = event

            if content:
                chunk = {
                    "id": f"chatcmpl-{int(time.time() * 1000)}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0.01)  # 防止过快

        # 发送结束信号
        final_chunk = {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as e:
        # 错误处理
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "internal_error",
                "code": "agent_execution_failed",
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"


# ===== API 端点 =====


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "githubhunt-api", "version": "1.0.0"}


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """列出可用模型（OpenAI 兼容）"""
    model_id = config["app"].get("deepseek_model", "deepseek-chat")
    return ModelsResponse(
        object="list",
        data=[
            ModelInfo(
                id="githubhunt-agent",
                object="model",
                created=int(time.time()),
                owned_by="githubhunt",
            ),
            ModelInfo(
                id=model_id,
                object="model",
                created=int(time.time()),
                owned_by="deepseek",
            ),
        ],
    )


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: Optional[str] = Header(None),
):
    """
    聊天补全端点（OpenAI 兼容）
    支持流式和非流式响应
    """
    # 鉴权
    await verify_api_key(authorization)

    # 提取 query
    try:
        query = messages_to_query(request.messages)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse messages: {str(e)}")

    # 创建 Agent
    agent = create_agent()

    # 流式响应
    if request.stream:
        return StreamingResponse(
            generate_stream(agent, query, request.model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            },
        )

    # 非流式响应
    try:
        response_text = await run_agent_sync(agent, query)

        return {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,  # agno 可能不提供，暂时填 0
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")


# ===== 启动配置 =====

if __name__ == "__main__":
    import uvicorn

    host = config.get("api", {}).get("host", "0.0.0.0")
    port = config.get("api", {}).get("port", 7777)

    uvicorn.run(
        "api_server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )
