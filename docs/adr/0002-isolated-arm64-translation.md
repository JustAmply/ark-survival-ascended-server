# ADR 0002: Isolate experimental ARM64 translation

Status: Accepted for the experimental ARM64 track

## Context

ARK and SteamCMD require x86 execution, while the stable image and supervisor
already serve native AMD64. Translation must not replace that base or change
its crash-restart policy. A SquashFS RootFS would require runtime FUSE mounts
that ordinary containers do not provide.

## Decision

Keep the existing AMD64 Python image in its own build stage. Install pinned
FEX and a checksum-verified, extracted x86 RootFS only in the ARM64 stage.
Publish ARM64 under separate experimental tags and verify it on native ARM CI.

`ExecutionContext` owns command wrapping. SteamCMD updates, Proton asset
selection, preflight and server launch receive it explicitly. Runtime settings
remain the configuration source; child profiles do not mutate process settings.
Only completed translated server runs use the early-crash profile retry.

## Consequences

AMD64 keeps its current OS, package set, environment and restart behavior.
The extracted RootFS needs more image space but avoids privileged mounts.
FEX and RootFS pins must be updated together with native smoke verification.
Image checks cannot replace an ARK startup and soak test on the target host.

To retire the experiment, remove the ARM64 image stage and CI job, translation
settings and adapter calls, and the translated retry policy. SteamCMD's native
wrapper, Proton selection/preflight, launch environments and shutdown contracts
remain independently usable. No control-tool dependency or game-data schema
belongs to the translation layer.
