# Lithium — Implementation Roadmap

Compatibility tool for macOS (Apple Silicon) based on Wine + Valve's Proton
components, to run unmodified Windows games. Target/dev machine: Mac mini,
Apple M4 Pro (arm64), macOS 15.7.7.

## Architecture decision (read first)

Apple Silicon has no native x86_64 CPU and no native Vulkan/DirectX, so two
translation layers are required, stacked:

```
Windows game (x86_64 PE, DirectX)
  -> Wine (Win32/PE loader + API emulation)      [built as x86_64, runs under Rosetta 2]
  -> DXVK / vkd3d-proton (D3D9/10/11 -> Vulkan, D3D12 -> Vulkan)
  -> MoltenVK (Vulkan -> Metal)
  -> Metal (GPU, M4 Pro)
```

Rationale, given what's actually available locally (see `docs/resources.md`):

- **Wine**: use the vanilla WineHQ clone (`~/external/wine`), which has an
  actively maintained native macOS "Mac driver". Do **not** try to build
  Proton's own pinned `wine` submodule — it resolves to Valve's Linux-only
  fork (esync/fsync, Linux-specific syscalls) and is not macOS-portable.
  We build wine as an **x86_64** binary so the entire process tree (wine +
  the Windows game's x86_64 code) runs transparently under **Rosetta 2**,
  which is already active on this machine. This is the same trick
  CrossOver/Whisky rely on and is far more realistic than a native-arm64
  wow64 wine for an MVP.
- **Graphics**: Apple's real "Game Porting Toolkit" (the private
  Wine+D3DMetal fork used by CrossOver/Whisky) is not open source and isn't
  what's cloned at `~/external/game-porting-toolkit` — that repo is Apple's
  *newer* docs/skills repo for porting **native** game source to Metal, and
  doesn't contain a Wine/DirectX translation stack at all. So Lithium's
  graphics path has to be assembled from open components: Valve's **DXVK**
  and **vkd3d-proton** (both referenced as submodules in `~/external/Proton`
  but currently uninitialized/empty) targeting Vulkan, plus **MoltenVK**
  (Vulkan-on-Metal) to actually reach the GPU. MoltenVK is not cloned
  anywhere yet and must be fetched (Homebrew `molten-vk`/`vulkan-sdk`, or
  `KhronosGroup/MoltenVK` source) — this is a gap in `docs/resources.md`.
- **Proton repo's role**: not used as a Linux/container build system (its
  Docker/Podman "Proton SDK" pipeline targets Linux and is irrelevant here).
  It's used as a *reference and parts bin*: the `proton` launcher script
  structure, `dxvk-nvapi`, `wineopenxr`, `steam_helper`/`lsteamclient`
  (only if/when Steam features are wanted later), and its default Wine
  prefix setup (`default_pfx.py`) as a model for Lithium's own prefix
  bootstrapping. `FEX` (x86-on-ARM Linux CPU emulation) is irrelevant on
  macOS and is skipped entirely — Rosetta 2 replaces it.
- **metal-cpp**: only becomes relevant if/when Lithium grows a native macOS
  GUI/launcher or a custom Metal-based DXVK backend later. Not needed for
  the MVP CLI/wine-prefix pipeline.
- **Game files**: the provided Silksong files are a two-part **InnoSetup
  offline installer** (`setup_...exe` + `...-1.bin`), not raw installed game
  files. Lithium must be able to *run a Windows installer inside a prefix*,
  not just launch a pre-installed `.exe`.

## Phase 0 — Environment & toolchain prep

- [ ] Install missing native build dependencies via Homebrew: `autoconf`,
      `automake`, `libtool`, `pkg-config`, `meson`, `ninja`, `gettext`,
      `freetype`, `sdl2` (already present), `molten-vk`, `vulkan-loader`
      (or `vulkan-sdk`), `gnutls`, `mpg123`, `sane-backends` deps as needed.
- [ ] Confirm full Xcode (not just Command Line Tools) is installed if wine's
      macOS build requires it; confirm macOS SDK version compatible with
      current WineHQ master.
- [ ] Decide and record Wine source baseline: pin a specific WineHQ commit/tag
      in `~/external/wine` known to have working macOS Mac-driver + Vulkan
      (winevulkan) support; avoid building against a moving `master`.
- [ ] Initialize the Proton submodules actually needed (`dxvk`, `vkd3d-proton`,
      `dxvk-nvapi`, `Vulkan-Headers`, `Vulkan-Loader`) — skip Linux/media-only
      ones (`gstreamer`, `ffmpeg`, `FEX`, `openvr`, etc.) until proven needed.
- [ ] Set up a scratch build directory + a repo layout in `lithium/` for
      build scripts, patches, and the resulting toolchain (e.g.
      `build/`, `patches/`, `scripts/`, `dist/`).

## Phase 1 — Baseline Wine on Apple Silicon

- [ ] Configure and build WineHQ wine as an **x86_64** macOS binary with the
      Mac driver enabled (`--enable-win64` as appropriate), running under
      Rosetta 2.
- [ ] Create a minimal Wine prefix (`WINEPREFIX`) and confirm `wineboot`
      completes cleanly.
- [ ] Run a trivial Win32 executable (e.g. `notepad.exe`, a "hello world"
      PE binary) to validate the Wine + Rosetta 2 + Mac driver path end to end.
- [ ] Validate windowing (a wine window actually renders on macOS via the Mac
      driver), keyboard/mouse input, and basic CoreAudio sound output.

## Phase 2 — Vulkan-on-Metal graphics path

- [ ] Build/install MoltenVK for macOS arm64 and confirm a standalone Vulkan
      sample (e.g. `vkcube`) renders via Metal.
- [ ] Build wine's `winevulkan` and confirm Wine can enumerate/use the Vulkan
      ICD (MoltenVK) from inside a Windows process.
- [ ] Build DXVK (from `~/external/Proton/dxvk` submodule, pinned) targeting
      this Vulkan/MoltenVK stack; identify and patch any Linux-only
      assumptions (may require pulling in known community macOS patches).
- [ ] Install DXVK's `d3d9/d3d10/d3d11.dll` overrides into the test prefix and
      validate with a small DirectX 11 sample/benchmark before touching the
      real game.
- [ ] Build `vkd3d-proton` (D3D12 -> Vulkan) the same way; validate with a
      minimal D3D12 sample. (Lower priority than D3D11 — confirm which API
      Silksong's Unity build actually uses before investing heavily here.)

## Phase 3 — Lithium tooling (the actual "compat tool")

- [ ] Design Lithium's on-disk layout: bundled Wine build, DXVK/vkd3d-proton
      DLLs, default prefix template — modeled on Proton's `dist/` tree and
      `default_pfx.py`, adapted for macOS paths.
- [ ] Write a `lithium` CLI (shell or Python, matching Proton's `proton`
      script style) supporting at minimum:
      - [ ] `lithium prefix create <name>`
      - [ ] `lithium run <prefix> <exe> [args...]` (sets `WINEPREFIX`, DLL
            overrides, env vars, launches via Rosetta-backed wine)
      - [ ] `lithium install <prefix> <installer.exe>` (for running Windows
            installers, e.g. the Silksong InnoSetup installer)
- [ ] Decide MVP distribution shape: standalone CLI/launcher first (since the
      test game is an offline installer, not a Steam depot); Steam
      `compatibilitytool.vdf` integration is a stretch goal, not required
      for MVP.
- [ ] Basic logging/diagnostics command (`lithium doctor`) to dump Wine/DXVK/
      MoltenVK versions and catch missing dependencies early.

## Phase 4 — Get Hollow Knight: Silksong installed and running

- [ ] Create a dedicated Lithium prefix for Silksong.
- [ ] Run the two-part installer (`setup_...exe`, using the co-located `.bin`
      part) inside the prefix via `lithium install`; verify it completes and
      produces installed game files.
- [ ] Launch the installed game executable via `lithium run`.
- [ ] Debug the graphics path first (Unity/DirectX renderer init, resolution/
      fullscreen handling, Metal frame presentation via MoltenVK).
- [ ] Debug input: keyboard/mouse first, then gamepad (wine's mac
      joystick/HID driver vs. macOS Game Controller framework) since
      Silksong is primarily controller-driven.
- [ ] Debug audio (CoreAudio via wine) and any video/cutscene codec needs
      (Unity often uses standard codecs; only pull in GStreamer/ffmpeg from
      Proton if something actually fails).
- [ ] Iterate on DLL overrides / wine registry tweaks / environment variables
      until the game reaches the main menu, then reaches gameplay, with
      stable frame pacing.

## Phase 5 — Stabilization & polish

- [ ] Shader cache persistence across runs (DXVK state cache) to avoid
      re-compiling shaders every launch.
- [ ] Performance pass: profile via Metal tools (`gpucapture`/Instruments),
      compare against expected M4 Pro performance for a 2D/2.5D Unity title.
- [ ] Crash/hang triage workflow (wine debug channels, core dumps, DXVK/wine
      logs) documented for future games, not just Silksong.
- [ ] Document known limitations (no D3DMetal, no Apple GPTK private
      backend, controller support caveats, etc.) in `docs/context.md`.

## Phase 6 — Beyond the first game (stretch)

- [ ] Generalize prefix templates / dependency install (equivalent of
      winetricks: VC++ redist, .NET, DXVK auto-install) for arbitrary games.
- [ ] Evaluate Steam Play `compatibilitytool.vdf` integration for launching
      Steam-owned games directly through Steam, reusing Proton's manifest
      format.
- [ ] Evaluate MetalFX upscaling / frame interpolation integration using
      `metal-cpp` for a future custom-Metal graphics backend, as a
      longer-term alternative to the DXVK+MoltenVK path.

## Open risks to flag before implementation starts

- DXVK and vkd3d-proton are developed and tested against Linux; macOS
  portability may require nontrivial patching (no epoll, different threading/
  memory primitives, etc.). This is the single biggest technical unknown.
- MoltenVK's Vulkan feature/extension coverage is not 1:1 with Linux
  Vulkan drivers; some DXVK features may be unavailable or behave
  differently.
- Wine's macOS Mac driver and winevulkan maturity should be spot-checked
  against the current WineHQ master before committing to a baseline commit.
