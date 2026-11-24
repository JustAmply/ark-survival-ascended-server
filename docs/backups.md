# Back up and recover a world

Run the backup on the Docker host using Python 3.15 and an account with Docker
CLI access. If you installed from the README, download the standalone
[backup script](../scripts/backup_server.py) into your Compose directory first:

```bash
mkdir -p scripts
wget -O scripts/backup_server.py https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/scripts/backup_server.py
```

The script copies each selected server's `ShooterGame/Saved` tree (worlds and
INI files), `mods.json`, shared cluster transfer data and any host files named
with `--include`. Game binaries, SteamCMD and Proton can be downloaded again.
The script expects the [standard volume mounts](../SETUP.md#storage-and-backups)
and an initialized server with both `Saved` and `mods.json` present.

## Create and schedule a backup

From the directory containing `docker-compose.yml` and `.env`, run:

```bash
python3.15 scripts/backup_server.py backup --stop \
  --container asa-server-1 --directory /srv/asa-backups --keep 7 \
  --include docker-compose.yml --include .env
```

This stops the server for the copy, verifies the archive and restarts any
selected container that was previously running, including after a copy or
verification error. Stopped containers stay stopped. The default stop timeout
is 300 seconds. Increase `--stop-timeout` if your shutdown needs more time.

For a cluster, repeat `--container` for each member. Shared transfer data is
copied once. A running unselected container using the same data blocks the
backup. To manage downtime yourself, stop the containers with
`docker compose stop -t 300`, omit `--stop`, then start them after the backup.
The tool copies from existing containers, so keep them in place.

For example, a host cron job can run daily at 03:00 in the host's timezone:

```cron
0 3 * * * cd /opt/asa && /usr/bin/python3.15 scripts/backup_server.py backup --stop --container asa-server-1 --directory /srv/asa-backups --keep 7 --include docker-compose.yml --include .env >> /var/log/asa-backup.log 2>&1
```

Adapt paths and add every intended cluster member with another `--container`.
Run under an account authorized to use Docker, keep other writers out, and
prevent overlapping runs. Monitor the job's exit status, including whether Docker
could restart the servers.

Archives contain a manifest and SHA-256 digest for every file. A newly written
archive is fully verified before it receives its final name and retention runs.
`--keep` retains the newest N valid `asa-backup-*.zip` archives in this dedicated
directory; it never removes invalid or unrelated files. Do not share the directory
with backups from another cluster. Keep a separate off-host copy. Archives may
contain passwords: newly created backup directories use mode 0700 and archives
0600 on POSIX; configure equivalent ACLs on Windows. SHA-256 detects corruption,
not malicious replacement of both files and their manifest.

## Verify and perform a recovery drill

```bash
python3.15 scripts/backup_server.py verify /srv/asa-backups/asa-backup-EXAMPLE.zip
python3.15 scripts/backup_server.py restore /srv/asa-backups/asa-backup-EXAMPLE.zip \
  --destination /srv/asa-recovery-drill
```

The destination's parent must exist; the destination itself must not exist. The
script verifies all archive bytes before extraction, rejects unsafe archive paths,
then verifies the extracted files again. It never writes into an existing world
or automatically changes live volumes. Empty directories are preserved.

Use `manifest.json` to map `servers/0`, `servers/1`, etc. to the original container
names and `clusters/0`, etc. to their shared cluster data. To recover service,
prepare new server-files and cluster-shared volumes with the usual Compose mounts.
With all cluster members stopped, copy each server's `Saved` directory into
`ShooterGame/Saved`, `mods.json` into the server-files root, and each cluster's
contents into its shared volume. Restore included configuration from
`configuration/<index>/<filename>` after reviewing host-specific paths and ports.
The runtime normalizes volume ownership on startup. Keep original volumes until
the recovered world has been started separately and checked in game.

Byte verification is a repeatable restore check, not proof that ARK can load a
particular world. Include an isolated game-server startup in periodic recovery
drills; do not run the drill against the production cluster volume.
