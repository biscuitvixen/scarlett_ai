from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All runtime configuration, read from environment variables.

    Field names map to env vars case-insensitively, so discord_token
    is filled from DISCORD_TOKEN and so on.
    """

    discord_token: str
    guild_id: int | None = None

    # a blank line in .env ("GUILD_ID=") should mean unset, not crash
    @field_validator("guild_id", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if v == "" else v

    llm_base_url: str = "http://vllm:8000/v1"
    llm_model: str = ""
    llm_api_key: str = "not-needed"

    personality_path: str = "/app/personality.md"
    # comma separated guild ids where the chat personality may talk
    chat_guild_ids: str = ""

    lavalink_url: str = "http://lavalink:2333"
    lavalink_password: str = "youshallnotpass"

    db_path: str = "/app/data/scarlett.db"

    @property
    def chat_guilds(self) -> set[int]:
        return {
            int(g)
            for g in self.chat_guild_ids.replace(" ", "").split(",")
            if g
        }
