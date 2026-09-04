# Batman: Arkham City - Game of the Year Edition

- Tested with: v0.1.1
- [Game source](https://www.gog.com/en/game/batman_arkham_city_goty)

## Setup

```bash
lithium prefix create batman_arkham_city_goty
mkdir -p "prefixes/batman_arkham_city_goty/drive_c/Games/Batman Arkham City"
innoextract --gog -d "prefixes/batman_arkham_city_goty/drive_c/Games/Batman Arkham City" "gamefiles/batman_arkham_city/setup_batman_arkham_city_goty_1.1_(38264).exe"
lithium run batman_arkham_city_goty "prefixes/batman_arkham_city_goty/drive_c/Games/Batman Arkham City/Binaries/Win32/BatmanAC.exe"
```

## Notes

- **Status**: Not working — hangs before reaching gameplay.
- **Installed via**: `innoextract` (avoids running the installer's 32-bit
  InnoSetup stub under Wine). Unlike Silksong, the game itself
  (`Binaries/Win32/BatmanAC.exe`) is genuinely 32-bit, so it always runs
  through Wine's WoW64 layer.
- **Blocker**: `BatmanAC.exe` hangs on startup — a pure userspace CPU
  spin with zero wineserver activity, no window ever appears. Same
  signature as the WoW64-on-Rosetta installer hang documented for
  Silksong (`project_lithium_wow64_installer_bug` in memory), but this
  time triggered by the game's own code, not an installer. No known fix.
- **Workarounds tried, none worked**: a Wine virtual desktop avoids the
  CPU spin but the game process is then never actually launched; the
  known Linux fix for this exact game (Windows XP compat mode + `.NET
  3.5`) hits its own separate bugs here — the installer dialog never
  renders/responds in interactive mode, and unattended mode (`-q`) hits a
  reproducible divide-by-zero crash loop instead. Four distinct blockers
  total, all pointing at Wine/Rosetta window-creation and WoW64 gaps, not
  Lithium itself. Full investigation: `docs/plan.md` Phase 4b.
- **Tested against**: Wine `wine-11.16`, DXVK `v2.7.1` + 498 commits
  (win64 and win32 builds), MoltenVK `v1.4.2`.
