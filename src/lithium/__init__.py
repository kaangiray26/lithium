"""lithium - manage Wine prefixes and launch Windows games through the
Lithium DXVK/MoltenVK stack on Apple Silicon.

This currently points straight at the dev build trees under build/ rather
than a packaged dist/ (see docs/plan.md phase 5/6) -- adjust the paths
below if you relocate things.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    no_args_is_help=True,
    help="Manage Wine prefixes and launch games. Prefixes live under: prefixes/<name>",
)

LITHIUM_ROOT = Path(__file__).resolve().parent.parent.parent

WINE_BUILD_DIR = LITHIUM_ROOT / "build" / "wine"
WINE_BIN = WINE_BUILD_DIR / "loader" / "wine"
WINESERVER_BIN = WINE_BUILD_DIR / "server" / "wineserver"

DXVK_BUILD_DIR = LITHIUM_ROOT / "build" / "dxvk" / "src"
# (subdir, dllname) pairs, copied into the prefix's system32 on prefix-create
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
        str(Path.home() / "external/MoltenVK/Package/Release/MoltenVK/dynamic/dylib/macOS"),
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


def require_wine_build() -> None:
    if not os.access(WINE_BIN, os.X_OK):
        typer.echo(f"error: wine binary not found at {WINE_BIN} (build it first)", err=True)
        raise typer.Exit(1)


def prefix_path(name: str) -> Path:
    return PREFIXES_DIR / name


def lithium_wine_exec(prefix_dir: Path, *args: str, extra_dll_overrides: Optional[str] = None) -> int:
    """Run a command against a prefix with all the env plumbing this stack needs."""
    require_wine_build()

    overrides = WINEDLLOVERRIDES_VALUE
    if extra_dll_overrides:
        overrides = f"{overrides},{extra_dll_overrides}"

    env = os.environ.copy()
    env["PATH"] = f"{EXTRA_PATH}:{env.get('PATH', '')}"
    env["WINEPREFIX"] = str(prefix_dir)
    env["DYLD_FALLBACK_LIBRARY_PATH"] = DYLD_FALLBACK_LIBRARY_PATH_VALUE
    env["GST_PLUGIN_PATH"] = GST_PLUGIN_PATH_VALUE
    env["WINEDLLOVERRIDES"] = overrides

    proc = subprocess.run(["arch", "-x86_64", str(WINE_BIN), *args], env=env)
    return proc.returncode


def lithium_winetricks_exec(prefix_dir: Path, *verbs: str) -> int:
    """Run winetricks against a prefix, pointed at our own Wine build."""
    require_wine_build()

    env = os.environ.copy()
    env["PATH"] = f"{EXTRA_PATH}:{env.get('PATH', '')}"
    env["WINEPREFIX"] = str(prefix_dir)
    env["WINE"] = str(WINE_BIN)
    env["WINESERVER"] = str(WINESERVER_BIN)
    env["DYLD_FALLBACK_LIBRARY_PATH"] = DYLD_FALLBACK_LIBRARY_PATH_VALUE
    env["GST_PLUGIN_PATH"] = GST_PLUGIN_PATH_VALUE
    env["WINEDLLOVERRIDES"] = WINEDLLOVERRIDES_VALUE

    proc = subprocess.run(["arch", "-x86_64", "winetricks", *verbs], env=env)
    return proc.returncode


@app.command()
def doctor() -> None:
    """Check that the toolchain/build is in place."""
    ok = True

    typer.echo(f"Lithium root:        {LITHIUM_ROOT}")

    if os.access(WINE_BIN, os.X_OK):
        typer.echo(f"Wine binary:          OK ({WINE_BIN})")
    else:
        typer.echo(f"Wine binary:          MISSING ({WINE_BIN})")
        ok = False

    for sub, dll in DXVK_DLLS:
        path = DXVK_BUILD_DIR / sub / dll
        label = f"DXVK {dll}:".ljust(20)
        if path.is_file():
            typer.echo(f"{label} OK")
        else:
            typer.echo(f"{label} MISSING ({path})")
            ok = False

    moltenvk_dylib = MOLTENVK_DYLIB_DIR / "libMoltenVK.dylib"
    if moltenvk_dylib.is_file():
        typer.echo(f"MoltenVK dylib:       OK ({moltenvk_dylib})")
    else:
        typer.echo(f"MoltenVK dylib:       MISSING ({moltenvk_dylib})")
        ok = False

    winetricks_bin = shutil.which("winetricks")
    if winetricks_bin:
        typer.echo(f"winetricks:           OK ({winetricks_bin})")
    else:
        typer.echo("winetricks:           MISSING (optional -- `brew install winetricks` for the 'winetricks' command)")

    if ok:
        typer.echo("Status: ready")
    else:
        typer.echo("Status: incomplete -- see docs/plan.md")
        raise typer.Exit(1)


@app.command("prefix-create")
def prefix_create(name: str = typer.Argument(..., help="Name of the prefix to create")) -> None:
    """Create and initialize a new Wine prefix."""
    require_wine_build()

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

    typer.echo(f"Prefix '{name}' ready.")


@app.command("prefix-kill")
def prefix_kill(name: str = typer.Argument(..., help="Name of the prefix to shut down")) -> None:
    """Cleanly shut down a prefix's Wine session."""
    require_wine_build()

    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name}", err=True)
        raise typer.Exit(1)

    returncode = lithium_wine_exec(prefix_dir, "wineboot", "-k")
    raise typer.Exit(returncode)


@app.command(context_settings={"ignore_unknown_options": True})
def winetricks(
    name: str = typer.Argument(..., help="Name of the prefix to install into"),
    verbs: list[str] = typer.Argument(..., help="Winetricks verbs, e.g. vcrun2019 dotnet48 corefonts"),
) -> None:
    """Install common Windows dependencies (VC++ redist, .NET, etc.) via winetricks."""
    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name} (run 'lithium prefix-create {name}' first)", err=True)
        raise typer.Exit(1)

    returncode = lithium_winetricks_exec(prefix_dir, *verbs)
    raise typer.Exit(returncode)


def _run_exe(name: str, exe: str, args: list[str]) -> None:
    require_wine_build()

    prefix_dir = prefix_path(name)
    if not prefix_dir.is_dir():
        typer.echo(f"error: no such prefix: {name} (run 'lithium prefix-create {name}' first)", err=True)
        raise typer.Exit(1)

    returncode = lithium_wine_exec(prefix_dir, exe, *args)
    raise typer.Exit(returncode)


@app.command(context_settings={"ignore_unknown_options": True})
def run(
    name: str = typer.Argument(..., help="Name of the prefix to run in"),
    exe: str = typer.Argument(..., help="Path to the Windows executable"),
    args: Optional[list[str]] = typer.Argument(None, help="Extra arguments passed to the executable"),
) -> None:
    """Run a Windows executable inside a prefix."""
    _run_exe(name, exe, args or [])


@app.command(context_settings={"ignore_unknown_options": True})
def install(
    name: str = typer.Argument(..., help="Name of the prefix to install into"),
    exe: str = typer.Argument(..., help="Path to the Windows installer"),
    args: Optional[list[str]] = typer.Argument(None, help="Extra arguments passed to the installer"),
) -> None:
    """Run a Windows installer inside a prefix (alias for 'run')."""
    _run_exe(name, exe, args or [])
