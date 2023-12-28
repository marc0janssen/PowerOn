# Name: poweronbymail
# Coder: Marco Janssen (twitter @marc0janssen)
# date: 2023-01-04 20:08:00
# update: 2023-12-28 12:47:00

import imaplib
import email
import re
import logging
import sys
import configparser
import shutil
import smtplib
import socket

from datetime import datetime
from email.header import decode_header
from wakeonlan import send_magic_packet
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
# from email.mime.base import MIMEBase
# from email import encoders
from socket import gaierror
from chump import Application


class POBE():

    def __init__(self):
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO)

        config_dir = "/config/"
        app_dir = "/app/"
        log_dir = "/logging/poweron/"

        self.config_file = "poweron.ini"
        self.exampleconfigfile = "poweron.ini.example"
        self.log_file = "poweronbymail.log"

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

                # MAIL
                self.mail_port = int(
                    self.config['MAIL']['MAIL_PORT'])
                self.mail_server = self.config['MAIL']['MAIL_SERVER']
                self.mail_login = self.config['MAIL']['MAIL_LOGIN']
                self.mail_password = self.config['MAIL']['MAIL_PASSWORD']
                self.mail_sender = self.config['MAIL']['MAIL_SENDER']

                # POWERON
                self.keyword = self.config['POWERON']['KEYWORD']
                self.allowed_senders = list(
                    self.config['POWERON']['ALLOWED_SENDERS'].split(","))
                self.macaddress = self.config['POWERON']['MACADDRESS']\
                    .replace(":", "-").lower()
                self.target_node = self.config['POWERON']['TARGET_NODE']
                self.target_port = int(self.config['POWERON']['TARGET_PORT'])

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
                "*****************************************")
            logging.info(
                "**** DRY RUN, NOTHING WILL SET AWAKE ****")
            logging.info(
                "*****************************************")

            self.writeLog(
                False,
                "Poweron - Dry run.\n"
            )

        # create an IMAP4 class with SSL
        imap = imaplib.IMAP4_SSL(self.mail_server)
        # authenticate
        imap.login(self.mail_login, self.mail_password)

        status, messages = imap.select("INBOX")

        # total number of emails
        messages = int(messages[0])

        for i in range(1, messages+1):

            # fetch the email message by ID
            res, msg = imap.fetch(str(i), "(RFC822)")
            for response in msg:
                if isinstance(response, tuple):
                    # parse a bytes email into a message object
                    msg = email.message_from_bytes(response[1])

                    # decode the email subject
                    subject, encoding = decode_header(msg["Subject"])[0]

                    if isinstance(subject, bytes):
                        # if it's a bytes, decode to str
                        if encoding:
                            subject = subject.decode(encoding)
                        else:
                            subject = subject.decode("utf-8")

                    # decode email sender
                    From, encoding = decode_header(msg.get("From"))[-1:][0]

                    if isinstance(From, bytes):
                        if encoding:
                            From = From.decode(encoding)
                        else:
                            From = From.decode("utf-8")

                    match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', From)

                    if str.lower(subject) == self.keyword:

                        if self.verbose_logging:
                            logging.info(
                                f"Poweron - Found matching subject from "
                                f"{match.group(0)}"
                            )
                        self.writeLog(
                            False, f"Poweron - Found matching subject from "
                            f"{match.group(0)}\n")

                        if match.group(0) in self.allowed_senders:

                            if self.enabled:
                                sock = socket.socket(
                                    socket.AF_INET, socket.SOCK_STREAM)
                                result = sock.connect_ex(
                                    (self.target_node, self.target_port))
                                if result != 0:
                                    if not self.dry_run:
                                        try:
                                            send_magic_packet(self.macaddress)

                                        except ValueError:
                                            logging.error(
                                                "Invalid MAC-address in INI."
                                            )
                                            sys.exit()

                                    logging.info(
                                        f"Poweron - Sending WOL command by"
                                        f" {match.group(0)}"
                                        )
                                    self.writeLog(
                                        False,
                                        f"Poweron - Sending WOL command by"
                                        f" {match.group(0)}\n"
                                    )

                                    self.message = \
                                        self.userPushover.send_message(
                                            message=f"PowerOnByEmail - "
                                            f"WOL command sent by "
                                            f"{match.group(0)}\n"
                                            )

                                else:
                                    logging.info(
                                        f"Poweron - Nodes already running"
                                        f" by {match.group(0)}"
                                    )
                                    self.writeLog(
                                        False,
                                        f"Poweron - Nodes already running by "
                                        f"{match.group(0)}\n"
                                    )
                            else:
                                if self.verbose_logging:
                                    logging.info(
                                        f"Poweron - Service is disabled by "
                                        f"{match.group(0)}"
                                    )
                                self.writeLog(
                                    False,
                                    f"Poweron - Service is disabled by "
                                    f"{match.group(0)}\n"
                                )

                            sender_email = self.mail_sender
                            receiver_email = match.group(0)

                            message = MIMEMultipart()
                            message["From"] = sender_email
                            message['To'] = receiver_email
                            message['Subject'] = (
                                "Poweron - Emby"
                            )

                            # attachment = open(self.log_filePath, 'rb')
                            # obj = MIMEBase('application', 'octet-stream')
                            # obj.set_payload((attachment).read())
                            # encoders.encode_base64(obj)
                            # obj.add_header(
                            #     'Content-Disposition',
                            #     "attachment; filename= "+self.log_file
                            # )
                            # message.attach(obj)

                            if self.enabled:
                                if result != 0:
                                    body = (
                                        "Hi,\n\n Emby wordt aangezet, "
                                        "even geduld.\n\n"
                                        "Fijne dag!\n\n"
                                    )
                                else:
                                    body = (
                                        "Hi,\n\n Emby is al aan, "
                                        "Je hoeft het 'power on' "
                                        "commando niet meer te sturen.\n\n"
                                        "Fijne dag!\n\n"
                                    )
                            else:
                                body = (
                                    "Hi,\n\n Service staat uit "
                                    ", je hoeft even geen commando's "
                                    "te sturen.\n\n"
                                    "Fijne dag!\n\n"
                                )

                            # logfile = open(self.log_filePath, "r")
                            # body += ''.join(logfile.readlines())
                            # logfile.close()

                            plain_text = MIMEText(
                                body, _subtype='plain', _charset='UTF-8')
                            message.attach(plain_text)

                            my_message = message.as_string()

                            try:
                                email_session = smtplib.SMTP(
                                    self.mail_server, self.mail_port)
                                email_session.starttls()
                                email_session.login(
                                    self.mail_login, self.mail_password)
                                email_session.sendmail(
                                    sender_email,
                                    receiver_email,
                                    my_message
                                    )
                                email_session.quit()
                                if self.verbose_logging:
                                    logging.info(
                                        f"Poweron - Mail Sent to "
                                        f"{receiver_email}."
                                    )

                                self.writeLog(
                                    False,
                                    f"Poweron - Mail Sent to "
                                    f"{receiver_email}.\n"
                                )

                            except (gaierror, ConnectionRefusedError):
                                logging.error(
                                    "Failed to connect to the server. "
                                    "Bad connection settings?")
                            except smtplib.SMTPServerDisconnected:
                                logging.error(
                                    "Failed to connect to the server. "
                                    "Wrong user/password?"
                                )
                            except smtplib.SMTPException as e:
                                logging.error(
                                    f"SMTP error occurred: {str(e)}.")

                        else:
                            if self.verbose_logging:
                                logging.info(
                                    f"Poweron - sender not in"
                                    f" list {match.group(0)}."
                                    )
                            self.writeLog(
                                False,
                                f"Poweron - sender not in list "
                                f"{match.group(0)}.\n"
                            )

                        if self.verbose_logging:
                            logging.info(
                                "Poweron - Marking message for delete.")
                        self.writeLog(
                            False, "Poweron - Marking message for delete.\n")

                        if not self.dry_run:
                            imap.store(str(i), "+FLAGS", "\\Deleted")

                    else:
                        if self.verbose_logging:
                            logging.info(
                                f"Poweron - Subject not recognized. "
                                f"Skipping message. "
                                f"{match.group(0)}"
                            )

                            self.writeLog(
                                False,
                                f"Poweron - Subject not recognized. "
                                f"Skipping message. {match.group(0)}\n"
                            )

        # close the connection and logout
        imap.expunge()
        imap.close()
        imap.logout()


if __name__ == '__main__':

    poweronbyemail = POBE()
    poweronbyemail.run()
    poweronbyemail = None
