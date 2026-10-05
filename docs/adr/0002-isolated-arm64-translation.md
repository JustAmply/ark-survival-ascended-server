# ADR 0002: Isolate experimental ARM64 translation

Status: Accepted for the experimental ARM64 track

## Context

ARK and SteamCMD require x86 execution, while the stable image and supervisor
already serve native AMD64. Translation must not replace that base or change
its crash-restart policy. A SquashFS RootFS would require runtime FUSE mounts
that ordinary containers do not provide.

## Decision

Keep the existing AMD64 Python image in its own build stage. Run the application
on Python 3.14 on both architectures. Build checksum-verified CPython against
Ubuntu 24.04 in a separate stage for ARM64, then copy its runtime under
`/usr/local`. Do not overwrite Ubuntu's system Python or copy a newer Debian
libc-dependent interpreter into Ubuntu. Build tooling and PPA setup helpers
are absent from the final image. Install pinned FEX only in the ARM64 stage.
Build the x86 RootFS in a separate AMD64 Ubuntu stage from signed distribution
packages. Declare the 32-bit SteamCMD and 64-bit Proton library closure and keep
guest Python, font, Vulkan-loader and X11 libraries for headless Wine. Exclude
desktop applications, GPU drivers and LLVM. Remove guest identity and mount
files according to FEX's custom RootFS contract so container users, DNS and
game volumes remain visible. Link this directory into ARM64 without depending
on a dated FEX CDN snapshot. QEMU is used only for this guest build stage on
ARM64 CI; the runtime smoke checks execute native ARM64 FEX.
Stable launch wrappers precede the independent
application source layers so code edits do not regenerate them.
Publish ARM64 under separate experimental tags and verify it on native ARM CI.

The immutable `ExecutionContext` owns command wrapping. SteamCMD updates,
Proton asset selection, preflight and server launch receive it explicitly. Runtime settings
remain the configuration source; the supervisor owns successful probe status,
the effective profile and early-crash count across relaunches. The launch
environment applies the effective profile; child profiles do not mutate
process settings.
Only completed translated server runs use the early-crash profile retry.

Each translated server run owns a process group and its Wine prefix session.
After the RCON save and delay, request `wineboot --end-session --shutdown`
through Proton's `runinprefix` before process signals. This preserves the
launched prefix's library paths and synchronization settings and reaches
applications that left the process group. The request is bounded to 30 seconds;
failure is logged and proceeds to process signals and prefix cleanup.
Shutdown gives living group members the configured graceful timeout even if
the wrapper exits first. Cleanup stops the prefix's Wine server before a
relaunch, since Wine children can leave the process group and otherwise carry
the previous synchronisation profile into the next run. Native lifecycle
behaviour remains unchanged.

## Consequences

AMD64 keeps its current OS, package set, environment and restart behavior.
The extracted RootFS needs more image space but avoids privileged mounts.
FEX pins and the guest package set must be updated with native smoke verification.
Python compilation and guest preparation are cached independently of application
code. CI reports the final image and RootFS sizes to make growth reviewable.
Image checks cannot replace an ARK startup and soak test on the target host.

To retire the experiment, remove the ARM64 image stage and CI job, translation
settings and adapter calls, and the translated retry policy. SteamCMD's native
wrapper, Proton selection/preflight, launch environments and shutdown contracts
remain independently usable. No control-tool dependency or game-data schema
belongs to the translation layer.
