#!/usr/bin/env bash
# Build Lithium's Wine + DXVK + MoltenVK stack from source.
#
# Captures, as an actual reproducible script, the manual steps documented in
# docs/plan.md phases 0-2. See docs/plan.md and the project_lithium_build_env
# / project_lithium_dxvk_patches memory notes for the "why" behind each step
# -- this script is deliberately just the "what commands to run."
#
# Requires: full Xcode (not just Command Line Tools) already installed and
# selected via `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`
# (needed for MoltenVK's xcodebuild) -- not automated here since it needs an
# interactive App Store install and admin password.
#
# Safe to re-run: each step skips work that's already done (existing clones
# are left on whatever commit they're checked out to, existing build output
# directories are reused/reconfigured rather than wiped).

set -euo pipefail

LITHIUM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTERNAL_DIR="$HOME/external"
BUILD_DIR="$LITHIUM_ROOT/build"

WINE_SRC="$EXTERNAL_DIR/wine"
WINE_TAG="wine-11.16"
MOLTENVK_SRC="$EXTERNAL_DIR/MoltenVK"
PROTON_SRC="$EXTERNAL_DIR/Proton"
DXVK_SRC="$PROTON_SRC/dxvk"

log() { echo "==> $*"; }

# ---------------------------------------------------------------------------
# Step 0: sanity checks
# ---------------------------------------------------------------------------

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "error: this script targets Apple Silicon macOS only" >&2
    exit 1
fi

XCODE_PATH="$(xcode-select -p 2>/dev/null || true)"
if [[ "$XCODE_PATH" != *"Xcode.app"* ]]; then
    echo "error: full Xcode must be installed and selected (found: ${XCODE_PATH:-none})." >&2
    echo "       Install Xcode from the App Store, then run:" >&2
    echo "       sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
    exit 1
fi

if ! command -v /opt/homebrew/bin/brew >/dev/null 2>&1; then
    echo "error: arm64 Homebrew not found at /opt/homebrew (install it first)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: arm64 Homebrew build tools (host-side, produce PE/x86_64 output)
# ---------------------------------------------------------------------------

log "Installing arm64 Homebrew build dependencies..."
/opt/homebrew/bin/brew install \
    autoconf automake pkgconf meson ninja gettext bison mingw-w64 \
    innoextract winetricks

BISON_PATH="/opt/homebrew/opt/bison/bin"

# ---------------------------------------------------------------------------
# Step 2: x86_64 Homebrew prefix (runtime deps -- Wine itself is x86_64)
# ---------------------------------------------------------------------------

if ! command -v /usr/local/bin/brew >/dev/null 2>&1; then
    log "Bootstrapping a second, x86_64 Homebrew prefix at /usr/local..."
    log "(this needs your admin password interactively)"
    arch -x86_64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

log "Installing x86_64 Homebrew runtime dependencies..."
arch -x86_64 /usr/local/bin/brew install \
    freetype sdl2 gnutls mpg123 gstreamer libffi bzip2 zlib

# Homebrew's bzip2 ships no .pc file, which breaks freetype2's pkg-config
# `Requires: bzip2` -- write one by hand.
EXTRA_PKGCONFIG_DIR="$BUILD_DIR/extra-pkgconfig"
mkdir -p "$EXTRA_PKGCONFIG_DIR"
cat > "$EXTRA_PKGCONFIG_DIR/bzip2.pc" <<'EOF'
prefix=/usr/local/opt/bzip2
exec_prefix=${prefix}
libdir=${exec_prefix}/lib
includedir=${prefix}/include

Name: bzip2
Description: bzip2 compression library
Version: 1.0.8
Libs: -L${libdir} -lbz2
Cflags: -I${includedir}
EOF

# ---------------------------------------------------------------------------
# Step 3: MoltenVK (Vulkan -> Metal), built x86_64
# ---------------------------------------------------------------------------

if [[ ! -d "$MOLTENVK_SRC" ]]; then
    log "Cloning MoltenVK..."
    git clone https://github.com/KhronosGroup/MoltenVK.git "$MOLTENVK_SRC"
fi

MOLTENVK_DYLIB="$MOLTENVK_SRC/Package/Release/MoltenVK/dynamic/dylib/macOS/libMoltenVK.dylib"
if [[ ! -f "$MOLTENVK_DYLIB" ]]; then
    log "Building MoltenVK (this takes a while)..."
    (
        cd "$MOLTENVK_SRC"
        ./fetchDependencies --macos -v
        xcodebuild build -project MoltenVKPackaging.xcodeproj \
            -scheme "MoltenVK Package (macOS only)" \
            -configuration Release ARCHS=x86_64 ONLY_ACTIVE_ARCH=NO
    )
else
    log "MoltenVK already built, skipping."
fi

# ---------------------------------------------------------------------------
# Step 4: Wine, built x86_64 with WoW64 + GStreamer support
# ---------------------------------------------------------------------------

if [[ ! -d "$WINE_SRC" ]]; then
    log "Cloning WineHQ wine..."
    git clone https://gitlab.winehq.org/wine/wine.git "$WINE_SRC"
fi
(cd "$WINE_SRC" && git fetch --tags && git checkout "$WINE_TAG")

WINE_BUILD_DIR="$BUILD_DIR/wine"
mkdir -p "$WINE_BUILD_DIR"

if [[ ! -f "$WINE_BUILD_DIR/Makefile" ]]; then
    log "Configuring Wine ($WINE_TAG, x86_64+i386 WoW64, Mac driver, GStreamer, MoltenVK)..."
    (
        cd "$WINE_BUILD_DIR"
        PATH="$BISON_PATH:/opt/homebrew/bin:/usr/local/bin:$PATH" \
        PKG_CONFIG_PATH="$EXTRA_PKGCONFIG_DIR:/usr/local/lib/pkgconfig:/usr/local/share/pkgconfig" \
        CC="gcc -std=gnu23 -m64" \
        CPPFLAGS="-I$MOLTENVK_SRC/Package/Release/MoltenVK/include" \
        LDFLAGS="-L$MOLTENVK_SRC/Package/Release/MoltenVK/dynamic/dylib/macOS" \
            "$WINE_SRC/configure" --enable-archs=i386,x86_64 --without-x --without-wayland
    )
else
    log "Wine already configured, skipping configure step."
fi

log "Building Wine (this takes a while)..."
(
    cd "$WINE_BUILD_DIR"
    PATH="$BISON_PATH:/opt/homebrew/bin:/usr/local/bin:$PATH" make -j"$(sysctl -n hw.ncpu)"
)

# ---------------------------------------------------------------------------
# Step 5: DXVK (D3D9/10/11 -> Vulkan), patched for Apple GPU limitations
# ---------------------------------------------------------------------------

if [[ ! -d "$PROTON_SRC" ]]; then
    log "Cloning Proton (for the dxvk submodule)..."
    git clone https://github.com/ValveSoftware/Proton.git "$PROTON_SRC"
fi
if [[ ! -f "$DXVK_SRC/meson.build" ]]; then
    (cd "$PROTON_SRC" && git submodule update --init dxvk)
fi

DXVK_PATCH="$LITHIUM_ROOT/patches/dxvk-apple-silicon.patch"
if (cd "$DXVK_SRC" && ! git apply --check --reverse "$DXVK_PATCH" 2>/dev/null); then
    log "Applying Apple Silicon DXVK patches..."
    (cd "$DXVK_SRC" && git apply "$DXVK_PATCH")
else
    log "DXVK patches already applied, skipping."
fi

DXVK_BUILD_DIR="$BUILD_DIR/dxvk"
if [[ ! -f "$DXVK_BUILD_DIR/build.ninja" ]]; then
    log "Configuring DXVK (mingw cross build)..."
    meson setup --cross-file "$DXVK_SRC/build-win64.txt" -Dbuildtype=release \
        "$DXVK_BUILD_DIR" "$DXVK_SRC"
else
    log "DXVK already configured, skipping configure step."
fi

log "Building DXVK..."
ninja -C "$DXVK_BUILD_DIR"

log "Done. Verify with: uv run lithium doctor"
