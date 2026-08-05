# scarlett

A friendly, growing utility bot for Discord. Right now she handles cross-timezone timestamps and voice-channel music, with more tools on the way. Runs anywhere Docker does, no GPU needed. She can also take on a chatty personality if you want one, but that part is entirely optional.

Features:

- **Timestamp coordination**: spots time phrases in messages ("friday at 7pm") and replies with Discord timestamp markup (`<t:unix:F>` and `<t:unix:R>`), so everyone sees the time in their own zone. Parsing is deterministic, so it needs no LLM. Users register a timezone with `/tz` (autocompleted), or say the zone in the message itself ("22:00 CET"), which works for everyone reading whether or not the author has registered one. `/time <phrase>` converts on demand, with none of the quiet-hours limits the listener applies.
- **Self-assignable roles**: buttons on a message that hand out roles when clicked, so members pick their own pronouns, game pings or colours without anyone with Manage Roles being awake. Panels are built with `/roles` and come in three flavours: pick as many as you like, pick exactly one, or click-to-opt-in with no take-backs. See [Reaction roles](#reaction-roles).
- **Music**: plays audio in voice channels via Lavalink. `/play` takes a link or a search term; `/skip`, `/stop`, `/pause`, `/volume`, `/shuffle`, `/loop`, `/queue` and `/nowplaying` round it out. She manages a queue and leaves on her own once the channel empties or nothing has played for a while.
- **Personality chat** (optional, off by default): if you want it, she can chat back in her own voice. This is the one feature that needs an extra service, so it lives in its own section at the end; everything above works without it.

Plus `/ping` to check she's alive and `/help` to list everything. More tools are on the way, so treat the list above as what she does today rather than the ceiling.

## Architecture

Two CPU-only containers, defined in `docker-compose.yml`, cover everything the utility features need. A third is only pulled in if you opt into the personality:

| Service  | What it does |
|----------|--------------|
| bot      | The discord.py bot itself. CPU only. |
| lavalink | Audio server the bot controls via wavelink for music playback. CPU only. |
| vllm     | Optional, off by default. Serves the LLM behind the personality; needs a GPU. See [Optional: the personality](#optional-the-personality). |

## Setup

1. Create an application at https://discord.com/developers/applications, add a bot, enable the **message content** intent, and grab the token.
2. Invite it to your server with the `bot` and `applications.commands` scopes.
3. Configure and start:

```sh
cp .env.example .env   # fill in DISCORD_TOKEN, and GUILD_ID for instant command sync
docker compose up -d --build
```

That is the whole utility bot up and running. Giving her a personality is a separate, optional step covered at the end.

## Reaction roles

Despite the name everyone uses for them, these are buttons rather than
reactions. Reactions were the only interactive surface bots had before
2021; buttons give real labels, a private reply to whoever clicked, and
no need for the message-reaction intent.

Scarlett never records who holds which role. Discord already knows, and
is the only authority on it, so nothing here can drift out of step with
the role list and nobody loses a role if the database is thrown away.

### Setting up the server

These are the once-off Discord-side jobs, and between them they account
for essentially every way a role panel fails.

1. **Put Scarlett's role above the roles she hands out.** Server
   Settings > Roles, drag her up. A bot can only manage roles strictly
   below its own highest role. This is the big one.
2. **Give her Manage Roles**, server-wide. It is not a per-channel
   permission.
3. **Check your 2FA setting.** If Server Settings > Safety Setup requires
   2FA for moderator actions, the account that owns the bot application
   needs 2FA switched on or every role change fails.
4. **Make a `#roles` channel.** Deny `@everyone` Send Messages so it
   stays nothing but panels, and allow Scarlett View Channel, Send
   Messages and Embed Links. She does not need Manage Messages.
5. **Create the roles.** If a role only exists to unlock a channel, give
   it no permissions at all and set the visibility on the channel
   instead: deny `@everyone` View Channel there, allow the role. The
   role then carries no power of its own.

Roles Discord will never let anyone assign by hand are refused up front
rather than at click time: `@everyone`, and any role managed by an
integration such as another bot or Nitro boosting.

### Building a panel

```
/roles create name:pronouns channel:#roles mode:multi title:"Pronouns"
/roles add    panel:pronouns role:@they/them label:"they/them" emoji:🦊
/roles add    panel:pronouns role:@she/her   label:"she/her"
```

Every edit rewrites the message straight away, so the panel takes shape
as you build it. Panels are addressed by the short name you gave them,
which autocompletes.

| Mode | Behaviour | Good for |
|------|-----------|----------|
| `multi` | Each button toggles its own role | Pronouns, game pings, notification opt-ins |
| `single` | Taking one role drops the others on that panel | Colours, region, age bracket |
| `sticky` | Click to gain the role, never to lose it | Rules agreement, verification |

The rest of the group: `/roles remove` takes a role off a panel,
`/roles order` moves a button, `/roles list` shows what exists,
`/roles repost` puts a panel back if its message got deleted, and
`/roles delete` removes the panel entirely. None of them take roles away
from anyone who already has one. The whole group is hidden from members
without Manage Roles, because Discord gates it.

One message holds at most 25 buttons, five to a row. Past that, make a
second panel.

### Moving over from Dyno

Nothing is lost in the switch, because neither bot ever owned the role
membership. Build the new panels in a staff-only channel and click
through them, post them in `#roles` alongside Dyno's, and once people
have moved across, delete Dyno's messages and take away its Manage
Roles permission.

Dyno's existing panels cannot be adopted in place. Only the bot that
posted a message can put buttons on it, so the panels get rebuilt.

## Music

Playback runs through the `lavalink` container using the [youtube-source](https://github.com/lavalink-devs/youtube-source) plugin (Lavalink 4 dropped its built-in YouTube support). Two things need doing once on a fresh machine:

- **Plugin volume ownership.** Lavalink runs as uid 322, but Docker creates the `lavalink-plugins` volume as root, so the first plugin download fails with a permission error until you fix it:

  ```sh
  docker run --rm -v scarlett_ai_lavalink-plugins:/p alpine chown -R 322:322 /p
  ```

- **YouTube OAuth**, which is the reliable cure for "sign in to confirm you're not a bot" errors. Start Lavalink with `YOUTUBE_OAUTH_REFRESH_TOKEN` blank in `.env` and watch its logs (`docker compose logs -f lavalink`): it prints a device-link URL and code. Authorise with a **burner** Google account (never your main one), then copy the refresh token it logs into `YOUTUBE_OAUTH_REFRESH_TOKEN` in `.env` and restart. The token is injected into `lavalink/application.yml` via the compose file, so it never lives in a tracked file.

### Sources

Beyond YouTube, the sources enabled in `lavalink/application.yml` are **SoundCloud**, **Bandcamp**, **Twitch**, **Vimeo**, and **HTTP** (direct audio URLs and stream/radio links). Paste a link from any of them into `/play`; plain-text searches go to YouTube. Lavalink also ships **Niconico** and **local files**, both left off. To turn one on, flip it to `true` under `lavalink.server.sources` and restart the `lavalink` container.

More services (Spotify, Apple Music, Deezer, Tidal, Yandex, ...) can be added with the [LavaSrc](https://github.com/topi314/LavaSrc) plugin, wired in the same way as the youtube-source plugin. Note that Spotify, Apple Music and Tidal are metadata-only "mirror" sources: LavaSrc reads the track details from the link but streams the actual audio from YouTube.

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

## Optional: the personality

Everything above is the whole bot. This section is only for the extra, off-by-default feature where she chats back in her own voice, and it is the only part that pulls in an LLM. Skip it entirely and nothing else changes.

When switched on, she replies when mentioned or replied to and occasionally interjects on her own, only in whitelisted guilds (`CHAT_GUILD_IDS`) and with per-user rate limiting. Her character lives in `personality.md`, reread on every reply, so you can edit it live without a rebuild.

She talks to any OpenAI-compatible endpoint (the bundled `vllm` container, a separate machine, Ollama, or a hosted API), so the model can live wherever you have the hardware for it. Set `LLM_ENABLED` and `LLM_BASE_URL` in `.env`:

| Mode | `LLM_ENABLED` | `LLM_BASE_URL` | Start with |
|------|---------------|----------------|-----------|
| Off (default) | `false` | ignored | `docker compose up -d` |
| Query a remote host | `true` | `http://<host>:8000/v1` | `docker compose up -d` (bot side) |
| Bot and model together | `true` | `http://vllm:8000/v1` (default) | `docker compose --profile llm up -d` |

For the remote mode, run just the model on the other machine with `docker compose --profile llm up -d vllm`.

**Security**: vLLM has no auth by default and ignores `LLM_API_KEY` unless it is started with `--api-key`. Publishing port `8000` to anything wider than a trusted LAN/VPN gives anyone free use of the machine. Keep the two machines on the same LAN (or a Tailscale/WireGuard network), or set a secret in `LLM_API_KEY` and add `--api-key <secret>` to the `vllm serve` command.

**Running the model locally**: the bundled `vllm` service needs an NVIDIA GPU and the container toolkit (Docker passes the GPU through via the `deploy.resources` reservation in the compose file). Weights are cached in the `hf-cache` volume, so a restart does not re-download them. On a DGX Spark specifically: it is aarch64 (GB10), so `vllm` must use NVIDIA's arm64 build (check [NGC](https://catalog.ngc.nvidia.com) for the current tag and update `docker-compose.yml` if needed; the other images are already multi-arch), and DGX OS ships the container toolkit so the GPU reservation works out of the box.

## Running her locally

Docker is the deployment story, but rebuilding an image to try a code
change is a slow way to work. For development, run the bot straight out
of a venv:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

set -a && . ./.env && set +a           # config comes from the environment
export DB_PATH=./data/scarlett.db      # the default path lives inside the image
export MUSIC_ENABLED=false LLM_ENABLED=false
.venv/bin/python -m scarlett
```

The `set -a` line is the part that catches people out. Under Docker,
compose reads `.env` and injects it; run directly, nothing does, and the
bot only ever reads the environment.

Use a second bot application for this, with its own token and `GUILD_ID`
pointing at a test server, so a half-finished change is never loose in a
real one.

`MUSIC_ENABLED=false` is the line that makes the logs readable. Lavalink
is not running outside compose, and wavelink retries an unreachable node
forever, so leaving it on buries everything you are actually trying to
read under reconnect warnings. Off, the music cog is never loaded and
the node is never created. `LLM_ENABLED=false` does the same for the
chat cog. Roles, timestamps and `/help` need neither.

Tests need nothing running at all:

```sh
.venv/bin/python -m pytest
```

## CI

Pushes to `main` (and `v*` tags) build a multi-arch image and publish it to GHCR as `ghcr.io/<owner>/<repo>`. Pull requests build without publishing.
