"""GitHub Actions entrypoint: build Mission Control and decision-grade overlay.

The build reads public-safe state only, calls no external APIs, needs no secret and
sends no Telegram message. Exact positions/account values remain excluded.
"""

from loguru import logger

from src.dashboard.apply_decision_quality import apply_decision_quality
from src.dashboard.build_decision_layer import build_decision_layer
from src.dashboard.build_mission_control import DEFAULT_OUTPUT, build_all


def main() -> None:
    payloads = build_all(DEFAULT_OUTPUT)
    decision = build_decision_layer(DEFAULT_OUTPUT)
    decision = apply_decision_quality(DEFAULT_OUTPUT, decision)
    payloads["decision_engine"] = decision
    logger.info(
        "mission control build done: "
        + ", ".join(f"{key}" for key in payloads)
        + f" -> {DEFAULT_OUTPUT}"
    )


if __name__ == "__main__":
    main()
