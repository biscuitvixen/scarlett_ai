"""Client for the LLM backend and prompt assembly for Scarlett's voice."""

import logging
from pathlib import Path

from openai import AsyncOpenAI

from .config import Settings

log = logging.getLogger(__name__)

# kept in code rather than personality.md so edits there can't break the
# output format
FORMAT_RULES = (
    "You are chatting on Discord. Reply with the message text only, "
    "no name prefix, no surrounding quotes. Keep it short, this is chat, "
    "not email."
)

FALLBACK_PERSONALITY = "You are Scarlett, a friendly Discord bot."


class LLM:
    def __init__(self, settings: Settings):
        self.client = AsyncOpenAI(
            base_url=settings.llm_base_url, api_key=settings.llm_api_key
        )
        self.model = settings.llm_model
        self.personality_path = Path(settings.personality_path)

    def _personality(self) -> str:
        # reread every call so the file can be edited without a restart
        try:
            return self.personality_path.read_text()
        except OSError:
            log.warning("no personality file at %s", self.personality_path)
            return FALLBACK_PERSONALITY

    async def chat_reply(self, transcript: str, bot_name: str) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self._personality() + "\n\n" + FORMAT_RULES,
                },
                {
                    "role": "user",
                    "content": (
                        f"Recent conversation:\n{transcript}\n\n"
                        f"Write {bot_name}'s next message."
                    ),
                },
            ],
            max_tokens=300,
            temperature=0.8,
            # Qwen3 chat templates take this to skip the reasoning block,
            # other templates just ignore it
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        text = resp.choices[0].message.content or ""
        # some models think out loud anyway
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        return text.strip()
