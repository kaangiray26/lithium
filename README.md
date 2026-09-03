<img src="https://raw.githubusercontent.com/kaangiray26/lithium/refs/heads/main/docs/images/lithium.svg" alt="lithium" width="256" />

# Lithium
Compatibility tool for macOS based on Valve's Proton and additional components

Lithium runs unmodified Windows games on Apple Silicon Macs, built from open
components (WineHQ Wine, Valve's DXVK/vkd3d-proton, Khronos's MoltenVK)
rather than Apple's private Game Porting Toolkit engine. Full roadmap and
architecture rationale: [`docs/plan.md`](docs/plan.md).

## Install

**As a standalone tool** (recommended if you just want to play games,
not develop Lithium itself):

```
uv tool install lithium-cli
```

This puts a `lithium` command on your PATH, published from this repo's
`src/lithium/` package (built with [Typer](https://typer.tiangolo.com/)).
Everything Lithium builds/stores (Wine, DXVK, MoltenVK, prefixes) lands
under `~/Library/Application Support/lithium` in this mode — override
with the `LITHIUM_DATA_DIR` environment variable if you want it
elsewhere.

**From a repo checkout** (for developing Lithium itself):

```
git clone https://github.com/kaangiray26/lithium.git
cd lithium
uv sync
```

Then run commands with `uv run lithium ...` (or activate `.venv` and
just run `lithium ...` directly). Everything lands inside the repo
(`build/`, `external/`, `prefixes/`) instead of `~/Library/Application
Support/lithium`.

Every command below is written as `lithium ...` — if you're working
from a repo checkout instead of a standalone install, prefix each one
with `uv run`.

## Quickstart

**Prerequisite: Wine, DXVK, and MoltenVK must already be built.** Full
Xcode (not just the Command Line Tools) must be installed and selected
first — `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`
— then run:

```
lithium build
```

This installs the Homebrew dependencies (both the arm64 build tools and a
second x86_64 Homebrew prefix at `/usr/local` for runtime deps), clones
and builds MoltenVK and WineHQ Wine, and builds DXVK with the Apple
Silicon patches applied. It's safe to re-run — already-built pieces are
skipped. See `docs/plan.md` Phases 0-2 for the rationale behind each step.

To force a real from-scratch rebuild (e.g. after moving the source
trees), wipe the build output first:

```
lithium clean             # wipes build/wine and build/dxvk
lithium clean --moltenvk  # also wipes external/MoltenVK/Package
```
Run `lithium doctor` to check whether the stack is already in place:

```
lithium doctor
```

If everything shows `OK` and it prints `Status: ready`, you're good to go.

### 1. Create a prefix

Each game gets its own Wine prefix (an isolated "Windows install"):

```
lithium prefix create <name>
```

The **first boot is genuinely slow** (several minutes) under Rosetta 2 —
that's normal first-time Windows registry/COM setup, not a hang. A "Wine
Mono Installer" popup is suppressed automatically during this step. See
`docs/troubleshooting.md` if you're unsure whether something is actually
stuck.

### 2. Get the game's files into the prefix

This is the part that varies most by game, and where you're most likely to
hit friction — see `docs/context.md` for known limitations.

- **If you have raw, already-extracted game files** (an `.exe` plus its
  data folder), just copy them into
  `prefixes/<name>/drive_c/Games/<game>/` and skip to step 3.
- **If you have a Windows installer**, try:
  ```
  lithium install <name> /path/to/setup.exe
  ```
  **Caveat**: if the installer is a classic **InnoSetup** installer (common
  for GOG-style offline installers) and its stub is **32-bit**, this can
  hang indefinitely due to a real Wine bug in 32-bit (WoW64) support under
  Rosetta 2 — confirmed while installing Hollow Knight: Silksong. If it
  does:
  ```
  brew install innoextract
  innoextract --gog -d "prefixes/<name>/drive_c/Games/<game>" /path/to/setup.exe
  ```
  This extracts the game files directly without running any Windows code,
  sidestepping the bug entirely. Modern games are almost always 64-bit-only
  anyway, so the extracted `.exe` runs fine afterward with no WoW64
  involved. Full story: `docs/troubleshooting.md` and `docs/plan.md` Phase 4.

### 2b. Install dependencies the game needs (optional)

Some games need VC++ redistributables, .NET, or similar before they'll run.
Lithium doesn't reimplement dependency management — it wires up
[winetricks](https://github.com/Winetricks/winetricks) (`brew install
winetricks`) against your own Wine build:

```
lithium winetricks <name> vcrun2019 dotnet48
```

You can also fold this into prefix creation in one step:

```
lithium prefix create <name> --with vcrun2019,dotnet48
```

### 3. Run the game

```
lithium run <name> "prefixes/<name>/drive_c/Games/<game>/Game.exe"
```

This sets up `WINEPREFIX`, the DXVK DLL overrides, the MoltenVK/Homebrew
library paths, and launches everything under Rosetta 2 (`arch -x86_64`) for
you — you don't need to set any of that up by hand.

### 4. Shut down cleanly

Wine keeps a background session (`wineserver` + helper processes) running
after a game closes, so it's fast to relaunch. To fully tear it down:

```
lithium prefix kill <name>
```

To delete a prefix entirely (prompts first; `--force` skips the prompt, and
it refuses while a `wineserver` is still live — `prefix kill` it first):

```
lithium prefix remove <name>
```

## Packaging (advanced)

Once `lithium build` has produced a working stack, you can package the
compiled Wine + DXVK + MoltenVK binaries into a single redistributable
archive instead of re-running the full source build on another machine:

```
lithium package
```

This produces `dist/lithium-<version>-macos-arm64.tar.gz` (plus a
`.sha256` checksum file) — self-contained, works if extracted anywhere.
There's no automated way to *consume* the archive yet (no `lithium build
--from-dist`); it's up to you to extract it and wire the paths up, or host
it somewhere (e.g. a GitHub Release) for now.

## Approach

Apple Silicon has no native x86_64 CPU and no native Vulkan/DirectX, so two
translation layers are stacked:

```
Windows game (x86_64 PE, DirectX)
  -> Wine (Win32/PE loader + API emulation)      [built as x86_64, runs under Rosetta 2]
  -> DXVK / vkd3d-proton (D3D9/10/11 -> Vulkan, D3D12 -> Vulkan)
  -> MoltenVK (Vulkan -> Metal)
  -> Metal (GPU)
```

Wine is built as an **x86_64** binary (not native arm64) so the whole process
tree — Wine itself and the Windows game's code it loads — runs transparently
under **Rosetta 2**. Wine doesn't emulate the game's CPU instructions itself;
it loads the game's PE binary and jumps straight into its machine code in the
same process, so something has to actually execute x86_64 instructions, and
Rosetta 2 is the only publicly available way to do that on Apple Silicon.
See `docs/plan.md` for the full rationale, including why native-arm64 WoW64
wasn't viable here.

## Status

See [`docs/games/`](docs/games/) for the full list of games actually
tested against Lithium and their status.

**Milestone: Hollow Knight: Silksong runs and is playable end to end.**
An unmodified Windows game — DirectX 11, Unity engine, downloaded as a
normal offline GOG-style installer — runs through the full stack: Wine
(x86_64, under Rosetta 2) -> patched DXVK -> MoltenVK -> Metal, rendering
real frames via `CAMetalLayer` on the host GPU:

```
[mvk-info] Created VkInstance ... Apple M4 Pro ...
info:  Created cache file: C:\users\...\AppData\Local\dxvk\....dxvk.bin
info:  DXVK: Using 14 compiler threads
info:  Presenter: Actual swapchain properties:
info:    Buffer size:  1920x1080
[mvk-info] Created 3 swapchain images ... in layer CAMetalLayer: WineMetalView ... on screen Main Screen.
```

This validates the riskiest architectural bet in the project end to end:
Wine, DXVK, and MoltenVK combine to run a real commercial game on Apple
Silicon without Apple's private Game Porting Toolkit engine.

What it took, in order:
- **Wine** builds and runs on macOS arm64 via Rosetta 2, both headless
  (`wine cmd`) and windowed (`wine notepad`, real Mac-driver windows).
- **winevulkan + MoltenVK**: Wine's configure natively detects MoltenVK as
  a `libvulkan` implementation (`SONAME_LIBVULKAN "libMoltenVK.dylib"`) —
  no shimming needed, just correct linker flags at Wine build time.
- **DXVK needed real patching** to run on MoltenVK at all — see
  `docs/plan.md`'s original risk list, confirmed correct. It hardcodes
  several Vulkan features as required that Apple GPUs permanently lack
  (`geometryShader`, `shaderCullDistance`) or that MoltenVK doesn't
  implement (`VK_EXT_depth_clip_enable`); relaxed those to optional.
- **The `lithium` CLI** (`src/lithium/`, Python/Typer) manages prefixes and launches
  games with the right env (`DYLD_FALLBACK_LIBRARY_PATH` for MoltenVK/
  Homebrew dylibs, DXVK DLL overrides, Rosetta invocation) baked in.
- **32-bit InnoSetup installers hang** under Wine's WoW64-on-Rosetta combo
  (a real, unresolved Wine bug — see project memory for the investigation).
  Worked around by extracting the installer directly with `innoextract`
  (no Windows code execution at all) instead of running it through Wine —
  the actual game payload is 64-bit-only anyway, so it launches on the
  plain x86_64 path with no WoW64 involved.

Next: vkd3d-proton (D3D12) for titles that need it, generalizing the
installer/dependency flow beyond this one game, and the stretch goals in
`docs/plan.md` (Steam Play integration, shader cache persistence, MetalFX).
