"""Basic test coverage for the lithium CLI (src/lithium).

Covers pure helper functions, the env/command plumbing in
lithium_wine_exec/lithium_winetricks_exec, and the doctor/prefix-create/
prefix-kill commands -- all via mocked subprocess calls and a tmp_path
filesystem, so no real Wine/DXVK/MoltenVK build is needed to run these.
"""

import stat
import subprocess

import pytest
from typer.testing import CliRunner

import lithium

runner = CliRunner()


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# --- pure helpers ---


def test_dyld_wrapped_command():
    result = lithium._dyld_wrapped_command("wine", "cmd", "/c", "echo hi")
    assert result[:3] == ["arch", "-x86_64", "/usr/bin/env"]
    assert result[3] == f"DYLD_FALLBACK_LIBRARY_PATH={lithium.DYLD_FALLBACK_LIBRARY_PATH_VALUE}"
    assert result[4:] == ["wine", "cmd", "/c", "echo hi"]


def test_prefix_path():
    assert lithium.prefix_path("silksong") == lithium.PREFIXES_DIR / "silksong"


def test_require_wine_build_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(lithium, "WINE_BIN", tmp_path / "does-not-exist")
    with pytest.raises(lithium.typer.Exit):
        lithium.require_wine_build()


def test_require_wine_build_present(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    lithium.require_wine_build()  # should not raise


# --- env/command construction ---


def test_lithium_wine_exec_env_and_command(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)

    captured = {}

    def fake_run(command, env=None):
        captured["command"] = command
        captured["env"] = env

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)

    prefix_dir = tmp_path / "prefixes" / "silksong"
    rc = lithium.lithium_wine_exec(prefix_dir, "cmd", "/c", "echo hi", extra_dll_overrides="mscoree=")
    assert rc == 0

    # command should be wrapped via _dyld_wrapped_command, targeting our wine binary
    assert captured["command"][:3] == ["arch", "-x86_64", "/usr/bin/env"]
    assert str(wine_bin) in captured["command"]
    assert "cmd" in captured["command"]

    env = captured["env"]
    assert env["WINEPREFIX"] == str(prefix_dir)
    assert env["DXVK_CONFIG"] == lithium.DXVK_CONFIG_VALUE
    assert env["WINEDLLOVERRIDES"] == f"{lithium.WINEDLLOVERRIDES_VALUE},mscoree="
    assert env["GST_PLUGIN_PATH"] == lithium.GST_PLUGIN_PATH_VALUE


def test_lithium_winetricks_exec_env(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    wineserver_bin = tmp_path / "wineserver"
    make_executable(wine_bin)
    make_executable(wineserver_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "WINESERVER_BIN", wineserver_bin)

    captured = {}

    def fake_run(command, env=None):
        captured["command"] = command
        captured["env"] = env

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)

    prefix_dir = tmp_path / "prefixes" / "silksong"
    rc = lithium.lithium_winetricks_exec(prefix_dir, "vcrun2019")
    assert rc == 0
    assert captured["command"][:3] == ["arch", "-x86_64", "/usr/bin/env"]
    assert "winetricks" in captured["command"]
    assert "vcrun2019" in captured["command"]

    env = captured["env"]
    assert env["WINE"] == str(wine_bin)
    assert env["WINESERVER"] == str(wineserver_bin)
    assert env["WINEPREFIX"] == str(prefix_dir)


# --- version-reporting helpers ---


def test_git_describe_none_for_non_git_dir(tmp_path):
    assert lithium._git_describe(tmp_path / "not-a-repo") is None


def test_git_describe_reports_tag(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "test")
    run("git", "commit", "--allow-empty", "-q", "-m", "init")
    run("git", "tag", "v9.9.9")
    assert lithium._git_describe(repo) == "v9.9.9"


def test_dxvk_version_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", tmp_path / "no-dxvk-build")
    assert lithium._dxvk_version() is None


def test_dxvk_version_reads_generated_header(monkeypatch, tmp_path):
    build_dir = tmp_path / "dxvk-build"
    build_dir.mkdir()
    (build_dir / "version.h").write_text('#pragma once\n\n#define DXVK_VERSION "v9.9.9-1-gabc123"\n')
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", build_dir)
    assert lithium._dxvk_version() == "v9.9.9-1-gabc123"


# --- doctor ---


def _setup_ready_stack(monkeypatch, tmp_path):
    wine_bin = tmp_path / "build" / "wine" / "loader" / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    # non-git dirs by default -- keeps version-reporting isolated too, see
    # the dedicated _git_describe/_dxvk_version tests above for that logic
    monkeypatch.setattr(lithium, "WINE_SRC", tmp_path / "external" / "wine")
    monkeypatch.setattr(lithium, "MOLTENVK_SRC", tmp_path / "external" / "MoltenVK-src")
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", tmp_path / "build" / "dxvk")

    dxvk_build_dir = tmp_path / "build" / "dxvk" / "src"
    for sub, dll in lithium.DXVK_DLLS:
        dll_path = dxvk_build_dir / sub / dll
        dll_path.parent.mkdir(parents=True, exist_ok=True)
        dll_path.write_bytes(b"")
    monkeypatch.setattr(lithium, "DXVK_BUILD_DIR", dxvk_build_dir)

    moltenvk_dir = tmp_path / "external" / "MoltenVK"
    (moltenvk_dir / "libMoltenVK.dylib").parent.mkdir(parents=True, exist_ok=True)
    (moltenvk_dir / "libMoltenVK.dylib").write_bytes(b"")
    monkeypatch.setattr(lithium, "MOLTENVK_DYLIB_DIR", moltenvk_dir)


def test_doctor_ready(monkeypatch, tmp_path):
    _setup_ready_stack(monkeypatch, tmp_path)
    result = runner.invoke(lithium.app, ["doctor"])
    assert result.exit_code == 0
    assert "Status: ready" in result.stdout
    # source trees aren't real git checkouts in this fake stack, so these
    # report "unknown" rather than crashing -- that's the expected fallback.
    # Checked as short standalone substrings, not full table rows, since
    # Rich truncates long Detail-column values (e.g. tmp_path-based
    # MISSING paths) to fit the table to console width.
    assert "unknown (external/wine not found)" in result.stdout
    assert "unknown (external/MoltenVK not found)" in result.stdout
    assert "unknown (not built)" in result.stdout


def test_doctor_incomplete_when_wine_missing(monkeypatch, tmp_path):
    _setup_ready_stack(monkeypatch, tmp_path)
    monkeypatch.setattr(lithium, "WINE_BIN", tmp_path / "nonexistent-wine")
    result = runner.invoke(lithium.app, ["doctor"])
    assert result.exit_code == 1
    assert "Wine binary" in result.stdout
    assert "MISSING" in result.stdout
    assert "Status: incomplete" in result.stdout


def test_doctor_incomplete_when_dxvk_dll_missing(monkeypatch, tmp_path):
    _setup_ready_stack(monkeypatch, tmp_path)
    monkeypatch.setattr(lithium, "DXVK_BUILD_DIR", tmp_path / "empty-dxvk-dir")
    result = runner.invoke(lithium.app, ["doctor"])
    assert result.exit_code == 1
    assert "Status: incomplete" in result.stdout


# --- ps ---


def test_wineserver_pids_matches_exact_command(monkeypatch, tmp_path):
    wineserver_bin = tmp_path / "wineserver"
    monkeypatch.setattr(lithium, "WINESERVER_BIN", wineserver_bin)

    def fake_run(command, capture_output=None, text=None):
        class Result:
            stdout = (
                f"111 {wineserver_bin}\n"
                f"222 {wineserver_bin} --extra-arg\n"  # not an exact match, ignored
                "333 /usr/bin/unrelated\n"
            )

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)
    assert lithium._wineserver_pids() == [111]


def test_wineserver_prefix_matches_open_directory(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "silksong").mkdir(parents=True)
    (prefixes_dir / "other").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)

    def fake_run(command, capture_output=None, text=None):
        class Result:
            returncode = 0
            stdout = f"wineserve 111 user 4r DIR ... {prefixes_dir / 'silksong'}\n"

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)
    assert lithium._wineserver_prefix(111) == "silksong"


def test_running_exe_ignores_windows_style_paths(monkeypatch, tmp_path):
    prefix_dir = tmp_path / "prefixes" / "silksong"
    prefix_dir.mkdir(parents=True)
    game_exe = prefix_dir / "drive_c" / "Games" / "Silksong.exe"

    def fake_run(command, capture_output=None, text=None):
        class Result:
            stdout = (
                "111 C:\\windows\\system32\\winedevice.exe\n"  # wine-internal, ignored
                f"222 {game_exe}\n"
            )

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)
    assert lithium._running_exe(prefix_dir) == ("Silksong.exe", 222)


def test_running_exe_none_when_idle(monkeypatch, tmp_path):
    prefix_dir = tmp_path / "prefixes" / "silksong"
    prefix_dir.mkdir(parents=True)

    def fake_run(command, capture_output=None, text=None):
        class Result:
            stdout = "111 C:\\windows\\system32\\winedevice.exe\n"

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)
    assert lithium._running_exe(prefix_dir) is None


def test_ps_command_no_prefixes(monkeypatch, tmp_path):
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "no-such-dir")
    result = runner.invoke(lithium.app, ["ps"])
    assert result.exit_code == 0
    assert "No prefixes found" in result.stdout


def test_ps_command_lists_idle_prefix(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "silksong").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)

    def fake_run(command, capture_output=None, text=None):
        class Result:
            stdout = ""  # nothing running at all

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)
    result = runner.invoke(lithium.app, ["ps"])
    assert result.exit_code == 0
    assert "silksong" in result.stdout


# --- prefix-list ---


def test_prefix_list_no_prefixes(monkeypatch, tmp_path):
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "no-such-dir")
    result = runner.invoke(lithium.app, ["prefix-list"])
    assert result.exit_code == 0
    assert "No prefixes found" in result.stdout


def test_prefix_list_shows_initialized_and_uninitialized(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "ready" / "drive_c").mkdir(parents=True)
    (prefixes_dir / "half-created").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)

    result = runner.invoke(lithium.app, ["prefix-list"])
    assert result.exit_code == 0
    assert "ready" in result.stdout
    assert "yes" in result.stdout
    assert "half-created" in result.stdout
    assert "no" in result.stdout


# --- prefix-create / prefix-kill ---


def test_prefix_create_fails_if_already_exists(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")

    existing = tmp_path / "prefixes" / "silksong"
    existing.mkdir(parents=True)

    result = runner.invoke(lithium.app, ["prefix-create", "silksong"])
    assert result.exit_code == 1
    # typer.echo(..., err=True) goes to stderr, which CliRunner only
    # surfaces via .output, not .stdout
    assert "already exists" in result.output


def test_prefix_kill_fails_if_missing(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")

    result = runner.invoke(lithium.app, ["prefix-kill", "does-not-exist"])
    assert result.exit_code == 1
    assert "no such prefix" in result.output
