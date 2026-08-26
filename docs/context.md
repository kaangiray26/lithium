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
- **Gamepad input not yet verified.** Silksong was only briefly played
  with keyboard/mouse-adjacent testing; controller support (wine's mac
  joystick/HID driver vs. macOS Game Controller framework) has not been
  specifically tested despite the game being primarily controller-driven.
- **Audio and video/cutscene codecs not specifically verified.** No issues
  were *reported*, but this hasn't been deliberately tested either.
- **No packaged `dist/` yet.** `scripts/lithium` points directly at the dev
  build trees under `build/wine` and `build/dxvk`, not a relocatable,
  packaged runtime. Fine for single-machine development, not yet suitable
  for distributing to another Mac.
- **Single-game CLI.** `scripts/lithium` has no dependency-installation
  step (winetricks equivalent: VC++ redist, .NET, etc.) beyond DXVK's own
  DLLs. A second, different game will likely need this.

## Status snapshot

Hollow Knight: Silksong installs (via `innoextract`, not the bundled
installer) and runs — confirmed playable (cutscenes + gameplay) on the dev
machine (Mac mini, Apple M4 Pro, macOS 15.7.7). See `docs/plan.md` Phase 4
for the full story and `README.md` for the milestone summary.
