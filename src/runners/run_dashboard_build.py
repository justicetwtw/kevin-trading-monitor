"""GitHub Actions entrypoint: build Trading Monitor v2 Mission Control.

Purely reads data_store/, does not call external APIs, needs no secret and does
not send Telegram messages. Output remains public/dashboard/ for the existing
Pages/deploy path.
"""

from loguru import logger

from src.dashboard.build_mission_control import DEFAULT_OUTPUT, build_all


def main() -> None:
    payloads = build_all(DEFAULT_OUTPUT)
    logger.info(
        "mission control build done: "
        + ", ".join(f"{key}" for key in payloads)
        + f" -> {DEFAULT_OUTPUT}"
    )


if __name__ == "__main__":
    main()
