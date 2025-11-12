"""Cron-based shutdown utility."""
import logging
import re
import subprocess

from chump import Application

from common import BasePowerService, ConfigError, ConfigOption


class PowerOff(BasePowerService):
    LOG_FILENAME = "poweron.log"
    CRONTAB_FILE = "/etc/crontabs/root"

    def __init__(self) -> None:
        super().__init__(self.LOG_FILENAME)
        try:
            self.nodename = self.require(ConfigOption("NODE", "NODE_NAME"))
            self.nodeip = self.require(ConfigOption("NODE", "NODE_IP"))
            self.nodeport = self.require_int(ConfigOption("NODE", "NODE_PORT"))
            self.nodesshport = self.require_int(ConfigOption("NODE", "NODE_SSHPORT"))
            self.nodeuser = self.require(ConfigOption("NODE", "NODE_USER"))
            self.nodepwd = self.require(ConfigOption("NODE", "NODE_PWD"))

            self.poweroffcommand = self.require(
                ConfigOption("POWEROFF", "POWEROFFCOMMAND")
            )

            self.defaulthour = self.require(ConfigOption("EXTENDTIME", "DEFAULT_HOUR"))
            self.defaultminutes = self.require(
                ConfigOption("EXTENDTIME", "DEFAULT_MINUTES")
            )
            self.maxhour = self.require(
                ConfigOption("EXTENDTIME", "MAX_SHUTDOWN_HOUR_TIME")
            )

            self.pushover_user_key = self.require(ConfigOption("PUSHOVER", "USER_KEY"))
            self.pushover_token_api = self.require(ConfigOption("PUSHOVER", "TOKEN_API"))
            self.pushover_sound = self.require(ConfigOption("PUSHOVER", "SOUND"))
        except ConfigError as error:
            self.exit_with_config_error(error)

    def _pushover(self):
        return self.pushover_user(factory=Application)

    def _update_crontab_defaults(self) -> None:
        try:
            with open(self.CRONTAB_FILE, "r", encoding="utf-8") as file:
                content = file.read()
        except FileNotFoundError:
            logging.error("File not found - %s.", self.CRONTAB_FILE)
            return
        except OSError as exc:
            logging.error("Error reading the file %s: %s", self.CRONTAB_FILE, exc)
            return

        lines = content.split("\n")
        for index, line in enumerate(lines):
            if "poweroff.py" in line:
                parts = line.split()
                parts[1] = f"{self.defaulthour},{self.maxhour}"
                parts[0] = self.defaultminutes
                lines[index] = " ".join(parts)
                break

        new_text = "\n".join(lines)
        try:
            with open(self.CRONTAB_FILE, "w", encoding="utf-8") as file:
                file.write(new_text)
        except OSError as exc:
            logging.error("Error writing the file %s: %s", self.CRONTAB_FILE, exc)

    def run(self) -> None:
        user = self._pushover()

        if self.dry_run:
            logging.info("********************************************")
            logging.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            logging.info("********************************************")
            self.write_log("PowerOff - Dry run.\n")

        if not self.enabled:
            self.verbose("PowerOff - Service is disabled by cron")
            self.write_log("PowerOff - Service is disabled by cron\n")
            return

        if not self.is_port_open(self.nodeip, self.nodeport):
            logging.info("PowerOff - Node already down by cron")
            self.write_log("PowerOff - Node already down by cron\n")
            return

        if self.dry_run:
            return

        escaped_pwd = re.escape(self.nodepwd)
        command = [
            "sshpass",
            "-p",
            self.nodepwd,
            "ssh",
            "-p",
            str(self.nodesshport),
            "-t",
            f"{self.nodeuser}@{self.nodeip}",
            f"echo {escaped_pwd}|sudo -S bash -c '{self.poweroffcommand}'",
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.stdout:
            logging.info(result.stdout.strip())
        if result.stderr:
            logging.error(result.stderr.strip())

        logging.info("PowerOff - Sending SLEEP command by cron")
        self.write_log("PowerOff - Sending SLEEP command by cron\n")
        user.send_message(
            message="PowerOff - SLEEP command sent by cron",
            sound=self.pushover_sound,
        )

        self._update_crontab_defaults()


if __name__ == "__main__":
    PowerOff().run()
