# scarlett

A Discord bot that runs on a DGX Spark, with a local LLM behind it.

Planned features:

- **Personality chat**: talks to a local model served by vLLM (OpenAI-compatible API in a separate container), replies when mentioned and occasionally interjects.
- **Timestamp coordination**: spots time phrases in messages ("friday at 7pm") and replies with Discord timestamp markup (`<t:unix:F>`), so everyone sees the time in their own zone. Deterministic parsing first, LLM only as a fallback for fuzzy phrasing. Users register a timezone with `/tz`.
- **Music**: plays audio from links in voice channels via Lavalink.

This is currently a skeleton. The bot connects, loads its cogs, and answers `/ping`. Everything else is stubbed.

## Architecture

Three containers, defined in `docker-compose.yml`:

| Service  | What it does |
|----------|--------------|
| bot      | The discord.py bot itself. CPU only. |
| lavalink | Audio server the bot will control via wavelink. |
| vllm     | Serves the LLM over an OpenAI-compatible API. Opt-in via the `llm` compose profile since it holds model weights in memory. |

The bot never touches the GPU directly. It just speaks HTTP to whatever `LLM_BASE_URL` points at, so vLLM can be swapped for Ollama or anything else OpenAI-compatible.

## Setup

1. Create an application at https://discord.com/developers/applications, add a bot, enable the **message content** intent, and grab the token.
2. Invite it to your server with the `bot` and `applications.commands` scopes.
3. Configure and start:

```sh
cp .env.example .env   # fill in DISCORD_TOKEN, and GUILD_ID for instant command sync
docker compose up -d --build
```

When you are ready to run inference, set `LLM_MODEL` in `.env` and start the LLM too:

```sh
docker compose --profile llm up -d
```

## Notes for the DGX Spark

- The Spark is aarch64 (GB10). All images here are multi-arch, but the vLLM service must use NVIDIA's arm64 build. Check [NGC](https://catalog.ngc.nvidia.com) for the current tag and update `docker-compose.yml` if needed.
- The GPU reservation in the compose file requires the NVIDIA container toolkit, which DGX OS ships with.
- Model weights are cached in the `hf-cache` volume, so restarting the vllm container does not re-download them.

## CI

Pushes to `main` (and `v*` tags) build a multi-arch image and publish it to GHCR as `ghcr.io/<owner>/<repo>`. Pull requests build without publishing.
