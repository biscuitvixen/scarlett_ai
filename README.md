# scarlett

A Discord bot with an optional local LLM behind it. Runs anywhere Docker does, from a small CPU-only box to a GPU host like a DGX Spark.

Features:

- **Personality chat**: talks to a model over an OpenAI-compatible API (vLLM in a separate container, or any remote endpoint). She replies when mentioned or replied to and occasionally interjects on her own, only in whitelisted guilds (`CHAT_GUILD_IDS`) and with per-user rate limiting. Her personality lives in `personality.md`, reread on every reply, so it can be edited live without a rebuild. Optional: set `LLM_ENABLED=false` and she stays silent while everything else keeps working.
- **Timestamp coordination**: spots time phrases in messages ("friday at 7pm") and replies with Discord timestamp markup (`<t:unix:F>` and `<t:unix:R>`), so everyone sees the time in their own zone. Parsing is deterministic, so it needs no LLM. Users register a timezone with `/tz` (autocompleted).
- **Music**: plays audio in voice channels via Lavalink. `/play` takes a link or a search term; `/skip`, `/stop`, `/pause`, `/volume`, `/shuffle`, `/loop`, `/queue` and `/nowplaying` round it out. She manages a queue and leaves on her own once the channel empties or nothing has played for a while.

Plus `/ping` to check she's alive.

## Architecture

Three containers, defined in `docker-compose.yml`:

| Service  | What it does |
|----------|--------------|
| bot      | The discord.py bot itself. CPU only. |
| lavalink | Audio server the bot controls via wavelink for music playback. |
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

## Music

Playback runs through the `lavalink` container using the [youtube-source](https://github.com/lavalink-devs/youtube-source) plugin (Lavalink 4 dropped its built-in YouTube support). Two things need doing once on a fresh machine:

- **Plugin volume ownership.** Lavalink runs as uid 322, but Docker creates the `lavalink-plugins` volume as root, so the first plugin download fails with a permission error until you fix it:

  ```sh
  docker run --rm -v scarlett_ai_lavalink-plugins:/p alpine chown -R 322:322 /p
  ```

- **YouTube OAuth**, which is the reliable cure for "sign in to confirm you're not a bot" errors. Start Lavalink with `YOUTUBE_OAUTH_REFRESH_TOKEN` blank in `.env` and watch its logs (`docker compose logs -f lavalink`): it prints a device-link URL and code. Authorise with a **burner** Google account (never your main one), then copy the refresh token it logs into `YOUTUBE_OAUTH_REFRESH_TOKEN` in `.env` and restart. The token is injected into `lavalink/application.yml` via the compose file, so it never lives in a tracked file.

## Slash command sync

Discord keeps slash commands in two separate registries: **global** (shows in every
guild the bot is in, but changes can take up to an hour to appear) and **per-guild**
(one guild, updates instantly). The bot chooses based on `GUILD_ID` in `.env`:

- `GUILD_ID` blank: syncs globally.
- `GUILD_ID=<id>`: syncs to that one guild, handy for instant iteration while developing.

Gotcha: if you sync globally and *then* set `GUILD_ID`, that guild ends up with **both**
copies and shows every command twice. Blanking `GUILD_ID` again stops the bot re-adding
the guild copy, but the commands already sitting in the guild registry stay until you
wipe them. To clear one guild's scope (global commands are left alone), run this against
the running bot container, which already has `DISCORD_TOKEN` in its environment:

```sh
docker compose exec -T bot python - <GUILD_ID> <<'PY'
import asyncio, os, sys, discord

async def main(guild_id):
    client = discord.Client(intents=discord.Intents.none())
    await client.login(os.environ["DISCORD_TOKEN"])
    app = await client.application_info()
    await client.http.bulk_upsert_guild_commands(app.id, guild_id, [])
    await client.close()
    print(f"cleared guild-scoped commands for {guild_id}")

asyncio.run(main(int(sys.argv[1])))
PY
```

Then leave `GUILD_ID` blank so it stays clean.

## Running the LLM on a GPU host

The `vllm` service needs an NVIDIA GPU and the container toolkit (so Docker can pass the GPU through via the `deploy.resources` reservation in the compose file). Model weights are cached in the `hf-cache` volume, so restarting the container does not re-download them.

If that host is a DGX Spark, note:

- The Spark is aarch64 (GB10), so the vLLM service must use NVIDIA's arm64 build. Check [NGC](https://catalog.ngc.nvidia.com) for the current tag and update `docker-compose.yml` if needed. (The other images are already multi-arch.)
- DGX OS ships with the NVIDIA container toolkit, so the GPU reservation works out of the box.

## CI

Pushes to `main` (and `v*` tags) build a multi-arch image and publish it to GHCR as `ghcr.io/<owner>/<repo>`. Pull requests build without publishing.
