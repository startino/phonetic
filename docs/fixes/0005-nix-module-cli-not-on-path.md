# NixOS: `phonetic` CLI not on PATH — Wayland triggers unreachable

**Date:** 2026-06-03
**Symptom:** On a NixOS host with `services.phonetic.enable = true`, the service
runs fine but `phonetic` in a shell returns `fish: Unknown command: phonetic`.
Consequently the documented Wayland workflow (`phonetic --list-profiles`,
compositor keybindings `exec phonetic --trigger <profile>`) cannot run at all.
**Affected:** `nix/module.nix`
**Root cause:** The module declared `systemd.user.services.phonetic` with an
absolute-store-path `ExecStart`, but never added `cfg.package` to
`environment.systemPackages`. So the binary existed only at its `/nix/store/...`
path — not on any interactive shell or graphical-session PATH. The systemd
service worked (absolute path), masking the fact that the CLI was uninstalled.
The Wayland trigger model depends entirely on the CLI being PATH-resolvable both
for the user's shell and for the compositor's `exec` environment.

## Investigation
1. v0.6.8 deployed cleanly (`phonetic-0.6.8` store path, `active (running)`).
2. Operator ran `phonetic` → `Unknown command`. The service binary was at
   `/nix/store/gg1...-phonetic-0.6.8/bin/.phonetic-wrapped` (per `systemctl
   status`), confirming the package builds and runs but isn't on PATH.
3. Read `nix/module.nix`: no `environment.systemPackages`, no `home.packages` —
   nothing exposes the CLI. Enabling the service installs a unit but not the
   command it documents.

## Fix
`nix/module.nix`: added `environment.systemPackages = [ cfg.package ];` inside
`config = lib.mkIf cfg.enable { ... }`. Enabling the service now puts `phonetic`
on `/run/current-system/sw/bin`, so both the shell and compositor `exec`
keybindings resolve it.

Immediate workaround before redeploy: invoke by absolute store path, e.g.
`/nix/store/<hash>-phonetic-0.6.8/bin/phonetic --list-profiles` (hash visible in
`systemctl --user status phonetic.service`).

**Commit:** see git log (v0.6.9)
