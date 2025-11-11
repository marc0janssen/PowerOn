"""Entry point for extending the shutdown schedule via e-mail."""

from power_manager import PowerManager


def main() -> None:
    manager = PowerManager()
    manager.extend_shutdown_from_mail()


if __name__ == "__main__":
    main()
