#!/usr/bin/env python3
import sys
import os
import datetime
import sqlite3
from collections import defaultdict

# For GUI
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QSplitter,
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

def check_database_format(db_path):
    """Check if database uses old (text State) or new (integer State + StateDescription) format"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if StateDescription column exists
        cursor.execute("PRAGMA table_info(Transfers)")
        columns = [column[1] for column in cursor.fetchall()]
        has_state_description = 'StateDescription' in columns
        
        if has_state_description:
            # New format with StateDescription column
            conn.close()
            return 'new'
        else:
            # Old format with text State column
            conn.close()
            return 'old'
    except sqlite3.Error:
        return 'old'  # Default to old format if error

def get_transfer_stats(db_paths, direction="Upload", days=None):
    """Get statistics on transfers from the database(s)"""
    stats = {
        "total_transfers": 0,
        "total_bytes": 0,
        "unique_users": set(),
        "user_stats": defaultdict(lambda: {"count": 0, "bytes": 0}),
        "extension_stats": defaultdict(lambda: {"count": 0, "bytes": 0}),
        "speeds": [],
        "durations": [],
        "total_attempts": 0,
        "errors": 0
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
            
            # Detect database format
            db_format = check_database_format(db_path)
            
            if db_format == 'new':
                # New format with StateDescription column
                completed_condition = "StateDescription LIKE 'Completed%'"
                error_condition = "StateDescription='Completed, Errored'"
                success_condition = "StateDescription='Completed, Succeeded'"
            else:
                # Old format with text State column
                completed_condition = "State LIKE 'Completed%'"
                error_condition = "State='Completed, Errored'"
                success_condition = "State LIKE 'Completed, Succeeded'"

            # Count total attempts and errors for error rate
            cursor.execute(f"""
                SELECT COUNT(*) FROM Transfers
                WHERE Direction=? AND {completed_condition}
                {date_filter}
            """, (direction,))
            stats["total_attempts"] += cursor.fetchone()[0]

            cursor.execute(f"""
                SELECT COUNT(*) FROM Transfers
                WHERE Direction=? AND {error_condition}
                {date_filter}
            """, (direction,))
            stats["errors"] += cursor.fetchone()[0]

            # Get successful transfers
            cursor.execute(f"""
                SELECT Username, Filename, Size, BytesTransferred, AverageSpeed,
                       RequestedAt, StartedAt, EndedAt
                FROM Transfers
                WHERE Direction=? AND {success_condition}
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

    # Calculate error rate
    if stats["total_attempts"] > 0:
        stats["error_rate"] = (stats["errors"] / stats["total_attempts"]) * 100
    else:
        stats["error_rate"] = 0

    stats["unique_users"] = len(stats["unique_users"])

    return stats


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

        # Time period filter
        self.periodComboBox = QComboBox()
        self.periodComboBox.addItems(["All time", "Last month", "Last year"])
        self.periodComboBox.setCurrentText("All time")
        filterLayout.addRow("Time period:", self.periodComboBox)

        # Top N filter
        self.topSpinBox = QSpinBox()
        self.topSpinBox.setMinimum(1)
        self.topSpinBox.setMaximum(100)
        self.topSpinBox.setValue(10)
        filterLayout.addRow("Show top N entries:", self.topSpinBox)

        # Hidden variables to replace checkboxes
        self.uploadsCheckBox = True
        self.downloadsCheckBox = True

        filterSection.setLayout(filterLayout)
        self.mainLayout.addWidget(filterSection)
        
    def createResultsTabs(self):
        # Create a widget for all statistics
        self.resultsWidget = QWidget()
        self.resultsLayout = QVBoxLayout(self.resultsWidget)

        # Summary section - horizontal layout with two text boxes
        summarySection = QHBoxLayout()

        # Upload summary
        uploadSummaryGroup = QGroupBox("Upload Summary")
        uploadSummaryLayout = QVBoxLayout()
        self.uploadSummary = QTextEdit()
        self.uploadSummary.setReadOnly(True)
        self.uploadSummary.setMaximumHeight(120)
        uploadSummaryLayout.addWidget(self.uploadSummary)
        uploadSummaryGroup.setLayout(uploadSummaryLayout)
        summarySection.addWidget(uploadSummaryGroup)

        # Download summary
        downloadSummaryGroup = QGroupBox("Download Summary")
        downloadSummaryLayout = QVBoxLayout()
        self.downloadSummary = QTextEdit()
        self.downloadSummary.setReadOnly(True)
        self.downloadSummary.setMaximumHeight(120)
        downloadSummaryLayout.addWidget(self.downloadSummary)
        downloadSummaryGroup.setLayout(downloadSummaryLayout)
        summarySection.addWidget(downloadSummaryGroup)

        self.resultsLayout.addLayout(summarySection)

        # Users section - horizontal layout with two tables
        usersSection = QHBoxLayout()

        # Upload users
        uploadUsersGroup = QGroupBox("Top Users by Upload Size")
        uploadUsersLayout = QVBoxLayout()
        self.uploadUsersTable = QTableWidget(0, 3)
        self.uploadUsersTable.setHorizontalHeaderLabels(["User", "Files", "Data"])
        self.uploadUsersTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        uploadUsersLayout.addWidget(self.uploadUsersTable)
        uploadUsersGroup.setLayout(uploadUsersLayout)
        usersSection.addWidget(uploadUsersGroup)

        # Download users
        downloadUsersGroup = QGroupBox("Top Users by Download Size")
        downloadUsersLayout = QVBoxLayout()
        self.downloadUsersTable = QTableWidget(0, 3)
        self.downloadUsersTable.setHorizontalHeaderLabels(["User", "Files", "Data"])
        self.downloadUsersTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        downloadUsersLayout.addWidget(self.downloadUsersTable)
        downloadUsersGroup.setLayout(downloadUsersLayout)
        usersSection.addWidget(downloadUsersGroup)

        self.resultsLayout.addLayout(usersSection)

        # File types section - horizontal layout with two tables
        typesSection = QHBoxLayout()

        # Upload file types
        uploadTypesGroup = QGroupBox("Top File Types (Uploads)")
        uploadTypesLayout = QVBoxLayout()
        self.uploadTypesTable = QTableWidget(0, 3)
        self.uploadTypesTable.setHorizontalHeaderLabels(["Extension", "Files", "Data"])
        self.uploadTypesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        uploadTypesLayout.addWidget(self.uploadTypesTable)
        uploadTypesGroup.setLayout(uploadTypesLayout)
        typesSection.addWidget(uploadTypesGroup)

        # Download file types
        downloadTypesGroup = QGroupBox("Top File Types (Downloads)")
        downloadTypesLayout = QVBoxLayout()
        self.downloadTypesTable = QTableWidget(0, 3)
        self.downloadTypesTable.setHorizontalHeaderLabels(["Extension", "Files", "Data"])
        self.downloadTypesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        downloadTypesLayout.addWidget(self.downloadTypesTable)
        downloadTypesGroup.setLayout(downloadTypesLayout)
        typesSection.addWidget(downloadTypesGroup)

        self.resultsLayout.addLayout(typesSection)

        # Add the results widget to the main layout
        self.mainLayout.addWidget(self.resultsWidget)
        
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

        # Convert period selection to days
        period_text = self.periodComboBox.currentText()
        if period_text == "All time":
            days = None
        elif period_text == "Last month":
            days = 30
        elif period_text == "Last year":
            days = 365
        else:
            days = None
        top_n = self.topSpinBox.value()

        # Always show both upload and download stats
        show_uploads = True
        show_downloads = True

        # Clear previous results
        self.uploadSummary.clear()
        self.downloadSummary.clear()
        self.uploadUsersTable.setRowCount(0)
        self.downloadUsersTable.setRowCount(0)
        self.uploadTypesTable.setRowCount(0)
        self.downloadTypesTable.setRowCount(0)

        # Get stats and update UI
        upload_stats = get_transfer_stats(self.db_paths, "Upload", days)
        if upload_stats["total_transfers"] > 0:
            stats_text = "\n".join([
                f"Total Uploads: {upload_stats['total_transfers']}",
                f"Total Data Uploaded: {format_size(upload_stats['total_bytes'])}",
                f"Unique Users: {upload_stats['unique_users']}",
                f"Average Upload Speed: {format_size(upload_stats['avg_speed'])}/s",
                f"Average Upload Duration: {format_time(upload_stats['avg_duration'])}",
                f"Error Rate: {upload_stats['error_rate']:.2f}% ({upload_stats['errors']} of {upload_stats['total_attempts']})"
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

        download_stats = get_transfer_stats(self.db_paths, "Download", days)
        if download_stats["total_transfers"] > 0:
            stats_text = "\n".join([
                f"Total Downloads: {download_stats['total_transfers']}",
                f"Total Data Downloaded: {format_size(download_stats['total_bytes'])}",
                f"Unique Users: {download_stats['unique_users']}",
                f"Average Download Speed: {format_size(download_stats['avg_speed'])}/s",
                f"Average Download Duration: {format_time(download_stats['avg_duration'])}",
                f"Error Rate: {download_stats['error_rate']:.2f}% ({download_stats['errors']} of {download_stats['total_attempts']})"
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

def main():
    # Launch GUI application
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()