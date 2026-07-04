# scarlett

A Discord bot with an optional local LLM behind it. Runs anywhere Docker does, from a small CPU-only box to a GPU host like a DGX Spark.

Planned features:

- **Personality chat**: talks to a model over an OpenAI-compatible API (vLLM in a separate container, or any remote endpoint), replies when mentioned and occasionally interjects. Optional, and can be turned off entirely.
- **Timestamp coordination**: spots time phrases in messages ("friday at 7pm") and replies with Discord timestamp markup (`<t:unix:F>`), so everyone sees the time in their own zone. Deterministic parsing first, LLM only as a fallback for fuzzy phrasing. Users register a timezone with `/tz`.
- **Music**: plays audio from links in voice channels via Lavalink.

This is currently a skeleton. The bot connects, loads its cogs, and answers `/ping`. Everything else is stubbed.

## Architecture

Three containers, defined in `docker-compose.yml`:

| Service  | What it does |
|----------|--------------|
| bot      | The discord.py bot itself. CPU only. |
| lavalink | Audio server the bot will control via wavelink. |
| vllm     | Serves the LLM over an OpenAI-compatible API. Needs a GPU. Opt-in via the `llm` compose profile since it holds model weights in memory. |

The bot never touches the GPU directly. It just speaks HTTP to whatever `LLM_BASE_URL` points at, so the LLM can run in the bundled `vllm` container, on a separate GPU machine, or be swapped for Ollama or anything else OpenAI-compatible. Without a GPU anywhere, run the bot on its own and leave the LLM off.

## Deployment modes

Because the bot only needs an HTTP endpoint, the LLM can live anywhere or be left out entirely. Set `LLM_ENABLED` and `LLM_BASE_URL` in `.env`:

| Mode | `LLM_ENABLED` | `LLM_BASE_URL` | Start with |
|------|---------------|----------------|-----------|
| No LLM (CPU-only box) | `false` | ignored | `docker compose up -d` |
| Query a remote GPU host | `true` | `http://<gpu-host>:8000/v1` | `docker compose up -d` (bot side) |
| Bot and LLM together | `true` | `http://vllm:8000/v1` (default) | `docker compose --profile llm up -d` |

With `LLM_ENABLED=false` the chat cog is not loaded, so she never speaks, but timestamps and music keep working. For the remote-host mode, run just the model on the GPU machine with `docker compose --profile llm up -d vllm`. A DGX Spark is one such host (see below), but any CUDA machine works.

**Security**: vLLM has no auth by default and ignores `LLM_API_KEY` unless it is started with `--api-key`. Publishing port `8000` to anything wider than a trusted LAN/VPN gives anyone free use of the GPU. Keep the two machines on the same LAN (or a Tailscale/WireGuard network), or set a secret in `LLM_API_KEY` and add `--api-key <secret>` to the `vllm serve` command.

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

## Running the LLM on a GPU host

The `vllm` service needs an NVIDIA GPU and the container toolkit (so Docker can pass the GPU through via the `deploy.resources` reservation in the compose file). Model weights are cached in the `hf-cache` volume, so restarting the container does not re-download them.

If that host is a DGX Spark, note:

- The Spark is aarch64 (GB10), so the vLLM service must use NVIDIA's arm64 build. Check [NGC](https://catalog.ngc.nvidia.com) for the current tag and update `docker-compose.yml` if needed. (The other images are already multi-arch.)
- DGX OS ships with the NVIDIA container toolkit, so the GPU reservation works out of the box.

## CI

Pushes to `main` (and `v*` tags) build a multi-arch image and publish it to GHCR as `ghcr.io/<owner>/<repo>`. Pull requests build without publishing.
