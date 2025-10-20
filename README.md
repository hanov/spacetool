# Disk Space Analyzer

A fast, cross-platform tool to analyze disk usage and generate beautiful HTML reports with interactive charts.

## Features

- 📊 **Visual Reports** - Beautiful HTML reports with interactive Chart.js visualizations
- 🚀 **Fast** - Optimized O(n×d) algorithm for large directory trees
- 💾 **Accurate** - Handles sparse files correctly (like Docker images)
- 🔗 **Smart** - Skips symlinks to avoid circular references and double-counting
- 📈 **Timeline** - Shows when storage was consumed based on modification dates
- 🎯 **No Double-Counting** - Intelligently calculates actual space used

## Quick Start

### Using Python

```bash
python3 disk_analyzer.py /path/to/analyze -o report.html -d 5
```

### Using Binary

```bash
# Build the binary
./build.sh

# Run it
./dist/disk_analyzer_macos_arm64 /path/to/analyze -o report.html -d 5
```

## Usage

```
disk_analyzer.py [-h] [-o OUTPUT] [-d DEPTH] [--manual] [path]

Options:
  path                  Path to analyze (default: current directory)
  -o, --output OUTPUT   Output HTML file (default: disk_report.html)
  -d, --depth DEPTH     Maximum directory depth to scan (default: 4)
  --manual              Show comprehensive user manual
  -h, --help            Show brief help message
```

### Getting Help

```bash
# Quick help
disk_analyzer -h

# Comprehensive manual (recommended for first-time users)
disk_analyzer --manual

# Read offline manual
cat MANUAL.txt
```

### Examples

```bash
# Analyze home directory with depth 5
python3 disk_analyzer.py ~/ -d 5

# Analyze Desktop and save to custom location
python3 disk_analyzer.py ~/Desktop -o ~/Desktop/report.html

# Analyze current directory with default settings
python3 disk_analyzer.py
```

## Building Binaries

See [BUILD.md](BUILD.md) for detailed build instructions.

### Quick Build

```bash
# Build for current platform
./build.sh

# Clean build artifacts
./build.sh clean
```

The binary will be created in `dist/` directory and can be distributed as a standalone executable (no Python required).

## How It Works

1. **Scan** - Recursively scans directories up to specified depth
2. **Calculate** - Uses `st_blocks` to get actual disk usage (handles sparse files)
3. **Analyze** - Identifies leaf folders to avoid double-counting nested directories
4. **Visualize** - Generates interactive HTML report with:
   - Top 20 largest folders (bar chart)
   - Storage growth timeline (line chart)
   - Top 50 space consumers (detailed table)
   - Summary statistics

## Key Features Explained

### Accurate Disk Usage

The tool uses `st_blocks * 512` instead of file size to calculate actual disk space used. This correctly handles:
- Sparse files (like Docker VM images)
- Compressed files
- Files with holes

### No Double-Counting

The algorithm identifies "leaf" folders (folders without sub-folders in the dataset) to calculate totals:
- Scans all directories up to max depth
- Builds parent-child relationships
- Only counts folders that have no children in the dataset
- Result: accurate total without counting the same data multiple times

### Timeline Analysis

Shows when storage was consumed by:
- Grouping folders by modification month
- Using only leaf folders to avoid double-counting
- Creating an interactive timeline chart

## Report Example

The HTML report includes:

```
📊 Disk Space Analysis Report
═══════════════════════════════

Total Space Used: 83.40 GB
Largest Folder: 43.58 GB
Folders Scanned: 116,519
Average Folder Size: 1.11 MB

🏆 Top 20 Largest Folders (Interactive Bar Chart)
📈 Storage Growth Timeline (Interactive Line Chart)
📁 Top 50 Space Consumers (Detailed Table)
```

## Requirements

### For Python Script
- Python 3.7+
- **No external dependencies** - uses only Python standard library

```bash
# No installation needed! Just run:
python3 disk_analyzer.py ~/Documents
```

### For Building Binaries
- Python 3.7+
- PyInstaller 6.0+

```bash
# Install build dependencies
pip install -r requirements.txt

# Or let the build script handle it automatically
./build.sh
```

## Platform Support

- ✅ macOS (ARM64 / Intel)
- ✅ Linux (x86_64)
- ✅ Windows (x86_64)

## Performance

- Scans ~100,000 items/minute (typical SSD)
- Report generation: seconds for 100k+ folders
- Optimized for large directory trees (tested with 950k+ items)

## Common Use Cases

### Find Space Hogs
```bash
python3 disk_analyzer.py ~/ -d 8 -o ~/space_report.html
```
Open the report and look at the bar chart to see your largest folders.

### Clean Up Projects
```bash
python3 disk_analyzer.py ~/Projects -d 5
```
Identify `node_modules`, `venv`, `.terraform`, and other cache directories.

### Analyze Docker Usage
```bash
python3 disk_analyzer.py ~/Library/Containers/com.docker.docker -d 10
```
See actual disk space used by Docker (not virtual size).

### Monitor Growth
```bash
# Run monthly and compare timeline charts
python3 disk_analyzer.py ~/ -o report_$(date +%Y-%m).html
```

## Troubleshooting

### "Permission denied" errors
The tool skips directories it can't access. Run with sudo for complete scan:
```bash
sudo python3 disk_analyzer.py / -d 5
```

### Scan is slow
Reduce depth or analyze specific subdirectories:
```bash
python3 disk_analyzer.py ~/Documents -d 3
```

### Docker shows huge size
You're looking at the old report! The fixed version shows actual disk usage, not virtual size.

## License

MIT License - See LICENSE file for details

## Contributing

Issues and pull requests welcome!

## Credits

Built with:
- Python standard library
- Chart.js for visualizations
- PyInstaller for standalone binaries
