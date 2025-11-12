"""Unified power management utilities.

This module consolidates the logic that used to live in the stand-alone
scripts for powering hosts on and off.  A single :class:`PowerManager`
instance is responsible for loading the configuration, handling logging,
notifying PushOver, updating crontabs and processing incoming mails.

The individual entry-point scripts (``poweron.py``, ``poweroff.py`` …)
delegate their work to the shared manager which keeps the behaviour
identical while drastically reducing duplicated code.
"""

from __future__ import annotations

import configparser
import imaplib
import email
import json
import logging
import re
import shutil
import smtplib
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from email.header import decode_header
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from chump import Application
from socket import gaierror
from wakeonlan import send_magic_packet


CONFIG_DIR = Path("/config")
APP_DIR = Path("/app")
LOG_DIR = Path("/var/log")
CONFIG_FILE = CONFIG_DIR / "poweron.ini"
EXAMPLE_CONFIG_FILE = APP_DIR / "poweron.ini.example"
STATE_FILE = CONFIG_DIR / "poweron.json"
CRON_FILE = Path("/etc/crontabs/root")


class ConfigurationError(RuntimeError):
    """Raised when the configuration file misses required information."""


def _ensure_example_config(config_path: Path, example_path: Path) -> None:
    """Ensure the configuration file exists.

    If the configuration file is missing we copy the example file so the
    user gets immediate feedback while keeping behaviour identical to the
    previous scripts.
    """

    if config_path.exists():
        return

    logging.error(
        "Can't open file %s, creating example INI file.", config_path
    )
    shutil.copyfile(example_path, config_path.with_name(example_path.name))
    sys.exit(1)


def _as_bool(value: str) -> bool:
    return value.strip().upper() == "ON"


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class GeneralSettings:
    enabled: bool
    dry_run: bool
    verbose_logging: bool


@dataclass
class NodeSettings:
    name: str
    mac: str
    ip: str
    port: int
    ssh_port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None


@dataclass
class MailSettings:
    server: str
    port: int
    login: str
    password: str
    sender: str


@dataclass
class PowerOnSettings:
    keyword: str
    allowed_senders: Sequence[str]
    allowed_credits: Sequence[str]


@dataclass
class PowerOffSettings:
    keyword: Optional[str]
    allowed_senders: Optional[Sequence[str]]
    command: str


@dataclass
class ExtendSettings:
    default_hour: str
    default_minutes: str
    max_hour: str
    keyword: str
    allowed_senders: Sequence[str]
    extend_hours: Optional[str] = None


@dataclass
class PushOverSettings:
    user_key: str
    token_api: str
    sound: str


@dataclass
class ExtraNode:
    name: str
    ip: str
    mac: str
    ssh_port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None


class PowerManager:
    """High level façade that exposes all power-management operations."""

    def __init__(
        self,
        config_path: Path = CONFIG_FILE,
        example_config_path: Path = EXAMPLE_CONFIG_FILE,
        log_directory: Path = LOG_DIR,
        state_path: Path = STATE_FILE,
        cron_path: Path = CRON_FILE,
    ) -> None:
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            level=logging.INFO,
        )
        self.logger = logging.getLogger("PowerManager")

        self.config_path = Path(config_path)
        self.example_config_path = Path(example_config_path)
        self.log_directory = Path(log_directory)
        self.state_path = Path(state_path)
        self.cron_path = Path(cron_path)

        _ensure_example_config(self.config_path, self.example_config_path)

        parser = configparser.ConfigParser()
        parser.read(self.config_path)
        self._parser = parser

        self.general = GeneralSettings(
            enabled=_as_bool(self._require("GENERAL", "ENABLED")),
            dry_run=_as_bool(self._require("GENERAL", "DRY_RUN")),
            verbose_logging=_as_bool(
                self._require("GENERAL", "VERBOSE_LOGGING")
            ),
        )

        self.node = NodeSettings(
            name=self._require("NODE", "NODE_NAME"),
            mac=self._require("NODE", "NODE_MAC").replace(":", "-").lower(),
            ip=self._require("NODE", "NODE_IP"),
            port=self._require_int("NODE", "NODE_PORT"),
            ssh_port=self._optional_int("NODE", "NODE_SSHPORT"),
            user=self._optional("NODE", "NODE_USER"),
            password=self._optional("NODE", "NODE_PWD"),
        )

        self.mail = None
        if parser.has_section("MAIL"):
            self.mail = MailSettings(
                server=self._require("MAIL", "MAIL_SERVER"),
                port=self._require_int("MAIL", "MAIL_PORT"),
                login=self._require("MAIL", "MAIL_LOGIN"),
                password=self._require("MAIL", "MAIL_PASSWORD"),
                sender=self._require("MAIL", "MAIL_SENDER"),
            )

        self.power_on_settings = None
        if parser.has_section("POWERON"):
            self.power_on_settings = PowerOnSettings(
                keyword=self._require("POWERON", "KEYWORD"),
                allowed_senders=_split_csv(
                    self._require("POWERON", "ALLOWED_SENDERS")
                ),
                allowed_credits=_split_csv(
                    self._require("POWERON", "ALLOWED_CREDITS")
                ),
            )

        self.power_off_settings = None
        if parser.has_section("POWEROFF"):
            keyword = self._optional("POWEROFF", "KEYWORD")
            allowed = (
                _split_csv(self._require("POWEROFF", "ALLOWED_SENDERS"))
                if parser.has_option("POWEROFF", "ALLOWED_SENDERS")
                else None
            )
            self.power_off_settings = PowerOffSettings(
                keyword=keyword,
                allowed_senders=allowed,
                command=self._require("POWEROFF", "POWEROFFCOMMAND"),
            )

        self.extend_settings = None
        if parser.has_section("EXTENDTIME"):
            self.extend_settings = ExtendSettings(
                default_hour=self._require("EXTENDTIME", "DEFAULT_HOUR"),
                default_minutes=self._require(
                    "EXTENDTIME", "DEFAULT_MINUTES"
                ),
                max_hour=self._require(
                    "EXTENDTIME", "MAX_SHUTDOWN_HOUR_TIME"
                ),
                keyword=self._require("EXTENDTIME", "KEYWORD"),
                allowed_senders=_split_csv(
                    self._require("EXTENDTIME", "ALLOWED_SENDERS")
                ),
                extend_hours=self._optional(
                    "EXTENDTIME", "EXTEND_TIME_IN_HOURS"
                ),
            )

        self.pushover = PushOverSettings(
            user_key=self._require("PUSHOVER", "USER_KEY"),
            token_api=self._require("PUSHOVER", "TOKEN_API"),
            sound=self._require("PUSHOVER", "SOUND"),
        )

        self.extra_nodes: List[ExtraNode] = []
        if parser.has_section("EXTRANODES"):
            names = _split_csv(self._require("EXTRANODES", "NODE_NAME"))
            ips = _split_csv(self._require("EXTRANODES", "NODE_IP"))
            macs = _split_csv(
                self._require("EXTRANODES", "NODE_MAC_ADDRESS")
            )
            ssh_ports = _split_csv(
                parser.get("EXTRANODES", "NODE_SSHPORT", fallback="")
            )
            users = _split_csv(
                parser.get("EXTRANODES", "NODE_USER", fallback="")
            )
            passwords = _split_csv(
                parser.get("EXTRANODES", "NODE_PWD", fallback="")
            )

            for index, name in enumerate(names):
                self.extra_nodes.append(
                    ExtraNode(
                        name=name,
                        ip=ips[index] if index < len(ips) else "",
                        mac=macs[index] if index < len(macs) else "",
                        ssh_port=int(ssh_ports[index])
                        if index < len(ssh_ports) and ssh_ports[index]
                        else None,
                        user=users[index] if index < len(users) else None,
                        password=(
                            passwords[index]
                            if index < len(passwords) and passwords[index]
                            else None
                        ),
                    )
                )

        self._pushover_user = None

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _require(self, section: str, option: str) -> str:
        if not self._parser.has_option(section, option):
            raise ConfigurationError(
                f"Missing option '{option}' in section '{section}'."
            )
        return self._parser.get(section, option)

    def _require_int(self, section: str, option: str) -> int:
        try:
            return self._parser.getint(section, option)
        except ValueError as exc:  # pragma: no cover - config errors
            raise ConfigurationError(
                f"Invalid integer for '{option}' in section '{section}'."
            ) from exc

    def _optional(self, section: str, option: str) -> Optional[str]:
        if not self._parser.has_option(section, option):
            return None
        value = self._parser.get(section, option)
        return value if value != "" else None

    def _optional_int(self, section: str, option: str) -> Optional[int]:
        value = self._optional(section, option)
        return int(value) if value else None

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _log_path(self, filename: str) -> Path:
        return self.log_directory / filename

    def _write_log(
        self,
        filename: str,
        message: str,
        init: bool = False,
    ) -> None:
        try:
            mode = "w" if init else "a"
            with self._log_path(filename).open(mode) as handle:
                handle.write(f"{datetime.now()} - {message}")
        except IOError:
            self.logger.error(
                "Can't write file %s.", self._log_path(filename)
            )

    def _pushover_user_or_none(self):
        if self._pushover_user is None:
            app = Application(self.pushover.token_api)
            self._pushover_user = app.get_user(self.pushover.user_key)
        return self._pushover_user

    def _send_pushover(self, message: str) -> None:
        user = self._pushover_user_or_none()
        if user is not None:
            user.send_message(message=message, sound=self.pushover.sound)

    def _port_open(self, host: str, port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            return sock.connect_ex((host, port)) == 0
        finally:
            sock.close()

    def _run_remote_command(
        self, user: str, password: str, host: str, port: int, command: str
    ) -> subprocess.CompletedProcess[str]:
        escaped_password = re.escape(password)
        return subprocess.run(
            [
                "sshpass",
                "-p",
                password,
                "ssh",
                "-p",
                str(port),
                "-t",
                f"{user}@{host}",
                (
                    f"echo {escaped_password}|sudo -S bash -c "
                    f"\"{command}\""
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def _update_cron_default_schedule(self) -> None:
        if not self.extend_settings:
            return

        try:
            with self.cron_path.open("r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except FileNotFoundError:
            self.logger.error("File not found - %s.", self.cron_path)
            return
        except IOError:
            self.logger.error("Error reading the file %s.", self.cron_path)
            return

        for index, line in enumerate(lines):
            if "poweroff.py" not in line:
                continue
            parts = line.split()
            parts[1] = (
                f"{self.extend_settings.default_hour},"
                f"{self.extend_settings.max_hour}"
            )
            parts[0] = self.extend_settings.default_minutes
            lines[index] = " ".join(parts)
            break

        try:
            with self.cron_path.open("w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
        except IOError:
            self.logger.error(
                "Error writing the file %s.", self.cron_path
            )

    def _extend_cron_schedule(self, extend_hours: int) -> Optional[str]:
        if not self.extend_settings:
            return None

        try:
            with self.cron_path.open("r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except FileNotFoundError:
            self.logger.error("File not found - %s.", self.cron_path)
            return None
        except IOError:
            self.logger.error("Error reading the file %s.", self.cron_path)
            return None

        shutdown_time = None

        for index, line in enumerate(lines):
            if "poweroff.py" not in line:
                continue
            parts = line.split()
            hour_field = parts[1]
            hours = hour_field.split(",")
            current_hour = int(hours[0])
            new_hour = (current_hour + extend_hours) % 24

            max_hour_value = (
                24
                if self.extend_settings.max_hour in {"0", "00"}
                else int(self.extend_settings.max_hour)
            )

            if new_hour >= max_hour_value:
                parts[1] = self.extend_settings.max_hour
                shutdown_time = (
                    f"{self.extend_settings.max_hour.zfill(2)}:"
                    f"{parts[0].zfill(2)}"
                )
            else:
                parts[1] = (
                    f"{str(new_hour).zfill(2)},"
                    f"{self.extend_settings.max_hour}"
                )
                shutdown_time = (
                    f"{str(new_hour).zfill(2)}:"
                    f"{parts[0].zfill(2)}"
                )

            lines[index] = " ".join(parts)
            break

        try:
            with self.cron_path.open("w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
        except IOError:
            self.logger.error(
                "Error writing the file %s.", self.cron_path
            )

        return shutdown_time

    def _send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
    ) -> None:
        if not self.mail:
            return

        message = MIMEMultipart()
        message["From"] = self.mail.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.attach(MIMEText(body, _subtype="plain", _charset="UTF-8"))

        try:
            session = smtplib.SMTP(self.mail.server, self.mail.port)
            session.starttls()
            session.login(self.mail.login, self.mail.password)
            data = message.as_string()
            session.sendmail(self.mail.sender, [recipient], data)
            session.quit()
            if self.general.verbose_logging:
                self.logger.info("Mail sent to %s.", recipient)
        except (gaierror, ConnectionRefusedError):
            self.logger.error(
                "Failed to connect to the mail server. "
                "Bad connection settings?"
            )
        except smtplib.SMTPServerDisconnected:
            self.logger.error("Mail server disconnected unexpectedly.")
        except smtplib.SMTPException:
            self.logger.error("Mail server error occurred.")

    # ------------------------------------------------------------------
    # High level operations
    # ------------------------------------------------------------------
    def power_on(self) -> None:
        log_name = "poweron.log"

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET AWAKE ****")
            self._write_log(log_name, "PowerOn - Dry run.\n")

        if not self.general.enabled:
            if self.general.verbose_logging:
                self.logger.info("PowerOn - Service is disabled by cron")
            msg = "PowerOn - Service is disabled by cron\n"
            self._write_log(log_name, msg)
            return

        if self._port_open(self.node.ip, self.node.port):
            self.logger.info("PowerOn - Nodes already running by cron")
            msg = "PowerOn - Nodes already running by cron\n"
            self._write_log(log_name, msg)
            return

        if self.general.dry_run:
            return

        try:
            send_magic_packet(self.node.mac)
        except ValueError:
            self.logger.error("Invalid MAC-address in INI.")
            sys.exit(1)

        self.logger.info("PowerOn - Sending WOL command by cron")
        msg = "PowerOn - Sending WOL command by cron\n"
        self._write_log(log_name, msg)
        self._send_pushover("PowerOn - WOL command sent by cron")

    def power_off(self) -> None:
        log_name = "poweron.log"

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            self._write_log(log_name, "PowerOff - Dry run.\n")

        if not self.general.enabled:
            if self.general.verbose_logging:
                self.logger.info("PowerOff - Service is disabled by cron")
            msg = "PowerOff - Service is disabled by cron\n"
            self._write_log(log_name, msg)
            return

        if not self._port_open(self.node.ip, self.node.port):
            self.logger.info("PowerOff - Node already down by cron")
            msg = "PowerOff - Node already down by cron\n"
            self._write_log(log_name, msg)
            return

        if self.general.dry_run:
            return

        if not self.power_off_settings:
            self.logger.error("Power off command not configured.")
            return

        if not all(
            [
                self.node.user,
                self.node.password,
                self.node.ssh_port,
            ]
        ):
            self.logger.error("Missing SSH credentials for power off action.")
            return

        result = self._run_remote_command(
            user=self.node.user,
            password=self.node.password,
            host=self.node.ip,
            port=self.node.ssh_port,
            command=self.power_off_settings.command
            if self.power_off_settings
            else "",
        )
        if result.stdout:
            self.logger.info(result.stdout)

        self.logger.info("PowerOff - Sending SLEEP command by cron")
        msg = "PowerOff - Sending SLEEP command by cron\n"
        self._write_log(log_name, msg)
        self._send_pushover("PowerOff - SLEEP command sent by cron")
        self._update_cron_default_schedule()

    # ---- Mail helpers -------------------------------------------------
    def _fetch_mail(self) -> Iterable[Message]:
        if not self.mail:
            return []

        imap = imaplib.IMAP4_SSL(self.mail.server)
        imap.login(self.mail.login, self.mail.password)
        _, messages = imap.select("INBOX")
        message_count = int(messages[0])
        for index in range(1, message_count + 1):
            _, data = imap.fetch(str(index), "(RFC822)")
            for response in data:
                if isinstance(response, tuple):
                    yield email.message_from_bytes(response[1])
        imap.logout()

    def _decode_subject(self, message: Message) -> str:
        subject, encoding = decode_header(message["Subject"])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8")
        return subject

    def _extract_sender(self, message: Message) -> Optional[str]:
        header = message.get("From")
        if not header:
            return None
        decoded, encoding = decode_header(header)[-1]
        if isinstance(decoded, bytes):
            sender_raw = decoded.decode(encoding or "utf-8")
        else:
            sender_raw = decoded
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender_raw)
        return match.group(0) if match else None

    # ------------------------------------------------------------------
    def power_off_from_mail(self) -> None:
        if not (self.power_off_settings and self.mail):
            self.logger.error("Mail or power off configuration missing.")
            return

        log_name = "poweroffbymail.log"

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            self._write_log(log_name, "PowerOff - Dry run.\n")

        for message in self._fetch_mail():
            subject = self._decode_subject(message)
            sender = self._extract_sender(message)
            if sender is None:
                continue

            if not self.power_off_settings.keyword:
                continue

            if subject.lower() != self.power_off_settings.keyword.lower():
                continue

            if self.general.verbose_logging:
                self.logger.info(
                    "PowerOff - Found matching subject from %s",
                    sender,
                )
            self._write_log(
                log_name,
                f"PowerOff - Found matching subject from {sender}\n",
            )

            if (
                self.power_off_settings.allowed_senders
                and sender
                not in self.power_off_settings.allowed_senders
            ):
                continue

            self._handle_power_off_request(sender, log_name)

    def _handle_power_off_request(self, sender: str, log_name: str) -> None:
        if not self.general.enabled:
            if self.general.verbose_logging:
                self.logger.info(
                    "PowerOff - Service is disabled by %s",
                    sender,
                )
            self._write_log(
                log_name,
                f"PowerOff - Service is disabled by {sender}\n",
            )
            self._send_email(
                recipient=sender,
                subject=f"PowerOff - {self.node.name}",
                body=(
                    "Hi,\n\n Service staat uit, je hoeft even geen commando's"
                    " te sturen.\n\nFijne dag!\n\n"
                ),
            )
            return

        is_online = self._port_open(self.node.ip, self.node.port)
        if is_online and not self.general.dry_run:
            if not self.power_off_settings:
                self.logger.error("Power off command not configured.")
                return
            if not all(
                [
                    self.node.user,
                    self.node.password,
                    self.node.ssh_port,
                ]
            ):
                self.logger.error("Missing SSH credentials for power off.")
                return
            result = self._run_remote_command(
                user=self.node.user,
                password=self.node.password,
                host=self.node.ip,
                port=self.node.ssh_port,
                command=self.power_off_settings.command
                if self.power_off_settings
                else "",
            )
            if result.stdout:
                self.logger.info(result.stdout)
            self._update_cron_default_schedule()
            self.logger.info(
                "PowerOff - Sending SLEEP command by %s", sender
            )
            self._write_log(
                log_name,
                f"PowerOff - Sending SLEEP command by {sender}\n",
            )
            self._send_pushover(
                f"PowerOffByEmail - SLEEP command sent by {sender}"
            )
        else:
            self.logger.info(
                "PowerOff - Nodes not running by %s", sender
            )
            self._write_log(
                log_name,
                f"PowerOff - Nodes not running by {sender}\n",
            )

        subject = f"PowerOff - {self.node.name}"
        if not self.general.enabled:
            body = (
                "Hi,\n\n Service staat uit, je hoeft even geen commando's"
                " te sturen.\n\nFijne dag!\n\n"
            )
        elif is_online:
            body = (
                f"Hi,\n\n {self.node.name} wordt uitgezet, even geduld."
                "\n\nFijne dag!\n\n"
            )
        else:
            body = (
                f"Hi,\n\n {self.node.name} is al uit, je hoeft het 'power off'"
                " commando niet meer te sturen.\n\nFijne dag!\n\n"
            )
        self._send_email(sender, subject, body)

    # ------------------------------------------------------------------
    def power_on_from_mail(self) -> None:
        if not (self.power_on_settings and self.mail):
            self.logger.error("Mail or power on configuration missing.")
            return

        log_name = "poweronbymail.log"

        # credits = self._load_credits()

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET AWAKE ****")
            self._write_log(log_name, "PowerOn - Dry run.\n")

        for message in self._fetch_mail():
            subject = self._decode_subject(message)
            sender = self._extract_sender(message)
            if sender is None:
                self.logger.info("geen sender gevonden")
                continue

            if subject.lower() != self.power_on_settings.keyword.lower():
                self.logger.info("geen juiste subject gevonden")
                continue

            if sender not in self.power_on_settings.allowed_senders:
                self.logger.info("sender niet toegestaan: %s", sender)
                continue

            # remaining = int(credits.get(sender, "0"))
            # if remaining <= 0:
            #     self.logger.info(
            #         "PowerOn - No remaining credits for %s", sender
            #     )
            #     continue

            if self.general.verbose_logging:
                self.logger.info(
                    "PowerOn - Found matching subject from %s",
                    sender,
                )
            self._write_log(
                log_name,
                f"PowerOn - Found matching subject from {sender}\n",
            )

            # if self._handle_power_on_request(sender, log_name):
            #    credits[sender] = str(remaining - 1)
            #    self._save_credits(credits)

    def _handle_power_on_request(self, sender: str, log_name: str) -> bool:
        if not self.general.enabled:
            if self.general.verbose_logging:
                self.logger.info(
                    "PowerOn - Service is disabled by %s",
                    sender,
                )
            self._write_log(
                log_name,
                f"PowerOn - Service is disabled by {sender}\n",
            )
            self._send_email(
                recipient=sender,
                subject=f"PowerOn - {self.node.name}",
                body=(
                    "Hi,\n\n Service staat uit, je hoeft even geen commando's"
                    " te sturen.\n\nFijne dag!\n\n"
                ),
            )
            return False

        is_online = self._port_open(self.node.ip, self.node.port)

        action_taken = False
        if not is_online and not self.general.dry_run:
            try:
                send_magic_packet(self.node.mac)
            except ValueError:
                self.logger.error("Invalid MAC-address in INI.")
                return False
            self.logger.info(
                "PowerOn - Sending WOL command by %s",
                sender,
            )
            self._write_log(
                log_name,
                f"PowerOn - Sending WOL command by {sender}\n",
            )
            self._send_pushover(
                f"PowerOnByEmail - WOL command sent by {sender}"
            )
            action_taken = True
        else:
            self.logger.info(
                "PowerOn - Nodes already running by %s", sender
            )
            self._write_log(
                log_name,
                f"PowerOn - Nodes already running by {sender}\n",
            )

        subject = f"PowerOn - {self.node.name}"
        if not self.general.enabled:
            body = (
                "Hi,\n\n Service staat uit, je hoeft even geen commando's"
                " te sturen.\n\nFijne dag!\n\n"
            )
        elif is_online:
            body = (
                f"Hi,\n\n {self.node.name} is al aan."
                "\n\nFijne dag!\n\n"
            )
        else:
            body = (
                f"Hi,\n\n {self.node.name} wordt aangezet, even geduld."
                "\n\nFijne dag!\n\n"
            )
        self._send_email(sender, subject, body)
        return action_taken and not self.general.dry_run

    # ------------------------------------------------------------------
    def extend_shutdown_from_mail(self) -> None:
        if not (self.extend_settings and self.mail):
            self.logger.error("Extend time configuration missing.")
            return

        log_name = "poweronbymail.log"

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            self._write_log(log_name, "PowerOff - Dry run.\n")

        for message in self._fetch_mail():
            subject = self._decode_subject(message)
            sender = self._extract_sender(message)
            if sender is None:
                continue

            if subject.lower() != self.extend_settings.keyword.lower():
                continue

            if sender not in self.extend_settings.allowed_senders:
                continue

            extend_hours = int(self.extend_settings.extend_hours or 0)
            shutdown_time = self._extend_cron_schedule(extend_hours)

            if shutdown_time:
                body = (
                    "Hi,\n\n Bedankt voor je mailtje. "
                    f"De server blijft aan tot {shutdown_time}."
                    "\n\nFijne dag!\n\n"
                )
            else:
                body = (
                    "Hi,\n\n Helaas kon ik de geplande shutdown niet "
                    "aanpassen.\n\nFijne dag!\n\n"
                )
            self._send_email(sender, f"PowerOn - {self.node.name}", body)

    # ------------------------------------------------------------------
    def power_on_extra_nodes(self) -> None:
        if not self.extra_nodes:
            self.logger.error("No extra nodes configured for power on.")
            return

        log_name = "extranodes.log"

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET AWAKE ****")
            self._write_log(log_name, "Poweron - Dry run.\n")

        if not self.general.enabled:
            if self.general.verbose_logging:
                self.logger.info("PowerOn - Service is disabled by cron")
            return

        if not self._port_open(self.node.ip, self.node.port):
            return

        for node in self.extra_nodes:
            if self.general.dry_run:
                continue
            if self._ping(node.ip):
                continue
            try:
                send_magic_packet(node.mac)
            except ValueError:
                self.logger.error("Invalid MAC-address for %s.", node.name)
                continue
            message = (
                f"PowerOn Extra Nodes - WOL command sent for {node.name} - "
                f"{node.mac}\n"
            )
            self._write_log(log_name, message)
            self._send_pushover(
                f"PowerOn Extra Nodes - WOL command sent for {node.name}"
            )
            self.logger.info(
                "PowerOn - Sending WOL command for %s - %s",
                node.name,
                node.mac,
            )

    def power_off_extra_nodes(self) -> None:
        if not self.extra_nodes:
            self.logger.error("No extra nodes configured for power off.")
            return

        log_name = "extranodes.log"

        if self.general.dry_run:
            self.logger.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            self._write_log(log_name, "PowerOff - Dry run.\n")

        if not self.general.enabled:
            if self.general.verbose_logging:
                self.logger.info("PowerOff - Service is disabled by cron")
            return

        if self._port_open(self.node.ip, self.node.port):
            return

        for node in self.extra_nodes:
            if self.general.dry_run:
                continue
            if not node.user or not node.password or not node.ssh_port:
                continue
            if not self._ping(node.ip):
                continue
            result = self._run_remote_command(
                user=node.user,
                password=node.password,
                host=node.ip,
                port=node.ssh_port,
                command=self.power_off_settings.command
                if self.power_off_settings
                else "",
            )
            if result.stdout:
                self.logger.info(result.stdout)
            message = (
                f"PowerOff Extra Nodes - SLEEP command sent for {node.name}\n"
            )
            self._write_log(log_name, message)
            self._send_pushover(
                f"PowerOff Extra Nodes - SLEEP command sent for {node.name}"
            )
            self.logger.info(
                "PowerOff - Sending SLEEP command for %s", node.name
            )

    # ------------------------------------------------------------------
    # Support for state handling / ping helpers
    # ------------------------------------------------------------------
    def _ping(self, ip_address: str) -> bool:
        command = ["ping", "-c", "1", ip_address]
        try:
            subprocess.check_output(command)
            return True
        except subprocess.CalledProcessError:
            return False

    def _load_credits(self) -> dict:
        credits = {
            sender: credit
            for sender, credit in zip(
                self.power_on_settings.allowed_senders,
                self.power_on_settings.allowed_credits,
            )
        }

        first_day = self._first_day_of_week()

        if not self.state_path.exists():
            return credits

        last_modified = datetime.fromtimestamp(self.state_path.stat().st_mtime)
        if last_modified < first_day:
            return credits

        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                stored = json.load(handle)
                credits.update(stored)
        except (IOError, FileNotFoundError):
            self.logger.info(
                "Can't open file %s, using default values from ini.",
                self.state_path,
            )

        return credits

    def _save_credits(self, credits: dict) -> None:
        try:
            with self.state_path.open("w", encoding="utf-8") as handle:
                json.dump(credits, handle)
        except IOError:
            self.logger.error("Can't write file %s.", self.state_path)

    def _first_day_of_week(self) -> datetime:
        today = datetime.today()
        first_day = today - timedelta(days=today.weekday())
        return datetime.combine(first_day, time.min)
    