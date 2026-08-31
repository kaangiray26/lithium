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
      the CLI points straight at the dev build trees under `build/wine` and
      `build/dxvk` rather than a packaged `dist/`. Revisit before this goes
      beyond a single dev machine.
- [x] Write a `lithium` CLI supporting:
      - [x] `lithium prefix-create <name>`
      - [x] `lithium run <name> <exe> [args...]`
      - [x] `lithium install <name> <installer>` (alias for `run` — see
            Phase 4 note on why installers need special-casing anyway)
      - [x] `lithium prefix-kill <name>` (clean session shutdown; not
            originally planned but needed once we learned killing
            wineserver mid-hang corrupts its lock state)
      Originally a bash script (`scripts/lithium`); ported to a Python
      package (`src/lithium/`, Typer-based, managed with `uv`) with
      identical functionality, run via `uv run lithium ...`.
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
- [x] Debug input beyond basic keyboard/mouse (gamepad specifically) —
      **confirmed working**, including vibration, out of the box. Wine logs
      a couple of unimplemented XInput/Windows.Gaming.Input stubs during
      controller enumeration (`xinput:pdo_pnp code 0xc`,
      `controller_get_IsWireless`) but they don't block real input.
- [x] Debug audio / video codec needs — audio **confirmed working**. Video:
      the opening cutscene is permanently blank. Initially traced to
      missing GStreamer support (fixed in Phase 5); after that fix, traced
      further to a genuine Wine `msvproc` alignment bug unrelated to
      GStreamer, which was not patched (see `docs/context.md`, decided
      not worth a native-code fix for one skippable video). Gameplay
      itself is unaffected either way.
- [x] Reached gameplay (cutscenes + playable) with the user confirming they
      could play. Frame pacing/perf not rigorously measured.

## Phase 5 — Stabilization & polish (next up)

- [x] Build GStreamer (x86_64, via Homebrew's precompiled bottles in the
      second `/usr/local` prefix — also needed keg-only `libffi` for
      `glib`) and reconfigure/rebuild Wine with GStreamer support
      (`winegstreamer`). **Done, fixed the COM-registration gap, but the
      cutscene still doesn't play end to end.** Silksong's opening
      cutscene was blank because Wine's generic media byte-stream COM
      handler wasn't registered — fixed. Next hit a real Wine regression
      in `msvproc`'s frame-alignment handling (bisected to commit
      `0fef7f2ab4f9`, which rewrote `winegstreamer`'s GStreamer-native
      video processor into a buggy `libswscale`-based one); **rebuilt Wine
      pinned to the `wine-11.11` tag (predates the regression) and
      confirmed that bug is fully gone**. But the cutscene is still blank,
      now blocked by what looks like a genuine platform gap (`VK_KHR_
      EXTERNAL_MEMORY_WIN32 not supported` — a Windows-only shared-GPU-
      handle mechanism with no macOS/MoltenVK equivalent), not something
      a Wine version or setting fixes. Net result: blank cutscene either
      way, so decided against permanently pinning to the older `wine-11.11`
      tag for zero actual compatibility gain — see `docs/context.md` for
      the full writeup and the open question of which Wine baseline to
      keep going forward. GStreamer support itself is real and should
      still help other games' audio/video needs.
- [x] Shader cache persistence across runs (DXVK state cache) to avoid
      re-compiling shaders every launch. Works automatically, no extra
      wiring needed — DXVK writes to
      `<prefix>/drive_c/users/<user>/AppData/Local/dxvk/<hash>.dxvk.bin`,
      which is part of the prefix and persists on disk across launches.
- [x] Performance pass: profile via Metal tools (`gpucapture`/Instruments),
      compare against expected M4 Pro performance for a 2D/2.5D Unity title.
      `gpucapture`/`gpudebug` aren't available on this OS (macOS 26+ only;
      this machine runs 15.7.7). Tried `xctrace record --template "Game
      Performance"`, but that template defaults to a 5-second rolling
      capture window regardless of `--time-limit`, so it wasn't useful for
      a real session — used DXVK's built-in HUD instead
      (`DXVK_HUD=fps,frametimes,gpuload,compiler,version`), which is
      simpler and gives the numbers directly. **Result: rock-solid 59.9
      FPS (VSync/FIFO-locked), frame time 15.9-17.5ms (tight, no
      stuttering), GPU at 65% utilization** — meaningful headroom left on
      a 2D/2.5D title. No evidence the Rosetta -> Wine -> DXVK -> MoltenVK
      stack costs noticeable performance for this class of game; the M4
      Pro isn't being stressed.
- [x] Crash/hang triage workflow (wine debug channels, core dumps, DXVK/wine
      logs) documented for future games, not just Silksong. See
      `docs/troubleshooting.md`.
- [x] Document known limitations (no D3DMetal, no Apple GPTK private
      backend, controller support caveats, etc.) in `docs/context.md`.

## Phase 6 — Beyond the first game (stretch)

- [x] Generalize prefix templates / dependency install (equivalent of
      winetricks: VC++ redist, .NET, DXVK auto-install) for arbitrary games.
      Didn't reimplement winetricks -- just wired the real thing in:
      `lithium winetricks <name> <verb...>` sets `WINE`/`WINESERVER` to
      point at our own build (winetricks respects these env vars) plus the
      same `DYLD_FALLBACK_LIBRARY_PATH`/`GST_PLUGIN_PATH`/DLL-override
      plumbing as `run`/`install`. Verified for real: correctly detected
      our `wine-11.16` build and WoW64 mode, applied DLL overrides, and
      downloaded a real ~13MB Microsoft VC++ redistributable
      (`vcrun2019`) over the network. DXVK auto-install isn't part of this
      -- that's still handled by `prefix-create` copying the DLLs directly,
      which was simpler and already worked before this.
- [x] Evaluate Steam Play `compatibilitytool.vdf` integration for launching
      Steam-owned games directly through Steam, reusing Proton's manifest
      format. **Evaluated and confirmed not viable on macOS right now.**
      Initially assumed (from general knowledge) that Steam Play is
      Linux-only, but direct inspection of the real, currently-installed
      macOS Steam client complicated that: `steamclient.dylib` (the real
      client library, not the small `steam_osx` bootstrap stub) genuinely
      contains the full compat-tool backend --
      `compatibilitytool.vdf`/`toolmanifest.vdf` parsing,
      `compatibilitytools.d` scanning, classes like
      `CLoadCompatibilityToolManifestJob` -- almost certainly shared
      codebase with the Linux build. So we actually registered Lithium as
      a real compat tool (`~/Library/Application Support/Steam/
      compatibilitytools.d/Lithium/`, with `to_oslist` set to `macos`) and
      pointed it at a diagnostic-only launcher to see what Steam would
      invoke it with. **Conclusive result, direct from the user**: Steam's
      macOS Settings has no "Compatibility" section at all, confirmed by
      checking the real client UI -- and the diagnostic launcher log file
      was never created, meaning Steam never even attempted to invoke the
      registered tool. So the backend code exists but the macOS UI never
      exposes it to users; there's no way to select a compat tool through
      any current UI path. Cleaned up the test registration afterward. Not
      worth revisiting unless Valve ships macOS UI for this.
- [ ] Evaluate MetalFX upscaling / frame interpolation integration using
      `metal-cpp` for a future custom-Metal graphics backend, as a
      longer-term alternative to the DXVK+MoltenVK path.

## Phase 7 — Project improvement backlog

Identified after the roadmap above was otherwise complete; roughly ordered
by value-to-effort.

- [x] Fix the VSync/device-lost crash: pinned `dxgi.syncInterval = 1` via
      `DXVK_CONFIG` (baked into `lithium_wine_exec` in `src/lithium`) so
      toggling VSync in a game's settings can't trigger a live swapchain
      reconfiguration. **Confirmed fixed** -- verified DXVK actually loads
      the config (`Found config env: dxgi.syncInterval = 1` in the log)
      and the user tested toggling VSync in-game with no crash, no
      `DEVICE_LOST`/`Lost VkDevice` errors in the log.
      Found and fixed a second, more serious bug along the way: the
      Python CLI port had never actually delivered
      `DYLD_FALLBACK_LIBRARY_PATH` to Wine at all (macOS strips `DYLD_*`
      vars from a restricted/SIP binary's own inherited environment the
      moment it's exec'd -- `arch` is one such binary, so passing it via
      `subprocess.run(..., env=...)` alone never worked; other vars like
      `WINEPREFIX` were unaffected, verified this is DYLD-specific). This
      had been silently broken since the CLI migration -- FreeType missing
      is non-fatal so it went unnoticed, but it meant MoltenVK could fail
      to load intermittently-looking-but-actually-always-broken, since it
      only surfaced once something *required* Vulkan to succeed. Fixed by
      routing `DYLD_FALLBACK_LIBRARY_PATH` through an explicit
      `/usr/bin/env VAR=val` argv step instead of relying on inherited
      environment -- `env` constructs its child's envp from its own argv
      rather than by inheritance, sidestepping the stripping. Does *not*
      fix DYLD propagation into wine calls made *by* winetricks
      internally, since winetricks is a `#!/bin/sh` script and shells
      re-trigger the same stripping on their own -- low-impact since
      typical winetricks verbs don't need graphics.
- [x] Automate the build: Phases 0-2 (Wine/DXVK/MoltenVK) are currently
      manual steps documented in prose across this file, not an actual
      script. Write a real `build.sh` (or similar) capturing the Homebrew
      dependency installs, configure flags, and build order, so the
      project is reproducible on a fresh machine without re-deriving
      everything by hand.
      **Done, as `lithium build`** in `src/lithium` (originally written as
      a standalone `build.sh`, then folded into the Python CLI so there's
      a single tool for all Lithium operations instead of a separate
      script to remember). Installs the arm64 Homebrew build tools
      (`autoconf`, `automake`, `pkgconf`, `meson`, `ninja`, `gettext`,
      `bison`, `mingw-w64`, `innoextract`, `winetricks`), bootstraps the
      second x86_64 Homebrew prefix at `/usr/local` if it's missing and
      installs the x86_64 runtime deps (`freetype`, `sdl2`, `gnutls`,
      `mpg123`, `gstreamer`, `libffi`, `bzip2`, `zlib`), writes the
      hand-rolled `bzip2.pc`, clones+builds MoltenVK (x86_64,
      `fetchDependencies` + `xcodebuild`), clones WineHQ wine and checks
      out `wine-11.16`, configures it with the exact flags/env recorded in
      `build/wine/config.log` (`--enable-archs=i386,x86_64 --without-x
      --without-wayland`, `CPPFLAGS`/`LDFLAGS` pointed at MoltenVK) and
      builds it, then clones Proton for the `dxvk` submodule, applies a
      new `patches/dxvk-apple-silicon.patch` (extracted from the real
      local edits described in `project_lithium_dxvk_patches` --
      `geometryShader`/`shaderCullDistance`/`depthClipEnable`/
      `robustness2`/`maintenance5`/`maintenance6` softened to optional,
      plus the `khrPortabilityEnumeration` addition), and builds DXVK via
      meson/ninja against `build-win64.txt`. Idempotent by design (checks
      for existing clones/build output/patch state before redoing work).
      MoltenVK's Xcode selection step is intentionally *not* automated
      (needs an interactive App Store install + admin password); the
      command fails fast with instructions if full Xcode isn't selected.

      **Follow-up: made it genuinely reproducible, not just idempotent.**
      Wine/MoltenVK/Proton originally cloned to `~/external/*` (outside the
      repo, following the same convention as other reference-only clones
      like `game-porting-toolkit`/`metal-cpp`/`typer`), and only Wine was
      pinned to an exact ref (`wine-11.16`) -- MoltenVK and Proton just
      cloned whatever HEAD happened to be that day. Fixed: all three now
      live under `<project>/external/` (gitignored, alongside `build/`) and
      are pinned to an exact commit each (`WINE_REF`/`MOLTENVK_REF`/
      `PROTON_REF` constants in `src/lithium`) -- pinning Proton also pins
      which commit its `dxvk` submodule resolves to, since that's recorded
      in Proton's own tree.

      Verified for real, not just re-run against an already-built stack:
      moved the existing `~/external/{wine,MoltenVK,Proton}` into the
      project (confirmed via `otool -L`/`otool -D` first that no compiled
      binary has an absolute path baked in, so relocating source trees
      doesn't break already-linked output), wiped `build/wine` and
      `build/dxvk` (autotools' `Makefile` and meson's `build.ninja` both
      hardcode the old absolute source path, so incremental rebuilds from
      a moved source tree would've silently broken), and ran
      `lithium build` fully fresh. **This caught a real, previously-latent
      bug**: Wine's own `configure`/`make` were never wrapped in
      `arch -x86_64`, so they ran under the host's native arm64 toolchain,
      which rejects the x86_64-only Homebrew dylibs (freetype, gnutls,
      ...) outright -- surfacing as a misleading `configure: error:
      FreeType development files not found` even though the `.dylib`
      files were right there (confirmed via a minimal repro: `gcc
      -L/usr/local/lib -lfreetype ...` gives `ld: warning: ignoring file
      '...libfreetype.dylib': found architecture 'x86_64', required
      architecture 'arm64'`, whereas `arch -x86_64 gcc ...` links fine).
      This had been masked ever since `build.sh` was first written,
      because every prior test run found `build/wine` already built and
      skipped configure (`make` with nothing to do "succeeds" instantly
      either way) -- it only had a chance to surface once `build/wine` was
      actually wiped and rebuilt from scratch. Fixed by wrapping both the
      `configure` and `make` invocations in `arch -x86_64` inside
      `_build_wine()`. Re-ran the full rebuild afterward: Wine and DXVK
      both compiled clean from the new `external/` layout, and
      `lithium run silksong cmd /c ...` against the freshly-rebuilt
      binaries created a real MoltenVK `VkInstance` and correctly detected
      the Apple M4 Pro GPU, confirming the rebuilt stack actually works at
      runtime, not just that the files exist.

      **Follow-up 2: switched to named stable-release tags instead of raw
      commit SHAs where one exists.** `PROTON_REF` -> `proton-11.0-2`
      (turned out to be the exact same commit already pinned by SHA, so
      purely a readability win, zero functional change). `MOLTENVK_REF` ->
      `v1.4.2` -- this one's a real change, not cosmetic: the previously
      -pinned commit was 20 commits *past* `v1.4.2` (including a bump of
      MoltenVK's own internal version string to "1.4.3", even though no
      `v1.4.3` tag exists upstream yet), so pinning to the latest actual
      stable tag means giving up those 20 commits (mostly new extension
      support and draw-indirect fixes, nothing that looked required by our
      DXVK patches). Didn't assume this was safe -- rebuilt MoltenVK
      against `v1.4.2` for real (wiped the old `Package/` output first so
      `lithium build` couldn't just skip past it) and re-verified against
      the real game: DXVK still creates a working D3D11 device (`Created
      VkInstance`, `GPU device: model: Apple M4 Pro`) with zero DXVK
      feature-rejection or `VK_ERROR_DEVICE_LOST` lines in the log, same
      as before the downgrade.
- [ ] Package a real `dist/`: the CLI (`src/lithium`) currently hardcodes
      paths into the dev build trees (`build/wine`, `build/dxvk`) and
      `<project>/external/MoltenVK`. Lithium can't run on any other
      machine as-is. Only matters once this needs to be usable beyond this
      one dev Mac (see Phase 3's original "on-disk layout" item, still
      skipped).
      **Deliberately deferred, not just unstarted**: this solves a
      different problem than the reproducible-build work above. Pinned
      refs + `lithium build` already answer "can I get Lithium running on
      another machine" -- yes, by re-running the full build there (needs
      full Xcode, two Homebrew prefixes, ~10GB of source checkouts, and
      real build time). A `dist/` package would instead let you *copy
      already-compiled binaries* over, skipping the toolchain and rebuild
      entirely -- only worth the cost if either (a) another machine of
      yours needs Lithium without waiting through a full rebuild, or
      (b) Lithium is ever handed to someone else who shouldn't need a C/C++
      toolchain just to play a game. Neither applies right now, so this
      stays on the backlog rather than getting built speculatively.
- [x] Add automated tests for the `lithium` CLI (`src/lithium`) -- zero
      test coverage currently. Even basic tests (path resolution, env var
      construction, `doctor` logic) would catch regressions as the tool
      grows.
      **Done, kept deliberately basic** (11 tests, `tests/test_lithium.py`,
      `pytest` added as a `[dependency-groups] dev` dep via `uv add
      --dev pytest`). No real Wine/DXVK/MoltenVK build needed to run
      them -- filesystem state is faked under `tmp_path` and
      `subprocess.run` is monkeypatched, so they run in milliseconds.
      Covers: `_dyld_wrapped_command`'s exact argv construction,
      `prefix_path`, `require_wine_build`'s pass/fail paths, the env
      dicts built by `lithium_wine_exec`/`lithium_winetricks_exec`
      (including the `extra_dll_overrides` append path used by
      `prefix-create`'s `mscoree=` override), `doctor`'s ready/incomplete
      branches via Typer's `CliRunner`, and `prefix-create`/`prefix-kill`'s
      already-exists/missing-prefix error paths. Confirmed the mocking is
      properly isolated -- ran real `lithium doctor` immediately after the
      full suite and got the actual, correct build status back, no state
      leakage. One non-obvious gotcha hit along the way: `typer.echo(...,
      err=True)` only shows up in Click's `CliRunner` via `result.output`,
      not `result.stdout` (which came back empty for both error-path
      tests until switched).
      Deliberately not covered: the `build` command's actual clone/
      configure/compile steps (`_build_wine`/`_build_moltenvk`/
      `_build_dxvk`) -- these are thin wrappers around real, slow external
      tools (git, xcodebuild, make, meson/ninja) where the actual bugs
      found this session (`arch -x86_64` wrapping, path constant mix-ups)
      only ever surfaced via genuine from-scratch rebuilds, not unit
      tests with mocked subprocess calls. Worth revisiting if `build`
      grows more internal branching logic worth protecting.
- [ ] Prepare (not apply) a patch for the `winegstreamer` stride-alignment
      bug, same `patches/` pattern as `dxvk-apple-silicon.patch` -- but
      unlike that one, there's no already-working fix to capture yet, so
      this means actually *writing* the fix first: pad into a 16-byte
      -aligned intermediate buffer in `dlls/winegstreamer/main.c`'s
      `wg_format_get_stride()` (or its caller) instead of deleting the
      alignment check outright. See `project_lithium_gstreamer_video_bug`
      in memory for the full root-cause writeup. **Note going in**: this
      alone won't make Silksong's cutscene play -- a second, independent
      platform gap (`VK_KHR_EXTERNAL_MEMORY_WIN32 not supported`, no macOS
      equivalent to that Windows shared-GPU-memory mechanism) blocks it
      regardless, confirmed by testing on a pre-regression Wine tag where
      the stride bug is entirely absent. Worth having ready mainly for a
      *future* game that hits the same non-16-aligned-video-width pattern
      somewhere more central to its experience than a skippable intro.
- [ ] Lower priority / already tracked elsewhere: the unimplemented
      XInput/Windows.Gaming.Input stubs (confirmed harmless so far) -- see
      `docs/context.md`. vkd3d-proton (D3D12) remains deferred until a
      game actually needs it (Phase 2).

## Phase 8 — CLI improvement ideas (brainstorm, not yet decided)

Ideas for `src/lithium` raised while reviewing the CLI, grounded in actual
pain points hit during this project rather than speculative features.
None of these are committed to yet -- pick items up individually when
there's a concrete reason to.

Visibility / debugging:
- [x] `doctor` reports files exist but not what they *are* -- surface the
      pinned Wine tag, MoltenVK ref, and DXVK/Proton ref actually built
      (now that these are tracked constants, see Phase 7) instead of
      requiring a dig through `build/wine/config.log`.
      **Done.** Added `_git_describe()` (runs `git describe --tags
      --always` against a source checkout) and `_dxvk_version()` (reads
      the `DXVK_VERSION` string from DXVK's meson-generated `version.h` --
      ground truth from the actual compiled artifact, not just the
      submodule's current checkout state). `doctor` now prints a `Wine
      ref:`/`MoltenVK ref:`/`DXVK version:` line under each corresponding
      binary check, e.g. `wine-11.16`, `v1.4.2`, `v2.7.1-498-ga6764047+`.
      Deliberately informational only (doesn't affect the ready/incomplete
      `ok` flag) and degrades to `unknown (...)` rather than erroring if a
      source tree isn't a git checkout at all. Caveat noted in the
      `_git_describe` docstring: the Wine/MoltenVK lines reflect what
      *source* is checked out, not a guarantee `build/wine` was actually
      rebuilt since -- `lithium build` keeps these in sync, but a
      manually-edited checkout could drift; DXVK's line doesn't have this
      caveat since it reads the build artifact directly. Added 4 new
      tests (`tests/test_lithium.py`) for the two helpers plus updated the
      existing `doctor` test fixture, which wasn't isolating
      `WINE_SRC`/`MOLTENVK_SRC`/`DXVK_MESON_BUILD_DIR` and would otherwise
      have reached into the real `external/`/`build/dxvk` on disk instead
      of the fake `tmp_path` stack -- 15 tests total, all passing.
      **Follow-up: reworked the output as a real table.** Originally
      plain `typer.echo()` lines with manual `.ljust()` padding; switched
      to `rich` (`Table(box=None, ...)`, a `Component`/`Status`/`Detail`
      layout, added as a real project dependency, not dev-only, since
      `doctor` is user-facing). Considered `rich.columns.Columns` first
      (what was originally asked about) but that's built for tiling many
      same-shaped short items across width, like `ls` output -- not
      aligned label/value pairs, which is what `doctor` actually is,
      so `Table` was the better fit. `OK`/`MISSING` are colored
      green/red, the final `Status` line is bold green/red. Folded the
      separate `Wine ref`/`MoltenVK ref` lines into the `Detail` column
      of their respective binary/dylib row instead of separate rows.
      One real gotcha hit updating the tests for this: Rich truncates
      long `Detail` values (e.g. `tmp_path`-based MISSING paths in the
      test fixtures) to fit the table to console width, so exact-substring
      assertions on full paths silently broke -- fixed by asserting on
      short, guaranteed-untruncated substrings instead (component names,
      `OK`/`MISSING`, the `unknown (...)` fallback strings) rather than
      full row text.
- [ ] `--debug=<channels>` flag on `run` to set `WINEDEBUG` -- every
      debugging session so far has meant hand-crafting
      `WINEDEBUG=+something` outside the CLI.
- [x] `lithium ps`/`lithium status` -- show which prefixes currently have
      a live `wineserver`/game process. Lingering-wineserver confusion has
      come up a few times; the only current check is `ps aux | grep wine`.
      **Done, as `lithium ps`.** Verified the linking mechanism
      empirically (`lsof -p <wineserver-pid>`) before implementing rather
      than assuming: `wineserver` keeps an open directory handle on its
      `WINEPREFIX` root for its entire lifetime (visible as a `DIR`-type
      FD in `lsof`), which reliably maps a running `wineserver` PID back
      to its prefix even with multiple prefixes' wineservers running
      concurrently. Also found that the real game `.exe` Wine `execve()`s
      shows up in `ps` under its actual Unix filesystem path
      (`prefixes/<name>/drive_c/...`), while Wine's own internal helper
      processes (`winedevice.exe`, `rundll32.exe`, ...) show up under
      their Windows-style path (`C:\windows\...`) instead -- so matching
      `ps` output against each prefix's real path only catches the actual
      game, not Wine's internal plumbing, without any extra filtering
      logic needed. Output is a `rich` table (`Prefix` / `wineserver` /
      `Running exe`), same style as the reworked `doctor`. Verified for
      real against a live game launch, not just mocked: idle state shows
      `-`/`-`, launching Silksong showed the live wineserver PID and
      `Hollow Knight Silksong.exe (PID ...)`, and `prefix-kill` correctly
      brought it back to idle within a few seconds. Added 6 new tests
      (mocking `subprocess.run` for both the `ps` and `lsof` calls) -- 21
      tests total, all passing.

Prefix lifecycle:
- [x] `lithium prefix-list` -- no way to see what prefixes exist without
      `ls prefixes/`.
      **Done.** Same `rich` table style as `doctor`/`ps`. Columns:
      `Prefix`, `Initialized` (yes/no based on whether `drive_c` exists --
      catches a `prefix-create` that failed partway through, e.g. a
      `wineboot --init` failure, rather than just showing an
      indistinguishable empty directory), `Path` (full absolute path,
      handy for copy-pasting elsewhere). Deliberately kept separate from
      `ps` rather than merged into it -- different question (\"what
      prefixes exist\" vs \"what's currently running\"), and `prefix-list`
      stays fast/side-effect-free with no `ps`/`lsof` shellouts needed.
      Added 2 tests -- 23 total, all passing.
- [x] `lithium prefix-remove <name>` -- deleting one currently means
      `rm -rf` by hand.
      **Done.** Prompts for confirmation before deleting (`typer.confirm(...,
      abort=True)`); `--force`/`-f` skips it. Refuses to delete a prefix that
      still has a live `wineserver` (reuses the `_wineserver_pids()` /
      `_wineserver_prefix()` helpers written for `lithium ps`) and points at
      `prefix-kill` instead -- deleting a prefix out from under a running
      wineserver corrupts its lock state, the same failure mode that
      motivated `prefix-kill`. Errors cleanly on a nonexistent prefix. Added
      4 tests (missing prefix, `--force` delete, abort-on-"n", refuse-while-
      wineserver-live) -- 27 total, all passing.
      Also fixed a latent trap found along the way: a bare `pytest` (no path
      arg) recursed into `external/` -- the multi-GB upstream
      wine/Proton/MoltenVK checkouts -- and effectively hung at collection.
      Added `[tool.pytest.ini_options] testpaths = ["tests"]` to
      `pyproject.toml` so `pytest` / `uv run pytest` scope to `tests/` by
      default.
- [x] Fold dependency install into creation, e.g.
      `lithium prefix-create <name> --with vcrun2019,dotnet48`, instead of
      the two separate manual steps the README currently documents.
      **Done.** `--with` takes a comma-separated list of winetricks verbs
      and runs `lithium_winetricks_exec` right after the DXVK DLL copy,
      reusing the exact same env plumbing as `lithium winetricks`. Fails
      fast (before creating the prefix dir) if winetricks isn't installed
      or `--with` lists no real verbs; if winetricks itself fails partway,
      the prefix is left in place and the error points at
      `lithium winetricks <name> ...` to retry. README's step 2b documents
      both forms now. Added 3 tests -- 34 total, all passing.

Build ergonomics:
- [x] `--quiet` flag for `build` -- output right now is the raw
      `make`/`ninja`/`xcodebuild` firehose between the `==>` phase
      markers; showing only phase transitions would be much more
      pleasant to watch for something that already takes real time.
      **Done, as `build --quiet` / `-q`.** A module-level `_QUIET` toggle
      (set by `build`, reset in a `finally`) switches `_run` to
      `capture_output=True` so child stdout/stderr is swallowed and only
      the `==>` markers scroll past. A step that fails still dumps its
      full captured output before exiting, so there's something to
      diagnose from. Caveat documented in the command docstring: the
      first-ever run's x86_64 Homebrew bootstrap prompts for a sudo
      password, which `--quiet` hides -- run the first build without it.
      Added 3 tests (quiet suppresses on success, dumps on failure,
      default stays verbose) -- 41 total, all passing.
- [x] `lithium clean` (or `build --force`) to deliberately wipe
      `build/wine`/`build/dxvk` and force a real rebuild, rather than the
      manual `rm -rf` used a few times this session for reproducibility
      testing.
      **Done, as `lithium clean`** (dedicated command rather than a
      `build --force` flag -- composes cleanly as `lithium clean &&
      lithium build`, and keeps `build`'s arg surface unchanged). Wipes
      `build/wine` and `build/dxvk` by default (the two dirs whose
      autotools `Makefile` / meson `build.ninja` bake in absolute source
      paths, so a stale incremental rebuild after a source-tree move
      silently breaks -- the exact reproducibility-testing footgun this
      item came from). `--moltenvk` also wipes `external/MoltenVK/Package`
      (left out of the default since it's the slowest piece to rebuild and
      rarely the one that needs refreshing). Confirmation prompt before
      deleting, `--force`/`-f` to skip -- same pattern as `prefix-remove`.
      No-ops with "Nothing to clean." when the dirs are already gone.
      Added 4 tests -- 31 total, all passing.

Safety / correctness:
- [x] Preflight checks on `run`/`install` -- a typo'd exe path currently
      fails deep inside Wine with a confusing error; checking the path
      exists first and failing fast would be a small, cheap win.
      **Done.** `_run_exe` now stat-checks the target before invoking Wine
      and exits with `error: no such file: <path>` if it's missing. Only
      applies when the arg looks like a host path (`_looks_like_host_path`
      -- contains a `/`); bare Wine builtins (`cmd`, `wineboot`, `notepad`)
      and `C:\\...`-style Windows paths are left alone since Wine resolves
      those itself. Covers both `run` and `install` (shared code path).
      Added 4 tests -- 38 total, all passing.

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
