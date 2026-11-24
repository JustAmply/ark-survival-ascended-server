# Back up and recover a world

Run the [backup script](../scripts/backup_server.py) on the Docker host with Python 3.15 and Docker CLI access. It backs up world saves, INI files, `mods.json`, cluster transfers and files selected with `--include`. The server must have initialized its [standard volumes](../SETUP.md#storage-and-backups).

<details>
<summary>Get the script if you followed the README quick start</summary>

From your Compose directory:

```bash
mkdir -p scripts
wget -O scripts/backup_server.py https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/scripts/backup_server.py
```

</details>

## Create and schedule a backup

Run from the directory containing `docker-compose.yml` and `.env`:

```bash
python3.15 scripts/backup_server.py backup --stop \
  --container asa-server-1 --directory /srv/asa-backups --keep 7 \
  --include docker-compose.yml --include .env
```

- **Downtime.** `--stop` stops the selected servers and restarts those previously running, even after a copy error. Increase `--stop-timeout` if shutdown needs more than 300 seconds. For manual stops, keep the stopped containers and omit `--stop`.
- **Clusters.** Repeat `--container` for each member. An unselected running container sharing the data blocks the backup.
- **Retention.** `--keep 7` keeps the seven newest valid archives. Use a separate directory per cluster and keep a private off-host copy. Archives can contain passwords.

<details>
<summary>Schedule a daily backup with cron</summary>

This example runs at 03:00 in the host timezone. Adapt the paths and containers, prevent overlapping writes and monitor the job's exit status.

```cron
0 3 * * * cd /opt/asa && /usr/bin/python3.15 scripts/backup_server.py backup --stop --container asa-server-1 --directory /srv/asa-backups --keep 7 --include docker-compose.yml --include .env >> /var/log/asa-backup.log 2>&1
```

</details>

## Verify and perform a recovery drill

Replace the example archive name. Choose a new destination under an existing directory.

```bash
python3.15 scripts/backup_server.py verify /srv/asa-backups/asa-backup-EXAMPLE.zip
python3.15 scripts/backup_server.py restore /srv/asa-backups/asa-backup-EXAMPLE.zip \
  --destination /srv/asa-recovery-drill
```

Restore verifies SHA-256 checksums before and after extraction. To test the world in ARK:

1. Prepare fresh server and cluster volumes. Keep all recovery servers stopped while copying.
2. Use `manifest.json` to match each `servers/<index>` to its container. Copy its `Saved` to `ShooterGame/Saved` and `mods.json` to the server-files volume root.
3. Copy each `clusters/<index>` into its matching shared volume. Review paths and ports before restoring files from `configuration/<index>`.
4. Start the recovered world separately and check it in game before retiring the original volumes.
