# resources

- https://gitlab.winehq.org/wine/wine -> cloned by `lithium build` into `<project>/external/wine`, pinned to `wine-11.16`
- https://github.com/valvesoftware/proton -> cloned by `lithium build` into `<project>/external/Proton`, pinned via `PROTON_REF` in `src/lithium` (also pins the `dxvk` submodule)
- https://github.com/KhronosGroup/MoltenVK -> cloned by `lithium build` into `<project>/external/MoltenVK`, pinned via `MOLTENVK_REF` in `src/lithium`
- https://github.com/apple/game-porting-toolkit -> reference-only clone at /Users/kaangiray26/external/game-porting-toolkit (not part of Lithium's own build)
- https://github.com/apple/metal-cpp -> reference-only clone at /Users/kaangiray26/external/metal-cpp (not part of Lithium's own build)
