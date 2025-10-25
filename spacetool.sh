#!/bin/bash
# SpaceTool - Build and Install Script
# Unified script for building binary and installing to system

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[*]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

show_help() {
    cat << EOF
SpaceTool - Disk Space Analyzer

USAGE:
    ./spacetool.sh [COMMAND]

COMMANDS:
    build       Build standalone binary
    install     Install binary to system
    uninstall   Remove installed binary
    clean       Clean build artifacts
    help        Show this help

EXAMPLES:
    ./spacetool.sh build              # Build binary
    ./spacetool.sh install            # Install to ~/.local/bin
    ./spacetool.sh uninstall          # Remove from system

AFTER INSTALLATION:
    spacetool ~/Documents             # Analyze disk space
    spacetool --help                  # Show help
    spacetool --manual                # Show full manual

NO INSTALLATION NEEDED:
    ./dist/disk_analyzer_macos_arm64 ~/Documents

EOF
}

build_binary() {
    print_status "Building SpaceTool binary..."

    # Detect platform
    PLATFORM=""
    BINARY_NAME=""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        ARCH=$(uname -m)
        if [[ "$ARCH" == "arm64" ]]; then
            BINARY_NAME="disk_analyzer_macos_arm64"
            PLATFORM="macOS ARM64"
        else
            BINARY_NAME="disk_analyzer_macos_x86_64"
            PLATFORM="macOS x86_64"
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        BINARY_NAME="disk_analyzer_linux_x86_64"
        PLATFORM="Linux"
    else
        print_error "Unsupported platform: $OSTYPE"
        exit 1
    fi

    print_status "Platform: $PLATFORM"

    # Create venv if doesn't exist
    if [ ! -d "venv" ]; then
        print_status "Creating virtual environment..."
        python3 -m venv venv
    fi

    # Activate venv
    source venv/bin/activate

    # Install PyInstaller if needed
    if ! python -c "import PyInstaller" 2>/dev/null; then
        print_status "Installing PyInstaller..."
        pip install pyinstaller --quiet
    fi

    # Build binary
    print_status "Building binary..."
    pyinstaller --onefile --name "$BINARY_NAME" disk_analyzer.py --noconfirm > /dev/null 2>&1

    if [ -f "dist/$BINARY_NAME" ]; then
        SIZE=$(ls -lh "dist/$BINARY_NAME" | awk '{print $5}')
        print_success "Binary built: dist/$BINARY_NAME ($SIZE)"
        echo ""
        print_status "Test it:"
        echo "  ./dist/$BINARY_NAME --help"
        echo "  ./dist/$BINARY_NAME ~/Desktop -d 3"
    else
        print_error "Build failed"
        exit 1
    fi
}

install_binary() {
    # Detect platform and binary
    ARCH=$(uname -m)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if [[ "$ARCH" == "arm64" ]]; then
            BINARY="dist/disk_analyzer_macos_arm64"
        else
            BINARY="dist/disk_analyzer_macos_x86_64"
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        BINARY="dist/disk_analyzer_linux_x86_64"
    else
        print_error "Unsupported platform"
        exit 1
    fi

    if [ ! -f "$BINARY" ]; then
        print_error "Binary not found: $BINARY"
        echo ""
        print_status "Build it first:"
        echo "  ./spacetool.sh build"
        exit 1
    fi

    print_status "Installing SpaceTool..."

    # Default to ~/.local/bin
    INSTALL_DIR="$HOME/.local/bin"

    # Ask for confirmation
    echo ""
    print_warning "Install to: $INSTALL_DIR"
    read -p "Continue? [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
        print_status "Installation cancelled"
        exit 0
    fi

    # Create directory
    mkdir -p "$INSTALL_DIR"

    # Copy binary
    cp "$BINARY" "$INSTALL_DIR/spacetool"
    chmod 755 "$INSTALL_DIR/spacetool"

    print_success "Installed to: $INSTALL_DIR/spacetool"

    # Check PATH
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        echo ""
        print_warning "$INSTALL_DIR is not in your PATH"
        echo ""
        print_status "Add to your shell config (~/.zshrc or ~/.bashrc):"
        echo '  export PATH="$HOME/.local/bin:$PATH"'
        echo ""
        print_status "Then reload: source ~/.zshrc"
    else
        echo ""
        print_success "Installation complete! Try it:"
        echo "  spacetool --help"
        echo "  spacetool ~/Documents"
    fi
}

uninstall_binary() {
    INSTALL_PATH="$HOME/.local/bin/spacetool"

    if [ ! -f "$INSTALL_PATH" ]; then
        print_warning "SpaceTool is not installed at $INSTALL_PATH"
        exit 0
    fi

    print_warning "Uninstall SpaceTool?"
    read -p "Continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_status "Cancelled"
        exit 0
    fi

    rm -f "$INSTALL_PATH"
    print_success "SpaceTool uninstalled"
}

clean_artifacts() {
    print_status "Cleaning build artifacts..."
    rm -rf build/ dist/ *.spec __pycache__/
    rm -f *.html *.txt
    find . -name "*.pyc" -delete 2>/dev/null || true
    print_success "Cleaned"
}

# Main
case "${1:-help}" in
    build)
        build_binary
        ;;
    install)
        install_binary
        ;;
    uninstall)
        uninstall_binary
        ;;
    clean)
        clean_artifacts
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
