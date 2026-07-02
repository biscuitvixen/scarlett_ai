from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All runtime configuration, read from environment variables.

    Field names map to env vars case-insensitively, so discord_token
    is filled from DISCORD_TOKEN and so on.
    """

    discord_token: str
    guild_id: int | None = None

    llm_base_url: str = "http://vllm:8000/v1"
    llm_model: str = ""
    llm_api_key: str = "not-needed"

    lavalink_url: str = "http://lavalink:2333"
    lavalink_password: str = "youshallnotpass"

    db_path: str = "/app/data/scarlett.db"
