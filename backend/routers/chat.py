"""
Chat router — RAG Chatbot API endpoints.

Endpoints:
- POST /api/chat          — Non-streaming (JSON response)
- POST /api/chat/stream   — Server-Sent Events streaming
- DELETE /api/chat/history — Reset conversation (client-side, hướng dẫn)
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.rag_service import chat_with_rag, stream_chat_with_rag

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|model)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    reply: str
    sources_used: bool = True


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Non-streaming chat endpoint với RAG context."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message không được để trống")

    history_dicts = [{"role": m.role, "content": m.content} for m in req.history]

    try:
        reply = await chat_with_rag(req.message, history_dicts)
        return ChatResponse(reply=reply, sources_used=True)
    except Exception as e:
        log.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"AI service tạm thời không khả dụng: {str(e)}",
        )


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """Streaming chat qua Server-Sent Events."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message không được để trống")

    history_dicts = [{"role": m.role, "content": m.content} for m in req.history]

    async def event_generator():
        try:
            async for chunk in stream_chat_with_rag(req.message, history_dicts):
                data = json.dumps({"chunk": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.error(f"Stream error: {e}")
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
