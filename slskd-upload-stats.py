#!/usr/bin/env python3
"""
SLSKD Transfer Size Analyzer

A script I created to analyze SLSKD HTML and calculate accurate transfer statistics.
After experimenting with different approaches, I found that checking the button text
directly gives more reliable results than relying on CSS classes.

I also added automatic conversion between MB and GB to make large numbers more readable.

Usage:
  python slskd_analyzer_with_gb.py <html_file>
"""

import re
import sys
import os
from bs4 import BeautifulSoup

def format_size(size_mb):
    """
    Format file size in MB or GB depending on the size.
    
    I added this function to make large transfer sizes more readable.
    After dealing with multi-GB transfers, seeing something like "2458.7 MB" 
    is less intuitive than "2.4 GB".
    """
    if size_mb >= 1024:
        return f"{size_mb/1024:.2f} GB"
    else:
        return f"{size_mb:.1f} MB"

def analyze_html(html_content):
    """
    Parse and analyze the SLSKD HTML content to extract transfer statistics.
    
    I initially tried looking only at CSS classes, but found inconsistencies in how 
    the success/failure states were represented. Checking the actual button text with
    "Completed, Succeeded" proved more reliable and worked across different versions.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Initialize statistics dictionary
    stats = {
        'successful_mb': 0,
        'failed_mb': 0,
        'total_mb': 0,
        'successful_files': 0,
        'failed_files': 0,
        'flac_files': 0,
        'mp3_files': 0,
        'users': {}
    }
    
    # Process each transfer card (one per user)
    # I structured it this way to make it easier to attribute transfers to users
    transfer_cards = soup.find_all('div', class_='ui raised card transfer-card')
    
    for card in transfer_cards:
        # Extract the username from the header
        header = card.find('div', class_='header')
        username = header.text.strip() if header else "Unknown"
        
        # Initialize user statistics if not already present
        if username not in stats['users']:
            stats['users'][username] = {
                'successful_mb': 0,
                'failed_mb': 0, 
                'total_mb': 0,
                'successful_files': 0,
                'failed_files': 0
            }
        
        # Process all file rows for this user
        # I tried several approaches and found traversing the rows directly was most reliable
        rows = card.find_all('tr')
        
        for row in rows:
            # Skip header rows - they have th elements
            if row.find('th'):
                continue
            
            # Extract the relevant cells
            filename_cell = row.find('td', class_='transferlist-filename')
            progress_cell = row.find('td', class_='transferlist-progress')
            size_cell = row.find('td', class_='transferlist-size')
            
            # Skip if any required cell is missing
            if not all([filename_cell, progress_cell, size_cell]):
                continue
            
            filename = filename_cell.text.strip()
            button = progress_cell.find('button')
            
            if not button:
                continue
                
            # Track file types - primarily interested in audio formats
            if filename.lower().endswith('.flac'):
                stats['flac_files'] += 1
            elif filename.lower().endswith('.mp3'):
                stats['mp3_files'] += 1
            
            # Check success/failure status based on button text
            # This was a key insight - looking for specific text patterns rather than
            # relying on CSS classes which can vary across SLSKD versions/themes
            button_text = button.text.strip()
            is_success = 'Completed, Succeeded' in button_text
            is_failed = 'Completed, Errored' in button_text
            
            # Parse size information
            # Format is typically "X.X/Y.Y MB" where X is transferred and Y is total
            size_text = size_cell.text.strip()
            size_match = re.search(r'(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)', size_text)
            
            if not size_match:
                continue
                
            transferred = float(size_match.group(1))
            total = float(size_match.group(2))
            
            # Update statistics based on transfer status
            if is_success:
                stats['successful_mb'] += transferred
                stats['successful_files'] += 1
                stats['users'][username]['successful_mb'] += transferred
                stats['users'][username]['successful_files'] += 1
            elif is_failed:
                # For failed transfers, I count the target size rather than the partial transfer
                # This gives a better sense of what "should have" transferred
                stats['failed_mb'] += total
                stats['failed_files'] += 1
                stats['users'][username]['failed_mb'] += total
                stats['users'][username]['failed_files'] += 1
            
            stats['total_mb'] += total
            stats['users'][username]['total_mb'] += total
    
    return stats

def print_report(stats):
    """
    Format and print a comprehensive report of the transfer statistics.
    
    I organized this to present the most relevant information first (overall stats),
    followed by file type breakdowns and user-specific information.
    
    For readability, I convert large values from MB to GB automatically.
    """
    print("\n===== SLSKD TRANSFER STATISTICS =====")
    
    print(f"\nOverall Statistics:")
    print(f"Successfully transferred: {format_size(stats['successful_mb'])} ({stats['successful_files']} files)")
    print(f"Failed transfers: {format_size(stats['failed_mb'])} ({stats['failed_files']} files)")
    print(f"Total size of all files: {format_size(stats['total_mb'])} ({stats['successful_files'] + stats['failed_files']} files)")
    
    if stats['total_mb'] > 0:
        success_rate = (stats['successful_mb'] / stats['total_mb']) * 100
        print(f"Success rate: {success_rate:.1f}%")
    
    print(f"\nFile Type Statistics:")
    print(f"FLAC files: {stats['flac_files']}")
    print(f"MP3 files: {stats['mp3_files']}")
    other_files = stats['successful_files'] + stats['failed_files'] - stats['flac_files'] - stats['mp3_files']
    print(f"Other files: {other_files}")
    
    # Top users by total volume
    print("\nTop Users by Total Transfer Volume:")
    sorted_users_total = sorted(stats['users'].items(), key=lambda x: x[1]['total_mb'], reverse=True)
    for i, (username, user_stats) in enumerate(sorted_users_total[:5], 1):
        print(f"{i}. {username}: {format_size(user_stats['total_mb'])} total")
    
    # Top users by successful transfers
    print("\nTop Users by Successful Transfers:")
    sorted_users_success = sorted(stats['users'].items(), key=lambda x: x[1]['successful_mb'], reverse=True)
    for i, (username, user_stats) in enumerate(sorted_users_success[:5], 1):
        if user_stats['successful_mb'] > 0:
            print(f"{i}. {username}: {format_size(user_stats['successful_mb'])} successful "
                  f"({user_stats['successful_files']} files)")
    
    print("\n=====================================")

def main():
    """
    Main entry point - handles command line arguments and file processing.
    
    I kept the interface simple - just provide the HTML file path as an argument.
    This makes it easy to analyze different snapshots over time.
    """
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <html_file>")
        sys.exit(1)
    
    html_file = sys.argv[1]
    
    if not os.path.exists(html_file):
        print(f"Error: File {html_file} does not exist")
        sys.exit(1)
    
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    stats = analyze_html(html_content)
    print_report(stats)

if __name__ == "__main__":
    main()
