# Hollow Knight: Silksong

- Tested with: v0.1.1
- Game source: https://www.gog.com/en/game/hollow_knight_silksong

## Setup

```bash
lithium prefix create hollow_knight_silksong
mkdir -p "prefixes/hollow_knight_silksong/drive_c/Games/Hollow Knight Silksong"
innoextract --gog -d "prefixes/hollow_knight_silksong/drive_c/Games/Hollow Knight Silksong" "gamefiles/setup_hollow_knight_silksong_1.0.30000_(64bit)_(89650).exe"
lithium run hollow_knight_silksong "prefixes/hollow_knight_silksong/drive_c/Games/Hollow Knight Silksong/Hollow Knight Silksong.exe"
```

## Notes

- **Status**: Playable with issues.
- **Installed via**: `innoextract` — the installer's 32-bit InnoSetup
  stub hangs under Wine's WoW64-on-Rosetta combo (a real, unresolved
  Wine bug, see `project_lithium_wow64_installer_bug` in memory). The
  extracted game itself is 64-bit-only, so no WoW64 is needed once
  installed.
- **Confirmed working**: audio, controller input (including vibration),
  core rendering, save/quit, performance (rock-solid 59.9 FPS, no
  stuttering), toggling VSync in-game.
- **Known issue**: the opening cutscene is permanently blank — a
  DXVK/MoltenVK platform gap (`VK_KHR_EXTERNAL_MEMORY_WIN32`), partially
  patched but not fully fixed. Gameplay is unaffected. Full
  investigation: `project_lithium_gstreamer_video_bug` in memory.
- **Tested against**: Wine `wine-11.16`, DXVK `v2.7.1` + 498 commits,
  MoltenVK `v1.4.2`.
