FROM python:3.12-slim

# ffmpeg and opus are for voice playback later, cheap to bake in now
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY scarlett ./scarlett
RUN pip install --no-cache-dir .

RUN useradd --create-home scarlett
USER scarlett

CMD ["python", "-m", "scarlett"]
