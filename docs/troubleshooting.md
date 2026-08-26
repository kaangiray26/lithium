# Troubleshooting: crash/hang triage

Workflow distilled from actually debugging Lithium's Wine/DXVK/MoltenVK
stack (see `docs/plan.md` Phase 4 and the WoW64 installer bug for the case
this was built around). Applies to any future game, not just Silksong.

## First question: is it actually stuck, or just slow?

Everything in this stack runs through Rosetta 2, and a fresh Wine prefix's
first boot alone can take several minutes. **A single low-CPU `ps` snapshot
is not enough to tell "stuck" from "slow."** Confirm properly:

- Watch for **external progress**: growing log file size (with verbose
  `WINEDEBUG`), growing files on disk, growing process memory (RSS). If
  none of these move over several checks spaced minutes apart, that's a
  real signal — one snapshot isn't.
- Sample the actual CPU-heavy thread twice, a few seconds apart:
  ```
  sample <pid> 2 -f /tmp/a.txt
  sleep 5
  sample <pid> 2 -f /tmp/b.txt
  grep "Rosetta JIT" /tmp/a.txt /tmp/b.txt | sort | uniq -c | sort -rn
  ```
  Real, varied computation shows many different addresses. **The same 1-2
  addresses dominating both samples is a strong signal of a genuine stuck
  spin loop**, not legitimate slow work — this is exactly how the WoW64
  installer hang was confirmed.
- Check `WINEDEBUG=+server` output during the stall. If wineserver calls
  are still happening, it's progressing through real Windows API work
  (slowly). **If there's zero `+server` output while CPU is pegged, the
  process is spinning in pure user-mode code with no syscalls at all** —
  that's not going to resolve on its own.

## If it's confirmed stuck

- Kill the specific stuck process first (`kill -9 <pid>`), not the whole
  session, and check whether wineserver survives cleanly.
- **Force-killing a process while it's mid-spin can corrupt wineserver's
  own lock state** — after such a kill, watch for wineserver itself
  spinning at high CPU afterward. If that happens, there's no recovering
  that session: `pkill -9 -f wineserver` and every remaining `C:\...`
  child process, then start a fresh prefix or relaunch.
- Don't call `wine wineboot -k` on a session you suspect is already
  corrupted — it can itself hang (observed once after a bad kill).

## Useful debug channels

- `WINEDEBUG=+server,+seh` — see wineserver round-trips; look for either
  silence (pure spin) or a tight repeating pattern (busy-poll).
- `DXVK_LOG_LEVEL=info` — DXVK's own instance/device/adapter selection
  logging. Look for `Skipping: Device does not support required feature
  'X'` — this is DXVK rejecting the only GPU over a feature Apple hardware
  doesn't have. Fix by finding that feature in
  `dxvk/src/dxvk/dxvk_device_info.cpp`'s `getFeatureList()` and changing
  its `ENABLE_FEATURE(..., true)` to `false`, but only after confirming via
  the MoltenVK source (`grep` for the feature name in `MVKDevice.mm`) that
  it's a genuine, permanent hardware gap and not something that should
  actually work.
- `WINEDEBUG=-all` for otherwise-noisy runs (e.g. `+relay`,
  default channels) — cuts log volume to just explicit `fixme`/`err`
  lines and your own log output, which is usually enough for a first pass.

## Reproducing hangs cheaply

If a hang only appears after a slow setup step (e.g. a multi-minute wizard
before the actual failure), look for a way to skip straight to the failing
step before doing repeated debug iterations:
- InnoSetup installers: `/VERYSILENT /LANG=english /SUPPRESSMSGBOXES`
  skips the entire wizard UI (including dialogs Wine can't expose to macOS
  Accessibility for scripted clicking — Wine's own window content isn't
  visible to `System Events`, only the outer window chrome is).
- This turned a ~50-minute-to-reproduce hang into a ~30-second one,
  making it practical to test multiple hypotheses.

## When Wine itself is the bug, not your config

Not every hang is fixable by configuration. The WoW64 32-bit installer hang
(see `project_lithium_wow64_installer_bug` in memory) was root-caused to a
likely bug in Wine's own userspace "fast sync" primitive under
WoW64-on-Rosetta, with no available toggle to disable it in this Wine
version. When you hit something like this:
- Check if the *actual payload* even needs the failing path. Modern 64-bit
  Windows games often ship 32-bit-only installers/stubs wrapping 64-bit
  game data — extracting directly with a native tool (`innoextract` for
  InnoSetup) can route around the whole problem.
- Don't sink more time into root-causing a Wine-internals bug than the
  problem actually warrants for the game at hand. Document it (here, and
  in memory) and move on with a workaround.
