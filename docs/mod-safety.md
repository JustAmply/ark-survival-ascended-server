# Recover a mod database

**Keep the damaged `mods.json`.** Deleting it can start the world with an empty list of database-managed mods.

1. Stop the service with `docker compose stop -t 300 asa-server-1`. Pause scripts or commands that edit mods.
2. Restore `mods.json` in the server-files volume from a [verified backup](backups.md#verify-and-perform-a-recovery-drill), or repair it. Check that UID/GID 25000 can access the file and its directory.
3. Run `docker compose start asa-server-1`, then `docker compose exec asa-server-1 asa-ctrl mods list --enabled-only`. Check [Compose mod IDs](../SETUP.md#mods-and-custom-maps) separately.

The persistent `mods.json.lock` file is normal. Use storage that supports locking and atomic replacement. Edit the database manually only while the server and mod commands are stopped.
