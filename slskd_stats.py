#!/usr/bin/env python3
import sqlite3
import os
import datetime
import argparse
from collections import defaultdict
from pathlib import Path
import glob

def format_size(size_bytes):
    """Format byte size to human readable format"""
    if size_bytes == 0:
        return "0B"
    size_names = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.2f} {size_names[i]}"

def format_time(seconds):
    """Format seconds to human readable time"""
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.2f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.2f} hours"

def get_transfer_stats(db_paths, direction="Upload", days=None):
    """Get statistics on transfers from the database(s)"""
    stats = {
        "total_transfers": 0,
        "total_bytes": 0,
        "unique_users": set(),
        "user_stats": defaultdict(lambda: {"count": 0, "bytes": 0}),
        "extension_stats": defaultdict(lambda: {"count": 0, "bytes": 0}),
        "speeds": [],
        "durations": []
    }
    
    date_filter = ""
    if days:
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        date_filter = f" AND RequestedAt >= '{cutoff_date}'"
    
    # Process each database file
    for db_path in db_paths:
        if not os.path.exists(db_path):
            print(f"Warning: Database file not found: {db_path}")
            continue
            
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get successful transfers
            cursor.execute(f"""
                SELECT Username, Filename, Size, BytesTransferred, AverageSpeed,
                       RequestedAt, StartedAt, EndedAt
                FROM Transfers
                WHERE Direction=? AND State LIKE 'Completed, Succeeded'
                {date_filter}
            """, (direction,))
            
            transfers = cursor.fetchall()
            conn.close()
            
            # Process transfer data
            for row in transfers:
                username, filename, size, bytes_transferred, avg_speed, req_at, start_at, end_at = row
                
                stats["total_transfers"] += 1
                stats["total_bytes"] += bytes_transferred
                stats["unique_users"].add(username)
                
                # User stats
                stats["user_stats"][username]["count"] += 1
                stats["user_stats"][username]["bytes"] += bytes_transferred
                
                # Extension stats
                ext = os.path.splitext(filename)[1].lower() if filename else ".unknown"
                if not ext:
                    ext = ".noext"
                
                stats["extension_stats"][ext]["count"] += 1
                stats["extension_stats"][ext]["bytes"] += bytes_transferred
                
                # Speed stats
                if avg_speed > 0:
                    stats["speeds"].append(avg_speed)
                
                # Duration stats
                if start_at and end_at:
                    try:
                        start_time = datetime.datetime.fromisoformat(start_at.replace('Z', '+00:00'))
                        end_time = datetime.datetime.fromisoformat(end_at.replace('Z', '+00:00'))
                        duration = (end_time - start_time).total_seconds()
                        if duration > 0:
                            stats["durations"].append(duration)
                    except (ValueError, TypeError):
                        pass
                
        except sqlite3.Error as e:
            print(f"Error processing database {db_path}: {e}")
    
    # Calculate averages
    if stats["speeds"]:
        stats["avg_speed"] = sum(stats["speeds"]) / len(stats["speeds"])
    else:
        stats["avg_speed"] = 0
        
    if stats["durations"]:
        stats["avg_duration"] = sum(stats["durations"]) / len(stats["durations"])
    else:
        stats["avg_duration"] = 0
    
    stats["unique_users"] = len(stats["unique_users"])
    
    return stats

def display_stats(stats, direction, top_n=10):
    """Display the statistics in a readable format"""
    if not stats or stats["total_transfers"] == 0:
        print(f"No {direction.lower()} data found for the specified period.")
        return
    
    print(f"\n=== {direction.upper()} STATISTICS ===\n")
    
    print(f"Total {direction}s: {stats['total_transfers']}")
    print(f"Total Data {direction}ed: {format_size(stats['total_bytes'])}")
    print(f"Unique Users: {stats['unique_users']}")
    print(f"Average {direction} Speed: {format_size(stats['avg_speed'])}/s")
    print(f"Average {direction} Duration: {format_time(stats['avg_duration'])}")
    
    # Top users by data transferred
    print(f"\n--- Top Users by Data {direction}ed ---")
    sorted_users = sorted(
        stats["user_stats"].items(), 
        key=lambda x: x[1]["bytes"], 
        reverse=True
    )
    
    for i, (username, data) in enumerate(sorted_users[:top_n], 1):
        print(f"{i}. {username}: {data['count']} files, {format_size(data['bytes'])}")
    
    # Top file types
    print("\n--- Top File Types ---")
    sorted_extensions = sorted(
        stats["extension_stats"].items(), 
        key=lambda x: x[1]["bytes"], 
        reverse=True
    )
    
    for i, (ext, data) in enumerate(sorted_extensions[:top_n], 1):
        print(f"{i}. {ext}: {data['count']} files, {format_size(data['bytes'])}")

def main():
    parser = argparse.ArgumentParser(description="Analyze transfer statistics from slskd transfers database")
    parser.add_argument("--db", action="append", help="Path to transfers.db file(s). Can be specified multiple times.")
    parser.add_argument("--days", type=int, help="Only analyze transfers from the last X days")
    parser.add_argument("--top", type=int, default=10, help="Show top N entries in each category")
    parser.add_argument("--uploads", action="store_true", help="Show only upload statistics")
    parser.add_argument("--downloads", action="store_true", help="Show only download statistics")
    parser.add_argument("--all", action="store_true", help="Show both upload and download statistics (default)")
    args = parser.parse_args()

    # Determine which db files to use
    db_paths = []
    if args.db:
        # User specified database files
        for db_path in args.db:
            if os.path.exists(db_path):
                db_paths.append(db_path)
            else:
                print(f"Warning: Database file not found: {db_path}")
    else:
        # Default: Only look for transfers.db in the current directory
        if os.path.exists("transfers.db"):
            db_paths.append("transfers.db")
        else:
            print("Default transfers.db not found in current directory.")

    if not db_paths:
        print("Error: No database files found. Please specify with --db option.")
        return

    print(f"Using database file(s): {', '.join(db_paths)}")

    # Default behavior is to show both uploads and downloads
    # Only change from default if specific flags are set
    if args.uploads and not args.downloads and not args.all:
        show_uploads = True
        show_downloads = False
    elif args.downloads and not args.uploads and not args.all:
        show_uploads = False
        show_downloads = True
    else:
        # Default behavior or --all flag
        show_uploads = True
        show_downloads = True
    
    if show_uploads:
        upload_stats = get_transfer_stats(db_paths, "Upload", args.days)
        display_stats(upload_stats, "Upload", args.top)
    
    if show_downloads:
        download_stats = get_transfer_stats(db_paths, "Download", args.days)
        display_stats(download_stats, "Download", args.top)

if __name__ == "__main__":
    main()