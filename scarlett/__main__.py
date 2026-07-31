import logging

from .bot import Scarlett
from .config import Settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()

    # LOG_LEVEL applies to our own loggers only. discord.py at DEBUG prints
    # every gateway frame, which buries the thing you turned it on to see,
    # so the root stays at INFO
    level = logging.getLevelNamesMapping().get(settings.log_level.upper())
    if level is None:
        logging.warning(
            "LOG_LEVEL=%r isn't a level name, staying at INFO", settings.log_level
        )
    else:
        logging.getLogger("scarlett").setLevel(level)

    bot = Scarlett(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
