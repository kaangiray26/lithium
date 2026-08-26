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

## Phase 0 — Environment & toolchain prep ✅ done

- [x] Install missing native build dependencies via Homebrew: `autoconf`,
      `automake`, `libtool`, `pkg-config`, `meson`, `ninja`, `gettext`,
      `freetype`, `sdl2` (already present), `molten-vk`, `vulkan-loader`
      (or `vulkan-sdk`), `gnutls`, `mpg123`, `sane-backends` deps as needed.
      Also needed, not originally anticipated: `bison` (macOS's is too old),
      `mingw-w64` (Wine now requires a PE cross-compiler), and a second,
      **x86_64 Homebrew prefix at `/usr/local`** (Wine is built x86_64, so
      it needs x86_64 dylibs; arm64 Homebrew only ships arm64 bottles).
- [x] Confirm full Xcode (not just Command Line Tools) is installed if wine's
      macOS build requires it; confirm macOS SDK version compatible with
      current WineHQ master. (Needed for MoltenVK's `xcodebuild`, not Wine
      itself.)
- [x] Decide and record Wine source baseline: pin a specific WineHQ commit/tag
      in `~/external/wine` known to have working macOS Mac-driver + Vulkan
      (winevulkan) support; avoid building against a moving `master`. Built
      against wine-11.16.
- [x] Initialize the Proton submodules actually needed (`dxvk`, `vkd3d-proton`,
      `dxvk-nvapi`, `Vulkan-Headers`, `Vulkan-Loader`) — skip Linux/media-only
      ones (`gstreamer`, `ffmpeg`, `FEX`, `openvr`, etc.) until proven needed.
- [x] Set up a scratch build directory + a repo layout in `lithium/` for
      build scripts, patches, and the resulting toolchain (e.g.
      `build/`, `patches/`, `scripts/`, `dist/`).

## Phase 1 — Baseline Wine on Apple Silicon ✅ done

- [x] Configure and build WineHQ wine as an **x86_64** macOS binary with the
      Mac driver enabled, running under Rosetta 2. (Later rebuilt with
      `--enable-archs=i386,x86_64` for WoW64 — see Phase 4 note.)
- [x] Create a minimal Wine prefix (`WINEPREFIX`) and confirm `wineboot`
      completes cleanly. (First boot is genuinely slow, several minutes,
      under Rosetta — not a hang, verify via log growth not a single `ps`
      snapshot.)
- [x] Run a trivial Win32 executable (`wine cmd`) to validate the Wine +
      Rosetta 2 + Mac driver path end to end.
- [x] Validate windowing (`wine notepad` produced a real Mac-driver window,
      confirmed via `System Events` window enumeration). Keyboard/mouse and
      audio validated implicitly by the game running; not separately unit
      tested.

## Phase 2 — Vulkan-on-Metal graphics path ✅ done

- [x] Build/install MoltenVK for macOS arm64. (Validation switched from a
      standalone `vkcube` to Wine's own `vulkan-1_test.exe`, which confirmed
      MoltenVK correctly identifies the Apple M4 Pro and creates real
      VkInstance/VkDevice objects.)
- [x] Build wine's `winevulkan` and confirm Wine can enumerate/use the Vulkan
      ICD (MoltenVK) from inside a Windows process. Turned out to need zero
      shimming — Wine's configure natively detects MoltenVK as a `libvulkan`
      implementation given the right linker flags.
- [x] Build DXVK targeting this Vulkan/MoltenVK stack; identify and patch
      Linux-only assumptions. **This was the single biggest real blocker in
      the project** — see `project_lithium_dxvk_patches` in memory for the
      full list. DXVK hardcodes several Vulkan features as required that
      Apple GPUs permanently lack (`geometryShader`, `shaderCullDistance`)
      or that MoltenVK doesn't implement (`VK_EXT_depth_clip_enable`);
      relaxed those to optional in `dxvk_device_info.cpp`.
- [x] Install DXVK's `d3d9/d3d10/d3d11.dll` overrides into the test prefix and
      validate with `d3d11_test.exe` before touching the real game.
- [ ] Build `vkd3d-proton` (D3D12 -> Vulkan). **Not done** — Silksong is
      D3D11 (Unity), didn't need it. Revisit only when a D3D12 title shows up.

## Phase 3 — Lithium tooling (the actual "compat tool") ✅ MVP done

- [ ] Design Lithium's on-disk layout: bundled Wine build, DXVK/vkd3d-proton
      DLLs, default prefix template — modeled on Proton's `dist/` tree and
      `default_pfx.py`, adapted for macOS paths. **Skipped for the MVP** —
      `scripts/lithium` points straight at the dev build trees under
      `build/wine` and `build/dxvk` rather than a packaged `dist/`. Revisit
      before this goes beyond a single dev machine.
- [x] Write a `lithium` CLI (`scripts/lithium`) supporting:
      - [x] `lithium prefix-create <name>`
      - [x] `lithium run <name> <exe> [args...]`
      - [x] `lithium install <name> <installer>` (alias for `run` — see
            Phase 4 note on why installers need special-casing anyway)
      - [x] `lithium prefix-kill <name>` (clean session shutdown; not
            originally planned but needed once we learned killing
            wineserver mid-hang corrupts its lock state)
- [x] Decide MVP distribution shape: standalone CLI, no Steam integration.
- [x] `lithium doctor` — dumps Wine/DXVK/MoltenVK paths and checks they exist.

## Phase 4 — Get Hollow Knight: Silksong installed and running ✅ done

- [x] Create a dedicated Lithium prefix for Silksong.
- [x] Run the offline installer inside the prefix — **but not via
      `lithium install` in the end.** The InnoSetup installer stub is
      32-bit, which needs Wine's WoW64 mode (`--enable-archs=i386,x86_64`,
      rebuilt from the win64-only Phase 1 build). Under WoW64-on-Rosetta,
      the installer's extraction step reliably **hangs in a real Wine bug**
      — a pure userspace spin with zero wineserver calls, most likely in
      Wine's "fast sync" futex-style wait path. Never found a fix or an env
      var to disable it. **Workaround**: `brew install innoextract` and
      extract the installer directly (`innoextract --gog -d <dir>
      setup_....exe`) — no Windows code executes at all, so the bug never
      triggers. The actual game payload turned out to be 64-bit-only
      (`StandaloneWindows64` paths, typical for modern Unity titles), so it
      needs no WoW64 at all once extracted. Full writeup:
      `project_lithium_wow64_installer_bug` in memory.
- [x] Launch the installed game executable via `lithium run`.
- [x] Debug the graphics path — worked after the Phase 2 DXVK patches, no
      Silksong-specific graphics issues hit.
- [ ] Debug input beyond basic keyboard/mouse (gamepad specifically) —
      **not yet verified**, game was only briefly played.
- [ ] Debug audio / video codec needs — **not yet verified**, no issues
      *reported* so far but not specifically tested.
- [x] Reached gameplay (cutscenes + playable) with the user confirming they
      could play. Frame pacing/perf not rigorously measured.

## Phase 5 — Stabilization & polish (next up)

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

## Risks — confirmed, and new ones found along the way

Original risks, both confirmed true in practice:

- DXVK is developed and tested against Linux; macOS portability **did**
  require nontrivial patching — confirmed, see Phase 2 and
  `project_lithium_dxvk_patches` in memory. vkd3d-proton hasn't been
  attempted yet, so still unconfirmed whether it needs similar patching.
- MoltenVK's Vulkan feature/extension coverage is not 1:1 with Linux Vulkan
  drivers — confirmed; several DXVK-required features
  (`geometryShader`, `shaderCullDistance`, `VK_EXT_depth_clip_enable`) are
  genuinely, permanently unavailable on Apple GPUs, not just missing in
  this particular MoltenVK build.

New risk found, not anticipated originally:

- **Wine's WoW64 mode (32-bit guest support) hangs under Rosetta 2** for at
  least one real-world case (InnoSetup's installer extraction step) — a
  pure userspace spin, most likely in Wine's futex-style "fast sync" wait
  path, with no known fix or workaround at the Wine level. Anything that
  requires running actual 32-bit Windows code (not just 32-bit-stub
  installers that can be bypassed with a native extractor like
  `innoextract`) is currently a real risk for future games. Full details:
  `project_lithium_wow64_installer_bug` in memory.
