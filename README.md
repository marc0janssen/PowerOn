# PowerOn Automation Suite

## Overview
PowerOn bundles the scripts that automate powering a home server and its companion nodes into a single, reusable `PowerManager`. The manager centralises configuration loading, logging, PushOver notifications, cron maintenance, and mail processing so every workflow shares the same behaviour and error handling.【F:app/power_manager.py†L1-L168】

The application is designed to run inside an environment that exposes the configuration volume at `/config`, the application code at `/app`, persistent logs in `/var/log`, and the root crontab at `/etc/crontabs/root`. Defaults for these paths are embedded in the manager so deployments remain consistent across scripts.【F:app/power_manager.py†L39-L167】

## Key capabilities
- **Wake-on-LAN orchestration** – Sends magic packets to the primary node and any extra nodes when the service is enabled, while supporting dry-run mode and PushOver notifications for auditing.【F:app/power_manager.py†L504-L534】【F:app/power_manager.py†L886-L927】
- **Graceful shutdowns** – Executes configurable SSH commands via `sshpass` to put systems to sleep and automatically restores the default cron schedule after a shutdown.【F:app/power_manager.py†L351-L579】
- **Mail-driven automation** – Polls an IMAP inbox, filters messages by keyword and sender, and handles mail replies for power-on, power-off, and shutdown-extension requests; optional weekly credits limit how often each sender can wake the system.【F:app/power_manager.py†L582-L884】【F:app/power_manager.py†L987-L1024】
- **Cron schedule management** – Rewrites the root crontab when extending or resetting the shutdown window so the infrastructure follows the configured time limits.【F:app/power_manager.py†L375-L456】
- **Stateful logging and notifications** – Persists timestamped activity logs alongside PushOver alerts so operators can review historical actions and receive real-time updates.【F:app/power_manager.py†L321-L341】【F:app/power_manager.py†L531-L534】

## Repository structure
| Path | Description |
| ---- | ----------- |
| `app/power_manager.py` | Core module that implements configuration parsing, notifications, cron helpers, mail processing, and the power on/off workflows.【F:app/power_manager.py†L1-L1028】 |
| `app/poweron.py`, `app/poweroff.py`, `app/poweronbymail.py`, etc. | Thin entry points that instantiate the manager and call the relevant operation, making it easy to wire each action into cron or other schedulers.【F:app/poweron.py†L1-L12】 |
| `app/poweron.ini.example` | Example configuration file that documents every supported setting and can be copied to `/config/poweron.ini` for real deployments.【F:app/poweron.ini.example†L1-L52】 |

## Configuration
1. Copy the sample configuration into the expected location:
   ```bash
   mkdir -p /config
   cp app/poweron.ini.example /config/poweron.ini
   ```
   The manager will automatically seed this example if the file is missing, but creating it ahead of time lets you version-control your own values.【F:app/power_manager.py†L52-L170】

2. Update `/config/poweron.ini` with your environment:
   - **`[GENERAL]`** – Toggle the automation (`ENABLED`), activate dry-run mode, and control verbose logging.【F:app/poweron.ini.example†L1-L4】
   - **`[NODE]`** – Describe the primary host: name, MAC for WOL, service port for health checks, and optional SSH credentials used during shutdowns.【F:app/poweron.ini.example†L6-L13】
   - **`[MAIL]`** – Provide IMAP connection and sender details when you want to react to incoming mail commands.【F:app/poweron.ini.example†L15-L20】
   - **`[POWERON]`** – Configure the subject keyword plus the list of authorised senders and their wake credits for e-mail based power-ons.【F:app/poweron.ini.example†L22-L25】
   - **`[POWEROFF]`** – Supply the shutdown keyword, allowed senders, and the SSH command that will shut down the primary node.【F:app/poweron.ini.example†L27-L30】
   - **`[EXTENDTIME]`** – Let trusted senders extend the shutdown window by defining defaults, maximums, and optional extend hours applied when processing the extension mail.【F:app/poweron.ini.example†L32-L38】
   - **`[EXTRANODES]`** – List additional machines that should mirror the primary node’s power state along with their credentials when remote shutdown is required.【F:app/poweron.ini.example†L40-L47】
   - **`[PUSHOVER]`** – Add your PushOver API token, user key, and desired notification sound so alerts reach the right destination.【F:app/poweron.ini.example†L49-L52】

3. Ensure the `/config` directory is writable so the manager can persist weekly credit usage to `poweron.json` and append activity logs in `/var/log`.【F:app/power_manager.py†L321-L341】【F:app/power_manager.py†L987-L1024】

## Installing dependencies
Install the Python requirements and external tools on the host that runs the automation:
```bash
pip install chump wakeonlan
sudo apt-get install sshpass
```
These packages cover PushOver integration, Wake-on-LAN packet generation, and non-interactive SSH commands used by the manager.【F:app/power_manager.py†L34-L37】【F:app/power_manager.py†L351-L369】

## Running the scripts
Each helper script can be executed directly with Python 3:
```bash
python app/poweron.py            # Wake the primary node
python app/poweroff.py           # Shut down the primary node
python app/poweronbymail.py      # Process power-on requests from mail
python app/poweroffbymail.py     # Process shutdown requests from mail
python app/poweroffdelaybymail.py# Extend the shutdown schedule via mail
python app/poweron_extra_nodes.py# Wake configured extra nodes
python app/poweroff_extra_nodes.py# Shut down extra nodes
```
The scripts immediately delegate to the shared manager, making them suitable targets for cron or external schedulers. Pair time-based crontab entries with the automation to maintain the desired daily rhythm, and schedule the mail-driven scripts frequently enough to react to inbox changes.【F:app/poweron.py†L1-L12】【F:app/power_manager.py†L375-L456】

## Monitoring and troubleshooting
- Review `/var/log/poweron.log`, `/var/log/poweroffbymail.log`, and `/var/log/extranodes.log` for timestamped activity notes.【F:app/power_manager.py†L321-L341】【F:app/power_manager.py†L504-L578】【F:app/power_manager.py†L886-L975】
- Inspect `/config/poweron.json` to see the remaining wake credits per sender; the file resets automatically at the start of each week.【F:app/power_manager.py†L987-L1028】
- Check PushOver notifications to confirm that actions succeeded without having to tail logs in real time.【F:app/power_manager.py†L531-L534】【F:app/power_manager.py†L918-L971】

With a single configuration file and unified logic, the PowerOn suite keeps your lab or home server responsive to schedules and remote triggers alike while remaining easy to audit and adjust.
