FROM python:3.12-slim

# ffmpeg and opus are for voice playback later, cheap to bake in now
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY personality.md ./
COPY scarlett ./scarlett
RUN pip install --no-cache-dir .

# /app/data holds the sqlite db, mounted as a volume in compose
RUN useradd --create-home scarlett \
    && mkdir /app/data \
    && chown scarlett:scarlett /app/data
USER scarlett

# The commit this image was built from, for the version she reports at
# runtime. Declared here rather than higher up because a build arg
# invalidates every layer below it, and the sha changes on every commit
# while the dependency install above it almost never does.
ARG GIT_SHA=""
ENV GIT_SHA=$GIT_SHA

# healthy == connected to the gateway. the Health cog stamps a heartbeat file
# while the bot is ready; this fails once it goes stale. start-period covers
# login and the first gateway connect before failures start counting
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "-m", "scarlett.health"]

CMD ["python", "-m", "scarlett"]
