# slskd Transfer Statistics

A tool to analyze upload and download statistics from your slskd transfers database with both command-line and GUI interfaces.

## Features

- Analyzes uploads and downloads stored in the transfers.db database(s)
- Automatically finds and combines data from multiple database files
- Calculates total transfers, data transferred, and unique users
- Shows average transfer speed and duration
- Lists top users by data transferred
- Shows statistics by file type
- Filter statistics by date range
- Graphical user interface for easier analysis
- Maintains full command-line functionality

## Requirements

- Python 3.6+
- SQLite3
- PyQt5 (for GUI version)

## Installation

1. Clone or download this repository to your local machine
2. Ensure Python 3 is installed
3. Place your `transfers.db` file in the same directory as the script, or specify database paths using the `--db` option

## Usage

### Command Line Interface

```bash
# Basic usage (uses transfers.db in current directory)
# Shows both upload and download stats by default
./slskd_stats.py

# Show only upload stats
./slskd_stats.py --uploads

# Show only download stats
./slskd_stats.py --downloads

# Explicitly show both upload and download stats (same as default)
./slskd_stats.py --all

# Specify single database file
./slskd_stats.py --db /path/to/transfers.db

# Specify multiple database files
./slskd_stats.py --db /path/to/transfers.db --db /path/to/another-transfers.db

# Only show transfers from the last 30 days
./slskd_stats.py --days 30

# Show top 15 entries in each category
./slskd_stats.py --top 15

# Combine options
./slskd_stats.py --all --days 7 --top 20 --db /path/to/transfers.db
```

### GUI Interface

```bash
# Launch the GUI version
./slskd_stats_gui.py

# Launch GUI even when providing command line arguments
./slskd_stats_gui.py --gui
```

With the GUI, you can:
- Select one or more database files using the file browser
- Choose to show upload stats, download stats, or both
- Filter by time period (last X days)
- Set the number of top entries to display
- View statistics in a user-friendly tabbed interface

## Example Output

```
=== UPLOAD STATISTICS ===

Total Uploads: 8583
Total Data Uploaded: 241.97 GB
Unique Users: 650
Average Upload Speed: 8.50 MB/s
Average Upload Duration: 10.02 seconds

--- Top Users by Data Uploaded ---
1. username1: 279 files, 18.01 GB
2. username2: 494 files, 12.29 GB
3. username3: 378 files, 11.05 GB
...

--- Top File Types ---
1. .flac: 8456 files, 241.00 GB
2. .mp3: 105 files, 830.71 MB
3. .m4a: 22 files, 165.58 MB

=== DOWNLOAD STATISTICS ===

Total Downloads: 357
Total Data Downloaded: 10.94 GB
Unique Users: 36
Average Download Speed: 2.03 MB/s
Average Download Duration: 26.21 seconds

--- Top Users by Data Downloaded ---
1. username1: 6 files, 1.45 GB
2. username2: 58 files, 1.33 GB
...
```

## About

This tool is designed to work with the `transfers.db` SQLite database created by [slskd](https://github.com/slskd/slskd), a Soulseek client daemon. It helps you understand your sharing patterns and track transfer statistics.

## License

MIT