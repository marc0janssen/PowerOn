"""Wake on LAN helper for additional nodes."""
import logging
import subprocess

from chump import Application
from wakeonlan import send_magic_packet

from common import BasePowerService, ConfigError, ConfigOption


class ExtraNodesPowerOn(BasePowerService):
    LOG_FILENAME = "extranodes.log"

    def __init__(self) -> None:
        super().__init__(self.LOG_FILENAME)
        try:
            self.nodeip = self.require(ConfigOption("NODE", "NODE_IP"))
            self.nodeport = self.require_int(ConfigOption("NODE", "NODE_PORT"))

            self.nodenames = self.require_list(ConfigOption("EXTRANODES", "NODE_NAME"))
            self.node_ips = self.require_list(ConfigOption("EXTRANODES", "NODE_IP"))
            self.node_mac_addresses = [
                mac.replace(":", "-").lower() for mac in self.require_list(
                    ConfigOption("EXTRANODES", "NODE_MAC_ADDRESS")
                )
            ]

            self.pushover_user_key = self.require(ConfigOption("PUSHOVER", "USER_KEY"))
            self.pushover_token_api = self.require(ConfigOption("PUSHOVER", "TOKEN_API"))
            self.pushover_sound = self.require(ConfigOption("PUSHOVER", "SOUND"))
        except ConfigError as error:
            self.exit_with_config_error(error)

    def _pushover(self):
        return self.pushover_user(factory=Application)

    @staticmethod
    def is_active_ip(ip_address: str) -> bool:
        command = ["ping", "-c", "1", ip_address]
        try:
            subprocess.check_output(command)
        except subprocess.CalledProcessError:
            return False
        return True

    def run(self) -> None:
        user = self._pushover()

        if self.dry_run:
            logging.info("*****************************************")
            logging.info("**** DRY RUN, NOTHING WILL SET AWAKE ****")
            logging.info("*****************************************")
            self.write_log("PowerOn - Dry run.\n")

        if not self.enabled:
            return

        if self.is_port_open(self.nodeip, self.nodeport):
            if self.dry_run:
                return

            for name, ip, mac in zip(self.nodenames, self.node_ips, self.node_mac_addresses):
                if self.is_active_ip(ip):
                    continue

                try:
                    send_magic_packet(mac)
                except ValueError:
                    logging.error("Invalid MAC-address in INI for %s.", name)
                    continue

                message = (
                    f"PowerOn Extra Nodes - WOL command sent for {name} - {mac}\n"
                )
                logging.info("PowerOn - Sending WOL command for %s - %s", name, mac)
                self.write_log(message)
                user.send_message(message=message.strip(), sound=self.pushover_sound)
        else:
            logging.info("PowerOn Extra Nodes - Primary node offline, skipping wake.")


if __name__ == "__main__":
    ExtraNodesPowerOn().run()
