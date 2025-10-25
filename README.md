# SpaceTool - Disk Space Analyzer

Fast and accurate disk space analyzer with interactive HTML reports and duplicate file detection.

## Features

- 📊 Interactive HTML reports with charts
- 🔍 Duplicate file detection (MD5 hashing)
- 💾 Accurate disk usage (handles sparse files)
- 📈 Storage timeline visualization
- 📁 File type statistics
- 🚀 Multi-core processing
- 📝 Detailed text logs (prevents browser crashes on large scans)

## Quick Start

### Option 1: Use Binary (No Python Required)

```bash
# Build binary
./spacetool.sh build

# Run directly (no installation)
./dist/disk_analyzer_macos_arm64 ~/Documents

# Or install to system
./spacetool.sh install
spacetool ~/Documents
```

### Option 2: Run Python Script Directly

```bash
python3 disk_analyzer.py ~/Documents
```

## Usage

```bash
# Basic scan
spacetool ~/Documents

# Deep scan with custom output
spacetool ~/ -d 8 -o full_scan.html

# Fast scan (no duplicate detection)
spacetool ~/Downloads --no-hash -d 3

# Show help
spacetool --help

# Show full manual
spacetool --manual
```

## Output

Every scan creates **two files**:

1. **HTML Report** (`disk_report.html`)
   - Interactive charts and visualizations
   - Limited to top items for performance

2. **Text Log** (`disk_report_detailed.txt`)
   - Complete details of ALL findings
   - All duplicate groups with file paths
   - All folders and file types

## Commands

```bash
./spacetool.sh build       # Build standalone binary
./spacetool.sh install     # Install to ~/.local/bin
./spacetool.sh uninstall   # Remove from system
./spacetool.sh clean       # Clean build artifacts
./spacetool.sh help        # Show help
```

## Requirements

- **For Binary:** None (standalone executable)
- **For Python Script:** Python 3.6+

## Examples

```bash
# Analyze home directory
spacetool ~/ -d 5

# Find duplicates in Downloads
spacetool ~/Downloads -o downloads.html

# Quick scan without MD5 hashing
spacetool ~/Desktop --no-hash -d 3

# System audit (requires sudo)
sudo spacetool / -d 5
```

## Options

```
positional arguments:
  path                 Path to analyze (default: current directory)

options:
  -h, --help           Show help message
  -o, --output FILE    Output HTML file (default: disk_report.html)
  -d, --depth N        Maximum directory depth (default: 4)
  --no-hash            Skip MD5 verification (faster)
  --manual             Show comprehensive manual
```

## Installation

### Install Binary to System

```bash
./spacetool.sh build
./spacetool.sh install
```

Add to PATH (if needed):
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Uninstall

```bash
./spacetool.sh uninstall
```

## Files

```
spacetool/
├── disk_analyzer.py       # Source code
├── spacetool.sh          # Build & install script
├── dist/                 # Built binaries
├── requirements.txt      # Python dependencies (for building)
└── README.md            # This file
```

## Platform Support

- ✅ macOS (Apple Silicon & Intel)
- ✅ Linux x86_64
- ✅ Windows (with WSL or native Python)

## Tips

1. **Limit depth** for faster scans: `-d 3`
2. **Skip MD5** for speed: `--no-hash`
3. **Check text log** for complete duplicate list
4. **Target specific folders** instead of scanning everything

## Why Two Output Files?

With millions of files, HTML can grow to 300MB+ and crash browsers. The text log holds all the details while the HTML stays lightweight and usable.

## License

MIT License - See source code for details.
