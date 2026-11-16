# Offline backups and recovery

Run `scripts/backup_server.py` on a host with Python 3.15 and Docker CLI access.
It has no third-party Python dependencies. It copies existing stopped containers
using `docker cp`; no helper image or direct Docker-volume filesystem access is
required. The containers must have completed at least one successful startup:
`ShooterGame/Saved` and `mods.json` must exist. A missing or unreadable source
aborts the backup instead of silently omitting data.

## Create and schedule a backup

Stop every server sharing the cluster first, allowing its save/shutdown sequence
to finish. Keep deployments, manual starts and other writers disabled throughout
the backup window. The script checks for running containers sharing the selected
mounts both before and after copying, but cannot lock out an external operator.
Use `stop`, not `down`: the stopped containers are the copy source.

```bash
docker compose stop -t 300
python scripts/backup_server.py backup \
  --container asa-server-1 --container asa-server-2 \
  --directory /srv/asa-backups --keep 7 \
  --include docker-compose.yml --include .env
docker compose start
```

Select every server whose world belongs in the backup; a shared cluster is copied
once. Remove `--container asa-server-2` for a single-server deployment. The script
expects the standard server-files and cluster-shared mount destinations. It
includes the entire `ShooterGame/Saved` tree (worlds and INI configuration),
`mods.json`, cluster transfer data and explicitly included host configuration.
Downloadable game binaries, SteamCMD and Proton are excluded.

For unattended operation, add `--stop`. This first checks that no unselected
running container shares the data, stops only selected containers that were
running, then restarts those containers in a `finally` block even if copying or
verification fails. Already stopped containers remain stopped. The default stop
timeout is 300 seconds; increase `--stop-timeout` when your save/shutdown settings
require longer. A Docker daemon failure or forced termination of the backup
process can prevent the restart, so monitor the scheduled job's exit status.

For example, a host cron job can run daily at 03:00 in the host's timezone:

```cron
0 3 * * * cd /opt/asa && /usr/bin/python3.15 scripts/backup_server.py backup --stop --container asa-server-1 --directory /srv/asa-backups --keep 7 --include docker-compose.yml --include .env >> /var/log/asa-backup.log 2>&1
```

Adapt paths and add every intended cluster member with another `--container`.
Run under an account authorized to use Docker, keep other writers out, and
configure the scheduler to prevent overlapping runs. No scheduling daemon is
added to the game image.

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
python scripts/backup_server.py verify /srv/asa-backups/asa-backup-EXAMPLE.zip
python scripts/backup_server.py restore /srv/asa-backups/asa-backup-EXAMPLE.zip \
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
