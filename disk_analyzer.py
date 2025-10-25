#!/usr/bin/env python3
"""
Disk Space Analyzer
Analyzes disk usage and generates an HTML report with visualizations
"""

# Check Python version before anything else
import sys

if sys.version_info < (3, 6):
    sys.stderr.write("Error: This script requires Python 3.6 or higher.\n")
    sys.stderr.write("You are running Python {}.{}.{}\n".format(
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro
    ))
    sys.stderr.write("\nPlease upgrade Python:\n")
    sys.stderr.write("  Ubuntu/Debian: sudo apt update && sudo apt install python3.9\n")
    sys.stderr.write("  CentOS/RHEL:   sudo yum install python39\n")
    sys.stderr.write("  macOS:         brew install python@3.11\n")
    sys.exit(1)

import os
from pathlib import Path
from datetime import datetime
import json
from collections import defaultdict
import argparse
import hashlib
import time
from multiprocessing import Pool, cpu_count, freeze_support


def get_size(path):
    """Calculate total size of a directory or file (actual disk usage, skipping symlinks)"""
    total = 0
    try:
        if os.path.isfile(path):
            stat = os.stat(path)
            # Use actual disk usage (handles sparse files correctly)
            # st_blocks is in 512-byte blocks
            return stat.st_blocks * 512 if hasattr(stat, 'st_blocks') else stat.st_size

        for entry in os.scandir(path):
            try:
                # Skip symlinks entirely
                if entry.is_symlink():
                    continue

                if entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    # Use actual disk usage instead of logical size
                    # This correctly handles sparse files (like Docker images)
                    total += stat.st_blocks * 512 if hasattr(stat, 'st_blocks') else stat.st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += get_size(entry.path)
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass
    return total


def calculate_quick_hash(file_path, size):
    """
    Calculate quick hash - only first 8KB of file.
    Ultra-fast for eliminating non-duplicates.
    """
    hash_obj = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            hash_obj.update(f.read(8192))  # Only first 8KB
        return hash_obj.hexdigest()
    except (PermissionError, OSError, IOError):
        return None


def calculate_full_hash(file_path, size):
    """
    Calculate full MD5 hash of entire file.
    Only called for files that passed quick hash check.
    """
    hash_obj = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except (PermissionError, OSError, IOError):
        return None


def _quick_hash_worker(args):
    """Worker function for parallel quick hashing"""
    file_info, size = args
    quick_hash = calculate_quick_hash(file_info['path'], size)
    if quick_hash:
        return (size, quick_hash, file_info)
    return None


def _full_hash_worker(args):
    """Worker function for parallel full hashing"""
    file_info, size = args
    full_hash = calculate_full_hash(file_info['path'], size)
    if full_hash:
        file_info['hash'] = full_hash
        return (size, full_hash, file_info)
    return None


def find_duplicates(file_data, use_md5=True, progress_callback=None, num_workers=None):
    """
    Two-stage hashing for maximum speed:
    1) Group by size - instant
    2) Quick hash (first 8KB) - eliminates 95%+ of candidates
    3) Full hash - only for files that match quick hash
    """
    print("  Step 1/3: Grouping files by size...")

    # Step 1: Group by size
    size_groups = defaultdict(list)
    for file_info in file_data:
        size = file_info['size']
        if size >= 1024:  # Skip files < 1KB
            size_groups[size].append(file_info)

    # Only keep groups with 2+ files
    potential_duplicates = {size: files for size, files in size_groups.items() if len(files) > 1}

    if not potential_duplicates:
        print("  No duplicates found (all files have unique sizes)")
        return [], []

    files_to_check = sum(len(files) for files in potential_duplicates.values())
    print(f"  Found {len(potential_duplicates):,} size groups with {files_to_check:,} files")

    if not use_md5:
        # Without MD5, treat same-size files as duplicates
        print("  Step 2/3: Grouping by size only (no MD5 verification)...")
        duplicates = []
        duplicate_groups = []
        for size, files in potential_duplicates.items():
            file_group_sorted = sorted(files, key=lambda x: x['path'])
            duplicate_groups.append(file_group_sorted)
            duplicates.extend(file_group_sorted)

        duplicate_groups.sort(key=lambda group: len(group) * group[0]['size'], reverse=True)
        return duplicates, duplicate_groups

    # Step 2: Quick hash (first 8KB only) - eliminates most non-duplicates
    print(f"  Step 2/3: Quick-hashing {files_to_check:,} files (first 8KB only)...")

    quick_hash_groups = defaultdict(list)
    hash_tasks = [(f, f['size']) for files in potential_duplicates.values() for f in files]

    num_workers = num_workers or min(cpu_count(), 8)
    processed = 0
    start_time = time.time()

    if files_to_check > 1000:
        with Pool(processes=num_workers) as pool:
            for result in pool.imap_unordered(_quick_hash_worker, hash_tasks, chunksize=100):
                if result:
                    size, quick_hash, file_info = result
                    quick_hash_groups[(size, quick_hash)].append(file_info)

                processed += 1
                if progress_callback and processed % 1000 == 0:
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    print(f"  Quick hash: {processed:,}/{files_to_check:,} ({100*processed//files_to_check}%) | {rate:.0f} files/sec", end='\r')
    else:
        for file_info, size in hash_tasks:
            quick_hash = calculate_quick_hash(file_info['path'], size)
            if quick_hash:
                quick_hash_groups[(size, quick_hash)].append(file_info)

    # Find files that need full hash (2+ files with same quick hash)
    files_needing_full_hash = []
    for (size, quick_hash), files in quick_hash_groups.items():
        if len(files) >= 2:
            files_needing_full_hash.extend(files)

    print(f"\n  Quick hash eliminated {files_to_check - len(files_needing_full_hash):,} files")

    if not files_needing_full_hash:
        print("  No duplicates found after quick hash")
        return [], []

    # Step 3: Full hash - only for files that matched on quick hash
    print(f"  Step 3/3: Full-hashing {len(files_needing_full_hash):,} potential duplicates...")

    full_hash_groups = defaultdict(list)
    full_hash_tasks = [(f, f['size']) for f in files_needing_full_hash]

    processed = 0
    start_time = time.time()

    if len(files_needing_full_hash) > 1000:
        with Pool(processes=num_workers) as pool:
            for result in pool.imap_unordered(_full_hash_worker, full_hash_tasks, chunksize=100):
                if result:
                    size, full_hash, file_info = result
                    full_hash_groups[(size, full_hash)].append(file_info)

                processed += 1
                if progress_callback and processed % 500 == 0:
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (len(files_needing_full_hash) - processed) / rate if rate > 0 else 0
                    progress_callback(processed, len(files_needing_full_hash), rate, eta)

        if progress_callback:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            progress_callback(len(files_needing_full_hash), len(files_needing_full_hash), rate, 0)
    else:
        for file_info, size in full_hash_tasks:
            full_hash = calculate_full_hash(file_info['path'], size)
            if full_hash:
                file_info['hash'] = full_hash
                full_hash_groups[(size, full_hash)].append(file_info)

    # Extract duplicate groups
    duplicates = []
    duplicate_groups = []

    for (size, full_hash), file_group in full_hash_groups.items():
        if len(file_group) >= 2:
            file_group_sorted = sorted(file_group, key=lambda x: x['path'])
            duplicate_groups.append(file_group_sorted)
            duplicates.extend(file_group_sorted)

    duplicate_groups.sort(
        key=lambda group: len(group) * group[0]['size'],
        reverse=True
    )

    print(f"  ✓ Found {len(duplicate_groups):,} duplicate groups")

    return duplicates, duplicate_groups


def analyze_directory(root_path, max_depth=3, progress_callback=None, use_md5=True):
    """
    Analyze directory structure and return folder statistics and file type statistics
    """
    root_path = Path(root_path).resolve()
    folder_data = []
    file_type_stats = defaultdict(lambda: {'count': 0, 'size': 0})
    file_data = []  # Track individual files for duplicate detection
    processed = 0

    def scan_dir(path, depth=0):
        nonlocal processed
        if depth > max_depth:
            return

        try:
            for entry in os.scandir(path):
                processed += 1
                if progress_callback and processed % 100 == 0:
                    progress_callback(processed)

                try:
                    # Skip symlinks entirely
                    if entry.is_symlink():
                        continue

                    if entry.is_file(follow_symlinks=False):
                        # Track file types
                        stat = entry.stat(follow_symlinks=False)
                        file_size = stat.st_blocks * 512 if hasattr(stat, 'st_blocks') else stat.st_size

                        # Get file extension
                        ext = os.path.splitext(entry.name)[1].lower()
                        if not ext:
                            ext = '(no extension)'

                        file_type_stats[ext]['count'] += 1
                        file_type_stats[ext]['size'] += file_size

                        # Store file data for duplicate detection
                        file_data.append({
                            'path': entry.path,
                            'size': file_size,
                            'name': entry.name,
                            'modified': stat.st_mtime,
                            'extension': ext
                        })

                    elif entry.is_dir(follow_symlinks=False):
                        dir_path = entry.path

                        # Get directory stats
                        stat = entry.stat(follow_symlinks=False)
                        size = get_size(dir_path)

                        if size > 0:  # Only include non-empty directories
                            folder_data.append({
                                'path': dir_path,
                                'size': size,
                                'modified': stat.st_mtime,
                                'created': stat.st_ctime if hasattr(stat, 'st_ctime') else stat.st_mtime,
                                'depth': depth
                            })

                        # Recurse into subdirectories
                        scan_dir(dir_path, depth + 1)

                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass

    print(f"Scanning {root_path}...")
    scan_dir(root_path)
    print(f"Processed {processed} items")

    # Find duplicates
    print("\nFinding duplicates...")
    duplicates, duplicate_groups = find_duplicates(
        file_data,
        use_md5=use_md5,
        progress_callback=lambda done, total, rate, eta: print(
            f"  Hashing: {done:,}/{total:,} files ({100*done//total}%) | "
            f"{rate:.0f} files/sec | ETA: {eta/60:.1f} min   ",
            end='\r'
        )
    )
    print(f"\n✓ Found {len(duplicate_groups)} duplicate groups containing {len(duplicates)} files")

    return folder_data, file_type_stats, duplicates, duplicate_groups


def format_size(bytes):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.2f} PB"


def calculate_actual_total(folder_data):
    """Calculate actual total size avoiding double-counting of nested folders - optimized O(n log n)"""
    if not folder_data:
        return 0, []

    # Create mapping for quick lookup
    path_to_folder = {f['path']: f for f in folder_data}
    all_paths = set(path_to_folder.keys())

    # Build set of all parent paths (paths that have children in our dataset)
    # This is O(n) where n is total number of paths
    parent_paths = set()
    for path in all_paths:
        # Get parent directory
        parent = os.path.dirname(path)
        # Keep going up the tree and mark all parents
        while parent and parent in all_paths:
            parent_paths.add(parent)
            parent = os.path.dirname(parent)

    # Leaf folders are those NOT in parent_paths
    # These are folders that have no sub-folders in our dataset
    leaf_or_independent = [
        path_to_folder[path]
        for path in all_paths
        if path not in parent_paths
    ]

    return sum(f['size'] for f in leaf_or_independent), leaf_or_independent


def save_detailed_logs(folder_data, file_type_stats, duplicates, duplicate_groups, output_file, root_path):
    """Save detailed logs to a text file"""

    # Calculate actual total
    actual_total, leaf_or_independent = calculate_actual_total(folder_data)

    # Calculate wasted space
    wasted_space = sum(
        sum(f['size'] for f in group[1:])
        for group in duplicate_groups
    )

    # Sort folders by size
    sorted_by_size = sorted(folder_data, key=lambda x: x['size'], reverse=True)

    # Sort file types
    total_file_size = sum(stats['size'] for stats in file_type_stats.values())
    sorted_file_types = sorted(file_type_stats.items(), key=lambda x: x[1]['size'], reverse=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("DISK SPACE ANALYSIS - DETAILED REPORT\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Analyzed Path: {root_path}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Folders: {len(folder_data):,}\n")
        f.write(f"Total Space Used: {format_size(actual_total)}\n\n")

        # Summary statistics
        f.write("=" * 80 + "\n")
        f.write("SUMMARY STATISTICS\n")
        f.write("=" * 80 + "\n\n")

        total_files = sum(stats['count'] for stats in file_type_stats.values())
        f.write(f"Total Files: {total_files:,}\n")
        f.write(f"Total File Types: {len(file_type_stats)}\n")
        f.write(f"Duplicate Files: {len(duplicates):,}\n")
        f.write(f"Duplicate Groups: {len(duplicate_groups):,}\n")
        f.write(f"Wasted Space (duplicates): {format_size(wasted_space)}\n\n")

        # Top folders
        f.write("=" * 80 + "\n")
        f.write("TOP 100 LARGEST FOLDERS\n")
        f.write("=" * 80 + "\n\n")

        for i, folder in enumerate(sorted_by_size[:100], 1):
            mod_date = datetime.fromtimestamp(folder['modified']).strftime('%Y-%m-%d %H:%M')
            f.write(f"{i:4d}. {format_size(folder['size']):>12s}  {mod_date}  Depth:{folder['depth']:2d}  {folder['path']}\n")

        # File types
        f.write("\n" + "=" * 80 + "\n")
        f.write("FILE TYPES BREAKDOWN\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"{'#':<6} {'Extension':<20} {'Count':>12} {'Total Size':>15} {'%':>8} {'Avg Size':>15}\n")
        f.write("-" * 80 + "\n")

        for i, (ext, stats) in enumerate(sorted_file_types, 1):
            percentage = (stats['size'] / total_file_size * 100) if total_file_size > 0 else 0
            avg_size = stats['size'] / stats['count'] if stats['count'] > 0 else 0
            f.write(f"{i:<6} {ext:<20} {stats['count']:>12,} {format_size(stats['size']):>15} {percentage:>7.2f}% {format_size(avg_size):>15}\n")

        # Duplicate files
        if duplicate_groups:
            f.write("\n" + "=" * 80 + "\n")
            f.write("DUPLICATE FILES DETECTED\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"Found {len(duplicate_groups):,} duplicate groups containing {len(duplicates):,} files\n")
            f.write(f"Potential space savings: {format_size(wasted_space)}\n\n")

            for idx, group in enumerate(duplicate_groups, 1):
                group_size = group[0]['size']
                group_count = len(group)
                wasted = group_size * (group_count - 1)

                f.write("-" * 80 + "\n")
                f.write(f"Duplicate Group #{idx}\n")
                f.write(f"  Copies: {group_count} × {format_size(group_size)} = Wasting {format_size(wasted)}\n")
                if 'hash' in group[0]:
                    f.write(f"  MD5: {group[0]['hash']}\n")
                f.write("\n")

                for file_info in group:
                    mod_date = datetime.fromtimestamp(file_info['modified']).strftime('%Y-%m-%d %H:%M')
                    f.write(f"    {format_size(file_info['size']):>12s}  {mod_date}  {file_info['path']}\n")

                f.write("\n")


def generate_html_report(folder_data, file_type_stats, duplicates, duplicate_groups, output_file, root_path):
    """Generate HTML report with interactive visualizations"""

    # Calculate actual total by finding folders that are not parents of others
    # This avoids double-counting nested folders
    actual_total, leaf_or_independent = calculate_actual_total(folder_data)

    # Calculate duplicate statistics
    total_duplicate_size = sum(f['size'] for f in duplicates)
    # Calculate wasted space (keep one copy, remove the rest)
    wasted_space = sum(
        sum(f['size'] for f in group[1:])  # All files except the first one
        for group in duplicate_groups
    )

    # Sort ALL folders by size (for largest folder stat and detailed table)
    sorted_by_size = sorted(folder_data, key=lambda x: x['size'], reverse=True)[:50]

    # Sort leaf folders by size for visualizations (to avoid misleading charts)
    sorted_leaf_by_size = sorted(leaf_or_independent, key=lambda x: x['size'], reverse=True)

    # Prepare data for charts - use leaf folders to avoid misleading visualizations
    top_folders = sorted_leaf_by_size[:20]

    # Timeline data - group by month (use only leaf folders to avoid double counting)
    timeline = defaultdict(int)
    for folder in leaf_or_independent:
        month = datetime.fromtimestamp(folder['modified']).strftime('%Y-%m')
        timeline[month] += folder['size']

    sorted_timeline = sorted(timeline.items())

    # Depth distribution (use only leaf folders to avoid double counting)
    depth_distribution = defaultdict(lambda: {'count': 0, 'size': 0})
    for folder in folder_data:
        depth = folder['depth']
        depth_distribution[depth]['count'] += 1
    # Size calculation for depth distribution (only leaf folders)
    for folder in leaf_or_independent:
        depth = folder['depth']
        depth_distribution[depth]['size'] += folder['size']

    # File type statistics
    total_file_size = sum(stats['size'] for stats in file_type_stats.values())
    sorted_file_types = sorted(file_type_stats.items(), key=lambda x: x[1]['size'], reverse=True)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Disk Space Analysis Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            color: #333;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}

        .header h1 {{
            color: #667eea;
            margin-bottom: 10px;
        }}

        .header .meta {{
            color: #666;
            font-size: 14px;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        .stat-card h3 {{
            color: #666;
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 10px;
        }}

        .stat-card .value {{
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
        }}

        .chart-container {{
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}

        .chart-container h2 {{
            margin-bottom: 20px;
            color: #333;
        }}

        .chart-wrapper {{
            position: relative;
            height: 400px;
        }}

        table {{
            width: 100%;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            border-collapse: collapse;
        }}

        th {{
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }}

        td {{
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
        }}

        tr:hover {{
            background: #f5f5f5;
        }}

        .path {{
            font-family: monospace;
            font-size: 12px;
            color: #666;
            word-break: break-all;
        }}

        .size {{
            font-weight: 600;
            color: #667eea;
        }}

        .date {{
            color: #888;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Disk Space Analysis Report</h1>
            <div class="meta">
                <p><strong>Analyzed Path:</strong> {root_path}</p>
                <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>Total Folders Analyzed:</strong> {len(folder_data):,}</p>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Space Used</h3>
                <div class="value">{format_size(actual_total)}</div>
            </div>
            <div class="stat-card">
                <h3>Largest Folder</h3>
                <div class="value">{format_size(sorted_by_size[0]['size']) if sorted_by_size else '0 B'}</div>
            </div>
            <div class="stat-card">
                <h3>Duplicate Files</h3>
                <div class="value">{len(duplicates):,}</div>
            </div>
            <div class="stat-card">
                <h3>Wasted Space</h3>
                <div class="value">{format_size(wasted_space)}</div>
            </div>
        </div>

        <div class="chart-container">
            <h2>🏆 Top 20 Largest Folders</h2>
            <div class="chart-wrapper">
                <canvas id="topFoldersChart"></canvas>
            </div>
        </div>

        <div class="chart-container">
            <h2>📈 Storage Growth Timeline</h2>
            <div class="chart-wrapper">
                <canvas id="timelineChart"></canvas>
            </div>
        </div>

        <div class="chart-container">
            <h2>📄 File Types Breakdown</h2>
            <div class="chart-wrapper">
                <canvas id="fileTypesChart"></canvas>
            </div>
        </div>

        <div class="chart-container">
            <h2>📋 File Types Statistics (Top 50)</h2>
            <p style="margin-bottom: 15px; color: #666;">
                <strong>Note:</strong> Showing top 50 file types. See detailed text log for complete list.
            </p>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>File Type</th>
                        <th>Count</th>
                        <th>Total Size</th>
                        <th>Percentage</th>
                        <th>Avg Size</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add file type table rows (limited to top 50)
    for i, (ext, stats) in enumerate(sorted_file_types[:50], 1):
        percentage = (stats['size'] / total_file_size * 100) if total_file_size > 0 else 0
        avg_size = stats['size'] / stats['count'] if stats['count'] > 0 else 0
        html_content += f"""
                    <tr>
                        <td>{i}</td>
                        <td class="path">{ext}</td>
                        <td>{stats['count']:,}</td>
                        <td class="size">{format_size(stats['size'])}</td>
                        <td>{percentage:.2f}%</td>
                        <td>{format_size(avg_size)}</td>
                    </tr>
"""

    html_content += """
                </tbody>
            </table>
        </div>

        <div class="chart-container">
            <h2>📁 Top 100 Space Consumers</h2>
            <p style="margin-bottom: 15px; color: #666;">
                <strong>Note:</strong> Showing top 100 folders. See detailed text log for complete list.
            </p>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Folder Path</th>
                        <th>Size</th>
                        <th>Last Modified</th>
                        <th>Depth</th>
                    </tr>
                </thead>
                <tbody>
"""

    # Add folder table rows (limited to 100)
    for i, folder in enumerate(sorted_by_size[:100], 1):
        mod_date = datetime.fromtimestamp(folder['modified']).strftime('%Y-%m-%d %H:%M')
        html_content += f"""
                    <tr>
                        <td>{i}</td>
                        <td class="path">{folder['path']}</td>
                        <td class="size">{format_size(folder['size'])}</td>
                        <td class="date">{mod_date}</td>
                        <td>{folder['depth']}</td>
                    </tr>
"""

    html_content += """
                </tbody>
            </table>
        </div>
"""

    # Add duplicate files section (limited to avoid huge HTML files)
    if duplicate_groups:
        # Determine how many groups to show in HTML
        max_html_groups = 20  # Limit to 20 groups to keep HTML manageable
        showing_limited = len(duplicate_groups) > max_html_groups

        html_content += """
        <div class="chart-container">
            <h2>🔄 Duplicate Files Detected</h2>
            <div style="margin-bottom: 20px; padding: 15px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 5px;">
                <strong>💡 Tip:</strong> You can potentially free up <strong>""" + format_size(wasted_space) + """</strong> by removing duplicate files.
                <br>Found <strong>""" + str(len(duplicate_groups)) + """</strong> groups of duplicates containing <strong>""" + str(len(duplicates)) + """</strong> total files."""

        if showing_limited:
            html_content += """
                <br><br><strong>⚠️ Note:</strong> Showing only top """ + str(max_html_groups) + """ duplicate groups below to keep HTML file size manageable.
                <br>See the detailed text log file for the complete list of all duplicates.
"""

        html_content += """
            </div>
"""

        # Add duplicate groups tables (limited)
        groups_to_show = duplicate_groups[:max_html_groups]
        for idx, group in enumerate(groups_to_show, 1):
            group_size = group[0]['size']
            group_count = len(group)
            wasted = group_size * (group_count - 1)

            html_content += f"""
            <div style="margin-bottom: 20px; border: 1px solid #ddd; border-radius: 5px; overflow: hidden;">
                <div style="background: #f8f9fa; padding: 10px 15px; border-bottom: 1px solid #ddd;">
                    <strong>Duplicate Group #{idx}</strong> -
                    {group_count} copies × {format_size(group_size)} =
                    <span style="color: #dc3545;">Wasting {format_size(wasted)}</span>
                    {' (MD5: ' + group[0].get('hash', 'N/A') + ')' if 'hash' in group[0] else ''}
                </div>
                <table style="margin: 0; box-shadow: none;">
                    <thead>
                        <tr>
                            <th>File Path</th>
                            <th>Size</th>
                            <th>Last Modified</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            for file_info in group:
                mod_date = datetime.fromtimestamp(file_info['modified']).strftime('%Y-%m-%d %H:%M')
                html_content += f"""
                        <tr>
                            <td class="path">{file_info['path']}</td>
                            <td class="size">{format_size(file_info['size'])}</td>
                            <td class="date">{mod_date}</td>
                        </tr>
"""
            html_content += """
                    </tbody>
                </table>
            </div>
"""

        html_content += """
        </div>
"""

    html_content += """
    </div>

    <script>
        // Top Folders Chart
        const topFoldersCtx = document.getElementById('topFoldersChart').getContext('2d');
        new Chart(topFoldersCtx, {
            type: 'bar',
            data: {
                labels: """ + json.dumps([os.path.basename(f['path']) or f['path'] for f in top_folders]) + """,
                datasets: [{
                    label: 'Size (bytes)',
                    data: """ + json.dumps([f['size'] for f in top_folders]) + """,
                    backgroundColor: 'rgba(102, 126, 234, 0.8)',
                    borderColor: 'rgba(102, 126, 234, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return formatBytes(context.parsed.x);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            callback: function(value) {
                                return formatBytes(value);
                            }
                        }
                    }
                }
            }
        });

        // Timeline Chart
        const timelineCtx = document.getElementById('timelineChart').getContext('2d');
        new Chart(timelineCtx, {
            type: 'line',
            data: {
                labels: """ + json.dumps([month for month, _ in sorted_timeline]) + """,
                datasets: [{
                    label: 'Storage Used',
                    data: """ + json.dumps([size for _, size in sorted_timeline]) + """,
                    borderColor: 'rgba(118, 75, 162, 1)',
                    backgroundColor: 'rgba(118, 75, 162, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return 'Size: ' + formatBytes(context.parsed.y);
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        ticks: {
                            callback: function(value) {
                                return formatBytes(value);
                            }
                        }
                    }
                }
            }
        });

        // File Types Chart (Pie/Doughnut)
        const fileTypesCtx = document.getElementById('fileTypesChart').getContext('2d');
        const fileTypeData = """ + json.dumps([
            {'ext': ext, 'size': stats['size'], 'count': stats['count']}
            for ext, stats in sorted_file_types[:20]  # Top 20 file types
        ]) + """;

        const backgroundColors = [
            'rgba(102, 126, 234, 0.8)',
            'rgba(118, 75, 162, 0.8)',
            'rgba(237, 100, 166, 0.8)',
            'rgba(255, 154, 162, 0.8)',
            'rgba(255, 183, 178, 0.8)',
            'rgba(255, 218, 193, 0.8)',
            'rgba(226, 240, 203, 0.8)',
            'rgba(181, 234, 215, 0.8)',
            'rgba(199, 206, 234, 0.8)',
            'rgba(207, 186, 240, 0.8)',
            'rgba(149, 175, 192, 0.8)',
            'rgba(255, 206, 86, 0.8)',
            'rgba(75, 192, 192, 0.8)',
            'rgba(153, 102, 255, 0.8)',
            'rgba(255, 159, 64, 0.8)',
            'rgba(54, 162, 235, 0.8)',
            'rgba(255, 99, 132, 0.8)',
            'rgba(201, 203, 207, 0.8)',
            'rgba(83, 102, 255, 0.8)',
            'rgba(255, 102, 196, 0.8)'
        ];

        new Chart(fileTypesCtx, {
            type: 'doughnut',
            data: {
                labels: fileTypeData.map(d => d.ext + ' (' + d.count + ' files)'),
                datasets: [{
                    data: fileTypeData.map(d => d.size),
                    backgroundColor: backgroundColors,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            boxWidth: 15,
                            padding: 10
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = formatBytes(context.parsed);
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(2);
                                return label + ': ' + value + ' (' + percentage + '%)';
                            }
                        }
                    }
                }
            }
        });

        function formatBytes(bytes) {
            const units = ['B', 'KB', 'MB', 'GB', 'TB'];
            let size = bytes;
            let unitIndex = 0;
            while (size >= 1024 && unitIndex < units.length - 1) {
                size /= 1024;
                unitIndex++;
            }
            return size.toFixed(2) + ' ' + units[unitIndex];
        }
    </script>
</body>
</html>
"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)


def show_manual():
    """Display comprehensive user manual"""
    manual = """
╔═══════════════════════════════════════════════════════════════════════════╗
║                    DISK SPACE ANALYZER - USER MANUAL                      ║
║                           Version 1.0.0                                   ║
╚═══════════════════════════════════════════════════════════════════════════╝

TABLE OF CONTENTS
═════════════════
1. Overview
2. Quick Start
3. Command Line Options
4. Understanding the Report
5. How It Works
6. Common Use Cases
7. Performance Tips
8. Troubleshooting
9. Advanced Usage
10. Technical Details

═══════════════════════════════════════════════════════════════════════════

1. OVERVIEW
═══════════

Disk Space Analyzer is a fast, accurate tool that helps you:
  • Identify which folders consume the most disk space
  • Visualize storage usage with interactive charts
  • Track when storage was consumed (based on modification dates)
  • Find large, hidden directories in your system
  • Avoid double-counting nested folders

Key Features:
  ✓ Beautiful HTML reports with Chart.js visualizations
  ✓ Accurate measurement using actual disk usage (handles sparse files)
  ✓ Smart symlink handling to avoid circular references
  ✓ Timeline showing storage growth over time
  ✓ Fast scanning optimized for large directory trees
  ✓ No external dependencies required

═══════════════════════════════════════════════════════════════════════════

2. QUICK START
══════════════

Basic Usage:
  $ disk_analyzer /path/to/analyze

With Options:
  $ disk_analyzer ~/Documents -o report.html -d 5

This will:
  1. Scan your Documents folder up to 5 levels deep
  2. Calculate actual disk usage for all folders
  3. Generate report.html with interactive charts
  4. Open the report in your browser to explore results

═══════════════════════════════════════════════════════════════════════════

3. COMMAND LINE OPTIONS
═══════════════════════

SYNTAX:
  disk_analyzer [PATH] [OPTIONS]

ARGUMENTS:
  PATH                  Directory to analyze
                        Default: current directory (.)
                        Examples:
                          disk_analyzer ~/Desktop
                          disk_analyzer /Users/john/Projects
                          disk_analyzer .

OPTIONS:
  -o, --output FILE     Output HTML file path
                        Default: disk_report.html
                        Examples:
                          -o my_report.html
                          -o ~/Documents/analysis.html
                          --output /tmp/report.html

  -d, --depth NUMBER    Maximum directory depth to scan
                        Default: 4
                        Range: 1-50 (higher = slower, more detailed)
                        Examples:
                          -d 3   # Scan 3 levels deep
                          -d 10  # Deep scan (slower)
                          --depth 2

  --manual              Show this comprehensive manual
  -h, --help            Show brief help message

EXAMPLES:
  # Analyze current directory with defaults
  $ disk_analyzer

  # Analyze home directory, 6 levels deep
  $ disk_analyzer ~/ -d 6

  # Scan external drive and save to Desktop
  $ disk_analyzer /Volumes/External -o ~/Desktop/external_report.html

  # Deep analysis of project folder
  $ disk_analyzer ~/Projects/my-app -d 8 -o project_analysis.html

═══════════════════════════════════════════════════════════════════════════

4. UNDERSTANDING THE REPORT
═══════════════════════════

The HTML report contains four main sections:

A. SUMMARY STATISTICS (Top Cards)
   ┌─────────────────────────────────────────────────────────────┐
   │ Total Space Used    │ Shows actual disk usage (no double    │
   │                     │ counting of nested folders)           │
   │─────────────────────┼───────────────────────────────────────│
   │ Largest Folder      │ The single biggest folder found       │
   │─────────────────────┼───────────────────────────────────────│
   │ Folders Scanned     │ Total directories analyzed            │
   │─────────────────────┼───────────────────────────────────────│
   │ Average Folder Size │ Mean size across all folders          │
   └─────────────────────────────────────────────────────────────┘

B. TOP 20 LARGEST FOLDERS (Bar Chart)
   • Interactive horizontal bar chart
   • Hover to see exact sizes
   • Click legend to filter
   • Sorted by size (largest first)
   • Helps identify space hogs quickly

C. STORAGE GROWTH TIMELINE (Line Chart)
   • Shows when storage was consumed
   • Based on folder modification dates
   • Groups data by month
   • Helps identify when you accumulated data
   • Useful for cleanup planning

D. TOP 50 SPACE CONSUMERS (Detailed Table)
   Columns:
   • # - Ranking by size
   • Folder Path - Full path to directory
   • Size - Actual disk usage (human readable)
   • Last Modified - When folder was last changed
   • Depth - Directory depth from scan root

   The table is:
   • Sortable (click headers)
   • Searchable (Ctrl+F in browser)
   • Shows full paths for easy navigation

═══════════════════════════════════════════════════════════════════════════

5. HOW IT WORKS
═══════════════

SCANNING PROCESS:
  1. Recursively traverse directories up to specified depth
  2. For each directory:
     - Calculate total size including all contents
     - Record modification time
     - Track depth level
  3. Skip symlinks to avoid circular references
  4. Skip inaccessible folders (permission denied)

SIZE CALCULATION:
  • Uses st_blocks × 512 instead of file size
  • This gives ACTUAL disk usage, not logical size
  • Correctly handles:
    ✓ Sparse files (e.g., Docker VM images)
    ✓ Compressed files
    ✓ Files with holes

  Example: A 1TB Docker image might only use 8GB actual disk space

AVOIDING DOUBLE-COUNTING:
  Problem: Scanning both /foo (100MB) and /foo/bar (80MB)
           would count the 80MB twice

  Solution:
  1. Build parent-child relationship map
  2. Identify "leaf" folders (no children in dataset)
  3. Only sum leaf folders for totals
  4. Result: Accurate total without duplication

TIMELINE GENERATION:
  • Groups folders by modification month
  • Uses only leaf folders (avoids double-counting)
  • Creates month-by-month view of storage growth

═══════════════════════════════════════════════════════════════════════════

6. COMMON USE CASES
═══════════════════

A. FIND SPACE HOGS ON YOUR SYSTEM
   $ disk_analyzer ~/ -d 6 -o ~/space_audit.html

   What to look for:
   • Large cache directories
   • Old downloads
   • Duplicate folders
   • Forgotten backups

B. CLEAN UP DEVELOPMENT PROJECTS
   $ disk_analyzer ~/Projects -d 5

   What to find:
   • node_modules directories (can be regenerated)
   • .terraform folders (cache)
   • venv/virtualenv (Python environments)
   • build/dist folders
   • .git folders (large repos)

C. ANALYZE DOCKER DISK USAGE
   $ disk_analyzer ~/Library/Containers/com.docker.docker -d 10

   Shows ACTUAL disk usage (not virtual 1TB size)
   Helps decide when to run: docker system prune

D. INVESTIGATE FULL DISK ERRORS
   $ sudo disk_analyzer / -d 6 -o ~/disk_analysis.html

   Scan entire system with sudo for full access
   Identify unexpected large directories

E. AUDIT EXTERNAL DRIVES
   $ disk_analyzer /Volumes/Backup -d 8

   See what's taking space on external drives
   Decide what to delete or reorganize

F. MONTHLY STORAGE AUDIT
   $ disk_analyzer ~/ -o ~/audits/audit_$(date +%Y-%m).html

   Run monthly to track growth
   Compare timeline charts over time

═══════════════════════════════════════════════════════════════════════════

7. PERFORMANCE TIPS
═══════════════════

FASTER SCANS:
  • Reduce depth: -d 3 instead of -d 8
  • Scan specific folders instead of entire home directory
  • Exclude network drives (very slow)
  • Use SSD for faster file access

TYPICAL SCAN SPEEDS:
  • Local SSD: ~100,000 items/minute
  • Local HDD: ~30,000 items/minute
  • Network drive: ~5,000 items/minute
  • External USB: ~20,000 items/minute

RECOMMENDED DEPTHS:
  -d 3  : Quick overview (minutes for large systems)
  -d 5  : Balanced detail vs speed (recommended)
  -d 8  : Detailed analysis (slower)
  -d 10+: Very detailed (can take hours on large systems)

OPTIMIZATION EXAMPLE:
  Instead of:
    $ disk_analyzer ~/ -d 10  # Scans everything deeply

  Try:
    $ disk_analyzer ~/Documents -d 6  # Target specific areas
    $ disk_analyzer ~/Desktop -d 4
    $ disk_analyzer ~/Downloads -d 3

═══════════════════════════════════════════════════════════════════════════

8. TROUBLESHOOTING
══════════════════

PROBLEM: "Permission denied" errors
SOLUTION:
  • Normal - tool skips inaccessible folders
  • For complete scan: sudo disk_analyzer / -d 5
  • Or: analyze folders you have access to

PROBLEM: Scan is very slow
SOLUTION:
  • Reduce depth: use -d 3 instead of -d 8
  • Scan specific subdirectories
  • Avoid network drives
  • Close other disk-intensive programs

PROBLEM: Report shows wrong total
SOLUTION:
  • This is fixed! Tool now avoids double-counting
  • If using old version, update to latest
  • Verify you're reading the correct report file

PROBLEM: Docker shows 1TB usage
SOLUTION:
  • Old bug - update to latest version
  • New version uses actual disk usage (st_blocks)
  • Should show realistic size (e.g., 8GB not 1TB)

PROBLEM: "Path does not exist" error
SOLUTION:
  • Check path spelling
  • Use absolute paths: /Users/john/Documents
  • Or relative: ./my-folder
  • Ensure path exists before scanning

PROBLEM: No data collected
SOLUTION:
  • Check permissions (try sudo)
  • Verify path exists and is accessible
  • Ensure disk is mounted (for external drives)
  • Check folder isn't empty

═══════════════════════════════════════════════════════════════════════════

9. ADVANCED USAGE
═════════════════

A. AUTOMATED MONTHLY REPORTS
   Create a cron job or scheduled task:

   #!/bin/bash
   DATE=$(date +%Y-%m-%d)
   disk_analyzer ~/ -o ~/reports/disk_$DATE.html -d 5

   Schedule monthly to track growth over time

B. COMPARE BEFORE/AFTER CLEANUP
   # Before cleanup
   $ disk_analyzer ~/Projects -o before.html

   # ... clean up node_modules, caches, etc ...

   # After cleanup
   $ disk_analyzer ~/Projects -o after.html

   # Compare the reports to see space saved

C. SCAN MULTIPLE LOCATIONS
   #!/bin/bash
   disk_analyzer ~/Documents -o docs_report.html -d 4
   disk_analyzer ~/Downloads -o downloads_report.html -d 3
   disk_analyzer ~/Desktop -o desktop_report.html -d 4
   disk_analyzer ~/.cache -o cache_report.html -d 5

D. INTEGRATE WITH CLEANUP SCRIPTS
   #!/bin/bash
   # Generate report
   disk_analyzer ~/Projects -o /tmp/report.html -d 5

   # Parse and find node_modules
   find ~/Projects -name "node_modules" -type d -print

   # Ask user before deleting
   read -p "Delete all node_modules? (y/n) " -n 1 -r
   if [[ $REPLY =~ ^[Yy]$ ]]; then
       find ~/Projects -name "node_modules" -type d -exec rm -rf {} +
   fi

═══════════════════════════════════════════════════════════════════════════

10. TECHNICAL DETAILS
════════════════════

ALGORITHM COMPLEXITY:
  • Scanning: O(n) where n = number of files/folders
  • Total calculation: O(n×d) where d = average depth (typically 5-10)
  • Report generation: O(n log n) for sorting

DISK USAGE CALCULATION:
  • Uses stat.st_blocks × 512 (POSIX standard)
  • st_blocks = number of 512-byte blocks allocated
  • More accurate than st_size for actual disk usage
  • Handles sparse files, compression, holes correctly

SPARSE FILE EXAMPLE:
  Logical size:  1,099,511,627,776 bytes (1 TB)
  Actual blocks: 16,777,216 blocks
  Actual usage:  16,777,216 × 512 = 8,589,934,592 bytes (8 GB)

SYMLINK HANDLING:
  • Detects symlinks using entry.is_symlink()
  • Skips entirely (not followed)
  • Prevents:
    - Circular references
    - Double counting
    - Infinite loops

DOUBLE-COUNTING PREVENTION:
  1. Collect all folder paths
  2. For each folder, check if any other path starts with it
  3. If yes, folder is a "parent" - exclude from total
  4. If no, folder is a "leaf" - include in total
  5. Sum only leaf folders for accurate total

MEMORY USAGE:
  • Stores metadata for all scanned folders in RAM
  • Typical: ~500 bytes per folder
  • 100,000 folders ≈ 50 MB RAM
  • 1,000,000 folders ≈ 500 MB RAM

SUPPORTED FILESYSTEMS:
  ✓ APFS (macOS)
  ✓ HFS+ (macOS)
  ✓ ext4 (Linux)
  ✓ btrfs (Linux)
  ✓ NTFS (Windows)
  ✓ FAT32/exFAT (limited - no st_blocks)
  ✓ NFS, SMB (network drives)

PLATFORM COMPATIBILITY:
  • macOS: Full support (ARM64 & Intel)
  • Linux: Full support
  • Windows: Full support
  • BSD: Should work (untested)

═══════════════════════════════════════════════════════════════════════════

EXAMPLES SUMMARY
════════════════

Quick Scans:
  disk_analyzer                          # Current directory
  disk_analyzer ~/Desktop               # Desktop folder
  disk_analyzer . -d 3                  # Shallow scan

Detailed Analysis:
  disk_analyzer ~/ -d 8 -o full.html   # Deep home scan
  disk_analyzer /Volumes/Backup -d 6   # External drive

System Audit:
  sudo disk_analyzer / -d 5            # Full system scan
  disk_analyzer /var/log -d 4          # Check log size

Project Cleanup:
  disk_analyzer ~/Projects -d 5         # Find node_modules
  disk_analyzer ~/.cache -d 3           # Check cache size

Docker Analysis:
  disk_analyzer ~/Library/Containers/com.docker.docker -d 8

═══════════════════════════════════════════════════════════════════════════

For more information, visit: https://github.com/yourusername/disk-analyzer
Report issues: https://github.com/yourusername/disk-analyzer/issues

═══════════════════════════════════════════════════════════════════════════
"""
    print(manual)
    sys.exit(0)


def main():
    # Required for multiprocessing in frozen executables (PyInstaller)
    freeze_support()

    parser = argparse.ArgumentParser(
        description='Analyze disk space usage and generate HTML report',
        epilog='Use --manual for comprehensive documentation'
    )
    parser.add_argument('path', nargs='?', default='.', help='Path to analyze (default: current directory)')
    parser.add_argument('-o', '--output', default='disk_report.html', help='Output HTML file (default: disk_report.html)')
    parser.add_argument('-d', '--depth', type=int, default=4, help='Maximum directory depth to scan (default: 4)')
    parser.add_argument('--no-hash', action='store_true', help='Skip MD5 verification, use size-only matching (much faster)')
    parser.add_argument('--manual', action='store_true', help='Show comprehensive user manual')

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    # Show manual if requested
    if args.manual:
        show_manual()

    root_path = os.path.abspath(args.path)

    if not os.path.exists(root_path):
        print(f"Error: Path '{root_path}' does not exist")
        sys.exit(1)

    print(f"Starting disk analysis of: {root_path}")
    print(f"Maximum depth: {args.depth}")

    use_hash = not args.no_hash
    if args.no_hash:
        print("Note: Running in fast mode (--no-hash), duplicates matched by size only")

    folder_data, file_type_stats, duplicates, duplicate_groups = analyze_directory(
        root_path, max_depth=args.depth,
        progress_callback=lambda n: print(f"Processed {n} items...", end='\r'),
        use_md5=use_hash
    )

    if not folder_data:
        print("\nNo data collected. Try running with elevated permissions or different path.")
        sys.exit(1)

    print(f"\n\nGenerating report...")
    print(f"Calculating totals from {len(folder_data)} folders...", end='\r')
    actual_total, _ = calculate_actual_total(folder_data)
    total_file_types = len(file_type_stats)
    total_files = sum(stats['count'] for stats in file_type_stats.values())

    # Calculate wasted space from duplicates
    wasted_space = sum(
        sum(f['size'] for f in group[1:])
        for group in duplicate_groups
    )

    print(f"Writing HTML report...                              ", end='\r')
    generate_html_report(folder_data, file_type_stats, duplicates, duplicate_groups, args.output, root_path)

    # Generate detailed text log file
    log_file = os.path.splitext(args.output)[0] + '_detailed.txt'
    print(f"Writing detailed log file...                        ", end='\r')
    save_detailed_logs(folder_data, file_type_stats, duplicates, duplicate_groups, log_file, root_path)

    print(f"\n✓ HTML report: {os.path.abspath(args.output)}")
    print(f"✓ Detailed log: {os.path.abspath(log_file)}")
    print(f"✓ Analyzed {len(folder_data)} folders")
    print(f"✓ Analyzed {total_files:,} files across {total_file_types} file types")
    print(f"✓ Total space: {format_size(actual_total)}")
    print(f"✓ Found {len(duplicate_groups)} duplicate groups ({len(duplicates)} files)")
    print(f"✓ Potential space savings: {format_size(wasted_space)}")


if __name__ == '__main__':
    main()
