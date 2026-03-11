import asyncio
import json
import os
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama


class OllamaClient:
    """
    Simple async Ollama client for controlled, deterministic LLM calls.
    - No tools
    - No MCP
    - No streaming
    - Explicit prompts
    """

    def __init__(
        self,
        model: str = "qwen2.5:1.5b",
        temperature: float = 0.2,
        timeout: int = 120,
    ):
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

        OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://ollama:11434")
        self.llm = ChatOllama(
            base_url=OLLAMA_URL,
            model=model,
            temperature=temperature,
            timeout=timeout,
        )

      



    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Simple text completion.
        Returns raw text.
        """

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)

        # ChatOllama returns AIMessage
        return response.content.strip()

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Completion that MUST return JSON.
        Fails loudly if parsing fails.
        """

        json_instruction = """
        Return ONLY valid JSON.
        Do not include explanations or markdown.
        """

        if schema_hint:
            json_instruction += f"\nJSON schema hint:\n{json.dumps(schema_hint, indent=2)}"

        messages = [
            SystemMessage(content=system_prompt + json_instruction),
            HumanMessage(content=user_prompt),
        ]

        response = await self.llm.ainvoke(messages)
        text = response.content.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Ollama JSON parse failed.\nRaw output:\n{text}"
            ) from e