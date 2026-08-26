# context

Project-related information for later use. See `docs/plan.md` for the
roadmap/checklist and architecture rationale; this file is for living
details (known limitations, status) that don't belong in a checklist.

## Known limitations (as of the Silksong milestone)

- **No Apple Game Porting Toolkit / D3DMetal.** Lithium is built entirely
  from open components (Wine + DXVK + MoltenVK). This is slower and less
  feature-complete than Apple's private CrossOver-derived engine, by design
  — see `docs/plan.md`'s architecture section for why that engine isn't
  available to build on.
- **No vkd3d-proton (D3D12) yet.** Only the D3D9/10/11 path (via DXVK) has
  been built and validated. Any game requiring D3D12 will not run until
  this is added (Phase 2 of the plan).
- **DXVK feature set is trimmed for Apple GPUs.** `geometryShader`,
  `shaderCullDistance`, and `VK_EXT_depth_clip_enable` are permanently
  unavailable on Apple Silicon GPUs (Metal has no equivalent) and were
  patched to be optional rather than required in DXVK. Any game whose
  rendering actually depends on geometry shaders or cull distance will
  likely render incorrectly or fail, not just run slower. See
  `project_lithium_dxvk_patches` in memory for the full patch list.
- **32-bit Windows code (WoW64) is unreliable.** Wine's WoW64 mode hangs
  reliably on at least one real workload (InnoSetup installer extraction)
  under Rosetta 2 — a low-level Wine bug, not something Lithium can patch
  around the way the DXVK issues were. Basic 32-bit execution (a plain
  32-bit `cmd.exe`) does work, so it's not a blanket failure, but any
  32-bit-heavy workload is a risk. Installers of this type should be
  extracted with `innoextract` (for InnoSetup) rather than run through
  Wine. See `project_lithium_wow64_installer_bug` in memory.
- **Video/cutscene playback is broken for at least one video** — confirmed
  via play-testing: the game's opening cutscene (played back separately
  from in-engine Unity rendering, likely via Media Foundation) showed as
  blank instead of playing. Root cause identified in the log: Wine's
  `winegstreamer` COM class `{317df618-...}` ("Generic Decodebin Byte
  Stream Handler") isn't registered, because this Wine build has no
  GStreamer support (skipped in Phase 0 as "not proven needed" — now
  proven needed). Fix: build GStreamer (x86_64) and reconfigure/rebuild
  Wine with it. Not yet done — gameplay itself is unaffected, so this is
  cosmetic/incomplete rather than blocking.
- **No packaged `dist/` yet.** `scripts/lithium` points directly at the dev
  build trees under `build/wine` and `build/dxvk`, not a relocatable,
  packaged runtime. Fine for single-machine development, not yet suitable
  for distributing to another Mac.
- **Single-game CLI.** `scripts/lithium` has no dependency-installation
  step (winetricks equivalent: VC++ redist, .NET, etc.) beyond DXVK's own
  DLLs. A second, different game will likely need this.

## Confirmed working (play-tested)

- **Audio** — sound effects and music play correctly.
- **Controller input, including vibration** — worked out of the box (menu
  navigation and in-game control), despite Wine logging a couple of
  unimplemented XInput/Windows.Gaming.Input stubs
  (`xinput:pdo_pnp code 0xc`, `controller_get_IsWireless`) during
  enumeration — those specific stubs don't block real input or rumble.
- **Core Unity/DXVK rendering** — main menu, in-engine cutscenes, and
  gameplay all render correctly with no reported visual issues.
- **Save and clean quit via the in-game menu** — process exits cleanly
  (`Destroyed VkDevice ...` in the log, no crash handler spawned).

## Status snapshot

Hollow Knight: Silksong installs (via `innoextract`, not the bundled
installer) and is fully playable — play-tested through the opening menu,
a new game, and into real gameplay, then saved and quit cleanly — on the
dev machine (Mac mini, Apple M4 Pro, macOS 15.7.7). The one confirmed gap
is the missing pre-rendered opening cutscene (see the GStreamer limitation
above); everything else tested clean. See `docs/plan.md` Phase 4 for the
full story and `README.md` for the milestone summary.
