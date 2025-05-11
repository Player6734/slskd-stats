#!/usr/bin/env python3
import sys
import os
import datetime
import sqlite3
import argparse
import glob
from collections import defaultdict
from pathlib import Path

# For GUI
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QFileDialog, QComboBox, QTabWidget, 
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QSpinBox, QGroupBox, QFormLayout, QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QIcon

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
    """Display the statistics in a readable format for CLI"""
    if not stats or stats["total_transfers"] == 0:
        print(f"No {direction.lower()} data found for the specified period.")
        return
    
    output = []
    output.append(f"\n=== {direction.upper()} STATISTICS ===\n")
    
    output.append(f"Total {direction}s: {stats['total_transfers']}")
    output.append(f"Total Data {direction}ed: {format_size(stats['total_bytes'])}")
    output.append(f"Unique Users: {stats['unique_users']}")
    output.append(f"Average {direction} Speed: {format_size(stats['avg_speed'])}/s")
    output.append(f"Average {direction} Duration: {format_time(stats['avg_duration'])}")
    
    # Top users by data transferred
    output.append(f"\n--- Top Users by Data {direction}ed ---")
    sorted_users = sorted(
        stats["user_stats"].items(), 
        key=lambda x: x[1]["bytes"], 
        reverse=True
    )
    
    for i, (username, data) in enumerate(sorted_users[:top_n], 1):
        output.append(f"{i}. {username}: {data['count']} files, {format_size(data['bytes'])}")
    
    # Top file types
    output.append("\n--- Top File Types ---")
    sorted_extensions = sorted(
        stats["extension_stats"].items(), 
        key=lambda x: x[1]["bytes"], 
        reverse=True
    )
    
    for i, (ext, data) in enumerate(sorted_extensions[:top_n], 1):
        output.append(f"{i}. {ext}: {data['count']} files, {format_size(data['bytes'])}")
    
    # Print all lines
    for line in output:
        print(line)
    
    return output

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("slskd Transfer Statistics")
        self.setMinimumSize(800, 600)
        
        self.db_paths = []
        
        # Create central widget and main layout
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)
        
        self.mainLayout = QVBoxLayout(self.centralWidget)
        
        # Create top section for database selection
        self.createDatabaseSection()
        
        # Create filter section
        self.createFilterSection()
        
        # Create tabs for results
        self.createResultsTabs()
        
        # Create analyze button
        self.analyzeButton = QPushButton("Analyze Transfers")
        self.analyzeButton.clicked.connect(self.analyzeTransfers)
        self.mainLayout.addWidget(self.analyzeButton)
        
        # Initial database check
        if os.path.exists("transfers.db"):
            self.db_paths.append("transfers.db")
            self.dbPathsLabel.setText("Database(s): transfers.db")
        
    def createDatabaseSection(self):
        # Database selection section
        dbSection = QGroupBox("Database Files")
        dbLayout = QVBoxLayout()
        
        # Create layout for database selection buttons
        buttonLayout = QHBoxLayout()
        
        # Add database button
        addDbButton = QPushButton("Add Database File")
        addDbButton.clicked.connect(self.addDatabaseFile)
        buttonLayout.addWidget(addDbButton)
        
        # Clear databases button
        clearDbButton = QPushButton("Clear Database Files")
        clearDbButton.clicked.connect(self.clearDatabaseFiles)
        buttonLayout.addWidget(clearDbButton)
        
        dbLayout.addLayout(buttonLayout)
        
        # Label to show selected databases
        self.dbPathsLabel = QLabel("No database files selected")
        dbLayout.addWidget(self.dbPathsLabel)
        
        dbSection.setLayout(dbLayout)
        self.mainLayout.addWidget(dbSection)
        
    def createFilterSection(self):
        # Filter options section
        filterSection = QGroupBox("Filters")
        filterLayout = QFormLayout()
        
        # Days filter
        self.daysSpinBox = QSpinBox()
        self.daysSpinBox.setMinimum(0)
        self.daysSpinBox.setMaximum(3650)  # 10 years
        self.daysSpinBox.setValue(0)
        self.daysSpinBox.setSpecialValueText("All time")
        filterLayout.addRow("Only show transfers from last X days:", self.daysSpinBox)
        
        # Top N filter
        self.topSpinBox = QSpinBox()
        self.topSpinBox.setMinimum(1)
        self.topSpinBox.setMaximum(100)
        self.topSpinBox.setValue(10)
        filterLayout.addRow("Show top N entries:", self.topSpinBox)
        
        # Direction filter
        directionLayout = QHBoxLayout()
        self.uploadsCheckBox = QCheckBox("Show Uploads")
        self.uploadsCheckBox.setChecked(True)
        self.downloadsCheckBox = QCheckBox("Show Downloads")
        self.downloadsCheckBox.setChecked(True)
        directionLayout.addWidget(self.uploadsCheckBox)
        directionLayout.addWidget(self.downloadsCheckBox)
        filterLayout.addRow("Statistics to show:", directionLayout)
        
        filterSection.setLayout(filterLayout)
        self.mainLayout.addWidget(filterSection)
        
    def createResultsTabs(self):
        # Tabs for results
        self.resultsTabs = QTabWidget()
        
        # Upload tab
        self.uploadTab = QWidget()
        self.uploadLayout = QVBoxLayout(self.uploadTab)
        self.uploadSummary = QTextEdit()
        self.uploadSummary.setReadOnly(True)
        self.uploadLayout.addWidget(self.uploadSummary)
        
        # Download tab
        self.downloadTab = QWidget()
        self.downloadLayout = QVBoxLayout(self.downloadTab)
        self.downloadSummary = QTextEdit()
        self.downloadSummary.setReadOnly(True)
        self.downloadLayout.addWidget(self.downloadSummary)
        
        # User tables
        self.uploadUsersTable = QTableWidget(0, 3)
        self.uploadUsersTable.setHorizontalHeaderLabels(["User", "Files", "Data"])
        self.uploadUsersTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.uploadLayout.addWidget(QLabel("Top Users by Upload Size"))
        self.uploadLayout.addWidget(self.uploadUsersTable)
        
        self.downloadUsersTable = QTableWidget(0, 3)
        self.downloadUsersTable.setHorizontalHeaderLabels(["User", "Files", "Data"])
        self.downloadUsersTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.downloadLayout.addWidget(QLabel("Top Users by Download Size"))
        self.downloadLayout.addWidget(self.downloadUsersTable)
        
        # File type tables
        self.uploadTypesTable = QTableWidget(0, 3)
        self.uploadTypesTable.setHorizontalHeaderLabels(["Extension", "Files", "Data"])
        self.uploadTypesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.uploadLayout.addWidget(QLabel("Top File Types (Uploads)"))
        self.uploadLayout.addWidget(self.uploadTypesTable)
        
        self.downloadTypesTable = QTableWidget(0, 3)
        self.downloadTypesTable.setHorizontalHeaderLabels(["Extension", "Files", "Data"])
        self.downloadTypesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.downloadLayout.addWidget(QLabel("Top File Types (Downloads)"))
        self.downloadLayout.addWidget(self.downloadTypesTable)
        
        # Add tabs to tab widget
        self.resultsTabs.addTab(self.uploadTab, "Upload Statistics")
        self.resultsTabs.addTab(self.downloadTab, "Download Statistics")
        
        self.mainLayout.addWidget(self.resultsTabs)
        
    def addDatabaseFile(self):
        options = QFileDialog.Options()
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Database File(s)", "", "SQLite Files (*.db);;All Files (*)", 
            options=options
        )
        
        if files:
            for file in files:
                if file not in self.db_paths:
                    self.db_paths.append(file)
            
            self.updateDbPathsLabel()
    
    def clearDatabaseFiles(self):
        self.db_paths = []
        self.dbPathsLabel.setText("No database files selected")
    
    def updateDbPathsLabel(self):
        if not self.db_paths:
            self.dbPathsLabel.setText("No database files selected")
        else:
            paths_text = ", ".join(os.path.basename(path) for path in self.db_paths)
            self.dbPathsLabel.setText(f"Database(s): {paths_text}")
    
    def populateTable(self, table, data, top_n):
        table.setRowCount(0)
        for i, (name, stats) in enumerate(data[:top_n]):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(name))
            table.setItem(i, 1, QTableWidgetItem(str(stats["count"])))
            table.setItem(i, 2, QTableWidgetItem(format_size(stats["bytes"])))
    
    def analyzeTransfers(self):
        if not self.db_paths:
            QMessageBox.warning(self, "No Database Files", 
                               "Please add at least one database file to analyze.")
            return
        
        days = self.daysSpinBox.value() if self.daysSpinBox.value() > 0 else None
        top_n = self.topSpinBox.value()
        show_uploads = self.uploadsCheckBox.isChecked()
        show_downloads = self.downloadsCheckBox.isChecked()
        
        if not show_uploads and not show_downloads:
            QMessageBox.warning(self, "No Direction Selected", 
                               "Please select at least one direction (uploads or downloads).")
            return
        
        # Clear previous results
        self.uploadSummary.clear()
        self.downloadSummary.clear()
        self.uploadUsersTable.setRowCount(0)
        self.downloadUsersTable.setRowCount(0)
        self.uploadTypesTable.setRowCount(0)
        self.downloadTypesTable.setRowCount(0)
        
        # Get stats and update UI
        if show_uploads:
            upload_stats = get_transfer_stats(self.db_paths, "Upload", days)
            if upload_stats["total_transfers"] > 0:
                stats_text = "\n".join([
                    f"Total Uploads: {upload_stats['total_transfers']}",
                    f"Total Data Uploaded: {format_size(upload_stats['total_bytes'])}",
                    f"Unique Users: {upload_stats['unique_users']}",
                    f"Average Upload Speed: {format_size(upload_stats['avg_speed'])}/s",
                    f"Average Upload Duration: {format_time(upload_stats['avg_duration'])}"
                ])
                self.uploadSummary.setText(stats_text)
                
                # Update tables
                sorted_users = sorted(
                    upload_stats["user_stats"].items(), 
                    key=lambda x: x[1]["bytes"], 
                    reverse=True
                )
                self.populateTable(self.uploadUsersTable, sorted_users, top_n)
                
                sorted_extensions = sorted(
                    upload_stats["extension_stats"].items(), 
                    key=lambda x: x[1]["bytes"], 
                    reverse=True
                )
                self.populateTable(self.uploadTypesTable, sorted_extensions, top_n)
            else:
                self.uploadSummary.setText("No upload data found for the specified period.")
        
        if show_downloads:
            download_stats = get_transfer_stats(self.db_paths, "Download", days)
            if download_stats["total_transfers"] > 0:
                stats_text = "\n".join([
                    f"Total Downloads: {download_stats['total_transfers']}",
                    f"Total Data Downloaded: {format_size(download_stats['total_bytes'])}",
                    f"Unique Users: {download_stats['unique_users']}",
                    f"Average Download Speed: {format_size(download_stats['avg_speed'])}/s",
                    f"Average Download Duration: {format_time(download_stats['avg_duration'])}"
                ])
                self.downloadSummary.setText(stats_text)
                
                # Update tables
                sorted_users = sorted(
                    download_stats["user_stats"].items(), 
                    key=lambda x: x[1]["bytes"], 
                    reverse=True
                )
                self.populateTable(self.downloadUsersTable, sorted_users, top_n)
                
                sorted_extensions = sorted(
                    download_stats["extension_stats"].items(), 
                    key=lambda x: x[1]["bytes"], 
                    reverse=True
                )
                self.populateTable(self.downloadTypesTable, sorted_extensions, top_n)
            else:
                self.downloadSummary.setText("No download data found for the specified period.")
        
        # Switch to the appropriate tab
        if show_uploads:
            self.resultsTabs.setCurrentIndex(0)
        elif show_downloads:
            self.resultsTabs.setCurrentIndex(1)

def main():
    # Check if command line args were provided
    if len(sys.argv) > 1:
        # Command line mode
        parser = argparse.ArgumentParser(description="Analyze transfer statistics from slskd transfers database")
        parser.add_argument("--db", action="append", help="Path to transfers.db file(s). Can be specified multiple times.")
        parser.add_argument("--days", type=int, help="Only analyze transfers from the last X days")
        parser.add_argument("--top", type=int, default=10, help="Show top N entries in each category")
        parser.add_argument("--uploads", action="store_true", help="Show only upload statistics")
        parser.add_argument("--downloads", action="store_true", help="Show only download statistics")
        parser.add_argument("--all", action="store_true", help="Show both upload and download statistics (default)")
        parser.add_argument("--gui", action="store_true", help="Launch the GUI instead of command line mode")
        args = parser.parse_args()
        
        # Check if GUI mode is requested
        if args.gui:
            # Launch GUI mode
            app = QApplication(sys.argv)
            window = MainWindow()
            window.show()
            sys.exit(app.exec_())
        
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
    else:
        # No args provided, launch GUI
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())

if __name__ == "__main__":
    main()