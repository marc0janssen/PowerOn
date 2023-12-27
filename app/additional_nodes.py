# Name: additional_nodes
# Coder: Marco Janssen (twitter @marc0janssen)
# date: 2023-12-27 19:28:00
# update: 2023-12-27 19:28:00

import logging
import sys
import configparser
import shutil
import socket

from datetime import datetime
from wakeonlan import send_magic_packet
from chump import Application
from scapy.all import ARP, Ether, srp


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
                self.target_network = self.config['ADDITIONALNODES']['TARGET_NETWORK']

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

    def get_ip(self, mac_address):
        # Create an ARP request packet to get the IP address
        arp_request = Ether(dst="ff:ff:ff:ff:ff:ff") \
            / ARP(pdst='f"{self.target_network}"')

        # Send the ARP request and capture the response
        result = srp(arp_request, timeout=3, verbose=0)[0]

        # Process the response to extract the IP address
        # associated with the MAC address
        for sent, received in result:
            if received[ARP].hwsrc == mac_address:
                return received[ARP].psrc

        return None

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
                            
                            print(f"-{mac_address}-")

                            ip_address = self.get_ip(mac_address)
                            if not ip_address:
                                print("IP not fund")
                                send_magic_packet(mac_address)
                            else:
                                print("ip found")

                        except ValueError:
                            logging.error(
                                "Invalid MAC-address in INI."
                            )
                            sys.exit()

                        logging.info(
                            f"Poweron - Sending WOL command for"
                            f" {mac_address}"
                            )

                        self.writeLog(
                            False,
                            f"Poweron - Sending WOL command for"
                            f" {mac_address}\n"
                        )

                        self.message = \
                            self.userPushover.send_message(
                                message=f"PowerOnByEmail - "
                                f"WOL command sent for "
                                f"{mac_address}\n"
                                )


if __name__ == '__main__':

    an = ADDITIONAL_NODES()
    an.run()
    an = None
