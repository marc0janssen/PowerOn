"""Extend shutdown schedules based on e-mail commands."""
import logging
import re
import smtplib
import subprocess
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from socket import gaierror

from chump import Application

from common import ConfigError, ConfigOption, MailPowerService


class PowerOffDelayByEmail(MailPowerService):
    LOG_FILENAME = "poweronbymail.log"
    CRONTAB_FILE = "/etc/crontabs/root"

    def __init__(self) -> None:
        super().__init__(self.LOG_FILENAME)
        self.shutdowntime = "00:00"
        self.maxshutdowntime = "00:00"
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

            self.keyword = self.require(
                ConfigOption("EXTENDTIME", "KEYWORD")
            )
            self.allowed_senders = self.require_list(
                ConfigOption("EXTENDTIME", "ALLOWED_SENDERS")
            )
            self.extend_hours = self.require_int(
                ConfigOption("EXTENDTIME", "EXTEND_TIME_IN_HOURS")
            )
            self.maxhour = self.require(
                ConfigOption("EXTENDTIME", "MAX_SHUTDOWN_HOUR_TIME")
            )
            self.defaultminutes = self.require(
                ConfigOption("EXTENDTIME", "DEFAULT_MINUTES")
            )
            self.defaulthour = self.require(
                ConfigOption("EXTENDTIME", "DEFAULT_HOUR")
            )
            self.maxshutdowntime = (
                f"{self.maxhour.zfill(2)}:{self.defaultminutes.zfill(2)}"
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

    def _extract_sender(self, message) -> str:
        header = message.get("From", "")
        decoded = (
            MailPowerService.decode_header_value(header) if header else ""
        )
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", decoded)
        return match.group(0) if match else ""

    def _send_status_mail(self, success: bool, sender: str) -> None:
        message = MIMEMultipart()
        message["From"] = self.mail_sender
        message["To"] = ", ".join(self.allowed_senders)
        message["Subject"] = f"PowerOffDelay - {self.nodename}"

        if not self.enabled:
            body = (
                "Hi Hacker,\n\n"
                f"De service staat uit om {self.nodename} "
                "aan te kunnen zetten.\n"
                "Je hoeft en kunt nu dus even geen commando's geven.\n\n"
                "Fijne dag!\n\n"
            )
        elif success:
            body = (
                "Hi Hacker,\n\n"
                f" De node {self.nodename} blijft {self.extend_hours} "
                "uur extra aan.\n\n"
                f"Deze opdracht komt van {sender}.\n\n"
                f"De eindtijd is nu {self.shutdowntime}\n\n"
            )
            if self.shutdowntime != self.maxshutdowntime:
                body += (
                    "Als de eerste tijd is gepasseerd, is de volgende "
                    f"eindtijd {self.maxshutdowntime}\n\n"
                )
            body += "Fijne dag!\n\n"
        else:
            body = (
                "Hi Hacker,\n\n"
                f" De node {self.nodename} staat nu uit.\n"
                "Je kunt de tijd nu niet verhogen.\n\n"
                f"Deze opdracht komt van {sender}.\n\n"
                "Fijne dag!\n\n"
            )

        message.attach(MIMEText(body, _subtype="plain", _charset="UTF-8"))

        try:
            session = smtplib.SMTP(self.mail_server, self.mail_port)
            session.starttls()
            session.login(self.mail_login, self.mail_password)
            session.sendmail(
                self.mail_sender,
                self.allowed_senders,
                message.as_string(),
            )
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
            self.verbose(
                "PowerOffDelay - Mail Sent to "
                f"{', '.join(self.allowed_senders)}."
            )
            self.write_log(
                "PowerOffDelay - Mail Sent to "
                f"{', '.join(self.allowed_senders)}.\n"
            )

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
        shutdown_time = self.maxshutdowntime
        for index, line in enumerate(lines):
            if "poweroff.py" in line:
                parts = line.split()
                minutes = self.defaultminutes
                current_hours = parts[1].split(",")[0]
                try:
                    base_hour = int(current_hours)
                except ValueError:
                    base_hour = int(self.defaulthour)
                new_hour = (base_hour + self.extend_hours) % 24
                max_compare = (
                    24 if self.maxhour in {"0", "00"} else int(self.maxhour)
                )

                if new_hour >= max_compare:
                    parts[1] = self.maxhour
                    shutdown_time = self.maxshutdowntime
                else:
                    parts[1] = f"{new_hour},{self.maxhour}"
                    shutdown_time = (
                        f"{str(new_hour).zfill(2)}:{minutes.zfill(2)}"
                    )

                parts[0] = minutes
                lines[index] = " ".join(parts)
                break

        self.shutdowntime = shutdown_time

        if self.dry_run:
            return

        try:
            with open(self.CRONTAB_FILE, "w", encoding="utf-8") as file:
                file.write("\n".join(lines))
        except OSError as exc:
            logging.error(
                "Error writing the file %s: %s",
                self.CRONTAB_FILE,
                exc,
            )
            return

        result = subprocess.run(
            ["crontab", self.CRONTAB_FILE], capture_output=True, text=True
        )
        if result.stdout:
            logging.info(result.stdout.strip())
        if result.stderr:
            logging.error(result.stderr.strip())

    def change_crontab(self, sender: str, user) -> bool:
        node_running = self.is_port_open(self.nodeip, self.nodeport)
        if not node_running:
            logging.info("PowerOffDelay - Nodes not running by %s", sender)
            self.write_log(
                f"PowerOffDelay - Nodes not running by {sender}\n"
            )
            return False

        self._update_crontab()

        logging.info("PowerOffDelay - PowerOffdelay by %s", sender)
        self.write_log(
            f"PowerOffDelay - PowerOffdelay by {sender}\n"
        )
        user.send_message(
            message=f"PowerOffDelay - PowerOffDelay sent by {sender}",
            sound=self.pushover_sound,
        )
        return True

    def run(self) -> None:
        user = self._pushover()

        if self.dry_run:
            logging.info("******************************************")
            logging.info("**** DRY RUN, NOTHING WILL DE DELAYED ****")
            logging.info("******************************************")
            self.write_log("PowerOffDelay - Dry run.\n")

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
                    "PowerOffDelay - Subject not recognized. "
                    f"Skipping message. {sender}"
                )
                self.write_log(
                    "PowerOffDelay - Subject not recognized. "
                    f"Skipping message. {sender}\n"
                )
                continue

            self.verbose(
                f"PowerOffDelay - Found matching subject from {sender}"
            )
            self.write_log(
                f"PowerOffDelay - Found matching subject from {sender}\n"
            )

            if sender not in self.allowed_senders:
                self.verbose(
                    f"PowerOffDelay - sender not in list {sender}."
                )
                self.write_log(
                    f"PowerOffDelay - sender not in list {sender}.\n"
                )
                continue

            if not self.enabled:
                self.verbose(
                    f"PowerOffDelay - Service is disabled by {sender}"
                )
                self.write_log(
                    f"PowerOffDelay - Service is disabled by {sender}\n"
                )
                self._send_status_mail(success=False, sender=sender)
                continue

            success = self.change_crontab(sender, user)
            self._send_status_mail(success=success, sender=sender)

            if not self.dry_run:
                mailbox.store(uid, "+FLAGS", "\\Deleted")

        mailbox.expunge()
        mailbox.close()
        mailbox.logout()


if __name__ == "__main__":
    PowerOffDelayByEmail().run()
