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
- **The opening cutscene never plays — root cause is a genuine Wine bug,
  not a missing dependency (that part is now fixed).** GStreamer support
  was added to the Wine build (x86_64 GStreamer via the second Homebrew
  prefix — Homebrew's `gstreamer` formula now bundles base/good/bad/ugly
  plugins into one package; also needed `libffi`, keg-only, for `glib`),
  and Wine's `winegstreamer` COM class now registers correctly — the
  original `{317df618-...}` "class not registered" error is gone. But the
  video still doesn't play, because of a **separate, deeper bug** in
  Wine's `msvproc` (Media Foundation video processor, `dlls/msvproc/
  video_processor.c`): the cutscene's frame width is **1916px** (not
  1920 — likely a horizontally-cropped/letterboxed encode), which isn't
  divisible by 16. `video_frame_wrap_buffer()` hard-requires 16-byte
  alignment for `swscale`'s SSE2 path and does `return -1` when it isn't
  met (line ~239) — on *every* frame, since the width never changes, so
  the video is permanently blank rather than glitchy. A correct fix means
  patching that function to copy into a padded, 16-aligned intermediate
  buffer before handing off to `swscale` — removing the check outright is
  not safe, since unaligned data through `swscale`'s SSE2 path can genuinely
  crash. **Decision: not patched.** Gameplay itself is unaffected and this
  is one skippable intro video; the fix is real native-code Wine internals
  work whose cost isn't justified by the payoff here. Revisit if a future
  game hits the same non-16-aligned-video pattern more centrally to its
  experience.
  Also checked (and ruled out) for a config-only workaround: no matching
  report exists in WineHQ Bugzilla or upstream (confirmed the same bug is
  still present, unpatched, in current Wine `master`), and forcing
  GStreamer's hardware VideoToolbox decoder over the software one via
  `GST_PLUGIN_FEATURE_RANK` doesn't help — the bug is in Wine's own
  stride-recompute logic downstream of whichever decoder runs, not in the
  decoder's own output. That attempt also triggered a real Metal/GPU
  device-lost crash (frozen black screen) that isn't present otherwise —
  **do not set `GST_PLUGIN_FEATURE_RANK` for vtdec/vtdec_hw**.

  **Update — found and tried a real fix, which worked partially.**
  Comparing against Proton's own (much older) wine fork locally showed its
  video processor is a pure GStreamer pipeline with no manual stride code
  at all; bisecting mainline WineHQ found the exact regression commit
  (`0fef7f2ab4f9`, "Reimplement using libswscale", landing 110 commits
  after the `wine-11.11` tag). **Rebuilt Wine pinned to `wine-11.11`
  instead of current master, and the original alignment bug is completely
  gone** — no more `aligned to 16 bytes` / COM-registration errors. But the
  cutscene *still* doesn't play, now blocked by a different, previously
  -masked issue: `Failed to create shared resource: VK_KHR_EXTERNAL_
  MEMORY_WIN32 not supported`. This looks like a genuine platform gap
  (Unity/Media Foundation trying to share the decoded video frame into the
  D3D11 scene via a Windows-only kernel shared-handle mechanism that has
  no macOS/MoltenVK equivalent), not something a Wine version or config
  change can fix. **Net effect: the cutscene is blank either way** — the
  `wine-11.11` pin fixes the originally-diagnosed bug but doesn't change
  the user-visible outcome, so there's no concrete compatibility win
  weighed against losing ~1000 commits of unrelated upstream fixes by
  staying on the older tag long-term. Full writeup:
  `project_lithium_gstreamer_video_bug` in memory.
- **Toggling VSync in-game crashes the renderer.** Confirmed reproducible:
  changing the VSync setting in Silksong's video options reliably triggers
  `[mvk-error] VK_ERROR_OUT_OF_DEVICE_MEMORY: Lost VkDevice ...
  IOGPUCommandBufferCallbackErrorInvalidResource`, followed by repeated
  `DxvkSubmissionQueue: Command submission failed: VK_ERROR_DEVICE_LOST` —
  an unrecoverable renderer crash (frozen/black screen, process must be
  killed). Looks like a real bug in DXVK/MoltenVK's present-mode-switch
  path (recreating the swapchain with a different present interval at
  runtime references an invalid/stale Metal resource). The same crash
  signature was also seen once spontaneously without any settings change,
  suggesting some swapchain-recreation-adjacent trigger, not exclusively
  the VSync toggle itself. **Workaround, not yet verified**: DXVK supports
  pinning the present interval via config (`dxgi.syncInterval` in
  `dxvk.conf` or `DXVK_CONFIG` env var) so the game's own toggle doesn't
  cause a live swapchain reconfiguration — worth trying before attempting
  any real fix. For now: don't toggle VSync in-game.
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
- **Performance** — rock-solid 59.9 FPS (VSync/FIFO-locked), frame time
  15.9-17.5ms (tight, no stuttering), GPU at 65% utilization during actual
  gameplay (measured via DXVK's HUD, `DXVK_HUD=fps,frametimes,gpuload`).
  Meaningful headroom left on a 2D/2.5D title — no sign the translation
  stack (Rosetta -> Wine -> DXVK -> MoltenVK) is costing real performance
  for this class of game.

## Status snapshot

Hollow Knight: Silksong installs (via `innoextract`, not the bundled
installer) and is fully playable — play-tested through the opening menu,
a new game, and into real gameplay, then saved and quit cleanly — on the
dev machine (Mac mini, Apple M4 Pro, macOS 15.7.7). The one confirmed gap
is the missing pre-rendered opening cutscene (see the GStreamer limitation
above); everything else tested clean. See `docs/plan.md` Phase 4 for the
full story and `README.md` for the milestone summary.
