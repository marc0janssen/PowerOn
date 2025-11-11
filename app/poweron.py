"""Entry point for powering on the primary node."""

from power_manager import PowerManager


def main() -> None:
    manager = PowerManager()
    manager.power_on()


if __name__ == "__main__":
    main()
