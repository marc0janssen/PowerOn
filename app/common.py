"""Shared utilities for PowerOn services."""
from __future__ import annotations

import configparser
import email
import imaplib
import logging
import shutil
import socket
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from email.header import decode_header
from email.message import Message
from typing import Callable, Generator, Optional, Tuple


CONFIG_DIR = Path("/config")
APP_DIR = Path("/app")
LOG_DIR = Path("/var/log")


class ConfigError(Exception):
    """Raised when a configuration item is missing or invalid."""


@dataclass(frozen=True)
class ConfigOption:
    section: str
    key: str
    description: Optional[str] = None

    def display_name(self) -> str:
        if self.description:
            return self.description
        return f"[{self.section}] {self.key}"


class BasePowerService:
    """Base class that centralises configuration and logging logic."""

    config_filename = "poweron.ini"
    example_filename = "poweron.ini.example"

    def __init__(self, log_filename: str) -> None:
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            level=logging.INFO,
        )
        self.log_path = LOG_DIR / log_filename
        self.config_path = CONFIG_DIR / self.config_filename
        self.example_path = APP_DIR / self.example_filename

        self._ensure_config_exists()
        self.config = self._load_config()

        try:
            self.enabled = self.require_bool(ConfigOption("GENERAL", "ENABLED"))
            self.dry_run = self.require_bool(ConfigOption("GENERAL", "DRY_RUN"))
            self.verbose_logging = self.require_bool(
                ConfigOption("GENERAL", "VERBOSE_LOGGING")
            )
        except ConfigError as error:
            self.exit_with_config_error(error)

        self._pushover_user = None
        self._pushover_app = None

    def _ensure_config_exists(self) -> None:
        if not self.config_path.exists():
            logging.error(
                "Can't open file %s, creating example INI file.",
                self.config_path,
            )
            try:
                shutil.copyfile(self.example_path, CONFIG_DIR / self.example_filename)
            except OSError as exc:
                logging.error("Failed to copy example configuration: %s", exc)
            sys.exit()

    def _load_config(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        try:
            parser.read(self.config_path)
        except (configparser.Error, UnicodeDecodeError) as exc:
            logging.error("Unable to parse configuration file %s: %s", self.config_path, exc)
            sys.exit()
        return parser

    def exit_with_config_error(self, error: ConfigError) -> None:
        logging.error("%s Please check for mistakes. Exiting.", error)
        sys.exit()

    def require(self, option: ConfigOption, *, allow_empty: bool = False) -> str:
        try:
            value = self.config[option.section][option.key]
        except KeyError as exc:
            raise ConfigError(
                f"Missing configuration value for {option.display_name()}"
            ) from exc

        value = value.strip()
        if not value and not allow_empty:
            raise ConfigError(
                f"Empty configuration value for {option.display_name()}"
            )
        return value

    def require_int(self, option: ConfigOption) -> int:
        value = self.require(option)
        try:
            return int(value)
        except ValueError as exc:
            raise ConfigError(
                f"Invalid integer value '{value}' for {option.display_name()}"
            ) from exc

    def require_bool(self, option: ConfigOption) -> bool:
        value = self.require(option)
        normalised = value.upper()
        if normalised not in {"ON", "OFF"}:
            raise ConfigError(
                f"Invalid boolean value '{value}' for {option.display_name()}"
            )
        return normalised == "ON"

    def require_list(self, option: ConfigOption) -> list[str]:
        value = self.require(option)
        return [item.strip() for item in value.split(",") if item.strip()]

    def write_log(self, message: str, *, init: bool = False) -> None:
        mode = "w" if init else "a"
        try:
            with open(self.log_path, mode) as logfile:
                logfile.write(f"{datetime.now()} - {message}")
        except OSError as exc:
            logging.error("Can't write file %s: %s", self.log_path, exc)

    def verbose(self, message: str) -> None:
        if self.verbose_logging:
            logging.info(message)

    @staticmethod
    def is_port_open(host: str, port: int, *, timeout: float = 5.0) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, port)) == 0

    def pushover_user(self, *, factory: Callable[[str], object]) -> object:
        if self._pushover_user is None:
            self._pushover_app = factory(self.pushover_token_api)
            self._pushover_user = self._pushover_app.get_user(self.pushover_user_key)
        return self._pushover_user


class MailPowerService(BasePowerService):
    """Base class that adds e-mail configuration helpers."""

    def __init__(self, log_filename: str) -> None:
        super().__init__(log_filename)
        try:
            self.mail_port = self.require_int(ConfigOption("MAIL", "MAIL_PORT"))
            self.mail_server = self.require(ConfigOption("MAIL", "MAIL_SERVER"))
            self.mail_login = self.require(ConfigOption("MAIL", "MAIL_LOGIN"))
            self.mail_password = self.require(ConfigOption("MAIL", "MAIL_PASSWORD"))
            self.mail_sender = self.require(ConfigOption("MAIL", "MAIL_SENDER"))
        except ConfigError as error:
            self.exit_with_config_error(error)

    def connect_mailbox(self) -> imaplib.IMAP4_SSL:
        mailbox = imaplib.IMAP4_SSL(self.mail_server)
        mailbox.login(self.mail_login, self.mail_password)
        return mailbox

    @staticmethod
    def iter_messages(mailbox: imaplib.IMAP4_SSL) -> Generator[Tuple[str, Message], None, None]:
        status, messages = mailbox.select("INBOX")
        if status != "OK":
            return
        total = int(messages[0])
        for index in range(1, total + 1):
            _, payload = mailbox.fetch(str(index), "(RFC822)")
            for response in payload:
                if isinstance(response, tuple):
                    yield str(index), email.message_from_bytes(response[1])

    @staticmethod
    def decode_header_value(value: str) -> str:
        decoded, encoding = decode_header(value)[0]
        if isinstance(decoded, bytes):
            return decoded.decode(encoding or "utf-8")
        return decoded

