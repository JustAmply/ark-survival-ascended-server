# Password files and strict startup

Keep passwords outside the Compose environment with `ASA_SERVER_ADMIN_PASSWORD_FILE`, `ASA_SERVER_PASSWORD_FILE` or `ASA_SPECTATOR_PASSWORD_FILE`. Each follows the [precedence of its named setting](../SETUP.md#legacy-launch-strings-and-precedence).

## Docker Compose

Replace the direct password variable with its `_FILE` setting. Defining both prevents startup, even if one is empty.

```yaml
services:
  asa-server-1:
    environment:
      ASA_SERVER_ADMIN_PASSWORD_FILE: /run/secrets/asa_admin_password
      ASA_REQUIRE_ADMIN_PASSWORD: "1"
    secrets:
      - asa_admin_password

secrets:
  asa_admin_password:
    file: ./secrets/admin-password.txt
```

- **File contents.** Store one nonempty UTF-8 password outside version control, readable by UID/GID 25000. Trailing line endings are stripped. Avoid whitespace, `?`, quotes, backslashes and NUL characters. Host administrators can still inspect the resolved launch arguments.
- **Require an admin password.** `ASA_REQUIRE_ADMIN_PASSWORD=1` blocks startup unless a launch setting, password file or `GameUserSettings.ini` supplies the admin password. The default allows the legacy fallback.
- **Rotate a password.** Replace the file, then recreate the service so the game and control commands use the new value:

```bash
docker compose up -d --force-recreate -t 300 asa-server-1
```
