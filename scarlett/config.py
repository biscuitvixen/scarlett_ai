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

    # off by default: Scarlett runs as a plain utility bot (timestamps, music)
    # and the chat cog is not loaded. flip to true to opt into the LLM
    # personality; timestamps and music work either way
    llm_enabled: bool = False
    llm_base_url: str = "http://vllm:8000/v1"
    llm_model: str = ""
    llm_api_key: str = "not-needed"

    personality_path: str = "/app/personality.md"
    # comma separated guild ids where the chat personality may talk
    chat_guild_ids: str = ""
    # comma separated user ids exempt from every chat rate limit (that's you)
    owner_ids: str = ""

    # how much friends can lean on her. the per person cooldown escalates the
    # more they talk: the first chat_cooldown_burst replies sit at the base
    # gap, then each extra reply multiplies it by chat_cooldown_factor up to
    # chat_cooldown_max. quiet time heals it back, one step per
    # chat_cooldown_recover seconds. a rolling one hour cap is the hard ceiling.
    chat_cooldown_base: float = 3.0
    chat_cooldown_burst: int = 3
    chat_cooldown_factor: float = 2.2
    chat_cooldown_max: float = 240.0
    chat_cooldown_recover: float = 45.0
    chat_user_hourly_cap: int = 20
    # how many generations may run at once, the rest queue so a flood can't
    # pile onto the gpu
    chat_max_concurrent: int = 2
    # caps on the transcript fed to the model, so a pasted wall of text can't
    # blow up the prompt. per line and total, in characters
    chat_line_char_cap: int = 500
    chat_transcript_char_cap: int = 4000
    # a swapped-out model (llama-swap) takes a moment to load on the first
    # request. if a reply she's been asked for is slower than this many seconds,
    # she posts a quick "waking up" line first instead of sitting silent
    chat_wake_after: float = 8.0

    lavalink_url: str = "http://lavalink:2333"
    lavalink_password: str = "youshallnotpass"
    # seconds she lingers in a voice channel with nothing playing before
    # disconnecting on her own
    music_idle_timeout: int = 300

    db_path: str = "/app/data/scarlett.db"

    @property
    def chat_guilds(self) -> set[int]:
        return self._id_set(self.chat_guild_ids)

    @property
    def owners(self) -> set[int]:
        return self._id_set(self.owner_ids)

    @staticmethod
    def _id_set(raw: str) -> set[int]:
        return {int(x) for x in raw.replace(" ", "").split(",") if x}
