"""Cron-based Wake on LAN utility."""
import logging
from wakeonlan import send_magic_packet
from chump import Application

from common import BasePowerService, ConfigError, ConfigOption


class PowerOn(BasePowerService):
    LOG_FILENAME = "poweron.log"

    def __init__(self) -> None:
        super().__init__(self.LOG_FILENAME)
        try:
            self.nodename = self.require(
                ConfigOption("NODE", "NODE_NAME")
            )
            self.macaddress = self.require(
                ConfigOption("NODE", "NODE_MAC")
            ).replace(":", "-").lower()
            self.nodeip = self.require(
                ConfigOption("NODE", "NODE_IP")
            )
            self.nodeport = self.require_int(
                ConfigOption("NODE", "NODE_PORT")
            )

            self.pushover_user_key = self.require(
                ConfigOption("PUSHOVER", "USER_KEY")
            )
            self.pushover_token_api = self.require(
                ConfigOption("PUSHOVER", "TOKEN_API")
            )
            self.pushover_sound = self.require(
                ConfigOption("PUSHOVER", "SOUND")
            )
        except ConfigError as error:
            self.exit_with_config_error(error)

    def _pushover(self):
        return self.pushover_user(factory=Application)

    def run(self) -> None:
        if self.dry_run:
            logging.info("*****************************************")
            logging.info("**** DRY RUN, NOTHING WILL SET AWAKE ****")
            logging.info("*****************************************")
            self.write_log("PowerOn - Dry run.\n")

        if not self.enabled:
            return

        if self.is_port_open(self.nodeip, self.nodeport):
            logging.info("PowerOn - Nodes already running by cron")
            self.write_log("PowerOn - Nodes already running by cron\n")
            return

        if self.dry_run:
            return

        try:
            send_magic_packet(self.macaddress)
        except ValueError:
            logging.error("Invalid MAC-address in INI.")
            return

        logging.info("PowerOn - Sending WOL command by cron")
        self.write_log("PowerOn - Sending WOL command by cron\n")
        self._pushover().send_message(
            message="PowerOn - WOL command sent by cron",
            sound=self.pushover_sound,
        )


if __name__ == "__main__":
    PowerOn().run()
