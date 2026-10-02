"""Verify migration request bodies without calling providers or writing product data."""
import ast
import asyncio
import json
import sys
from pathlib import Path

import httpx
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings


async def main():
    settings = Settings(_env_file=None, DATABASE_BACKEND="sqlite")
    assert settings.LLM_MODEL == settings.VLM_MODEL == "gpt-6.1-sol"
    assert settings.LLM_REASONING_EFFORT == settings.VLM_REASONING_EFFORT == "medium"
    captured = []

    def handle(request):
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": '{"ok":true}'}}],
        })

    async with AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))) as client:
        for vision, budget in ((False, 4500), (True, 80)):
            await client.chat.completions.create(
                model=settings.VLM_MODEL if vision else settings.LLM_MODEL,
                messages=[{"role": "user", "content": "Return JSON."}],
                response_format={"type": "json_object"},
                **settings.chat_completion_options(model="gpt-6.1-sol", max_tokens=budget, temperature=0.3, vision=vision),
            )
            body = captured[-1]
            assert body["reasoning_effort"] == "medium"
            assert body["max_completion_tokens"] == budget + 8192
            assert "temperature" not in body and "max_tokens" not in body
            assert body["response_format"] == {"type": "json_object"}
    assert settings.chat_completion_options(model="legacy-model", max_tokens=80, temperature=0.2) == {
        "max_tokens": 80, "temperature": 0.2,
    }
    count = 0
    for path in (ROOT / "backend/app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not ast.unparse(node.func).endswith(".chat.completions.create"):
                continue
            assert any(k.arg is None and isinstance(k.value, ast.Call) and ast.unparse(k.value.func) == "settings.chat_completion_options" for k in node.keywords), path
            assert not any(k.arg in ("temperature", "max_tokens") for k in node.keywords), path
            count += 1
    assert count == 12
    print(f"PASS: model defaults, serialized medium requests, token budgets, legacy compatibility, {count} call sites")


if __name__ == "__main__":
    asyncio.run(main())
