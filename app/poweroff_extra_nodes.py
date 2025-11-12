"""Shutdown helper for additional nodes."""
import logging
import re
import subprocess

from chump import Application

from common import BasePowerService, ConfigError, ConfigOption


class ExtraNodesPowerOff(BasePowerService):
    LOG_FILENAME = "extranodes.log"

    def __init__(self) -> None:
        super().__init__(self.LOG_FILENAME)
        try:
            self.nodeip = self.require(
                ConfigOption("NODE", "NODE_IP")
            )
            self.nodeport = self.require_int(
                ConfigOption("NODE", "NODE_PORT")
            )

            self.nodenames = self.require_list(
                ConfigOption("EXTRANODES", "NODE_NAME")
            )
            self.node_ips = self.require_list(
                ConfigOption("EXTRANODES", "NODE_IP")
            )
            self.node_users = self.require_list(
                ConfigOption("EXTRANODES", "NODE_USER")
            )
            self.node_pwds = self.require_list(
                ConfigOption("EXTRANODES", "NODE_PWD")
            )
            self.node_ports = [
                int(port) for port in self.require_list(
                    ConfigOption("EXTRANODES", "NODE_SSHPORT")
                )
            ]
            self.poweroffcommand = self.require(
                ConfigOption("EXTRANODES", "POWEROFFCOMMAND")
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
        except (ConfigError, ValueError) as error:
            self.exit_with_config_error(ConfigError(str(error)))

    def _pushover(self):
        return self.pushover_user(factory=Application)

    @staticmethod
    def _build_command(
        user: str,
        host: str,
        port: int,
        password: str,
        command: str,
    ) -> list[str]:
        escaped_pwd = re.escape(password)
        return [
            "sshpass",
            "-p",
            password,
            "ssh",
            "-p",
            str(port),
            "-t",
            f"{user}@{host}",
            f"echo {escaped_pwd}|sudo -S bash -c '{command}'",
        ]

    def run(self) -> None:
        user = self._pushover()

        if self.dry_run:
            logging.info("********************************************")
            logging.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            logging.info("********************************************")
            self.write_log("PowerOff - Dry run.\n")

        if not self.enabled:
            return

        if self.is_port_open(self.nodeip, self.nodeport):
            logging.info(
                "PowerOff Extra Nodes - Primary node online, "
                "skipping shutdown."
            )
            return

        if self.dry_run:
            return

        for name, host, port, pwd, user_name in zip(
            self.nodenames,
            self.node_ips,
            self.node_ports,
            self.node_pwds,
            self.node_users,
        ):
            if not self.is_port_open(host, port):
                continue

            command = self._build_command(
                user_name,
                host,
                port,
                pwd,
                self.poweroffcommand,
            )
            result = subprocess.run(command, capture_output=True, text=True)
            if result.stdout:
                logging.info(result.stdout.strip())
            if result.stderr:
                logging.error(result.stderr.strip())

            message = f"PowerOff Extra Nodes - SLEEP command sent for {name}\n"
            logging.info("PowerOff - Sending SLEEP command for %s", name)
            self.write_log(message)
            user.send_message(
                message=message.strip(),
                sound=self.pushover_sound,
            )


if __name__ == "__main__":
    ExtraNodesPowerOff().run()
