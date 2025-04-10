# Name: poweroff
# Coder: Marco Janssen (mastodon @marc0janssen@mastodon.online)
# date: 2023-12-29 13:33:00
# update: 2023-12-29 13:33:00

import logging
import sys
import configparser
import shutil
import socket
import subprocess
import re

from datetime import datetime
from chump import Application


class POWEROFF():

    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

        config_dir = "/config/"
        app_dir = "/app/"
        log_dir = "/var/log/"

        self.config_file = "poweron.ini"
        self.exampleconfigfile = "poweron.ini.example"
        self.log_file = "poweron.log"

        self.config_filePath = f"{config_dir}{self.config_file}"
        self.log_filePath = f"{log_dir}{self.log_file}"

        try:
            with open(self.config_filePath, "r") as f:
                f.close()
            try:
                self.config = configparser.ConfigParser()
                self.config.read(self.config_filePath)

                # GENERAL
                self.enabled = True if (
                    self.config['GENERAL']['ENABLED'] == "ON") else False
                self.dry_run = True if (
                    self.config['GENERAL']['DRY_RUN'] == "ON") else False
                self.verbose_logging = True if (
                    self.config['GENERAL']['VERBOSE_LOGGING'] == "ON") \
                    else False

                # NODE
                self.nodename = self.config['NODE']['NODE_NAME']
                self.nodeip = self.config['NODE']['NODE_IP']
                self.nodeport = int(self.config['NODE']['NODE_PORT'])
                self.nodesshport = int(self.config['NODE']['NODE_SSHPORT'])
                self.nodeuser = self.config['NODE']['NODE_USER']
                self.nodepwd = self.config['NODE']['NODE_PWD']

                # POWEROFF
                self.poweroffcommand = \
                    self.config['POWEROFF']['POWEROFFCOMMAND']

                # EXTENDTIME
                self.defaulthour = self.config['EXTENDTIME']['DEFAULT_HOUR']
                self.defaultminutes = \
                    self.config['EXTENDTIME']['DEFAULT_MINUTES']
                self.maxhour = \
                    self.config['EXTENDTIME']['MAX_SHUTDOWN_HOUR_TIME']

                # PUSHOVER
                self.pushover_user_key = self.config['PUSHOVER']['USER_KEY']
                self.pushover_token_api = self.config['PUSHOVER']['TOKEN_API']
                self.pushover_sound = self.config['PUSHOVER']['SOUND']

            except KeyError as e:
                logging.error(
                    f"Seems a key(s) {e} is missing from INI file. "
                    f"Please check for mistakes. Exiting."
                )

                sys.exit()

            except ValueError as e:
                logging.error(
                    f"Seems a invalid value in INI file. "
                    f"Please check for mistakes. Exiting. "
                    f"MSG: {e}"
                )

                sys.exit()

        except IOError or FileNotFoundError:
            logging.error(
                f"Can't open file {self.config_filePath}"
                f", creating example INI file."
            )

            shutil.copyfile(f'{app_dir}{self.exampleconfigfile}',
                            f'{config_dir}{self.exampleconfigfile}')
            sys.exit()

    def writeLog(self, init, msg):
        try:
            if init:
                logfile = open(self.log_filePath, "w")
            else:
                logfile = open(self.log_filePath, "a")
            logfile.write(f"{datetime.now()} - {msg}")
            logfile.close()
        except IOError:
            logging.error(
                f"Can't write file {self.log_filePath}."
            )

    def run(self):
        # Setting for PushOver
        self.appPushover = Application(self.pushover_token_api)
        self.userPushover = self.appPushover.get_user(self.pushover_user_key)

        if self.dry_run:
            logging.info(
                "********************************************")
            logging.info(
                "**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            logging.info(
                "********************************************")

            self.writeLog(
                False,
                "PowerOff - Dry run.\n"
            )

        if self.enabled:
            sock = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(
                (self.nodeip, self.nodeport))
            if result == 0:
                if not self.dry_run:
                    try:
                        # Execute the shell command

                        ecsapedpwd = re.escape(
                            self.nodepwd)

                        result = subprocess.run(
                            ["sshpass",
                                "-p",
                                f"{self.nodepwd}",
                                "ssh",
                                "-p",
                                f"{self.nodesshport}",
                                "-t",
                                f"{self.nodeuser}"
                                f"@{self.nodeip}",
                                f"echo {ecsapedpwd}"
                                f"|sudo -S bash -c "
                                f"{self.poweroffcommand}"],
                            capture_output=True, text=True)

                        # Print the command output
                        logging.info(result.stdout)

                        logging.info(
                            "PowerOff - Sending SLEEP command by cron"
                            )
                        self.writeLog(
                            False,
                            "PowerOff - Sending SLEEP command by cron\n"
                        )

                        self.message = \
                            self.userPushover.send_message(
                                message="PowerOff - "
                                "SLEEP command sent by cron",
                                sound=self.pushover_sound
                                )

                    except ValueError:
                        logging.error(
                            "Invalid MAC-address in INI."
                        )
                        sys.exit()

                try:
                    with open("/etc/crontabs/root", 'r') as file:
                        content = file.read()
                        file.close()

                        lines = content.split('\n')

                        for line in range(len(lines)):
                            if "poweroff.py" in lines[line]:

                                line_parts = lines[line].split()
                                line_parts[1] = (
                                    f"{self.defaulthour},"
                                    f"{self.maxhour}"
                                )
                                line_parts[0] = self.defaultminutes

                                lines[line] = ' '.join(line_parts)
                                break

                        new_text = '\n'.join(lines)

                        try:
                            with open("/etc/crontabs/root", 'w') as file:
                                file.write(new_text)
                                file.close()

                        except IOError:
                            logging.error(
                                "Error writing the "
                                "file /etc/crontabs/root.")

                except FileNotFoundError:
                    logging.error(
                        "File not found - "
                        "/etc/crontabs/root.")
                except IOError:
                    logging.error(
                        "Error reading the"
                        " file /etc/crontabs/root.")

            else:
                logging.info(
                    "PowerOff - Node already down"
                    " by cron"
                )
                self.writeLog(
                    False,
                    "PowerOff - Node already down by cron\n"
                )
        else:
            if self.verbose_logging:
                logging.info(
                    "PowerOff - Service is disabled by cron"
                )
            self.writeLog(
                False,
                "PowerOff - Service is disabled by cron\n"
            )


if __name__ == '__main__':

    poweroff = POWEROFF()
    poweroff.run()
    poweroff = None
