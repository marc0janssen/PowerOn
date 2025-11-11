"""Entry point for powering on configured extra nodes."""

from power_manager import PowerManager


def main() -> None:
    manager = PowerManager()
    manager.power_on_extra_nodes()


if __name__ == "__main__":
    main()
