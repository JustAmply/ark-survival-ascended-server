# Password files and strict startup

Use a mounted file when you want to keep a password out of the Compose
environment. The runtime and `asa-ctrl` accept these UTF-8 file settings:

- `ASA_SERVER_ADMIN_PASSWORD_FILE`
- `ASA_SERVER_PASSWORD_FILE`
- `ASA_SPECTATOR_PASSWORD_FILE`

Each file supplies its corresponding named launch setting. Do not set the direct
variable and its `_FILE` variant together, even with an empty direct value: this
is rejected as ambiguous. Unreadable files, invalid UTF-8 and empty files fail
configuration resolution rather than falling back to a default password.

Trailing line endings are removed. Use a single password without whitespace,
`?`, quotes, backslashes or NUL characters: these cannot be represented safely
as a password in the current launch-line query/token grammar. Error messages
never include the contents or path of a secret file. Launch-line diagnostics
redact the resolved password using the same rules as direct settings.

File values follow the same [precedence as named launch variables](../SETUP.md#legacy-launch-strings-and-precedence).

## Docker Compose

Replace the existing `ASA_SERVER_ADMIN_PASSWORD` environment entry with the
file setting when using this example; do not leave both in the service:

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

Create the source file outside version control. It must be readable inside the
container by the gameserver user (UID/GID 25000); startup resolves the password
after dropping privileges. This avoids putting the password itself in Compose
environment configuration, but the game still receives its resolved password in
the launch line. Secret files do not hide it from administrators of the host.

`ASA_REQUIRE_ADMIN_PASSWORD=1` disables automatic insertion of the legacy
fallback password. An explicit password from the launch line, named variable,
secret file or `GameUserSettings.ini` is required before launching. With no
launch line, the default map still works when an INI password is present.
The switch defaults to off to preserve existing stacks. It checks that a
password is configured; it does not enforce password strength.

After rotating a file, run `docker compose up -d --force-recreate -t 300 asa-server-1`
to remount it and apply the new password, including when only the file contents
changed. The supervisor keeps the launched password for shutdown RCON even if
the file changes or disappears. An external `asa-ctrl status` or RCON invocation reads the current
file and may fail authentication until the server has restarted with that value.
