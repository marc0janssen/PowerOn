# PowerOn Automation Suite

PowerOn is a small collection of automation scripts that keep a lab or home server responsive on demand.  
It unifies Wake-on-LAN orchestration, remote shutdowns, cron schedule management, and mail-driven triggers in a
single, reusable service base class. Each script focuses on a specific workflow while inheriting the same
configuration handling, logging, and PushOver notification behaviour.

## Features
- **Wake-on-LAN orchestration** – Brings the primary node (and optional extra nodes) online through scheduled
  cron jobs or ad-hoc mail commands.
- **Graceful shutdowns** – Runs configurable SSH commands to power machines down and restore cron schedules
  after the shutdown window ends.
- **Mail driven automation** – Polls an IMAP inbox, validates authorised senders, and reacts to power-on,
  power-off, or shutdown-extension requests.
- **Cron schedule management** – Updates the root crontab so the infrastructure follows the expected runtime
  windows while still allowing emergency overrides.
- **Unified logging and notifications** – Persists timestamped logs alongside PushOver alerts to simplify
  monitoring and auditing.

## Repository structure

| Path | Description |
| ---- | ----------- |
| `app/common.py` | Shared helpers that load configuration, handle logging, and provide e-mail utilities. |
| `app/poweron.py` | Wakes the primary node when cron schedules or mail commands request it. |
| `app/poweroff.py` | Shuts the primary node down and restores the default cron schedule. |
| `app/poweronbymail.py`, `app/poweroffbymail.py`, `app/poweroffdelaybymail.py` | Mail processors that react to keywords from authorised senders. |
| `app/poweron_extra_nodes.py`, `app/poweroff_extra_nodes.py` | Keep additional hosts in sync with the primary node. |
| `app/poweron.ini.example` | Example configuration that documents every available option. |

## Getting started

### Prerequisites
- Python 3.9 or newer.
- Access to an IMAP mailbox when using the e-mail workflows.
- `sshpass` installed on the host for automated shutdown commands:
  ```bash
  sudo apt-get install sshpass
  ```

### Installation
1. Clone the repository and install the Python dependencies:
   ```bash
   git clone https://github.com/<your-account>/PowerOn.git
   cd PowerOn
   pip install -r requirements.txt
   ```

2. (Optional) Install development dependencies if you plan to contribute:
   ```bash
   pip install -r dev-requirements.txt
   ```

3. Create the configuration directory structure expected by the scripts:
   ```bash
   sudo mkdir -p /config /var/log
   sudo chown $(id -u):$(id -g) /config /var/log
   ```

## Configuration
PowerOn looks for its configuration in `/config/poweron.ini` and will copy `app/poweron.ini.example`
to that location if the file is missing. Start by copying the example yourself so you can version
control your changes:
```bash
cp app/poweron.ini.example /config/poweron.ini
```

Key sections to review:
- **`[GENERAL]`** – Toggle the automation (`ENABLED`), enable dry-run mode (`DRY_RUN`), and control verbose
  logging (`VERBOSE_LOGGING`).
- **`[NODE]`** – Describe the primary host: human-friendly name, Wake-on-LAN MAC address, IP/port used for the
  availability check, and optional SSH credentials for shutdown.
- **`[MAIL]`** – IMAP server, port, credentials, and the sender address used when sending confirmations.
- **`[POWERON]` / `[POWEROFF]`** – Mail keywords, authorised senders, and the SSH command that powers the node
  off.
- **`[EXTENDTIME]`** – Default and maximum extensions when processing shutdown delay requests.
- **`[EXTRANODES]`** – Additional machines that should follow the primary node’s state, including credentials
  for remote shutdowns.
- **`[PUSHOVER]`** – API token, user key, and the notification sound to use for alerts.

When the scripts run they also maintain:
- `/config/poweron.json` for tracking weekly wake credits by sender.
- `/var/log/*.log` files for an audit trail of each workflow.

Ensure the process owner can write to both locations.

## Running the scripts
Each automation entry point is a small wrapper around the shared service logic, so they can be invoked
directly with Python 3:
```bash
python app/poweron.py               # Wake the primary node
python app/poweroff.py              # Shut the primary node down
python app/poweronbymail.py         # Handle power-on requests from the mailbox
python app/poweroffbymail.py        # Handle shutdown requests from the mailbox
python app/poweroffdelaybymail.py   # Extend the shutdown window based on e-mail commands
python app/poweron_extra_nodes.py   # Wake additional nodes
python app/poweroff_extra_nodes.py  # Shut down additional nodes
```

### Scheduling with cron
All scripts are designed to be run from cron. A minimal example that wakes the server at 17:00 and
shuts it down at 01:00 might look like:
```
0 17 * * * /usr/bin/python3 /app/poweron.py
0  1 * * * /usr/bin/python3 /app/poweroff.py
*/5 * * * * /usr/bin/python3 /app/poweronbymail.py
*/5 * * * * /usr/bin/python3 /app/poweroffbymail.py
```
Adjust the schedule and polling frequency to match your environment.

## Monitoring and troubleshooting
- Check the `/var/log/*.log` files for timestamped activity details.
- Review PushOver notifications to confirm that actions succeeded or to investigate failures.
- Inspect `/config/poweron.json` to see remaining weekly wake credits for each authorised sender.

## Contributing
1. Fork the repository and create a feature branch.
2. Install the development requirements (`pip install -r dev-requirements.txt`).
3. Apply changes and ensure they follow the existing code style (the project currently relies on
   standard `flake8`/`black` defaults).
4. Submit a pull request with a clear description of the problem being solved.

## License
This project is licensed under the terms of the [MIT License](LICENSE).
