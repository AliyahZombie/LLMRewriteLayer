from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import json
import asyncio
import logging
import yaml
import os

# 加载配置文件
def load_config():
    config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except Exception as e:
        logging.error(f"加载配置文件失败: {e}")
        raise Exception(f"无法加载配置文件 {config_path}: {str(e)}")

# 全局配置
config = load_config()

# 初始化 FastAPI 应用
app = FastAPI(
    title=config.get("app_name", "文风转换 API 代理"),
    description=config.get("app_description", "代理并重写 AI 接口响应"),
    version=config.get("app_version", "1.0.0")
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get("cors", {}).get("allow_origins", ["*"]),
    allow_credentials=config.get("cors", {}).get("allow_credentials", True),
    allow_methods=config.get("cors", {}).get("allow_methods", ["*"]),
    allow_headers=config.get("cors", {}).get("allow_headers", ["*"]),
)

# 配置日志
log_level = getattr(logging, config.get("logging", {}).get("level", "DEBUG"))
logging.basicConfig(
    level=log_level,
    format=config.get("logging", {}).get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger = logging.getLogger(__name__)

# 从配置文件读取 API 配置
TARGET_API_URL = config.get("target_api", {}).get("url", "https://example.com/v1")
TARGET_API_KEY = config.get("target_api", {}).get("api_key", "")
REWRITE_API_URL = config.get("rewrite_api", {}).get("url", "https://api.example.cn/v1/chat/completions")
REWRITE_API_KEY = config.get("rewrite_api", {}).get("api_key", "")
REWRITE_MODEL = config.get("rewrite_api", {}).get("model", "Pro/deepseek-ai/DeepSeek-R1")
REWRITE_STYLE = config.get("rewrite_api", {}).get("style", "更加自然的中文 去除机械味")
REWRITE_TIMEOUT = float(config.get("rewrite_api", {}).get("timeout", 60.0))

# 文风重写函数（非流式，用于非流式响应）
async def rewrite_chunk(content: str) -> str:
    logger.debug(f"重写片段: {content}")
    if config.get("debug", False):
        print(f"原始内容: {content}")
    
    rewrite_prompt = f"请将以下文本重写为{REWRITE_STYLE}：{content} \n\n不要其它内容 直接输出改写文本"
    rewrite_body = {
        "model": REWRITE_MODEL,
        "messages": [{"role": "user", "content": rewrite_prompt}]
    }
    headers = {
        "Authorization": f"Bearer {REWRITE_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        async with httpx.AsyncClient(timeout=REWRITE_TIMEOUT) as client:
            response = await client.post(REWRITE_API_URL, headers=headers, json=rewrite_body)
            response.raise_for_status()
            rewritten = response.json()["choices"][0]["message"]["content"]
            logger.debug(f"重写后的片段: {rewritten}")
            if config.get("debug", False):
                print(f"重写后的消息: {rewritten}")
            return rewritten
    except httpx.ReadTimeout:
        logger.error("重写超时，返回原始内容")
        if config.get("debug", False):
            print("重写超时，返回原始内容")
        return content

# 流式响应生成器（原始 API 非流式，重写 API 流式）
async def stream_response(request: Request, endpoint: str):
    body = await request.json()
    # 强制原始 API 调用为非流式
    body["stream"] = False
    target_url = f"{TARGET_API_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {TARGET_API_KEY}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=REWRITE_TIMEOUT) as client:
        # 获取原始 API 的完整响应
        response = await client.post(target_url, headers=headers, json=body)
        response.raise_for_status()
        original_response = response.json()
        full_message = original_response["choices"][0]["message"]["content"]
        if config.get("debug", False):
            print(f"完整原始消息: {full_message}")

        # 准备流式重写请求
        rewrite_prompt = f"请将以下文本重写为{REWRITE_STYLE}：{full_message}不要其它内容 直接输出改写文本"
        rewrite_body = {
            "model": REWRITE_MODEL,
            "messages": [{"role": "user", "content": rewrite_prompt}],
            "stream": True  # 启用流式重写
        }
        rewrite_headers = {
            "Authorization": f"Bearer {REWRITE_API_KEY}",
            "Content-Type": "application/json"
        }
        # 发起流式重写请求并实时返回
        async with client.stream("POST", REWRITE_API_URL, headers=rewrite_headers, json=rewrite_body) as rewrite_response:
            async for chunk in rewrite_response.aiter_lines():
                if chunk:
                    if chunk.startswith("data: "):
                        chunk = chunk[len("data: "):].strip()
                        if chunk == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            data = json.loads(chunk)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n"
                        except json.JSONDecodeError:
                            logger.error(f"重写 API 返回无效 JSON 块: {chunk}")
                            if config.get("debug", False):
                                print(f"重写 API 返回无效 JSON 块: {chunk}")
                            continue

# 非流式响应处理
async def non_stream_response(request: Request, endpoint: str):
    body = await request.json()
    target_url = f"{TARGET_API_URL}{endpoint}"
    logger.debug(f"非流式请求 {endpoint}: {body}")
    if config.get("debug", False):
        print(f"非流式请求 {endpoint}: {body}")
    
    headers = {
        "Authorization": f"Bearer {TARGET_API_KEY}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(timeout=REWRITE_TIMEOUT) as client:
        response = await client.post(target_url, headers=headers, json=body)
        response.raise_for_status()
        original_response = response.json()
    
    if endpoint == "/chat/completions":
        latest_message = original_response["choices"][0]["message"]["content"]
        logger.debug(f"原始消息: {latest_message}")
        if config.get("debug", False):
            print(f"原始消息: {latest_message}")
        
        rewritten_message = await rewrite_chunk(latest_message)
        original_response["choices"][0]["message"]["content"] = rewritten_message
        logger.debug(f"重写后的消息: {rewritten_message}")
        if config.get("debug", False):
            print(f"非流式重写后的消息: {rewritten_message}")
    
    return original_response

# 通用的 API 路由处理
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def forward_request(request: Request, path: str):
    try:
        endpoint = f"/{path}"
        
        # 处理 CORS 的 OPTIONS 请求
        if request.method == "OPTIONS":
            return JSONResponse(
                content={},
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                }
            )

        # 专门处理聊天补全请求
        if endpoint == "/v1/chat/completions":
            body = await request.json()
            if body.get("stream", False):
                return StreamingResponse(
                    stream_response(request, "/chat/completions"),
                    media_type="text/event-stream"
                )
            else:
                return await non_stream_response(request, "/chat/completions")
        
        # 处理其他所有端点
        target_url = f"{TARGET_API_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {TARGET_API_KEY}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=REWRITE_TIMEOUT) as client:
            if request.method == "POST":
                body = await request.json()
                response = await client.post(target_url, headers=headers, json=body)
            elif request.method == "GET":
                response = await client.get(target_url, headers=headers)
            elif request.method == "PUT":
                body = await request.json()
                response = await client.put(target_url, headers=headers, json=body)
            elif request.method == "DELETE":
                response = await client.delete(target_url, headers=headers)
            else:
                raise HTTPException(status_code=405, detail="不支持的方法")
            
            response.raise_for_status()
            return JSONResponse(content=response.json())
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        if config.get("debug", False):
            print(f"HTTP 错误: {e}")
        raise HTTPException(status_code=e.response.status_code, detail=f"API 调用失败: {e}")
    except Exception as e:
        logger.error(f"服务器内部错误: {e}")
        if config.get("debug", False):
            print(f"服务器内部错误: {e}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

# 运行服务
if __name__ == "__main__":
    import uvicorn
    host = config.get("server", {}).get("host", "0.0.0.0")
    port = int(config.get("server", {}).get("port", 8000))
    uvicorn.run(app, host=host, port=port)