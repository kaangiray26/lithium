# Hollow Knight: Silksong

- **Status**: Playable with issues.
- **Installed via**: `innoextract` directly on the offline GOG-style
  two-part installer (`setup_....exe` + `...-1.bin`), _not_ `lithium
install` — the installer's 32-bit InnoSetup stub hangs under
  Wine's WoW64-on-Rosetta combo (a real, unresolved Wine bug). The
  extracted game itself is 64-bit-only, so no WoW64 is needed once
  installed. Full story: `docs/troubleshooting.md`, `docs/plan.md`
  Phase 4, `project_lithium_wow64_installer_bug` in memory.
- **Confirmed working**: audio, controller input (including vibration),
  core rendering (menus, in-engine cutscenes, gameplay), save/quit,
  performance (rock-solid 59.9 FPS, no stuttering, GPU at 65%
  utilization), toggling VSync in-game (required pinning
  `dxgi.syncInterval` — see `docs/context.md`).
- **Known issue**: the pre-rendered opening cutscene is permanently
  blank. Root cause is a DXVK/MoltenVK platform gap
  (`VK_KHR_EXTERNAL_MEMORY_WIN32`, a Windows-only Vulkan extension no
  non-Windows Vulkan driver can implement) combined with Unity's Media
  Foundation video pipeline likely needing genuine cross-device D3D11
  texture sharing. Partially patched (`src/lithium/patches/wine-mfplat-shared-
video-texture.patch` eliminates the hard crash and lets the decode
  pipeline complete cleanly) but the video still doesn't visibly render.
  Gameplay itself is entirely unaffected — this is one skippable intro
  video. Full investigation: `project_lithium_gstreamer_video_bug` in
  memory.
- **Tested against**: Wine `wine-11.16`, DXVK `v2.7.1` + 498 commits,
  MoltenVK `v1.4.2` (see `docs/plan.md` Phase 7 for how these are
  pinned/reproduced via `lithium build`).
