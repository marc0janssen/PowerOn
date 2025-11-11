"""Entry point for handling power-off requests via e-mail."""

from power_manager import PowerManager


def main() -> None:
    manager = PowerManager()
    manager.power_off_from_mail()


if __name__ == "__main__":
    main()
