"""Shut down nodes based on e-mail commands."""
import logging
import re
import smtplib
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from socket import gaierror

from chump import Application

from common import ConfigError, ConfigOption, MailPowerService


class PowerOffByEmail(MailPowerService):
    LOG_FILENAME = "poweroffbymail.log"
    CRONTAB_FILE = "/etc/crontabs/root"

    def __init__(self) -> None:
        super().__init__(self.LOG_FILENAME)
        try:
            self.nodename = self.require(
                ConfigOption("NODE", "NODE_NAME")
            )
            self.nodeip = self.require(
                ConfigOption("NODE", "NODE_IP")
            )
            self.nodeport = self.require_int(
                ConfigOption("NODE", "NODE_PORT")
            )
            self.nodesshport = self.require_int(
                ConfigOption("NODE", "NODE_SSHPORT")
            )
            self.nodeuser = self.require(
                ConfigOption("NODE", "NODE_USER")
            )
            self.nodepwd = self.require(
                ConfigOption("NODE", "NODE_PWD")
            )

            self.keyword = self.require(
                ConfigOption("POWEROFF", "KEYWORD")
            )
            self.allowed_senders = self.require_list(
                ConfigOption("POWEROFF", "ALLOWED_SENDERS")
            )
            self.poweroffcommand = self.require(
                ConfigOption("POWEROFF", "POWEROFFCOMMAND")
            )

            self.defaulthour = self.require(
                ConfigOption("EXTENDTIME", "DEFAULT_HOUR")
            )
            self.defaultminutes = self.require(
                ConfigOption("EXTENDTIME", "DEFAULT_MINUTES")
            )
            self.maxhour = self.require(
                ConfigOption("EXTENDTIME", "MAX_SHUTDOWN_HOUR_TIME")
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

    def _update_crontab(self) -> None:
        try:
            with open(self.CRONTAB_FILE, "r", encoding="utf-8") as file:
                content = file.read()
        except FileNotFoundError:
            logging.error("File not found - %s.", self.CRONTAB_FILE)
            return
        except OSError as exc:
            logging.error(
                "Error reading the file %s: %s",
                self.CRONTAB_FILE,
                exc,
            )
            return

        lines = content.split("\n")
        for index, line in enumerate(lines):
            if "poweroff.py" in line:
                parts = line.split()
                parts[1] = f"{self.defaulthour},{self.maxhour}"
                parts[0] = self.defaultminutes
                lines[index] = " ".join(parts)
                break

        try:
            with open(self.CRONTAB_FILE, "w", encoding="utf-8") as file:
                file.write("\n".join(lines))
        except OSError as exc:
            logging.error(
                "Error writing the file %s: %s",
                self.CRONTAB_FILE,
                exc,
            )

    def _execute_shutdown(self) -> subprocess.CompletedProcess:
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
        return subprocess.run(command, capture_output=True, text=True)

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
        message["Subject"] = f"PowerOff - {self.nodename}"
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
            self.verbose(f"PowerOff - Mail Sent to {receiver}.")
            self.write_log(f"PowerOff - Mail Sent to {receiver}.\n")

    def run(self) -> None:
        user = self._pushover()

        if self.dry_run:
            logging.info("********************************************")
            logging.info("**** DRY RUN, NOTHING WILL SET TO SLEEP ****")
            logging.info("********************************************")
            self.write_log("PowerOff - Dry run.\n")

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
                    "PowerOff - Subject not recognized. "
                    f"Skipping message. {sender}"
                )
                self.write_log(
                    "PowerOff - Subject not recognized. "
                    f"Skipping message. {sender}\n"
                )
                continue

            self.verbose(f"PowerOff - Found matching subject from {sender}")
            self.write_log(
                f"PowerOff - Found matching subject from {sender}\n"
            )

            if sender not in self.allowed_senders:
                self.verbose(f"PowerOff - sender not in list {sender}.")
                self.write_log(
                    f"PowerOff - sender not in list {sender}.\n"
                )
                continue

            if not self.enabled:
                self.verbose(f"PowerOff - Service is disabled by {sender}")
                self.write_log(
                    f"PowerOff - Service is disabled by {sender}\n"
                )
                continue

            node_running = self.is_port_open(self.nodeip, self.nodeport)

            if not node_running:
                logging.info("PowerOff - Nodes not running by %s", sender)
                self.write_log(
                    f"PowerOff - Nodes not running by {sender}\n"
                )
                response = (
                    "Hi,\n\n"
                    f" {self.nodename} is al uit, je hoeft het 'power off' "
                    "commando niet meer te sturen.\n\n"
                    "Fijne dag!\n\n"
                )
            else:
                if not self.dry_run:
                    result = self._execute_shutdown()
                    if result.stdout:
                        logging.info(result.stdout.strip())
                    if result.stderr:
                        logging.error(result.stderr.strip())
                    self._update_crontab()

                logging.info("PowerOff - Sending SLEEP command by %s", sender)
                self.write_log(
                    f"PowerOff - Sending SLEEP command by {sender}\n"
                )
                user.send_message(
                    message=(
                        f"PowerOffByEmail - SLEEP command sent by {sender}"
                    ),
                    sound=self.pushover_sound,
                )
                response = (
                    "Hi,\n\n"
                    f" {self.nodename} wordt uitgezet, even geduld.\n\n"
                    "Fijne dag!\n\n"
                )

            self._send_mail_response(sender, response)

            if not self.dry_run:
                mailbox.store(uid, "+FLAGS", "\\Deleted")

        mailbox.expunge()
        mailbox.close()
        mailbox.logout()


if __name__ == "__main__":
    PowerOffByEmail().run()
