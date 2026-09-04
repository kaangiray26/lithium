"""Basic test coverage for the lithium CLI (src/lithium).

Covers pure helper functions, the env/command plumbing in
lithium_wine_exec/lithium_winetricks_exec, and the doctor/`prefix create`/
`prefix kill` commands -- all via mocked subprocess calls and a tmp_path
filesystem, so no real Wine/DXVK/MoltenVK build is needed to run these.
"""

import stat
import subprocess
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lithium

runner = CliRunner()


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def write_fake_dxvk_dlls(build_dir):
    for sub, dll in lithium.DXVK_DLLS:
        dll_path = build_dir / sub / dll
        dll_path.parent.mkdir(parents=True, exist_ok=True)
        dll_path.write_bytes(b"fake-dll")


# --- pure helpers ---


def test_dyld_wrapped_command():
    result = lithium._dyld_wrapped_command("wine", "cmd", "/c", "echo hi")
    assert result[:3] == ["arch", "-x86_64", "/usr/bin/env"]
    assert result[3] == f"DYLD_FALLBACK_LIBRARY_PATH={lithium.DYLD_FALLBACK_LIBRARY_PATH_VALUE}"
    assert result[4:] == ["wine", "cmd", "/c", "echo hi"]


def test_prefix_path():
    assert lithium.prefix_path("silksong") == lithium.PREFIXES_DIR / "silksong"


# --- LITHIUM_ROOT detection (dev checkout vs installed standalone) ---


def test_detect_lithium_root_dev_checkout(monkeypatch, tmp_path):
    repo_root = tmp_path / "some-checkout"
    package_dir = repo_root / "src" / "lithium"
    package_dir.mkdir(parents=True)
    monkeypatch.setattr(lithium, "PACKAGE_DIR", package_dir)
    assert lithium._detect_lithium_root() == repo_root


def test_detect_lithium_root_installed_uses_app_support(monkeypatch, tmp_path):
    site_packages_lithium = tmp_path / "site-packages" / "lithium"
    site_packages_lithium.mkdir(parents=True)
    monkeypatch.setattr(lithium, "PACKAGE_DIR", site_packages_lithium)
    monkeypatch.delenv("LITHIUM_DATA_DIR", raising=False)
    assert lithium._detect_lithium_root() == Path.home() / "Library" / "Application Support" / "lithium"


def test_detect_lithium_root_installed_respects_override(monkeypatch, tmp_path):
    site_packages_lithium = tmp_path / "site-packages" / "lithium"
    site_packages_lithium.mkdir(parents=True)
    monkeypatch.setattr(lithium, "PACKAGE_DIR", site_packages_lithium)
    monkeypatch.setenv("LITHIUM_DATA_DIR", str(tmp_path / "custom-data-dir"))
    assert lithium._detect_lithium_root() == tmp_path / "custom-data-dir"


def test_patches_are_bundled_as_package_data():
    assert lithium.DXVK_PATCH.is_file()
    for patch_path in lithium.WINE_PATCHES:
        assert patch_path.is_file()
    # Bundled under the package itself, not the dev-checkout LITHIUM_ROOT --
    # this is what makes them ship inside an installed wheel.
    assert lithium.PACKAGE_DIR in lithium.DXVK_PATCH.parents


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


def test_lithium_wine_exec_sets_winedebug_when_given(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)

    captured = {}

    def fake_run(command, env=None):
        captured["env"] = env

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)

    lithium.lithium_wine_exec(tmp_path / "prefixes" / "silksong", "cmd", winedebug="+relay,+server")
    assert captured["env"]["WINEDEBUG"] == "+relay,+server"


def test_lithium_wine_exec_no_winedebug_key_by_default(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.delenv("WINEDEBUG", raising=False)

    captured = {}

    def fake_run(command, env=None):
        captured["env"] = env

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)

    lithium.lithium_wine_exec(tmp_path / "prefixes" / "silksong", "cmd")
    assert "WINEDEBUG" not in captured["env"]


def test_run_command_passes_debug_flag_through(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    prefix_dir = tmp_path / "prefixes" / "silksong"
    prefix_dir.mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefix_dir.parent)

    captured = {}

    def fake_exec(prefix_dir, *args, extra_dll_overrides=None, winedebug=None):
        captured["winedebug"] = winedebug
        captured["args"] = args
        return 0

    monkeypatch.setattr(lithium, "lithium_wine_exec", fake_exec)

    result = runner.invoke(lithium.app, ["run", "silksong", "cmd", "--debug=+relay", "/c", "echo hi"])
    assert result.exit_code == 0
    assert captured["winedebug"] == "+relay"
    # --debug shouldn't leak into the passthrough args meant for the exe
    assert "--debug=+relay" not in captured["args"]
    assert captured["args"] == ("cmd", "/c", "echo hi")


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


# --- _run quiet mode (build --quiet) ---


def test_run_helper_quiet_suppresses_output_on_success(monkeypatch, capsys):
    monkeypatch.setattr(lithium, "_QUIET", True)
    lithium._run(["sh", "-c", "echo to-stdout; echo to-stderr >&2"])
    captured = capsys.readouterr()
    assert "to-stdout" not in captured.out
    assert "to-stderr" not in captured.err


def test_run_helper_quiet_dumps_output_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(lithium, "_QUIET", True)
    with pytest.raises(lithium.typer.Exit) as exc:
        lithium._run(["sh", "-c", "echo boom >&2; exit 3"])
    assert exc.value.exit_code == 3
    captured = capsys.readouterr()
    assert "boom" in captured.err


def test_run_helper_non_quiet_is_default(monkeypatch):
    # sanity: module default is False so normal builds stay verbose
    assert lithium._QUIET is False


# --- clean ---


def test_clean_nothing_to_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(lithium, "WINE_BUILD_DIR", tmp_path / "build" / "wine")
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", tmp_path / "build" / "dxvk")
    monkeypatch.setattr(lithium, "DXVK32_MESON_BUILD_DIR", tmp_path / "build" / "dxvk32")
    result = runner.invoke(lithium.app, ["clean"])
    assert result.exit_code == 0
    assert "Nothing to clean" in result.output


def test_clean_removes_build_dirs_with_force(monkeypatch, tmp_path):
    wine_build = tmp_path / "build" / "wine"
    dxvk_build = tmp_path / "build" / "dxvk"
    (wine_build / "loader").mkdir(parents=True)
    (dxvk_build / "src").mkdir(parents=True)
    monkeypatch.setattr(lithium, "WINE_BUILD_DIR", wine_build)
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", dxvk_build)
    monkeypatch.setattr(lithium, "DXVK32_MESON_BUILD_DIR", tmp_path / "build" / "dxvk32")

    result = runner.invoke(lithium.app, ["clean", "--force"])
    assert result.exit_code == 0
    assert not wine_build.exists()
    assert not dxvk_build.exists()


def test_clean_aborts_without_confirmation(monkeypatch, tmp_path):
    wine_build = tmp_path / "build" / "wine"
    wine_build.mkdir(parents=True)
    monkeypatch.setattr(lithium, "WINE_BUILD_DIR", wine_build)
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", tmp_path / "build" / "dxvk")
    monkeypatch.setattr(lithium, "DXVK32_MESON_BUILD_DIR", tmp_path / "build" / "dxvk32")

    result = runner.invoke(lithium.app, ["clean"], input="n\n")
    assert result.exit_code != 0
    assert wine_build.exists()


def test_clean_moltenvk_flag_includes_package_dir(monkeypatch, tmp_path):
    package_dir = tmp_path / "external" / "MoltenVK" / "Package"
    package_dir.mkdir(parents=True)
    monkeypatch.setattr(lithium, "WINE_BUILD_DIR", tmp_path / "build" / "wine")
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", tmp_path / "build" / "dxvk")
    monkeypatch.setattr(lithium, "DXVK32_MESON_BUILD_DIR", tmp_path / "build" / "dxvk32")
    monkeypatch.setattr(lithium, "MOLTENVK_PACKAGE_DIR", package_dir)

    result = runner.invoke(lithium.app, ["clean", "--moltenvk", "--force"])
    assert result.exit_code == 0
    assert not package_dir.exists()


# --- package ---


def _setup_packageable_stack(monkeypatch, tmp_path):
    wine_bin = tmp_path / "build" / "wine" / "loader" / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "WINE_BUILD_DIR", tmp_path / "build" / "wine")
    monkeypatch.setattr(lithium, "WINE_SRC", tmp_path / "external" / "wine")
    monkeypatch.setattr(lithium, "MOLTENVK_SRC", tmp_path / "external" / "MoltenVK-src")
    monkeypatch.setattr(lithium, "DXVK_MESON_BUILD_DIR", tmp_path / "build" / "dxvk")
    monkeypatch.setattr(lithium, "DIST_DIR", tmp_path / "dist")

    dxvk_build_dir = tmp_path / "build" / "dxvk" / "src"
    write_fake_dxvk_dlls(dxvk_build_dir)
    monkeypatch.setattr(lithium, "DXVK_BUILD_DIR", dxvk_build_dir)

    dxvk32_build_dir = tmp_path / "build" / "dxvk32" / "src"
    write_fake_dxvk_dlls(dxvk32_build_dir)
    monkeypatch.setattr(lithium, "DXVK32_BUILD_DIR", dxvk32_build_dir)

    moltenvk_dir = tmp_path / "external" / "MoltenVK"
    (moltenvk_dir / "libMoltenVK.dylib").parent.mkdir(parents=True, exist_ok=True)
    (moltenvk_dir / "libMoltenVK.dylib").write_bytes(b"fake-dylib")
    monkeypatch.setattr(lithium, "MOLTENVK_DYLIB_DIR", moltenvk_dir)

    def fake_run(command, cwd=None, env=None):
        destdir = next(arg.split("=", 1)[1] for arg in command if arg.startswith("DESTDIR="))
        bin_dir = Path(destdir) / "usr" / "local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "wine").write_bytes(b"fake-installed-wine")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)


def test_package_fails_when_build_incomplete(monkeypatch, tmp_path):
    _setup_packageable_stack(monkeypatch, tmp_path)
    monkeypatch.setattr(lithium, "WINE_BIN", tmp_path / "nonexistent-wine")

    result = runner.invoke(lithium.app, ["package"])
    assert result.exit_code == 1
    assert "build is incomplete" in result.output
    assert not (tmp_path / "dist").exists()


def test_package_produces_archive_and_checksum(monkeypatch, tmp_path):
    _setup_packageable_stack(monkeypatch, tmp_path)

    result = runner.invoke(lithium.app, ["package"])
    assert result.exit_code == 0, result.output

    archives = list((tmp_path / "dist").glob("lithium-*-macos-*.tar.gz"))
    assert len(archives) == 1
    archive_path = archives[0]

    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    assert checksum_path.is_file()
    assert lithium._sha256_file(archive_path) == checksum_path.read_text().split()[0]

    with tarfile.open(archive_path) as tar:
        names = tar.getnames()
        base = names[0].split("/")[0]
        assert f"{base}/manifest.json" in names
        assert f"{base}/wine/bin/wine" in names
        assert f"{base}/moltenvk/libMoltenVK.dylib" in names
        for sub, dll in lithium.DXVK_DLLS:
            assert f"{base}/dxvk/{sub}/{dll}" in names
            assert f"{base}/dxvk32/{sub}/{dll}" in names

        import json

        manifest = json.loads(tar.extractfile(f"{base}/manifest.json").read())
        assert manifest["arch"] == "arm64"
        assert manifest["wine_ref"] == "unknown"


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
    write_fake_dxvk_dlls(dxvk_build_dir)
    monkeypatch.setattr(lithium, "DXVK_BUILD_DIR", dxvk_build_dir)

    dxvk32_build_dir = tmp_path / "build" / "dxvk32" / "src"
    write_fake_dxvk_dlls(dxvk32_build_dir)
    monkeypatch.setattr(lithium, "DXVK32_BUILD_DIR", dxvk32_build_dir)

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
    result = runner.invoke(lithium.app, ["prefix", "list"])
    assert result.exit_code == 0
    assert "No prefixes found" in result.stdout


def test_prefix_list_shows_initialized_and_uninitialized(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "ready" / "drive_c").mkdir(parents=True)
    (prefixes_dir / "half-created").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)

    result = runner.invoke(lithium.app, ["prefix", "list"])
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

    result = runner.invoke(lithium.app, ["prefix", "create", "silksong"])
    assert result.exit_code == 1
    # typer.echo(..., err=True) goes to stderr, which CliRunner only
    # surfaces via .output, not .stdout
    assert "already exists" in result.output


def test_prefix_create_installs_dxvk32_into_syswow64(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")

    dxvk_build_dir = tmp_path / "dxvk"
    write_fake_dxvk_dlls(dxvk_build_dir)
    monkeypatch.setattr(lithium, "DXVK_BUILD_DIR", dxvk_build_dir)

    dxvk32_build_dir = tmp_path / "dxvk32"
    write_fake_dxvk_dlls(dxvk32_build_dir)
    monkeypatch.setattr(lithium, "DXVK32_BUILD_DIR", dxvk32_build_dir)

    monkeypatch.setattr(
        lithium.subprocess, "run", lambda command, env=None: type("Result", (), {"returncode": 0})()
    )

    result = runner.invoke(lithium.app, ["prefix", "create", "batman"])
    assert result.exit_code == 0, result.output

    prefix_dir = tmp_path / "prefixes" / "batman"
    for sub, dll in lithium.DXVK_DLLS:
        assert (prefix_dir / "drive_c" / "windows" / "system32" / dll).read_bytes() == b"fake-dll"
        assert (prefix_dir / "drive_c" / "windows" / "syswow64" / dll).read_bytes() == b"fake-dll"


def test_prefix_create_with_deps_runs_winetricks(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    wineserver_bin = tmp_path / "wineserver"
    make_executable(wine_bin)
    make_executable(wineserver_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "WINESERVER_BIN", wineserver_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")
    monkeypatch.setattr(lithium.shutil, "which", lambda _name: "/usr/local/bin/winetricks")

    dxvk_build_dir = tmp_path / "dxvk"
    write_fake_dxvk_dlls(dxvk_build_dir)
    monkeypatch.setattr(lithium, "DXVK_BUILD_DIR", dxvk_build_dir)

    dxvk32_build_dir = tmp_path / "dxvk32"
    write_fake_dxvk_dlls(dxvk32_build_dir)
    monkeypatch.setattr(lithium, "DXVK32_BUILD_DIR", dxvk32_build_dir)

    calls = []

    def fake_run(command, env=None):
        calls.append(command)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)

    result = runner.invoke(
        lithium.app, ["prefix", "create", "silksong", "--with", "vcrun2019, dotnet48"]
    )
    assert result.exit_code == 0, result.output

    winetricks_calls = [c for c in calls if "winetricks" in c]
    assert len(winetricks_calls) == 1
    assert winetricks_calls[0][-2:] == ["vcrun2019", "dotnet48"]


def test_prefix_create_with_requires_winetricks_installed(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")
    monkeypatch.setattr(lithium.shutil, "which", lambda _name: None)

    result = runner.invoke(lithium.app, ["prefix", "create", "silksong", "--with", "vcrun2019"])
    assert result.exit_code == 1
    assert "needs winetricks" in result.output
    # bailed before creating anything
    assert not (tmp_path / "prefixes" / "silksong").exists()


def test_prefix_create_with_empty_verbs_errors(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")

    result = runner.invoke(lithium.app, ["prefix", "create", "silksong", "--with", " , "])
    assert result.exit_code == 1
    assert "lists no verbs" in result.output


# --- run / install preflight ---


def _setup_run_stack(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")
    (tmp_path / "prefixes" / "silksong" / "drive_c").mkdir(parents=True)

    calls = []

    def fake_run(command, env=None):
        calls.append(command)

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(lithium.subprocess, "run", fake_run)
    return calls


def test_run_rejects_missing_host_path(monkeypatch, tmp_path):
    calls = _setup_run_stack(monkeypatch, tmp_path)
    result = runner.invoke(
        lithium.app, ["run", "silksong", "prefixes/silksong/drive_c/Games/Typo.exe"]
    )
    assert result.exit_code == 1
    assert "no such file" in result.output
    assert calls == []  # bailed before invoking wine


def test_run_allows_existing_host_path(monkeypatch, tmp_path):
    calls = _setup_run_stack(monkeypatch, tmp_path)
    game_exe = tmp_path / "prefixes" / "silksong" / "drive_c" / "Games" / "Game.exe"
    game_exe.parent.mkdir(parents=True)
    game_exe.write_bytes(b"MZ")

    result = runner.invoke(lithium.app, ["run", "silksong", str(game_exe)])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert str(game_exe) in calls[0]


def test_run_skips_preflight_for_bare_builtin_name(monkeypatch, tmp_path):
    calls = _setup_run_stack(monkeypatch, tmp_path)
    result = runner.invoke(lithium.app, ["run", "silksong", "wineboot"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert "wineboot" in calls[0]


def test_install_preflights_too(monkeypatch, tmp_path):
    calls = _setup_run_stack(monkeypatch, tmp_path)
    result = runner.invoke(lithium.app, ["install", "silksong", "./no/such/setup.exe"])
    assert result.exit_code == 1
    assert "no such file" in result.output
    assert calls == []


def test_prefix_kill_fails_if_missing(monkeypatch, tmp_path):
    wine_bin = tmp_path / "wine"
    make_executable(wine_bin)
    monkeypatch.setattr(lithium, "WINE_BIN", wine_bin)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")

    result = runner.invoke(lithium.app, ["prefix", "kill", "does-not-exist"])
    assert result.exit_code == 1
    assert "no such prefix" in result.output


# --- prefix-remove ---


def test_prefix_remove_fails_if_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(lithium, "PREFIXES_DIR", tmp_path / "prefixes")
    result = runner.invoke(lithium.app, ["prefix", "remove", "does-not-exist"])
    assert result.exit_code == 1
    assert "no such prefix" in result.output


def test_prefix_remove_deletes_with_force(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "silksong" / "drive_c").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)
    monkeypatch.setattr(lithium, "_wineserver_pids", lambda: [])

    result = runner.invoke(lithium.app, ["prefix", "remove", "silksong", "--force"])
    assert result.exit_code == 0
    assert not (prefixes_dir / "silksong").exists()
    assert "Removed prefix 'silksong'" in result.output


def test_prefix_remove_aborts_without_confirmation(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "silksong").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)
    monkeypatch.setattr(lithium, "_wineserver_pids", lambda: [])

    result = runner.invoke(lithium.app, ["prefix", "remove", "silksong"], input="n\n")
    assert result.exit_code != 0
    assert (prefixes_dir / "silksong").exists()


def test_prefix_remove_refuses_while_wineserver_live(monkeypatch, tmp_path):
    prefixes_dir = tmp_path / "prefixes"
    (prefixes_dir / "silksong").mkdir(parents=True)
    monkeypatch.setattr(lithium, "PREFIXES_DIR", prefixes_dir)
    monkeypatch.setattr(lithium, "_wineserver_pids", lambda: [4242])
    monkeypatch.setattr(lithium, "_wineserver_prefix", lambda pid: "silksong")

    result = runner.invoke(lithium.app, ["prefix", "remove", "silksong", "--force"])
    assert result.exit_code == 1
    assert "live wineserver" in result.output
    assert (prefixes_dir / "silksong").exists()
