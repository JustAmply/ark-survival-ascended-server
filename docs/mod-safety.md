# Recover a mod database

If the server refuses to start because `mods.json` is unreadable or invalid,
preserve the file. On a fresh install a missing database creates an empty mod
list, so deleting a damaged file could launch an existing world without the
mods it needs.

1. Stop the affected service with `docker compose stop -t 300 asa-server-1`.
   Pause scripts and `asa-ctrl mods` commands that write to the same volume.
2. In the server-files volume, restore `mods.json` from a
   [verified backup](backups.md#verify-and-perform-a-recovery-drill), or repair the
   file and its permissions. The game user (UID/GID 25000) needs access to both
   the file and its directory.
3. Start the service and check its enabled database entries with
   `docker compose exec asa-server-1 asa-ctrl mods list --enabled-only`.
   For IDs also supplied in Compose, see [mods and custom maps](../SETUP.md#mods-and-custom-maps).

Use volumes that support file locking and atomic replacement. Control commands
coordinate through a persistent `mods.json.lock` file. Its presence after a
command finishes is normal. Manual edits bypass that lock, so make them only
while the server and mod commands are stopped.
