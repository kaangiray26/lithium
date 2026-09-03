<img src="https://raw.githubusercontent.com/kaangiray26/lithium/refs/heads/main/docs/images/lithium.svg" alt="lithium" width="128" />

# Lithium

Compatibility tool for macOS (Apple Silicon) that runs unmodified Windows
games, built from open components instead of Apple's private Game Porting
Toolkit:

- **Wine** ([WineHQ](https://www.winehq.org/), built x86_64, runs under Rosetta 2) — Win32/PE loader + API emulation
- **[DXVK](https://github.com/doitsujin/dxvk)** — DirectX 9/10/11 → Vulkan
- **[MoltenVK](https://github.com/KhronosGroup/MoltenVK)** — Vulkan → Metal

**Milestone:** Hollow Knight: Silksong runs and is playable end to end. See
[`docs/games/`](docs/games/) for the full compatibility list.

## Install

```sh
uv tool install lithium-cli
lithium build
lithium doctor
```

`lithium build` compiles Wine, DXVK, and MoltenVK from source (needs full
Xcode, not just the Command Line Tools). Everything lands under
`~/Library/Application Support/lithium` (override with `LITHIUM_DATA_DIR`).
Prefer not to build? Grab a pre-built archive from
[Releases](https://github.com/kaangiray26/lithium/releases) instead.

<details>
<summary><b>Developing Lithium itself</b></summary>

```sh
git clone https://github.com/kaangiray26/lithium.git
cd lithium
uv sync
```

Run commands as `uv run lithium ...`. Everything lands inside the repo
(`build/`, `external/`, `prefixes/`) instead of `~/Library/Application
Support/lithium`.

</details>

<details>
<summary><b>Using a pre-built release archive instead of building</b></summary>

Download and extract an archive from
[Releases](https://github.com/kaangiray26/lithium/releases) (e.g.
`lithium-0.1.1-macos-arm64.tar.gz`), then point Lithium at it with env vars
instead of running `lithium build`:

```sh
tar -xzf lithium-0.1.1-macos-arm64.tar.gz
export LITHIUM_WINE_BIN="$PWD/lithium-0.1.1-macos-arm64/wine/bin/wine"
export LITHIUM_WINESERVER_BIN="$PWD/lithium-0.1.1-macos-arm64/wine/bin/wineserver"
export LITHIUM_DXVK_DIR="$PWD/lithium-0.1.1-macos-arm64/dxvk"
export LITHIUM_MOLTENVK_DIR="$PWD/lithium-0.1.1-macos-arm64/moltenvk"
lithium doctor
```

Put these in your shell profile to make them permanent. Every other
command (`prefix create`, `run`, `winetricks`, ...) works exactly the same
either way.

</details>

## Quickstart

```sh
lithium prefix create <name>
lithium install <name> /path/to/setup.exe   # or copy files into prefixes/<name>/drive_c/Games/<game>/
lithium winetricks <name> vcrun2019 dotnet48   # optional: VC++/.NET/etc dependencies
lithium run <name> "prefixes/<name>/drive_c/Games/<game>/Game.exe"
lithium prefix kill <name>                   # clean shutdown when done
```

See [`docs/context.md`](docs/context.md) for known limitations and
[`docs/troubleshooting.md`](docs/troubleshooting.md) if something hangs.

## Approach

```
Windows game (x86_64 PE, DirectX)
  -> Wine (x86_64, under Rosetta 2)
  -> DXVK / vkd3d-proton (D3D9/10/11/12 -> Vulkan)
  -> MoltenVK (Vulkan -> Metal)
  -> Metal (GPU)
```

Full architecture rationale: [`docs/plan.md`](docs/plan.md).

## Packaging

```sh
lithium package
```

Packages an already-built stack into `dist/lithium-<version>-macos-arm64.tar.gz`
— a redistributable archive instead of rebuilding from source on every machine.

## License

[MIT](LICENSE)
