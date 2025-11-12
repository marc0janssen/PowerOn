"""Wake up nodes based on e-mail commands received via e-mail."""
import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from socket import gaierror

from chump import Application
from wakeonlan import send_magic_packet

from common import ConfigError, ConfigOption, MailPowerService


class PowerOnByEmail(MailPowerService):
    LOG_FILENAME = "poweronbymail.log"

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

            self.keyword = self.require(
                ConfigOption("POWERON", "KEYWORD")
            )
            self.allowed_senders = self.require_list(
                ConfigOption("POWERON", "ALLOWED_SENDERS")
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
    def _extract_sender(message) -> str:
        header = message.get("From", "")
        decoded = (
            MailPowerService.decode_header_value(header) if header else ""
        )
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", decoded)
        return match.group(0) if match else ""


    def _send_mail_response(self, receiver: str, body: str) -> None:
        message = MIMEMultipart()
        message["From"] = self.mail_sender
        message["To"] = receiver
        message["Subject"] = f"PowerOn - {self.nodename}"
        message.attach(MIMEText(body, _subtype="plain", _charset="UTF-8"))

        try:
            session = smtplib.SMTP(self.mail_server, self.mail_port)
            session.starttls()
            session.login(self.mail_login, self.mail_password)
            session.sendmail(self.mail_sender, [receiver], message.as_string())
            session.quit()
        except (gaierror, ConnectionRefusedError):
            logging.error(
                "Failed to connect to the server. Bad connection settings?"
            )
        except smtplib.SMTPServerDisconnected:
            logging.error(
                "Failed to connect to the server. Wrong user/password?"
            )
        except smtplib.SMTPException as exc:
            logging.error("SMTP error occurred: %s.", exc)
        else:
            self.verbose(f"PowerOn - Mail Sent to {receiver}.")
            self.write_log(f"PowerOn - Mail Sent to {receiver}.\n")

    def _handle_wol(self, sender: str, user) -> str:
        node_running = self.is_port_open(self.nodeip, self.nodeport)
        if node_running:
            logging.info("PowerOn - Nodes already running by %s", sender)
            self.write_log(
                f"PowerOn - Nodes already running by {sender}\n"
            )
            return (
                "Hi,\n\n"
                f" {self.nodename} is al aan, Je hoeft het 'power on' commando"
                " niet meer te sturen.\n\nFijne dag!\n\n"
            )

        if not self.dry_run:
            try:
                send_magic_packet(self.macaddress)
            except ValueError:
                logging.error("Invalid MAC-address in INI.")
        logging.info("PowerOn - Sending WOL command by %s", sender)
        self.write_log(
            f"PowerOn - Sending WOL command by {sender}\n"
        )
        user.send_message(
            message=f"PowerOnByEmail - WOL command sent by {sender}",
            sound=self.pushover_sound,
        )

        body = (
            f"Hi,\n\n {self.nodename} wordt aangezet, even geduld.\n\n"
        )
        body += "Fijne dag!\n\n"
        return body

    def run(self) -> None:
        user = self._pushover()

        if self.dry_run:
            logging.info("*****************************************")
            logging.info("**** DRY RUN, NOTHING WILL SET AWAKE ****")
            logging.info("*****************************************")
            self.write_log("PowerOn - Dry run.\n")

        mailbox = self.connect_mailbox()

        for uid, message in self.iter_messages(mailbox):
            subject = message.get("Subject", "")
            subject_text = (
                MailPowerService.decode_header_value(subject)
                if subject
                else ""
            )
            sender = self._extract_sender(message)

            if subject_text.lower() != self.keyword.lower():
                self.verbose(
                    "PowerOn - Subject not recognized. "
                    f"Skipping message. {sender}"
                )
                self.write_log(
                    "PowerOn - Subject not recognized. "
                    f"Skipping message. {sender}\n"
                )
                continue

            self.verbose(f"PowerOn - Found matching subject from {sender}")
            self.write_log(
                f"PowerOn - Found matching subject from {sender}\n"
            )

            if sender not in self.allowed_senders:
                self.verbose(f"PowerOn - sender not in list {sender}.")
                self.write_log(
                    f"PowerOn - sender not in list {sender}.\n"
                )
                continue

            if not self.enabled:
                self.verbose(f"PowerOn - Service is disabled by {sender}")
                self.write_log(
                    f"PowerOn - Service is disabled by {sender}\n"
                )
                body = (
                    "Hi,\n\n"
                    f"De service voor {self.nodename} staat uit, "
                    "je hoeft even geen commando's te sturen.\n\n"
                    "Fijne dag!\n\n"
                )
            else:
                body = self._handle_wol(sender, user)

            self._send_mail_response(sender, body)

            if not self.dry_run:
                mailbox.store(uid, "+FLAGS", "\\Deleted")

        mailbox.expunge()
        mailbox.close()
        mailbox.logout()


if __name__ == "__main__":
    PowerOnByEmail().run()
