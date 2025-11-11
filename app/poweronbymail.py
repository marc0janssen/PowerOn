"""Entry point for handling power-on requests via e-mail."""

from power_manager import PowerManager


def main() -> None:
    manager = PowerManager()
    manager.power_on_from_mail()


if __name__ == "__main__":
    main()
