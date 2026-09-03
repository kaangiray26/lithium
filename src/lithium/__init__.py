"""lithium - manage Wine prefixes and launch Windows games through the
Lithium DXVK/MoltenVK stack on Apple Silicon.

This currently points straight at the dev build trees under build/ rather
than a packaged dist/ (see docs/plan.md phase 5/6) -- adjust the paths
below if you relocate things.
"""

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    no_args_is_help=True,
    help="Manage Wine prefixes and launch games. Prefixes live under: prefixes/<name>",
)

prefix_app = typer.Typer(no_args_is_help=True, help="Manage Wine prefixes.")
app.add_typer(prefix_app, name="prefix")

LITHIUM_ROOT = Path(__file__).resolve().parent.parent.parent

# Source checkouts cloned/built by `lithium build`, kept inside the project
# (not e.g. ~/external) so that cloning the repo + running `lithium build`
# reproduces the same layout on any machine. Gitignored -- these are large
# upstream trees, not Lithium's own code.
EXTERNAL_DIR = LITHIUM_ROOT / "external"

WINE_BUILD_DIR = LITHIUM_ROOT / "build" / "wine"
WINE_BIN = WINE_BUILD_DIR / "loader" / "wine"
WINESERVER_BIN = WINE_BUILD_DIR / "server" / "wineserver"

DXVK_MESON_BUILD_DIR = LITHIUM_ROOT / "build" / "dxvk"
DXVK_BUILD_DIR = DXVK_MESON_BUILD_DIR / "src"
# (subdir, dllname) pairs, copied into the prefix's system32 on prefix create
DXVK_DLLS = [
    ("d3d8", "d3d8.dll"),
    ("d3d9", "d3d9.dll"),
    ("d3d10", "d3d10core.dll"),
    ("d3d11", "d3d11.dll"),
    ("dxgi", "dxgi.dll"),
]

MOLTENVK_DYLIB_DIR = Path(
    os.environ.get(
        "LITHIUM_MOLTENVK_DIR",
        str(EXTERNAL_DIR / "MoltenVK/Package/Release/MoltenVK/dynamic/dylib/macOS"),
    )
)

PREFIXES_DIR = LITHIUM_ROOT / "prefixes"

# Extra x86_64 Homebrew tool/lib locations Wine's build and runtime need.
# See docs memory: bison (macOS ships a too-old one), mingw-w64, and the
# x86_64 Homebrew prefix at /usr/local for runtime dylibs.
EXTRA_PATH = "/opt/homebrew/opt/bison/bin:/opt/homebrew/bin:/usr/local/bin"

# Wine can't dlopen these x86_64 Homebrew dylibs via the default fallback
# path in this environment (see docs memory) -- point it at them explicitly.
DYLD_FALLBACK_LIBRARY_PATH_VALUE = (
    f"/usr/local/lib:/usr/local/opt/freetype/lib:/usr/local/opt/gnutls/lib:{MOLTENVK_DYLIB_DIR}"
)

# Use DXVK's native DLLs instead of Wine's built-in Direct3D implementations.
WINEDLLOVERRIDES_VALUE = "d3d8,d3d9,d3d10core,d3d11,dxgi=n"

# winegstreamer (video/audio codec support) needs the actual GStreamer
# plugins findable at runtime, not just its shared libs (already covered
# by DYLD_FALLBACK_LIBRARY_PATH_VALUE above).
GST_PLUGIN_PATH_VALUE = "/usr/local/lib/gstreamer-1.0"

# Pin the present interval so a game's own in-game VSync toggle can't
# trigger a live swapchain reconfiguration -- that's a confirmed trigger
# for a DXVK/MoltenVK bug (VK_ERROR_OUT_OF_DEVICE_MEMORY: Lost VkDevice,
# an unrecoverable renderer crash). See docs/context.md and
# project_lithium_dxvk_patches in memory.
DXVK_CONFIG_VALUE = "dxgi.syncInterval = 1"

# --- `lithium build` (host bootstrap: Homebrew, Wine, DXVK, MoltenVK) ---
# Each upstream repo is pinned to an exact commit/tag (not just "clone and
# use HEAD") so that cloning this repo and running `lithium build` produces
# the same result every time, not whatever upstream happened to be on the
# day you built it. See docs/plan.md Phases 0-2 and project_lithium_build_env
# / project_lithium_dxvk_patches in memory for the "why" behind each pin.
WINE_SRC = EXTERNAL_DIR / "wine"
WINE_REF = "wine-11.16"
MOLTENVK_SRC = EXTERNAL_DIR / "MoltenVK"
MOLTENVK_REF = "v1.4.2"  # latest stable tag as of writing; no v1.4.3 tag yet
PROTON_SRC = EXTERNAL_DIR / "Proton"
PROTON_REF = "proton-11.0-2"  # latest stable tag as of writing
DXVK_SRC = PROTON_SRC / "dxvk"  # pinned via PROTON_REF's recorded submodule commit
DXVK_PATCH = LITHIUM_ROOT / "patches" / "dxvk-apple-silicon.patch"
WINE_PATCHES = [
    LITHIUM_ROOT / "patches" / "wine-mfplat-shared-video-texture.patch",
]
BISON_PATH = "/opt/homebrew/opt/bison/bin"

# MoltenVK's built output (the dylib/headers `lithium build` consumes).
# Wiped only by `lithium clean --moltenvk` -- it's the slowest piece to
# rebuild and rarely the thing that needs refreshing.
MOLTENVK_PACKAGE_DIR = MOLTENVK_SRC / "Package"


def require_wine_build() -> None:
    if not os.access(WINE_BIN, os.X_OK):
        typer.echo(f"error: wine binary not found at {WINE_BIN} (build it first)", err=True)
        raise typer.Exit(1)


def prefix_path(name: str) -> Path:
    return PREFIXES_DIR / name


def _dyld_wrapped_command(*command: str) -> list[str]:
    """Wrap a command so DYLD_FALLBACK_LIBRARY_PATH actually survives.

    macOS strips DYLD_* environment variables from a restricted (SIP)
    binary's own inherited environment the moment it's exec'd -- `arch`
    is one such binary, so passing DYLD_FALLBACK_LIBRARY_PATH via
    subprocess's `env=` alone never reaches the target when `arch` is the
    first thing exec'd (verified empirically; other vars like WINEPREFIX
    are unaffected, only DYLD_* is stripped this way). Explicitly setting
    it as a literal `/usr/bin/env VAR=val` argv entry works instead,
    since `env` constructs a fresh envp from its own argv rather than by
    inheritance, and the actual target (our own Wine binary) isn't itself
    a restricted binary. This does NOT help if the target itself is a
    restricted shell (e.g. winetricks' `#!/bin/sh`) -- shells re-trigger
    the same stripping on their own inherited environment regardless.
    """
    return [
        "arch", "-x86_64", "/usr/bin/env",
        f"DYLD_FALLBACK_LIBRARY_PATH={DYLD_FALLBACK_LIBRARY_PATH_VALUE}",
        *command,
    ]


def lithium_wine_exec(
    prefix_dir: Path,
    *args: str,
    extra_dll_overrides: Optional[str] = None,
    winedebug: Optional[str] = None,
) -> int:
    """Run a command against a prefix with all the env plumbing this stack needs."""
    require_wine_build()

    overrides = WINEDLLOVERRIDES_VALUE
    if extra_dll_overrides:
        overrides = f"{overrides},{extra_dll_overrides}"

    env = os.environ.copy()
    env["PATH"] = f"{EXTRA_PATH}:{env.get('PATH', '')}"
    env["WINEPREFIX"] = str(prefix_dir)
    env["GST_PLUGIN_PATH"] = GST_PLUGIN_PATH_VALUE
    env["WINEDLLOVERRIDES"] = overrides
    env["DXVK_CONFIG"] = DXVK_CONFIG_VALUE
    if winedebug:
        # Explicit --debug always wins over whatever WINEDEBUG the parent
        # shell happens to have set, rather than silently deferring to it.
        env["WINEDEBUG"] = winedebug

    proc = subprocess.run(_dyld_wrapped_command(str(WINE_BIN), *args), env=env)
    return proc.returncode


def lithium_winetricks_exec(prefix_dir: Path, *verbs: str) -> int:
    """Run winetricks against a prefix, pointed at our own Wine build."""
    require_wine_build()

    env = os.environ.copy()
    env["PATH"] = f"{EXTRA_PATH}:{env.get('PATH', '')}"
    env["WINEPREFIX"] = str(prefix_dir)
    env["WINE"] = str(WINE_BIN)
    env["WINESERVER"] = str(WINESERVER_BIN)
    env["GST_PLUGIN_PATH"] = GST_PLUGIN_PATH_VALUE
    env["WINEDLLOVERRIDES"] = WINEDLLOVERRIDES_VALUE

    # Note: winetricks is a `#!/bin/sh` script, and shells re-trigger their
    # own DYLD_* stripping regardless of this wrapper -- see
    # _dyld_wrapped_command's docstring. So this won't fix DYLD propagation
    # into wine calls winetricks makes internally, but doesn't hurt either.
    proc = subprocess.run(_dyld_wrapped_command("winetricks", *verbs), env=env)
    return proc.returncode


def _log(message: str) -> None:
    typer.echo(f"==> {message}")


# Set by `build --quiet`: when True, _run swallows a child's stdout/stderr
# so only the `==>` phase markers scroll past. A failing step still dumps
# its full captured output so there's something to diagnose from.
_QUIET = False


def _run(command: list[str], *, cwd: Optional[Path] = None, env: Optional[dict] = None) -> None:
    if _QUIET:
        proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            if proc.stdout:
                typer.echo(proc.stdout, nl=False)
            if proc.stderr:
                typer.echo(proc.stderr, nl=False, err=True)
            raise typer.Exit(proc.returncode)
        return

    proc = subprocess.run(command, cwd=cwd, env=env)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


def _git_describe(repo_dir: Path) -> Optional[str]:
    """Best-effort `git describe --tags` on a source checkout.

    Reports what source is checked out, not a guarantee the compiled
    binary was actually rebuilt since -- `lithium build` keeps these in
    sync, but a manually-edited checkout could drift. Returns None if the
    directory isn't a git repo at all (e.g. never built).
    """
    if not (repo_dir / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "describe", "--tags", "--always"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def _dxvk_version() -> Optional[str]:
    """Read the git-describe-derived version DXVK actually compiled with.

    Ground truth from the build artifact itself (meson generates this
    file from `git describe` at build time), not just the dxvk
    submodule's current checkout state.
    """
    version_header = DXVK_MESON_BUILD_DIR / "version.h"
    if not version_header.is_file():
        return None
    match = re.search(r'DXVK_VERSION\s+"([^"]+)"', version_header.read_text())
    return match.group(1) if match else None


def _build_sanity_checks() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        typer.echo("error: `lithium build` targets Apple Silicon macOS only", err=True)
        raise typer.Exit(1)

    xcode_path = subprocess.run(
        ["xcode-select", "-p"], capture_output=True, text=True
    ).stdout.strip()
    if "Xcode.app" not in xcode_path:
        typer.echo(
            f"error: full Xcode must be installed and selected (found: {xcode_path or 'none'}).\n"
            "       Install Xcode from the App Store, then run:\n"
            "       sudo xcode-select -s /Applications/Xcode.app/Contents/Developer",
            err=True,
        )
        raise typer.Exit(1)

    if not shutil.which("brew", path="/opt/homebrew/bin"):
        typer.echo("error: arm64 Homebrew not found at /opt/homebrew (install it first)", err=True)
        raise typer.Exit(1)


def _build_arm64_brew_deps() -> None:
    _log("Installing arm64 Homebrew build dependencies...")
    _run(
        [
            "/opt/homebrew/bin/brew", "install",
            "autoconf", "automake", "pkgconf", "meson", "ninja", "gettext",
            "bison", "mingw-w64", "innoextract", "winetricks",
        ]
    )


def _build_x86_64_brew_deps() -> None:
    if not shutil.which("brew", path="/usr/local/bin"):
        _log("Bootstrapping a second, x86_64 Homebrew prefix at /usr/local...")
        _log("(this needs your admin password interactively)")
        install_script = subprocess.run(
            ["curl", "-fsSL", "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        _run(["arch", "-x86_64", "/bin/bash", "-c", install_script])

    _log("Installing x86_64 Homebrew runtime dependencies...")
    _run(
        [
            "arch", "-x86_64", "/usr/local/bin/brew", "install",
            "freetype", "sdl2", "gnutls", "mpg123", "gstreamer", "libffi", "bzip2", "zlib",
        ]
    )

    # Homebrew's bzip2 ships no .pc file, which breaks freetype2's pkg-config
    # `Requires: bzip2` -- write one by hand.
    extra_pkgconfig_dir = LITHIUM_ROOT / "build" / "extra-pkgconfig"
    extra_pkgconfig_dir.mkdir(parents=True, exist_ok=True)
    (extra_pkgconfig_dir / "bzip2.pc").write_text(
        "prefix=/usr/local/opt/bzip2\n"
        "exec_prefix=${prefix}\n"
        "libdir=${exec_prefix}/lib\n"
        "includedir=${prefix}/include\n"
        "\n"
        "Name: bzip2\n"
        "Description: bzip2 compression library\n"
        "Version: 1.0.8\n"
        "Libs: -L${libdir} -lbz2\n"
        "Cflags: -I${includedir}\n"
    )


def _build_moltenvk() -> None:
    if not MOLTENVK_SRC.is_dir():
        _log("Cloning MoltenVK...")
        _run(["git", "clone", "https://github.com/KhronosGroup/MoltenVK.git", str(MOLTENVK_SRC)])

    _run(["git", "fetch", "--tags"], cwd=MOLTENVK_SRC)
    _run(["git", "checkout", MOLTENVK_REF], cwd=MOLTENVK_SRC)

    dylib = MOLTENVK_SRC / "Package/Release/MoltenVK/dynamic/dylib/macOS/libMoltenVK.dylib"
    if dylib.is_file():
        _log("MoltenVK already built, skipping.")
        return

    _log("Building MoltenVK (this takes a while)...")
    _run(["./fetchDependencies", "--macos", "-v"], cwd=MOLTENVK_SRC)
    _run(
        [
            "xcodebuild", "build", "-project", "MoltenVKPackaging.xcodeproj",
            "-scheme", "MoltenVK Package (macOS only)",
            "-configuration", "Release", "ARCHS=x86_64", "ONLY_ACTIVE_ARCH=NO",
        ],
        cwd=MOLTENVK_SRC,
    )


def _apply_patch(repo_dir: Path, patch_path: Path) -> None:
    """Apply a patch if not already applied (checked via a dry-run reverse-apply)."""
    already_applied = subprocess.run(
        ["git", "apply", "--check", "--reverse", str(patch_path)],
        cwd=repo_dir,
        capture_output=True,
    ).returncode == 0
    if not already_applied:
        _log(f"Applying {patch_path.name}...")
        _run(["git", "apply", str(patch_path)], cwd=repo_dir)
    else:
        _log(f"{patch_path.name} already applied, skipping.")


def _build_wine() -> None:
    if not WINE_SRC.is_dir():
        _log("Cloning WineHQ wine...")
        _run(["git", "clone", "https://gitlab.winehq.org/wine/wine.git", str(WINE_SRC)])

    _run(["git", "fetch", "--tags"], cwd=WINE_SRC)
    _run(["git", "checkout", WINE_REF], cwd=WINE_SRC)

    for patch_path in WINE_PATCHES:
        _apply_patch(WINE_SRC, patch_path)

    wine_build_dir = WINE_BUILD_DIR
    wine_build_dir.mkdir(parents=True, exist_ok=True)
    moltenvk_include = MOLTENVK_SRC / "Package/Release/MoltenVK/include"
    moltenvk_lib = MOLTENVK_SRC / "Package/Release/MoltenVK/dynamic/dylib/macOS"

    if not (wine_build_dir / "Makefile").is_file():
        _log(f"Configuring Wine ({WINE_REF}, x86_64+i386 WoW64, Mac driver, GStreamer, MoltenVK)...")
        env = os.environ.copy()
        env["PATH"] = f"{BISON_PATH}:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"
        env["PKG_CONFIG_PATH"] = (
            f"{LITHIUM_ROOT / 'build' / 'extra-pkgconfig'}:/usr/local/lib/pkgconfig:/usr/local/share/pkgconfig"
        )
        env["CC"] = "gcc -std=gnu23 -m64"
        env["CPPFLAGS"] = f"-I{moltenvk_include}"
        env["LDFLAGS"] = f"-L{moltenvk_lib}"
        # Wine itself is built as a native x86_64 macOS binary (see
        # project_lithium_overview in memory for why) -- configure/make must
        # run under `arch -x86_64` (Rosetta) so the compiler it resolves is
        # the x86_64 slice. Without this, the host's native arm64 gcc/ld
        # rejects the x86_64-only Homebrew dylibs outright (freetype,
        # gnutls, gstreamer, ...) as wrong-architecture, which surfaces as a
        # misleading "-lfreetype not found" / "-lgnutls not found" in
        # configure's output even though the .dylib files are right there.
        _run(
            [
                "arch", "-x86_64", str(WINE_SRC / "configure"),
                "--enable-archs=i386,x86_64", "--without-x", "--without-wayland",
            ],
            cwd=wine_build_dir,
            env=env,
        )
    else:
        _log("Wine already configured, skipping configure step.")

    _log("Building Wine (this takes a while)...")
    env = os.environ.copy()
    env["PATH"] = f"{BISON_PATH}:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"
    _run(["arch", "-x86_64", "make", f"-j{os.cpu_count()}"], cwd=wine_build_dir, env=env)


def _build_dxvk() -> None:
    if not PROTON_SRC.is_dir():
        _log("Cloning Proton (for the dxvk submodule)...")
        _run(["git", "clone", "https://github.com/ValveSoftware/Proton.git", str(PROTON_SRC)])

    # Pinning Proton itself also pins which dxvk commit the submodule
    # resolves to -- Proton's tree records an exact commit for that path.
    _run(["git", "fetch", "--tags"], cwd=PROTON_SRC)
    _run(["git", "checkout", PROTON_REF], cwd=PROTON_SRC)
    _run(["git", "submodule", "update", "--init", "dxvk"], cwd=PROTON_SRC)

    _apply_patch(DXVK_SRC, DXVK_PATCH)

    if not (DXVK_MESON_BUILD_DIR / "build.ninja").is_file():
        _log("Configuring DXVK (mingw cross build)...")
        _run(
            [
                "meson", "setup", "--cross-file", str(DXVK_SRC / "build-win64.txt"),
                "-Dbuildtype=release", str(DXVK_MESON_BUILD_DIR), str(DXVK_SRC),
            ]
        )
    else:
        _log("DXVK already configured, skipping configure step.")

    _log("Building DXVK...")
    _run(["ninja", "-C", str(DXVK_MESON_BUILD_DIR)])


@app.command()
def build(
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Only print the ==> phase markers, not the raw make/ninja/xcodebuild output "
        "(a failing step still dumps its full output)",
    ),
) -> None:
    """Build the Wine + DXVK + MoltenVK stack from source (one-time host bootstrap).

    Safe to re-run -- already-built pieces are skipped. Requires full Xcode
    (not just Command Line Tools) already installed and selected via
    `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`.

    Note: the very first run also bootstraps a second, x86_64 Homebrew
    prefix, which prompts for your admin password -- that prompt is hidden
    under --quiet, so run the first build without it.
    """
    global _QUIET
    _QUIET = quiet
    try:
        _build_sanity_checks()
        _build_arm64_brew_deps()
        _build_x86_64_brew_deps()
        _build_moltenvk()
        _build_wine()
        _build_dxvk()
        _log("Done. Verify with: lithium doctor")
    finally:
        _QUIET = False


@app.command()
def clean(
    moltenvk: bool = typer.Option(
        False, "--moltenvk", help="Also wipe MoltenVK's built Package/ output (slowest to rebuild)"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip the confirmation prompt"),
) -> None:
    """Wipe build output so the next `lithium build` is a real from-scratch rebuild.

    Removes build/wine and build/dxvk. Autotools' Makefile and meson's
    build.ninja both bake in absolute source paths, so an incremental
    rebuild after the source tree moves silently breaks -- wiping forces a
    clean reconfigure. MoltenVK's Package/ output is left alone unless
    --moltenvk is passed.
    """
    targets = [WINE_BUILD_DIR, DXVK_MESON_BUILD_DIR]
    if moltenvk:
        targets.append(MOLTENVK_PACKAGE_DIR)

    existing = [t for t in targets if t.exists()]
    if not existing:
        typer.echo("Nothing to clean.")
        return

    typer.echo("Will remove:")
    for target in existing:
        typer.echo(f"  {target}")
    if not force:
        typer.confirm("Proceed?", abort=True)

    for target in existing:
        shutil.rmtree(target)
        typer.echo(f"Removed {target}")

    typer.echo("Done. Run 'lithium build' to rebuild.")


@app.command()
def doctor() -> None:
    """Check that the toolchain/build is in place."""
    ok = True
    console = Console()

    console.print(f"Lithium root: {LITHIUM_ROOT}")

    table = Table(box=None, pad_edge=False)
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")

    def status_cell(is_ok: bool, ok_text: str = "OK", missing_text: str = "MISSING") -> str:
        return f"[green]{ok_text}[/green]" if is_ok else f"[red]{missing_text}[/red]"

    wine_ok = os.access(WINE_BIN, os.X_OK)
    wine_detail = (_git_describe(WINE_SRC) or "unknown (external/wine not found)") if wine_ok else str(WINE_BIN)
    table.add_row("Wine binary", status_cell(wine_ok), wine_detail)
    ok = ok and wine_ok

    for sub, dll in DXVK_DLLS:
        path = DXVK_BUILD_DIR / sub / dll
        dll_ok = path.is_file()
        table.add_row(f"DXVK {dll}", status_cell(dll_ok), "" if dll_ok else str(path))
        ok = ok and dll_ok
    table.add_row("DXVK version", "[dim]--[/dim]", _dxvk_version() or "unknown (not built)")

    moltenvk_dylib = MOLTENVK_DYLIB_DIR / "libMoltenVK.dylib"
    moltenvk_ok = moltenvk_dylib.is_file()
    moltenvk_detail = (
        (_git_describe(MOLTENVK_SRC) or "unknown (external/MoltenVK not found)")
        if moltenvk_ok
        else str(moltenvk_dylib)
    )
    table.add_row("MoltenVK dylib", status_cell(moltenvk_ok), moltenvk_detail)
    ok = ok and moltenvk_ok

    winetricks_bin = shutil.which("winetricks")
    table.add_row(
        "winetricks",
        status_cell(bool(winetricks_bin), missing_text="MISSING (optional)"),
        winetricks_bin or "`brew install winetricks` for the 'winetricks' command",
    )

    console.print(table)

    if ok:
        console.print("[bold green]Status: ready[/bold green]")
    else:
        console.print("[bold red]Status: incomplete[/bold red] -- see docs/plan.md")
        raise typer.Exit(1)


@prefix_app.command("list")
def prefix_list() -> None:
    """List existing Wine prefixes."""
    console = Console()

    if not PREFIXES_DIR.is_dir() or not any(PREFIXES_DIR.iterdir()):
        console.print("No prefixes found.")
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("Prefix")
    table.add_column("Initialized")
    table.add_column("Path")

    for prefix_dir in sorted(p for p in PREFIXES_DIR.iterdir() if p.is_dir()):
        # A prefix is "initialized" once wineboot has actually run against
        # it (prefix create's first step) -- drive_c only exists after that.
        initialized = (prefix_dir / "drive_c").is_dir()
        init_cell = "[green]yes[/green]" if initialized else "[yellow]no[/yellow]"
        table.add_row(prefix_dir.name, init_cell, str(prefix_dir))

    console.print(table)


@prefix_app.command("create")
def prefix_create(
    name: str = typer.Argument(..., help="Name of the prefix to create"),
    with_: Optional[str] = typer.Option(
        None,
        "--with",
        metavar="VERBS",
        help="Comma-separated winetricks verbs to install right after creation, "
        "e.g. --with vcrun2019,dotnet48",
    ),
) -> None:
    """Create and initialize a new Wine prefix.

    Pass --with to fold a winetricks dependency install into creation
    instead of running `lithium winetricks <name> ...` as a separate step.
    """
    require_wine_build()

    verbs = [v.strip() for v in with_.split(",") if v.strip()] if with_ else []
    if with_ and not verbs:
        typer.echo("error: --with was given but lists no verbs", err=True)
        raise typer.Exit(1)
    if verbs and not shutil.which("winetricks"):
        typer.echo("error: --with needs winetricks (`brew install winetricks`)", err=True)
        raise typer.Exit(1)

    prefix_dir = prefix_path(name)
    if prefix_dir.exists():
        typer.echo(f"error: prefix already exists at {prefix_dir}", err=True)
        raise typer.Exit(1)

    prefix_dir.mkdir(parents=True)
    typer.echo(f"Creating prefix '{name}' at {prefix_dir} (first boot is slow under Rosetta, be patient)...")
    # Disable mscoree during first boot only, to skip the "Wine Mono Installer"
    # nag dialog -- it's unrelated to whether the game itself needs .NET.
    returncode = lithium_wine_exec(prefix_dir, "wineboot", "--init", extra_dll_overrides="mscoree=")
    if returncode != 0:
        raise typer.Exit(returncode)

    typer.echo("Installing DXVK...")
    system32 = prefix_dir / "drive_c" / "windows" / "system32"
    system32.mkdir(parents=True, exist_ok=True)
    for sub, dll in DXVK_DLLS:
        src = DXVK_BUILD_DIR / sub / dll
        (system32 / dll).write_bytes(src.read_bytes())

    if verbs:
        typer.echo(f"Installing dependencies via winetricks: {' '.join(verbs)}...")
        returncode = lithium_winetricks_exec(prefix_dir, *verbs)
        if returncode != 0:
            typer.echo(
                f"error: winetricks failed (exit {returncode}); the prefix at {prefix_dir} "
                f"was still created -- retry with 'lithium winetricks {name} {' '.join(verbs)}'",
                err=True,
            )
            raise typer.Exit(returncode)

    typer.echo(f"Prefix '{name}' ready.")


@prefix_app.command("kill")
def prefix_kill(name: str = typer.Argument(..., help="Name of the prefix to shut down")) -> None:
    """Cleanly shut down a prefix's Wine session."""
    require_wine_build()

    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name}", err=True)
        raise typer.Exit(1)

    returncode = lithium_wine_exec(prefix_dir, "wineboot", "-k")
    raise typer.Exit(returncode)


@prefix_app.command("remove")
def prefix_remove(
    name: str = typer.Argument(..., help="Name of the prefix to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip the confirmation prompt"),
) -> None:
    """Delete a Wine prefix and everything in it.

    Refuses to run while the prefix still has a live wineserver -- deleting
    a prefix out from under a running session corrupts wineserver's lock
    state (the same reason `prefix kill` exists). Kill it first.
    """
    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name}", err=True)
        raise typer.Exit(1)

    for pid in _wineserver_pids():
        if _wineserver_prefix(pid) == name:
            typer.echo(
                f"error: prefix '{name}' has a live wineserver (PID {pid}); "
                f"run 'lithium prefix kill {name}' first",
                err=True,
            )
            raise typer.Exit(1)

    if not force:
        typer.confirm(f"Delete prefix '{name}' at {prefix_dir}?", abort=True)

    shutil.rmtree(prefix_dir)
    typer.echo(f"Removed prefix '{name}'.")


def _ps_lines() -> list[str]:
    """Raw `ps -eo pid=,args=` output, one process per line, no header."""
    proc = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True)
    return proc.stdout.splitlines()


def _wineserver_pids() -> list[int]:
    """PIDs of currently-running wineserver processes launched by Lithium."""
    pids = []
    for line in _ps_lines():
        pid_str, _, args = line.strip().partition(" ")
        if args.strip() == str(WINESERVER_BIN):
            pids.append(int(pid_str))
    return pids


def _wineserver_prefix(pid: int) -> Optional[str]:
    """Which prefix a running wineserver PID belongs to, if any.

    wineserver keeps an open directory handle on its WINEPREFIX root for
    its entire lifetime -- confirmed empirically via `lsof -p <pid>`.
    Checked by exact-path substring match against known prefixes rather
    than parsing lsof's columnar output, since that's simpler and just as
    reliable for this purpose.
    """
    proc = subprocess.run(["lsof", "-p", str(pid)], capture_output=True, text=True)
    if proc.returncode != 0 or not PREFIXES_DIR.is_dir():
        return None
    for prefix_dir in PREFIXES_DIR.iterdir():
        if prefix_dir.is_dir() and str(prefix_dir) in proc.stdout:
            return prefix_dir.name
    return None


def _running_exe(prefix_dir: Path) -> Optional[tuple[str, int]]:
    """The first real Windows .exe currently running under a prefix, if any.

    Wine's own internal helper processes (winedevice.exe, rundll32.exe,
    ...) show up in `ps` under their Windows-style path (`C:\\windows\\...`),
    but the actual game .exe Wine execve()s shows up under its real Unix
    filesystem path -- confirmed empirically. So matching on "does the ps
    command start with this prefix's real path" only catches the game
    itself, not Wine's internal plumbing, which is exactly what we want.
    """
    prefix_str = str(prefix_dir) + os.sep
    for line in _ps_lines():
        pid_str, _, args = line.strip().partition(" ")
        args = args.strip()
        if args.startswith(prefix_str) and args.lower().endswith(".exe"):
            return Path(args).name, int(pid_str)
    return None


@app.command()
def ps() -> None:
    """Show which prefixes currently have a live wineserver/game process."""
    console = Console()

    if not PREFIXES_DIR.is_dir() or not any(PREFIXES_DIR.iterdir()):
        console.print("No prefixes found.")
        return

    prefix_by_wineserver = {}
    for pid in _wineserver_pids():
        name = _wineserver_prefix(pid)
        if name:
            prefix_by_wineserver[name] = pid

    table = Table(box=None, pad_edge=False)
    table.add_column("Prefix")
    table.add_column("wineserver")
    table.add_column("Running exe")

    for prefix_dir in sorted(PREFIXES_DIR.iterdir()):
        if not prefix_dir.is_dir():
            continue
        ws_pid = prefix_by_wineserver.get(prefix_dir.name)
        ws_cell = f"[green]PID {ws_pid}[/green]" if ws_pid else "[dim]-[/dim]"

        exe = _running_exe(prefix_dir)
        exe_cell = f"[green]{exe[0]} (PID {exe[1]})[/green]" if exe else "[dim]-[/dim]"

        table.add_row(prefix_dir.name, ws_cell, exe_cell)

    console.print(table)


@app.command(context_settings={"ignore_unknown_options": True})
def winetricks(
    name: str = typer.Argument(..., help="Name of the prefix to install into"),
    verbs: list[str] = typer.Argument(..., help="Winetricks verbs, e.g. vcrun2019 dotnet48 corefonts"),
) -> None:
    """Install common Windows dependencies (VC++ redist, .NET, etc.) via winetricks."""
    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name} (run 'lithium prefix create {name}' first)", err=True)
        raise typer.Exit(1)

    returncode = lithium_winetricks_exec(prefix_dir, *verbs)
    raise typer.Exit(returncode)


def _looks_like_host_path(exe: str) -> bool:
    """Whether `exe` is meant to be a file on the host, vs a Wine builtin.

    A bare name like `cmd`, `notepad`, or `wineboot` is resolved by Wine
    inside the prefix and never exists on the host. `C:\\...`-style Windows
    paths aren't host paths we can stat either. Anything with a POSIX path
    separator (`lithium run x prefixes/.../Game.exe`, `./setup.exe`,
    `/abs/path.exe`) is a host path and worth preflighting.
    """
    return "/" in exe


def _run_exe(name: str, exe: str, args: list[str], debug: Optional[str] = None) -> None:
    require_wine_build()

    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name} (run 'lithium prefix create {name}' first)", err=True)
        raise typer.Exit(1)

    # Preflight the target path -- a typo otherwise fails deep inside Wine
    # with a confusing error far removed from the actual cause.
    if _looks_like_host_path(exe) and not Path(exe).is_file():
        typer.echo(f"error: no such file: {exe}", err=True)
        raise typer.Exit(1)

    returncode = lithium_wine_exec(prefix_dir, exe, *args, winedebug=debug)
    raise typer.Exit(returncode)


@app.command(context_settings={"ignore_unknown_options": True})
def run(
    name: str = typer.Argument(..., help="Name of the prefix to run in"),
    exe: str = typer.Argument(..., help="Path to the Windows executable"),
    args: Optional[list[str]] = typer.Argument(None, help="Extra arguments passed to the executable"),
    debug: Optional[str] = typer.Option(
        None,
        "--debug",
        help="Set WINEDEBUG for this run, e.g. --debug=+relay or --debug=+server,+loaddll",
    ),
) -> None:
    """Run a Windows executable inside a prefix."""
    _run_exe(name, exe, args or [], debug=debug)


@app.command(context_settings={"ignore_unknown_options": True})
def install(
    name: str = typer.Argument(..., help="Name of the prefix to install into"),
    exe: str = typer.Argument(..., help="Path to the Windows installer"),
    args: Optional[list[str]] = typer.Argument(None, help="Extra arguments passed to the installer"),
    debug: Optional[str] = typer.Option(
        None,
        "--debug",
        help="Set WINEDEBUG for this run, e.g. --debug=+relay or --debug=+server,+loaddll",
    ),
) -> None:
    """Run a Windows installer inside a prefix (alias for 'run')."""
    _run_exe(name, exe, args or [], debug=debug)
