# Mod database safety

The runtime refuses to launch when its configured `mods.json` cannot be read or
parsed. It never silently drops dynamic mods from an existing world. Restore a
known-good backup or repair the database and its permissions before restarting.
Do not delete a damaged database merely to make startup succeed: that would
discard the record of required mods.

A missing database is still initialized as an empty list for a new installation.

CLI reads and changes share a process-level lock in `mods.json.lock`. Every
change reloads the current database while holding that lock, then writes and
flushes a temporary sibling file before atomically replacing `mods.json`.
Concurrent CLI processes therefore cannot overwrite each other's changes with
stale snapshots. The lock file remains present; its existence does not mean a
process still holds the lock. Do not remove it while commands are running.

Use local filesystem volumes that support file locking and atomic replacement.
Manual edits and external tools must be performed with the server and control
commands stopped; they do not participate in this locking protocol.
