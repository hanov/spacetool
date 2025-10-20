#!/bin/bash
# Build script for disk_analyzer - creates standalone binaries
# Usage: ./build.sh [all|macos-arm|macos-intel|linux|windows]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Detect current platform
detect_platform() {
    case "$(uname -s)" in
        Darwin*)
            if [[ $(uname -m) == 'arm64' ]]; then
                echo "macos-arm"
            else
                echo "macos-intel"
            fi
            ;;
        Linux*)
            echo "linux"
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "windows"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

# Setup virtual environment and install PyInstaller
setup_venv() {
    local VENV_DIR="$SCRIPT_DIR/venv"

    if [ ! -d "$VENV_DIR" ]; then
        print_info "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
        print_success "Virtual environment created"
    fi

    # Activate virtual environment
    source "$VENV_DIR/bin/activate"
    print_success "Virtual environment activated"

    # Check if PyInstaller is installed in venv
    if ! command -v pyinstaller &> /dev/null; then
        print_info "Installing PyInstaller in virtual environment..."
        pip install --quiet pyinstaller
        print_success "PyInstaller installed"
    else
        print_success "PyInstaller found"
    fi
}

# Build for current platform
build_current() {
    local platform=$(detect_platform)
    print_info "Building for current platform: $platform"

    setup_venv

    # Clean previous builds
    rm -rf "$BUILD_DIR" "$DIST_DIR"

    case "$platform" in
        macos-arm)
            build_macos_arm
            ;;
        macos-intel)
            build_macos_intel
            ;;
        linux)
            build_linux
            ;;
        windows)
            build_windows
            ;;
        *)
            print_error "Unsupported platform: $platform"
            exit 1
            ;;
    esac
}

# Build for macOS ARM (Apple Silicon)
build_macos_arm() {
    print_info "Building macOS ARM binary..."

    pyinstaller --onefile \
        --name disk_analyzer_macos_arm64 \
        --target-arch arm64 \
        --add-data "disk_analyzer.py:." \
        disk_analyzer.py

    if [ -f "$DIST_DIR/disk_analyzer_macos_arm64" ]; then
        chmod +x "$DIST_DIR/disk_analyzer_macos_arm64"
        print_success "macOS ARM binary created: $DIST_DIR/disk_analyzer_macos_arm64"
        ls -lh "$DIST_DIR/disk_analyzer_macos_arm64"
    else
        print_error "Failed to create macOS ARM binary"
        exit 1
    fi
}

# Build for macOS Intel
build_macos_intel() {
    print_info "Building macOS Intel binary..."

    pyinstaller --onefile \
        --name disk_analyzer_macos_x86_64 \
        --target-arch x86_64 \
        --add-data "disk_analyzer.py:." \
        disk_analyzer.py

    if [ -f "$DIST_DIR/disk_analyzer_macos_x86_64" ]; then
        chmod +x "$DIST_DIR/disk_analyzer_macos_x86_64"
        print_success "macOS Intel binary created: $DIST_DIR/disk_analyzer_macos_x86_64"
        ls -lh "$DIST_DIR/disk_analyzer_macos_x86_64"
    else
        print_error "Failed to create macOS Intel binary"
        exit 1
    fi
}

# Build for Linux
build_linux() {
    print_info "Building Linux binary..."

    pyinstaller --onefile \
        --name disk_analyzer_linux_x86_64 \
        disk_analyzer.py

    if [ -f "$DIST_DIR/disk_analyzer_linux_x86_64" ]; then
        chmod +x "$DIST_DIR/disk_analyzer_linux_x86_64"
        print_success "Linux binary created: $DIST_DIR/disk_analyzer_linux_x86_64"
        ls -lh "$DIST_DIR/disk_analyzer_linux_x86_64"
    else
        print_error "Failed to create Linux binary"
        exit 1
    fi
}

# Build for Windows
build_windows() {
    print_info "Building Windows binary..."

    pyinstaller --onefile \
        --name disk_analyzer_windows.exe \
        disk_analyzer.py

    if [ -f "$DIST_DIR/disk_analyzer_windows.exe" ]; then
        print_success "Windows binary created: $DIST_DIR/disk_analyzer_windows.exe"
        ls -lh "$DIST_DIR/disk_analyzer_windows.exe"
    else
        print_error "Failed to create Windows binary"
        exit 1
    fi
}

# Build Linux binary using Docker (works on any platform)
build_linux_docker() {
    print_info "Building Linux binary using Docker..."

    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please install Docker Desktop."
        print_info "Download from: https://www.docker.com/products/docker-desktop"
        exit 1
    fi

    # Clean previous builds
    rm -rf "$BUILD_DIR" "$DIST_DIR"
    mkdir -p "$DIST_DIR"

    print_info "Building Docker image..."
    docker build --platform linux/amd64 -t disk-analyzer-builder:linux-amd64 -f Dockerfile .

    print_info "Extracting binary from container..."
    # Create a temporary container and copy the binary
    CONTAINER_ID=$(docker create --platform linux/amd64 disk-analyzer-builder:linux-amd64)
    docker cp "$CONTAINER_ID:/app/dist/disk_analyzer_linux_x86_64" "$DIST_DIR/"
    docker rm "$CONTAINER_ID"

    if [ -f "$DIST_DIR/disk_analyzer_linux_x86_64" ]; then
        chmod +x "$DIST_DIR/disk_analyzer_linux_x86_64"
        print_success "Linux x86_64 binary created: $DIST_DIR/disk_analyzer_linux_x86_64"
        ls -lh "$DIST_DIR/disk_analyzer_linux_x86_64"
    else
        print_error "Failed to create Linux binary"
        exit 1
    fi
}

# Build Windows binary using Docker (works on any platform)
build_windows_docker() {
    print_info "Building Windows binary using Docker..."

    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please install Docker Desktop."
        exit 1
    fi

    # Create Windows Dockerfile
    cat > Dockerfile.windows <<'EOF'
FROM python:3.11-windowsservercore

WORKDIR /app

RUN pip install pyinstaller

COPY disk_analyzer.py .

RUN pyinstaller --onefile --name disk_analyzer_windows disk_analyzer.py

CMD ["cmd", "/c", "copy", "dist\\*", "C:\\output\\"]
EOF

    print_info "Building Docker image for Windows..."
    docker build --platform windows/amd64 -t disk-analyzer-builder:windows -f Dockerfile.windows .

    mkdir -p "$DIST_DIR"

    print_info "Extracting binary from container..."
    CONTAINER_ID=$(docker create disk-analyzer-builder:windows)
    docker cp "$CONTAINER_ID:/app/dist/disk_analyzer_windows.exe" "$DIST_DIR/"
    docker rm "$CONTAINER_ID"

    rm Dockerfile.windows

    if [ -f "$DIST_DIR/disk_analyzer_windows.exe" ]; then
        print_success "Windows binary created: $DIST_DIR/disk_analyzer_windows.exe"
        ls -lh "$DIST_DIR/disk_analyzer_windows.exe"
    else
        print_error "Failed to create Windows binary"
        exit 1
    fi
}

# Show usage
show_usage() {
    cat << EOF
Disk Analyzer Build Script
==========================

Usage: $0 [OPTION]

Native Build Options (builds for current platform):
  current         Build for current platform (default)
  macos-arm       Build for macOS ARM64 (Apple Silicon) - requires macOS
  macos-intel     Build for macOS Intel (x86_64) - requires macOS
  linux           Build for Linux x86_64 - requires Linux
  windows         Build for Windows x86_64 - requires Windows

Cross-Platform Build Options (using Docker):
  docker-linux    Build Linux x86_64 binary using Docker (works on Mac/Linux/Windows)
  docker-windows  Build Windows binary using Docker (experimental)

Maintenance:
  clean           Clean build artifacts
  help            Show this help message

Examples:
  $0                    # Build for current platform (macOS ARM on M1)
  $0 macos-arm          # Build only macOS ARM binary (on macOS)
  $0 docker-linux       # Build Linux binary using Docker (on any platform)

Cross-Platform Notes:
  • PyInstaller can only build for the platform it's running on
  • Use Docker options to build for other platforms
  • Requires Docker Desktop installed
  • docker-linux works on M1 Mac, Intel Mac, Linux, Windows
  • Best option for M1 Mac users: use docker-linux or GitHub Actions

For building all platforms:
  1. Use GitHub Actions (recommended - automatic on git tag)
  2. Use Docker for Linux/Windows (this script)
  3. Run on each platform natively

EOF
}

# Clean build artifacts
clean() {
    print_info "Cleaning build artifacts..."
    rm -rf "$BUILD_DIR" "$DIST_DIR" "$SCRIPT_DIR/venv" *.spec
    print_success "Build artifacts cleaned"
}

# Main
main() {
    case "${1:-current}" in
        all|current)
            build_current
            ;;
        macos-arm)
            if [[ $(detect_platform) != "macos"* ]]; then
                print_error "macOS builds can only be created on macOS"
                exit 1
            fi
            setup_venv
            build_macos_arm
            ;;
        macos-intel)
            if [[ $(detect_platform) != "macos"* ]]; then
                print_error "macOS builds can only be created on macOS"
                exit 1
            fi
            setup_venv
            build_macos_intel
            ;;
        linux)
            if [[ $(detect_platform) != "linux" ]]; then
                print_error "Linux builds can only be created on Linux"
                print_info "Use 'docker-linux' option for cross-platform build"
                exit 1
            fi
            setup_venv
            build_linux
            ;;
        windows)
            if [[ $(detect_platform) != "windows" ]]; then
                print_error "Windows builds can only be created on Windows"
                exit 1
            fi
            setup_venv
            build_windows
            ;;
        docker-linux)
            build_linux_docker
            ;;
        docker-windows)
            build_windows_docker
            ;;
        clean)
            clean
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac

    if [ -d "$DIST_DIR" ]; then
        echo ""
        print_success "Build completed! Binaries are in: $DIST_DIR"
        echo ""
        ls -lh "$DIST_DIR"
    fi
}

main "$@"
