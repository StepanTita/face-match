#!/bin/sh
# Installs the facematch CLI as a single standalone binary — no Python or
# uv required. Usage:
#
#   curl -fsSL https://raw.githubusercontent.com/StepanTita/face-match/main/install.sh | sh
#
# Safe to re-run: it just re-downloads and overwrites the binary in place.
# See https://github.com/StepanTita/face-match for the source and
# https://github.com/StepanTita/face-match/blob/main/packaging/README.md for
# how these binaries are built.

set -eu

REPO="StepanTita/face-match"
INSTALL_DIR="${FACEMATCH_INSTALL_DIR:-$HOME/.local/bin}"
BIN_NAME="facematch"

say() {
    printf '%s\n' "$*"
}

err() {
    printf 'Error: %s\n' "$*" >&2
}

fetch() {
    # fetch <url> <output-path> — returns non-zero on any HTTP error (404
    # included) or transport failure, and never leaves a partial file behind
    # on failure.
    url="$1"
    out="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$out" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$out" "$url"
    else
        err "neither curl nor wget is available — install one of them and try again."
        exit 1
    fi
}

detect_asset() {
    os="$(uname -s)"
    arch="$(uname -m)"

    case "$os" in
        Darwin)
            case "$arch" in
                arm64) echo "facematch-macos-arm64" ;;
                *) echo "" ;;
            esac
            ;;
        Linux)
            case "$arch" in
                x86_64 | amd64) echo "facematch-linux-x86_64" ;;
                *) echo "" ;;
            esac
            ;;
        *) echo "" ;;
    esac
}

source_fallback() {
    cat <<'EOF'

No prebuilt binary is available for your platform yet — either this
platform/architecture isn't built by the release workflow, or no release
has been published yet.

You can still run facematch from source with uv (https://docs.astral.sh/uv/):

    git clone https://github.com/StepanTita/face-match.git
    cd face-match
    uv sync
    uv run facematch --help

See https://github.com/StepanTita/face-match#install for details.
EOF
}

check_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
        return 0
    fi
    say ""
    say "Note: ffmpeg/ffprobe were not found on your PATH. facematch works"
    say "fine on photos without them, but needs them to scan videos."
    case "$(uname -s)" in
        Darwin)
            say "Install with:  brew install ffmpeg"
            ;;
        Linux)
            say "Install with your package manager, e.g.:"
            say "  sudo apt install ffmpeg      (Debian/Ubuntu)"
            say "  sudo dnf install ffmpeg      (Fedora)"
            say "  sudo pacman -S ffmpeg        (Arch)"
            ;;
        *)
            say "Install ffmpeg using your system's package manager."
            ;;
    esac
}

check_path() {
    case ":$PATH:" in
        *":$INSTALL_DIR:"*) ;;
        *)
            say ""
            say "Note: $INSTALL_DIR is not on your PATH."
            say "Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
            say ""
            say "    export PATH=\"$INSTALL_DIR:\$PATH\""
            ;;
    esac
}

main() {
    asset="$(detect_asset)"
    if [ -z "$asset" ]; then
        err "no prebuilt binary for $(uname -s)/$(uname -m)."
        source_fallback
        exit 1
    fi

    url="https://github.com/$REPO/releases/latest/download/$asset"
    say "Downloading $asset..."

    tmp_file="$(mktemp)"
    trap 'rm -f "$tmp_file"' EXIT

    if ! fetch "$url" "$tmp_file"; then
        err "couldn't download a release binary from:"
        err "  $url"
        err "(no release has been published yet, or this asset is missing from it)"
        source_fallback
        exit 1
    fi

    if [ ! -s "$tmp_file" ]; then
        err "downloaded file is empty — something went wrong fetching $url"
        source_fallback
        exit 1
    fi

    mkdir -p "$INSTALL_DIR"
    dest="$INSTALL_DIR/$BIN_NAME"
    mv "$tmp_file" "$dest"
    chmod +x "$dest"
    trap - EXIT

    say "Installed facematch to $dest"

    check_path
    check_ffmpeg

    say ""
    say "Done. Try:"
    say ""
    say "    $dest --help"
    say ""
    say "(or just 'facematch --help' once $INSTALL_DIR is on your PATH)"
}

main "$@"
