# Name: additional_nodes
# Coder: Marco Janssen (twitter @marc0janssen)
# date: 2023-12-27 19:28:00
# update: 2023-12-27 19:28:00

import logging
import sys
import configparser
import shutil
import socket
import subprocess

from datetime import datetime
from wakeonlan import send_magic_packet
from chump import Application


class ADDITIONAL_NODES():

    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

        config_dir = "/config/"
        app_dir = "/app/"
        log_dir = "/logging/poweronbymail/"

        self.config_file = "poweronbymail.ini"
        self.exampleconfigfile = "poweronbymail.ini.example"
        self.log_file = "additionalnodes.log"

        self.config_filePath = f"{config_dir}{self.config_file}"
        self.log_filePath = f"{log_dir}{self.log_file}"

        try:
            with open(self.config_filePath, "r") as f:
                f.close()
            try:
                self.config = configparser.ConfigParser()
                self.config.read(self.config_filePath)

                # POWERON
                self.enabled = True if (
                    self.config['POWERON']['ENABLED'] == "ON") else False
                self.dry_run = True if (
                    self.config['POWERON']['DRY_RUN'] == "ON") else False
                self.verbose_logging = True if (
                    self.config['POWERON']['VERBOSE_LOGGING'] == "ON") \
                    else False
                self.target_node = self.config['POWERON']['TARGET_NODE']
                self.target_port = int(self.config['POWERON']['TARGET_PORT'])

                # ADDITIONALNODES
                self.target_mac_addresses = list(
                    self.config['ADDITIONALNODES']
                    ['TARGET_MAC_ADDRESSES'].split(","))

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

    def is_mac_address_active(self, mac_address):
        command = "arp -n | grep {}".format(mac_address)
        result = subprocess.call(command, shell=True)
        if result == 0:
            return True
        else:
            return False

    def run(self):
        # Setting for PushOver
        self.appPushover = Application(self.pushover_token_api)
        self.userPushover = self.appPushover.get_user(self.pushover_user_key)

        if self.dry_run:
            logging.info(
                "*****************************************")
            logging.info(
                "**** DRY RUN, NOTHING WILL SET AWAKE ****")
            logging.info(
                "*****************************************")

            self.writeLog(
                False,
                "Poweron - Dry run.\n"
            )

        if self.enabled:
            sock = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(
                (self.target_node, self.target_port))
            # Port is open

            if result == 0:
                if not self.dry_run:
                    for mac_address in self.target_mac_addresses:
                        try:
                            # is MAC is not active then send magic packet
                            if not self.is_mac_address_active(mac_address.lower()):
                                send_magic_packet(mac_address.lower())

                                self.message = \
                                    self.userPushover.send_message(
                                        message=f"PowerOnByEmail - "
                                        f"WOL command sent for "
                                        f"{mac_address}\n"
                                        )

                                logging.info(
                                    f"Poweron - Sending WOL command for"
                                    f" {mac_address}"
                                    )

                                self.writeLog(
                                    False,
                                    f"Poweron - Sending WOL command for"
                                    f" {mac_address}\n"
                                )

                        except ValueError:
                            logging.error(
                                "Invalid MAC-address in INI."
                            )


if __name__ == '__main__':

    an = ADDITIONAL_NODES()
    an.run()
    an = None
