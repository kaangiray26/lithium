# Lithium
Compatibility tool for macOS based on Valve's Proton and additional components

Lithium runs unmodified Windows games on Apple Silicon Macs, built from open
components (WineHQ Wine, Valve's DXVK/vkd3d-proton, Khronos's MoltenVK)
rather than Apple's private Game Porting Toolkit engine. Full roadmap and
architecture rationale: [`docs/plan.md`](docs/plan.md).

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
- **The `lithium` CLI** (`scripts/lithium`) manages prefixes and launches
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
