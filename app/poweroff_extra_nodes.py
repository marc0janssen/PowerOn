# Name: poweroff_extra_nodes
# Coder: Marco Janssen (mastodon @marc0janssen@mastodon.online)
# date: 2023-12-29 14:07:00
# update: 2023-12-29 14:07:00

import logging
import sys
import configparser
import shutil
import socket
import subprocess

from datetime import datetime
from chump import Application


class EXTRA_NODES():

    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

        config_dir = "/config/"
        app_dir = "/app/"
        log_dir = "/logging/poweron/"

        self.config_file = "poweron.ini"
        self.exampleconfigfile = "poweron.ini.example"
        self.log_file = "extranodes.log"

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
                self.nodeip = self.config['NODE']['NODE_IP']
                self.nodeport = int(self.config['NODE']['NODE_PORT'])

                # EXTRANODES
                self.nodename = list(
                    self.config['EXTRANODES']
                    ['NODE_NAME'].split(","))
                self.nodepwd = list(
                    self.config['EXTRANODES']
                    ['NODE_PWD'].split(","))
                self.nodeuser = list(
                    self.config['EXTRANODES']
                    ['NODE_USER'].split(","))
                self.extranodeip = list(
                    self.config['EXTRANODES']
                    ['NODE_IP'].split(","))
                self.extranodesshport = list(
                    self.config['EXTRANODES']
                    ['NODE_SSHPORT'].split(","))
                self.nodemacaddress = list(
                    self.config['EXTRANODES']
                    ['NODE_MAC_ADDRESS'].split(","))

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
        command = "arp -n | grep {} >/dev/null 2>/dev/null".format(mac_address)
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
                "PowerOff - Dry run.\n"
            )

        if self.enabled:
            sock = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(
                (self.nodeip, self.nodeport))
            # Port is open of the master node

            if result != 0:
                if not self.dry_run:

                    numofnodes = len(self.nodename)

                    for node in range(numofnodes):
                        try:

                            # is MAC is not active then send magic packet
                            if self.is_mac_address_active(
                                    self.nodemacaddress[node].lower()):

                                # Execute the shell command

                                result = subprocess.run(
                                    ["sshpass",
                                        "-p",
                                        f"{self.nodepwd[node]}",
                                        "ssh",
                                        "-p",
                                        f"{self.extranodesshport[node]}",
                                        "-t",
                                        f"{self.nodeuser[node]}"
                                        f"@{self.extranodeip[node]}",
                                        f"echo {self.nodepwd[node]}"
                                        f"|sudo -S poweroff"],
                                    capture_output=True, text=True)

                                # Print the command output
                                # logging.info(result.stdout)

                                self.message = \
                                    self.userPushover.send_message(
                                        message=f"PowerOff Extra Nodes - "
                                        f"SLEEP command sent for "
                                        f"{self.nodename[node]}\n"
                                        )

                                logging.info(
                                    f"PowerOff - Sending SLEEP command for"
                                    f" {self.nodename[node]}"
                                    )

                                self.writeLog(
                                    False,
                                    f"PowerOff - Sending SLEEP command for"
                                    f" {self.nodename[node]}\n"
                                    )

                        except ValueError:
                            logging.error(
                                "Invalid MAC-address in INI."
                            )


if __name__ == '__main__':

    extranodes = EXTRA_NODES()
    extranodes.run()
    extranodes = None
