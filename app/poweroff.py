"""Entry point for powering off the primary node."""

from power_manager import PowerManager


def main() -> None:
    manager = PowerManager()
    manager.power_off()


if __name__ == "__main__":
    main()
