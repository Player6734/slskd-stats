#!/usr/bin/env python3
import sys
import os
import datetime
import sqlite3
from collections import defaultdict

# For GUI
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QSpinBox, QGroupBox, QFormLayout, QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QIcon

# For graphs
import matplotlib
matplotlib.use('Qt5Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator

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

def get_time_series_data(db_paths, days=None):
    """Get time series data for graphing"""
    time_series = {
        'dates': [],
        'upload_counts': [],
        'download_counts': [],
        'upload_bytes': [],
        'download_bytes': [],
        'upload_errors': [],
        'download_errors': [],
        'upload_speeds': [],
        'download_speeds': [],
        'new_users': [],
        'upload_error_rates': [],
        'download_error_rates': []
    }
    
    date_filter = ""
    if days:
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        date_filter = f" AND RequestedAt >= '{cutoff_date}'"
    
    # Collect all data points by date
    daily_data = defaultdict(lambda: {
        'upload_count': 0, 'download_count': 0,
        'upload_bytes': 0, 'download_bytes': 0,
        'upload_errors': 0, 'download_errors': 0,
        'upload_attempts': 0, 'download_attempts': 0,
        'upload_speeds': [], 'download_speeds': [],
        'users': set()
    })
    
    for db_path in db_paths:
        if not os.path.exists(db_path):
            continue
            
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Detect database format
            db_format = check_database_format(db_path)
            
            if db_format == 'new':
                success_condition = "StateDescription='Completed, Succeeded'"
                error_condition = "StateDescription='Completed, Errored'"
                completed_condition = "StateDescription LIKE 'Completed%'"
            else:
                success_condition = "State LIKE 'Completed, Succeeded'"
                error_condition = "State='Completed, Errored'"
                completed_condition = "State LIKE 'Completed%'"
            
            # Get successful transfers
            cursor.execute(f"""
                SELECT Direction, Username, BytesTransferred, AverageSpeed, 
                       DATE(RequestedAt) as date
                FROM Transfers
                WHERE {success_condition}
                {date_filter}
                ORDER BY date
            """)
            
            for row in cursor.fetchall():
                direction, username, bytes_transferred, avg_speed, date = row
                daily_data[date]['users'].add(username)
                
                if direction == 'Upload':
                    daily_data[date]['upload_count'] += 1
                    daily_data[date]['upload_bytes'] += bytes_transferred
                    if avg_speed > 0:
                        daily_data[date]['upload_speeds'].append(avg_speed)
                else:
                    daily_data[date]['download_count'] += 1
                    daily_data[date]['download_bytes'] += bytes_transferred
                    if avg_speed > 0:
                        daily_data[date]['download_speeds'].append(avg_speed)
            
            # Get error counts
            cursor.execute(f"""
                SELECT Direction, COUNT(*) as error_count, DATE(RequestedAt) as date
                FROM Transfers
                WHERE {error_condition}
                {date_filter}
                GROUP BY Direction, DATE(RequestedAt)
            """)
            
            for row in cursor.fetchall():
                direction, error_count, date = row
                if direction == 'Upload':
                    daily_data[date]['upload_errors'] += error_count
                else:
                    daily_data[date]['download_errors'] += error_count
            
            # Get total attempts for error rate calculation
            cursor.execute(f"""
                SELECT Direction, COUNT(*) as total_count, DATE(RequestedAt) as date
                FROM Transfers
                WHERE {completed_condition}
                {date_filter}
                GROUP BY Direction, DATE(RequestedAt)
            """)
            
            for row in cursor.fetchall():
                direction, total_count, date = row
                if direction == 'Upload':
                    daily_data[date]['upload_attempts'] += total_count
                else:
                    daily_data[date]['download_attempts'] += total_count
            
            conn.close()
            
        except sqlite3.Error as e:
            print(f"Error processing database {db_path}: {e}")
    
    # Convert to time series format
    sorted_dates = sorted(daily_data.keys())
    
    for date_str in sorted_dates:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        data = daily_data[date_str]
        
        time_series['dates'].append(date_obj)
        time_series['upload_counts'].append(data['upload_count'])
        time_series['download_counts'].append(data['download_count'])
        time_series['upload_bytes'].append(data['upload_bytes'])
        time_series['download_bytes'].append(data['download_bytes'])
        time_series['upload_errors'].append(data['upload_errors'])
        time_series['download_errors'].append(data['download_errors'])
        time_series['new_users'].append(len(data['users']))
        
        # Calculate average speeds
        upload_avg_speed = sum(data['upload_speeds']) / len(data['upload_speeds']) if data['upload_speeds'] else 0
        download_avg_speed = sum(data['download_speeds']) / len(data['download_speeds']) if data['download_speeds'] else 0
        time_series['upload_speeds'].append(upload_avg_speed)
        time_series['download_speeds'].append(download_avg_speed)
        
        # Calculate error rates
        upload_error_rate = (data['upload_errors'] / data['upload_attempts'] * 100) if data['upload_attempts'] > 0 else 0
        download_error_rate = (data['download_errors'] / data['download_attempts'] * 100) if data['download_attempts'] > 0 else 0
        time_series['upload_error_rates'].append(upload_error_rate)
        time_series['download_error_rates'].append(download_error_rate)
    
    return time_series


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("slskd Transfer Statistics")
        self.setMinimumSize(900, 700)
        self.resize(1000, 750)
        
        self.db_paths = []
        
        # Create central widget and main layout
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)
        
        self.mainLayout = QVBoxLayout(self.centralWidget)
        
        # Create compact controls section
        self.createControlsSection()
        
        # Create tabs for results
        self.createTabs()
        
        # Initial database check
        if os.path.exists("transfers.db"):
            self.db_paths.append("transfers.db")
            self.dbPathsLabel.setText("Database(s): transfers.db")
        
    def createControlsSection(self):
        # Compact controls section
        controlsGroup = QGroupBox("Controls")
        controlsLayout = QHBoxLayout()
        
        # Database buttons only (no label)
        dbButtonsLayout = QHBoxLayout()
        addDbButton = QPushButton("Add Database File")
        addDbButton.clicked.connect(self.addDatabaseFile)
        clearDbButton = QPushButton("Clear Database Files")
        clearDbButton.clicked.connect(self.clearDatabaseFiles)
        dbButtonsLayout.addWidget(addDbButton)
        dbButtonsLayout.addWidget(clearDbButton)
        
        # Analysis controls - right side
        analyzeControlsLayout = QHBoxLayout()
        analyzeControlsLayout.addWidget(QLabel("Time period:"))
        
        self.periodComboBox = QComboBox()
        self.periodComboBox.addItems(["All time", "Last month", "Last year"])
        self.periodComboBox.setCurrentText("All time")
        analyzeControlsLayout.addWidget(self.periodComboBox)
        
        self.analyzeButton = QPushButton("Analyze Transfers")
        self.analyzeButton.clicked.connect(self.analyzeTransfers)
        analyzeControlsLayout.addWidget(self.analyzeButton)
        
        # Create a frame for the vertical separator
        separator = QLabel("|")
        separator.setAlignment(Qt.AlignCenter)
        separator.setStyleSheet("color: gray; font-size: 16px; padding: 0 10px;")
        
        # Add all sections to main layout with centered separator
        controlsLayout.addStretch()  # Push everything to center
        controlsLayout.addLayout(dbButtonsLayout)
        controlsLayout.addWidget(separator)
        controlsLayout.addLayout(analyzeControlsLayout)
        controlsLayout.addStretch()  # Balance the other side
        
        # Hidden variables to replace checkboxes
        self.uploadsCheckBox = True
        self.downloadsCheckBox = True
        
        controlsGroup.setLayout(controlsLayout)
        self.mainLayout.addWidget(controlsGroup)
        
        # Database status label at bottom left
        self.dbPathsLabel = QLabel("No database files selected")
        self.dbPathsLabel.setMaximumWidth(400)
        self.dbPathsLabel.setWordWrap(True)
        self.mainLayout.addWidget(self.dbPathsLabel)
        
    def createTabs(self):
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Create summary stats tab
        self.createSummaryTab()
        
        # Create visual stats tab
        self.createVisualTab()
        
        # Create popularity stats tab
        self.createPopularityTab()
        
        # Add tabs to main layout
        self.mainLayout.addWidget(self.tabs)
    
    def createSummaryTab(self):
        # Create a widget for all statistics
        self.summaryWidget = QWidget()
        self.summaryLayout = QVBoxLayout(self.summaryWidget)

        # Summary section - horizontal layout with two text boxes
        summarySection = QHBoxLayout()

        # Upload summary
        uploadSummaryGroup = QGroupBox("Upload Summary")
        uploadSummaryLayout = QVBoxLayout()
        self.uploadSummary = QTextEdit()
        self.uploadSummary.setReadOnly(True)
        self.uploadSummary.setMinimumHeight(60)
        uploadSummaryLayout.addWidget(self.uploadSummary)
        uploadSummaryGroup.setLayout(uploadSummaryLayout)
        summarySection.addWidget(uploadSummaryGroup)

        # Download summary
        downloadSummaryGroup = QGroupBox("Download Summary")
        downloadSummaryLayout = QVBoxLayout()
        self.downloadSummary = QTextEdit()
        self.downloadSummary.setReadOnly(True)
        self.downloadSummary.setMinimumHeight(60)
        downloadSummaryLayout.addWidget(self.downloadSummary)
        downloadSummaryGroup.setLayout(downloadSummaryLayout)
        summarySection.addWidget(downloadSummaryGroup)

        self.summaryLayout.addLayout(summarySection)

        # Users section - horizontal layout with two tables
        usersSection = QHBoxLayout()

        # Upload users
        uploadUsersGroup = QGroupBox("Top Users by Upload Size")
        uploadUsersLayout = QVBoxLayout()
        self.uploadUsersTable = QTableWidget(0, 3)
        self.uploadUsersTable.setHorizontalHeaderLabels(["User", "Files", "Data"])
        self.uploadUsersTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.uploadUsersTable.setMinimumHeight(100)
        self.uploadUsersTable.setAlternatingRowColors(True)
        self.uploadUsersTable.setEditTriggers(QTableWidget.NoEditTriggers)
        uploadUsersLayout.addWidget(self.uploadUsersTable)
        uploadUsersGroup.setLayout(uploadUsersLayout)
        usersSection.addWidget(uploadUsersGroup)

        # Download users
        downloadUsersGroup = QGroupBox("Top Users by Download Size")
        downloadUsersLayout = QVBoxLayout()
        self.downloadUsersTable = QTableWidget(0, 3)
        self.downloadUsersTable.setHorizontalHeaderLabels(["User", "Files", "Data"])
        self.downloadUsersTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.downloadUsersTable.setMinimumHeight(100)
        self.downloadUsersTable.setAlternatingRowColors(True)
        self.downloadUsersTable.setEditTriggers(QTableWidget.NoEditTriggers)
        downloadUsersLayout.addWidget(self.downloadUsersTable)
        downloadUsersGroup.setLayout(downloadUsersLayout)
        usersSection.addWidget(downloadUsersGroup)

        self.summaryLayout.addLayout(usersSection)

        # File types section - horizontal layout with two tables
        typesSection = QHBoxLayout()

        # Upload file types
        uploadTypesGroup = QGroupBox("Top File Types (Uploads)")
        uploadTypesLayout = QVBoxLayout()
        self.uploadTypesTable = QTableWidget(0, 3)
        self.uploadTypesTable.setHorizontalHeaderLabels(["Extension", "Files", "Data"])
        self.uploadTypesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.uploadTypesTable.setMinimumHeight(100)
        self.uploadTypesTable.setAlternatingRowColors(True)
        self.uploadTypesTable.setEditTriggers(QTableWidget.NoEditTriggers)
        uploadTypesLayout.addWidget(self.uploadTypesTable)
        uploadTypesGroup.setLayout(uploadTypesLayout)
        typesSection.addWidget(uploadTypesGroup)

        # Download file types
        downloadTypesGroup = QGroupBox("Top File Types (Downloads)")
        downloadTypesLayout = QVBoxLayout()
        self.downloadTypesTable = QTableWidget(0, 3)
        self.downloadTypesTable.setHorizontalHeaderLabels(["Extension", "Files", "Data"])
        self.downloadTypesTable.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.downloadTypesTable.setMinimumHeight(100)
        self.downloadTypesTable.setAlternatingRowColors(True)
        self.downloadTypesTable.setEditTriggers(QTableWidget.NoEditTriggers)
        downloadTypesLayout.addWidget(self.downloadTypesTable)
        downloadTypesGroup.setLayout(downloadTypesLayout)
        typesSection.addWidget(downloadTypesGroup)

        self.summaryLayout.addLayout(typesSection)

        # Add the summary tab
        self.tabs.addTab(self.summaryWidget, "Summary Stats")
    
    def createVisualTab(self):
        # Create visual stats tab
        self.visualWidget = QWidget()
        self.visualLayout = QVBoxLayout(self.visualWidget)
        
        # Create amounts graph section
        amountsGroup = QGroupBox("Transfer Amounts Over Time")
        amountsLayout = QVBoxLayout()
        
        # Checkboxes for amounts metrics
        amountsCheckboxLayout = QHBoxLayout()
        self.uploadsCheckbox = QCheckBox("Uploads")
        self.uploadsCheckbox.setChecked(True)
        self.uploadsCheckbox.stateChanged.connect(self.updateGraphs)
        
        self.downloadsCheckbox = QCheckBox("Downloads")
        self.downloadsCheckbox.setChecked(True)
        self.downloadsCheckbox.stateChanged.connect(self.updateGraphs)
        
        self.errorsCheckbox = QCheckBox("Errors")
        self.errorsCheckbox.setChecked(True)
        self.errorsCheckbox.stateChanged.connect(self.updateGraphs)
        
        self.newUsersCheckbox = QCheckBox("New Users")
        self.newUsersCheckbox.setChecked(False)
        self.newUsersCheckbox.stateChanged.connect(self.updateGraphs)
        
        amountsCheckboxLayout.addWidget(self.uploadsCheckbox)
        amountsCheckboxLayout.addWidget(self.downloadsCheckbox)
        amountsCheckboxLayout.addWidget(self.errorsCheckbox)
        amountsCheckboxLayout.addWidget(self.newUsersCheckbox)
        amountsCheckboxLayout.addStretch()
        
        # Amounts graph canvas
        self.amountsFigure = Figure(figsize=(10, 3))
        self.amountsFigure.subplots_adjust(left=0.08, right=0.95, top=0.9, bottom=0.15)
        self.amountsCanvas = FigureCanvas(self.amountsFigure)
        self.amountsCanvas.setMinimumHeight(200)
        
        amountsLayout.addLayout(amountsCheckboxLayout)
        amountsLayout.addWidget(self.amountsCanvas)
        amountsGroup.setLayout(amountsLayout)
        
        # Create ratios graph section
        ratiosGroup = QGroupBox("Transfer Ratios Over Time")
        ratiosLayout = QVBoxLayout()
        
        # Checkboxes for ratios metrics
        ratiosCheckboxLayout = QHBoxLayout()
        self.speedsCheckbox = QCheckBox("Average Speed (MB/s)")
        self.speedsCheckbox.setChecked(True)
        self.speedsCheckbox.stateChanged.connect(self.updateGraphs)
        
        self.errorRateCheckbox = QCheckBox("Error Rate (%)")
        self.errorRateCheckbox.setChecked(True)
        self.errorRateCheckbox.stateChanged.connect(self.updateGraphs)
        
        ratiosCheckboxLayout.addWidget(self.speedsCheckbox)
        ratiosCheckboxLayout.addWidget(self.errorRateCheckbox)
        ratiosCheckboxLayout.addStretch()
        
        # Ratios graph canvas
        self.ratiosFigure = Figure(figsize=(10, 3))
        self.ratiosFigure.subplots_adjust(left=0.08, right=0.92, top=0.9, bottom=0.15)
        self.ratiosCanvas = FigureCanvas(self.ratiosFigure)
        self.ratiosCanvas.setMinimumHeight(200)
        
        ratiosLayout.addLayout(ratiosCheckboxLayout)
        ratiosLayout.addWidget(self.ratiosCanvas)
        ratiosGroup.setLayout(ratiosLayout)
        
        # Add both graph sections to visual layout
        self.visualLayout.addWidget(amountsGroup)
        self.visualLayout.addWidget(ratiosGroup)
        
        # Add the visual tab
        self.tabs.addTab(self.visualWidget, "Visual Stats")
        
        # Initialize empty graphs
        self.timeSeriesData = None
        self.updateGraphs()
        
    def createPopularityTab(self):
        # Create popularity stats tab
        self.popularityWidget = QWidget()
        self.popularityLayout = QVBoxLayout(self.popularityWidget)
        
        # Create compact top entries selector with fixed height
        settingsWidget = QWidget()
        settingsWidget.setMaximumHeight(35)  # Fixed height to prevent scaling
        topEntriesLayout = QHBoxLayout(settingsWidget)
        topEntriesLayout.setContentsMargins(5, 5, 5, 5)  # Minimal margins
        
        topEntriesLayout.addWidget(QLabel("Show top:"))
        
        self.topEntriesSpinBox = QSpinBox()
        self.topEntriesSpinBox.setMinimum(5)
        self.topEntriesSpinBox.setMaximum(50)
        self.topEntriesSpinBox.setValue(10)
        self.topEntriesSpinBox.valueChanged.connect(self.updatePopularityStats)
        topEntriesLayout.addWidget(self.topEntriesSpinBox)
        
        topEntriesLayout.addWidget(QLabel("entries"))
        topEntriesLayout.addStretch()  # Push everything to the left
        
        self.popularityLayout.addWidget(settingsWidget)
        
        # Create splitter for side-by-side layout
        popularitySplitter = QSplitter(Qt.Horizontal)
        
        # Create artists section
        artistsGroup = QGroupBox("Top Artists by Downloads")
        artistsLayout = QVBoxLayout()
        
        self.artistsTable = QTableWidget()
        self.artistsTable.setColumnCount(3)
        self.artistsTable.setHorizontalHeaderLabels(["Artist", "Downloads", "Total Data"])
        self.artistsTable.horizontalHeader().setStretchLastSection(True)
        self.artistsTable.setAlternatingRowColors(True)
        self.artistsTable.setSortingEnabled(True)
        self.artistsTable.setEditTriggers(QTableWidget.NoEditTriggers)
        artistsLayout.addWidget(self.artistsTable)
        
        # Artists chart
        self.artistsFigure = Figure(figsize=(8, 6))
        self.artistsCanvas = FigureCanvas(self.artistsFigure)
        artistsLayout.addWidget(self.artistsCanvas, 0, Qt.AlignCenter)
        
        artistsGroup.setLayout(artistsLayout)
        popularitySplitter.addWidget(artistsGroup)
        
        # Create albums section
        albumsGroup = QGroupBox("Top Albums by Downloads")
        albumsLayout = QVBoxLayout()
        
        self.albumsTable = QTableWidget()
        self.albumsTable.setColumnCount(4)
        self.albumsTable.setHorizontalHeaderLabels(["Artist", "Album", "Downloads", "Total Data"])
        self.albumsTable.horizontalHeader().setStretchLastSection(True)
        self.albumsTable.setAlternatingRowColors(True)
        self.albumsTable.setSortingEnabled(True)
        self.albumsTable.setEditTriggers(QTableWidget.NoEditTriggers)
        albumsLayout.addWidget(self.albumsTable)
        
        # Albums chart
        self.albumsFigure = Figure(figsize=(8, 6))
        self.albumsCanvas = FigureCanvas(self.albumsFigure)
        albumsLayout.addWidget(self.albumsCanvas, 0, Qt.AlignCenter)
        
        albumsGroup.setLayout(albumsLayout)
        popularitySplitter.addWidget(albumsGroup)
        
        self.popularityLayout.addWidget(popularitySplitter)
        
        # Add the popularity tab
        self.tabs.addTab(self.popularityWidget, "Popularity Stats")
        
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
    
    def updateGraphs(self):
        """Update the graphs based on current data and checkbox states"""
        if not self.timeSeriesData or not self.timeSeriesData['dates']:
            # Clear graphs if no data
            self.amountsFigure.clear()
            self.ratiosFigure.clear()
            self.amountsCanvas.draw()
            self.ratiosCanvas.draw()
            return
        
        # Update amounts graph
        self.amountsFigure.clear()
        ax1 = self.amountsFigure.add_subplot(111)
        
        dates = self.timeSeriesData['dates']
        
        # Plot lines and collect them for cursor tooltips
        lines = []
        if self.uploadsCheckbox.isChecked():
            plot_result = ax1.plot(dates, self.timeSeriesData['upload_counts'], label='Uploads', color='blue', linewidth=2)
            if plot_result:
                lines.append((plot_result[0], 'upload_counts', 'Uploads'))
        if self.downloadsCheckbox.isChecked():
            plot_result = ax1.plot(dates, self.timeSeriesData['download_counts'], label='Downloads', color='green', linewidth=2)
            if plot_result:
                lines.append((plot_result[0], 'download_counts', 'Downloads'))
        if self.errorsCheckbox.isChecked():
            total_errors = [u + d for u, d in zip(self.timeSeriesData['upload_errors'], self.timeSeriesData['download_errors'])]
            plot_result = ax1.plot(dates, total_errors, label='Total Errors', color='red', linewidth=2)
            if plot_result:
                lines.append((plot_result[0], 'total_errors', 'Total Errors'))
        if self.newUsersCheckbox.isChecked():
            plot_result = ax1.plot(dates, self.timeSeriesData['new_users'], label='New Users', color='purple', linewidth=2)
            if plot_result:
                lines.append((plot_result[0], 'new_users', 'New Users'))
        
        # Interactive functionality disabled to avoid compatibility issues
        # Charts remain readable with legends and axis labels
        
        ax1.set_xlabel('Date')
        ax1.set_ylabel('Count')
        ax1.set_title('Transfer Amounts Over Time')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Format x-axis dates
        if len(dates) > 30:
            ax1.xaxis.set_major_locator(mdates.WeekdayLocator())
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        else:
            ax1.xaxis.set_major_locator(mdates.DayLocator())
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        
        self.amountsFigure.autofmt_xdate()
        self.amountsFigure.tight_layout()
        
        # Update ratios graph with dynamic y-axes
        self.ratiosFigure.clear()
        
        # Check which metrics are enabled
        show_speeds = self.speedsCheckbox.isChecked()
        show_error_rates = self.errorRateCheckbox.isChecked()
        
        # Plot ratios and collect lines for cursor tooltips
        ratio_lines = []
        if show_speeds and show_error_rates:
            # Both metrics - use dual y-axis
            ax2 = self.ratiosFigure.add_subplot(111)
            ax3 = ax2.twinx()
            
            # Speed on left axis
            upload_speeds = [s / (1024*1024) for s in self.timeSeriesData['upload_speeds']]  # Convert to MB/s
            download_speeds = [s / (1024*1024) for s in self.timeSeriesData['download_speeds']]  # Convert to MB/s
            
            speed_plot1 = ax2.plot(dates, upload_speeds, label='Upload Speed', color='blue', linewidth=2)
            speed_plot2 = ax2.plot(dates, download_speeds, label='Download Speed', color='green', linewidth=2)
            if speed_plot1:
                ratio_lines.append((speed_plot1[0], 'upload_speeds', 'Upload Speed', 'MB/s'))
            if speed_plot2:
                ratio_lines.append((speed_plot2[0], 'download_speeds', 'Download Speed', 'MB/s'))
            ax2.set_ylabel('Speed (MB/s)', color='black')
            ax2.tick_params(axis='y', labelcolor='black')
            
            # Error rates on right axis
            error_plot1 = ax3.plot(dates, self.timeSeriesData['upload_error_rates'], label='Upload Error Rate', color='red', linewidth=2, linestyle='--')
            error_plot2 = ax3.plot(dates, self.timeSeriesData['download_error_rates'], label='Download Error Rate', color='orange', linewidth=2, linestyle='--')
            if error_plot1:
                ratio_lines.append((error_plot1[0], 'upload_error_rates', 'Upload Error Rate', '%'))
            if error_plot2:
                ratio_lines.append((error_plot2[0], 'download_error_rates', 'Download Error Rate', '%'))
            ax3.set_ylabel('Error Rate (%)', color='black')
            ax3.tick_params(axis='y', labelcolor='black')
            
            # Combine legends
            legend_lines = []
            if speed_plot1:
                legend_lines.append(speed_plot1[0])
            if speed_plot2:
                legend_lines.append(speed_plot2[0])
            if error_plot1:
                legend_lines.append(error_plot1[0])
            if error_plot2:
                legend_lines.append(error_plot2[0])
            
            if legend_lines:
                labels = [l.get_label() for l in legend_lines]
                ax2.legend(legend_lines, labels, loc='upper left')
            
        elif show_speeds:
            # Only speeds - single y-axis
            ax2 = self.ratiosFigure.add_subplot(111)
            
            upload_speeds = [s / (1024*1024) for s in self.timeSeriesData['upload_speeds']]  # Convert to MB/s
            download_speeds = [s / (1024*1024) for s in self.timeSeriesData['download_speeds']]  # Convert to MB/s
            
            plot_result1 = ax2.plot(dates, upload_speeds, label='Upload Speed', color='blue', linewidth=2)
            plot_result2 = ax2.plot(dates, download_speeds, label='Download Speed', color='green', linewidth=2)
            if plot_result1:
                ratio_lines.append((plot_result1[0], 'upload_speeds', 'Upload Speed', 'MB/s'))
            if plot_result2:
                ratio_lines.append((plot_result2[0], 'download_speeds', 'Download Speed', 'MB/s'))
            ax2.set_ylabel('Speed (MB/s)')
            ax2.legend()
            
        elif show_error_rates:
            # Only error rates - single y-axis
            ax2 = self.ratiosFigure.add_subplot(111)
            
            plot_result1 = ax2.plot(dates, self.timeSeriesData['upload_error_rates'], label='Upload Error Rate', color='red', linewidth=2)
            plot_result2 = ax2.plot(dates, self.timeSeriesData['download_error_rates'], label='Download Error Rate', color='orange', linewidth=2)
            if plot_result1:
                ratio_lines.append((plot_result1[0], 'upload_error_rates', 'Upload Error Rate', '%'))
            if plot_result2:
                ratio_lines.append((plot_result2[0], 'download_error_rates', 'Download Error Rate', '%'))
            ax2.set_ylabel('Error Rate (%)')
            ax2.legend()
        
        # Interactive functionality disabled to avoid compatibility issues
        # Charts remain readable with legends and axis labels
        
        if show_speeds or show_error_rates:
            ax2.set_xlabel('Date')
            ax2.set_title('Transfer Ratios Over Time')
            ax2.grid(True, alpha=0.3)
            
            # Format x-axis dates
            if len(dates) > 30:
                ax2.xaxis.set_major_locator(mdates.WeekdayLocator())
                ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            else:
                ax2.xaxis.set_major_locator(mdates.DayLocator())
                ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        
        self.ratiosFigure.autofmt_xdate()
        self.ratiosFigure.tight_layout()
        
        # Refresh canvases
        self.amountsCanvas.draw()
        self.ratiosCanvas.draw()
    
    def format_amounts_tooltip(self, sel, lines):
        """Format tooltip for amounts graph - disabled"""
        pass
    
    def format_ratios_tooltip(self, sel, lines):
        """Format tooltip for ratios graph - disabled"""
        pass
    
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
        top_n = 10  # Fixed value since we removed the spinbox

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
        
        # Get time series data and update graphs
        self.timeSeriesData = get_time_series_data(self.db_paths, days)
        self.updateGraphs()
        
        # Update popularity stats
        self.updatePopularityStats()
        
    def updatePopularityStats(self):
        if not self.db_paths:
            return
            
        # Get current period setting
        period_text = self.periodComboBox.currentText()
        if period_text == "All time":
            days = None
        elif period_text == "Last month":
            days = 30
        elif period_text == "Last year":
            days = 365
        else:
            days = None
            
        top_n = self.topEntriesSpinBox.value()
        
        # Analyze library format first
        format_info = analyze_library_format(self.db_paths)
        
        # Get popularity data
        artist_stats, album_stats = get_popularity_stats(self.db_paths, days)
        
        # Check if we have data and good format compatibility
        if not artist_stats and not album_stats:
            self.showPopularityError("No successful download transfers found.", format_info)
            return
        elif format_info['match_percentage'] < 50:
            self.showPopularityWarning(format_info)
        
        # Update artists table and chart
        self.updateArtistsTable(artist_stats, top_n)
        self.updateArtistsChart(artist_stats, top_n)
        
        # Update albums table and chart
        self.updateAlbumsTable(album_stats, top_n)
        self.updateAlbumsChart(album_stats, top_n)
        
    def updateArtistsTable(self, artist_stats, top_n):
        # Sort by transfer count
        sorted_artists = sorted(artist_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:top_n]
        
        self.artistsTable.setRowCount(len(sorted_artists))
        for i, (artist, stats) in enumerate(sorted_artists):
            self.artistsTable.setItem(i, 0, QTableWidgetItem(artist))
            self.artistsTable.setItem(i, 1, QTableWidgetItem(str(stats['count'])))
            self.artistsTable.setItem(i, 2, QTableWidgetItem(format_size(stats['bytes'])))
            
    def updateArtistsChart(self, artist_stats, top_n):
        self.artistsFigure.clear()
        if not artist_stats:
            self.artistsCanvas.draw()
            return
            
        # Sort by transfer count
        sorted_artists = sorted(artist_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:top_n]
        
        ax = self.artistsFigure.add_subplot(111)
        artists = [item[0] for item in sorted_artists]
        counts = [item[1]['count'] for item in sorted_artists]
        
        # Truncate long artist names for display
        max_name_length = 25
        truncated_artists = []
        for artist in artists:
            if len(artist) > max_name_length:
                truncated_artists.append(artist[:max_name_length-3] + "...")
            else:
                truncated_artists.append(artist)
        
        # Create horizontal bar chart
        bars = ax.barh(range(len(truncated_artists)), counts)
        ax.set_yticks(range(len(truncated_artists)))
        ax.set_yticklabels(truncated_artists, fontsize=8)
        ax.set_xlabel('Downloads')
        ax.set_title(f'Top {len(artists)} Artists by Downloads')
        
        # Add value labels on bars
        for i, (bar, count) in enumerate(zip(bars, counts)):
            ax.text(bar.get_width() + max(counts) * 0.01, bar.get_y() + bar.get_height()/2, 
                   str(count), ha='left', va='center', fontsize=8)
        
        # Expand x-axis to accommodate labels
        ax.set_xlim(0, max(counts) * 1.15)
        
        ax.grid(axis='x', alpha=0.3)
        self.artistsFigure.tight_layout()
        
        # Add custom hover functionality
        self.artistsCanvas.mpl_connect('motion_notify_event', 
            lambda event: self.onArtistHover(event, bars, artists, counts))
        
        self.artistsCanvas.draw()
        
    def updateAlbumsTable(self, album_stats, top_n):
        # Sort by transfer count
        sorted_albums = sorted(album_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:top_n]
        
        self.albumsTable.setRowCount(len(sorted_albums))
        for i, (album_key, stats) in enumerate(sorted_albums):
            artist, album = album_key
            self.albumsTable.setItem(i, 0, QTableWidgetItem(artist))
            self.albumsTable.setItem(i, 1, QTableWidgetItem(album))
            self.albumsTable.setItem(i, 2, QTableWidgetItem(str(stats['count'])))
            self.albumsTable.setItem(i, 3, QTableWidgetItem(format_size(stats['bytes'])))
            
    def updateAlbumsChart(self, album_stats, top_n):
        self.albumsFigure.clear()
        if not album_stats:
            self.albumsCanvas.draw()
            return
            
        # Sort by transfer count
        sorted_albums = sorted(album_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:top_n]
        
        ax = self.albumsFigure.add_subplot(111)
        album_labels = [item[0][1] for item in sorted_albums]  # Just album name, not artist
        counts = [item[1]['count'] for item in sorted_albums]
        
        # Truncate long album labels for display
        max_label_length = 30
        truncated_labels = []
        for label in album_labels:
            if len(label) > max_label_length:
                truncated_labels.append(label[:max_label_length-3] + "...")
            else:
                truncated_labels.append(label)
        
        # Create horizontal bar chart
        bars = ax.barh(range(len(truncated_labels)), counts)
        ax.set_yticks(range(len(truncated_labels)))
        ax.set_yticklabels(truncated_labels, fontsize=7)
        ax.set_xlabel('Downloads')
        ax.set_title(f'Top {len(album_labels)} Albums by Downloads')
        
        # Add value labels on bars
        for i, (bar, count) in enumerate(zip(bars, counts)):
            ax.text(bar.get_width() + max(counts) * 0.01, bar.get_y() + bar.get_height()/2, 
                   str(count), ha='left', va='center', fontsize=7)
        
        # Expand x-axis to accommodate labels
        ax.set_xlim(0, max(counts) * 1.15)
        
        ax.grid(axis='x', alpha=0.3)
        try:
            self.albumsFigure.tight_layout()
        except:
            pass  # Ignore tight_layout warnings for long album names
        
        # Add custom hover functionality (pass full artist-album info for tooltips)
        full_album_labels = [f"{item[0][0]} - {item[0][1]}" for item in sorted_albums]
        self.albumsCanvas.mpl_connect('motion_notify_event', 
            lambda event: self.onAlbumHover(event, bars, full_album_labels, counts))
        
        self.albumsCanvas.draw()
        
    def onArtistHover(self, event, bars, artists, counts):
        """Handle hover events on artist chart bars"""
        if event.inaxes is None:
            self.artistsCanvas.setToolTip("")
            return
            
        for i, bar in enumerate(bars):
            if bar.contains(event)[0]:
                # Show tooltip with full artist name and count
                tooltip_text = f"{artists[i]}\n{counts[i]} downloads"
                self.artistsCanvas.setToolTip(tooltip_text)
                return
        
        # Clear tooltip when not hovering over a bar
        self.artistsCanvas.setToolTip("")
        
    def onAlbumHover(self, event, bars, album_labels, counts):
        """Handle hover events on album chart bars"""
        if event.inaxes is None:
            self.albumsCanvas.setToolTip("")
            return
            
        for i, bar in enumerate(bars):
            if bar.contains(event)[0]:
                # Show tooltip with full album name and count
                tooltip_text = f"{album_labels[i]}\n{counts[i]} downloads"
                self.albumsCanvas.setToolTip(tooltip_text)
                return
        
        # Clear tooltip when not hovering over a bar
        self.albumsCanvas.setToolTip("")
        
    def showPopularityError(self, message, format_info):
        """Show error message and clear popularity displays"""
        # Clear tables and charts
        self.artistsTable.setRowCount(0)
        self.albumsTable.setRowCount(0)
        
        self.artistsFigure.clear()
        self.albumsFigure.clear()
        
        # Show explanatory text in charts
        self.showPopularityExplanation(self.artistsFigure, self.artistsCanvas, message, format_info)
        self.showPopularityExplanation(self.albumsFigure, self.albumsCanvas, message, format_info)
        
    def showPopularityWarning(self, format_info):
        """Show warning about library format compatibility"""
        warning_msg = f"Library format compatibility: {format_info['match_percentage']:.1f}%"
        print(f"Warning: {warning_msg}")  # Console warning
        
    def showPopularityExplanation(self, figure, canvas, message, format_info):
        """Show explanation text in the chart area"""
        ax = figure.add_subplot(111)
        ax.axis('off')
        
        explanation_text = f"""Popularity Stats Requirements:

{message}

How it works:
• Analyzes successful download transfers (what users want)
• Smart left-to-right path parsing
• Detects media folders (/music/, \\Artists\\, etc.)
• Removes artist name prefixes from album titles

Library Analysis:
• Total files analyzed: {format_info['total_files']}
• Compatible files: {format_info['matching_files']} ({format_info['match_percentage']:.1f}%)

Parsing Examples:"""
        
        if format_info.get('format_examples'):
            explanation_text += "\n\n" + "\n".join(
                f"• {ex['artist']} → {ex['album']}" 
                for ex in format_info['format_examples'][:5]
            )
        
        if format_info['match_percentage'] < 50:
            explanation_text += f"""

⚠️  Low compatibility detected ({format_info['match_percentage']:.1f}%)
The smart parser couldn't extract artist/album info from most files.
Check if your files are in media folders like /music/ or /audiobooks/"""
            
        ax.text(0.05, 0.95, explanation_text, transform=ax.transAxes, 
                fontsize=9, verticalalignment='top', fontfamily='monospace',
                bbox=dict(boxstyle="round,pad=0.5", facecolor="lightgray", alpha=0.8))
        
        canvas.draw()

def analyze_library_format(db_paths):
    """Analyze the library format using smart left-to-right parsing"""
    total_files = 0
    matching_files = 0
    sample_paths = []
    format_examples = []
    
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Detect database format
            db_format = check_database_format(db_path)
            
            if db_format == 'new':
                success_condition = "StateDescription='Completed, Succeeded'"
            else:
                success_condition = "State LIKE 'Completed, Succeeded'"
            
            # Get a sample of successful upload filenames
            cursor.execute(f"""
                SELECT Filename 
                FROM Transfers 
                WHERE {success_condition} AND Direction = 'Download' AND Filename IS NOT NULL
                LIMIT 200
            """)
            
            rows = cursor.fetchall()
            for (filename,) in rows:
                total_files += 1
                sample_paths.append(filename)
                
                # Use smart parsing to extract artist/album
                artist, album = parse_media_path(filename)
                if artist and album:
                    matching_files += 1
                    # Keep some examples for display
                    if len(format_examples) < 10:
                        format_examples.append({
                            'path': filename,
                            'artist': artist,
                            'album': album
                        })
            
            conn.close()
            
        except sqlite3.Error:
            continue
    
    match_percentage = (matching_files / total_files * 100) if total_files > 0 else 0
    return {
        'total_files': total_files,
        'matching_files': matching_files,
        'match_percentage': match_percentage,
        'sample_paths': sample_paths[:10],
        'format_examples': format_examples
    }

def parse_media_path(filepath):
    """Smart left-to-right analysis of media file paths to extract artist and album"""
    if not filepath:
        return None, None
    
    # Normalize path separators (handle both single and double backslashes)
    normalized_path = filepath.replace('\\\\', '/').replace('\\', '/')
    lower_path = normalized_path.lower()
    
    # Find potential media indicators (case insensitive)
    media_indicators = [
        '/music/', '/audiobooks/', '/audio/', '/media/',
        '/artists/', '/musica/', '/jazz/', '/rock/', '/electronic/',
        'music/', 'artists/', 'musica/', 'jazz/', 'albums/'
    ]
    
    path_parts = []
    
    # Try to find a media root
    media_start_idx = -1
    for indicator in media_indicators:
        idx = lower_path.find(indicator)
        if idx >= 0:
            media_start_idx = idx + len(indicator)
            break
    
    if media_start_idx >= 0:
        # Extract from media root
        media_path = normalized_path[media_start_idx:]
        path_parts = [part for part in media_path.split('/') if part]
    else:
        # No clear media indicator - use heuristic approach
        # Look for Artist/Album pattern in the path structure
        all_parts = [part for part in normalized_path.split('/') if part]
        
        # Filter out common system/user prefixes
        filtered_parts = []
        skip_patterns = ['@@', '!', '#', 'my files', 'downloads', 'shared', 'soulseek', 'main']
        
        for part in all_parts:
            part_lower = part.lower()
            should_skip = False
            for pattern in skip_patterns:
                if part_lower.startswith(pattern):
                    should_skip = True
                    break
            # Also skip parts that look like disk/volume identifiers
            if len(part) <= 2 or part.isdigit() or (len(part) < 8 and any(c in part for c in '-_0123456789')):
                should_skip = True
            if not should_skip:
                filtered_parts.append(part)
        
        # Take meaningful parts (likely Artist/Album/File or Genre/Artist/Album/File)
        if len(filtered_parts) >= 3:
            # Assume last 3 are Genre/Artist/Album or Artist/Album/File
            # If last part looks like a file, take the two before it
            if '.' in filtered_parts[-1]:
                path_parts = filtered_parts[-3:-1]  # Artist and Album
            else:
                path_parts = filtered_parts[-2:]    # Artist and Album
        elif len(filtered_parts) >= 2:
            path_parts = filtered_parts[-2:]        # Assume Artist/Album
    
    # Need at least 2 parts: Artist/Album
    if len(path_parts) < 2:
        return None, None
    
    artist = path_parts[0]
    raw_album = path_parts[1]
    
    # Smart album cleaning
    cleaned_album = clean_album_name(artist, raw_album)
    
    return artist, cleaned_album

def clean_album_name(artist, album):
    """Enhanced album name cleaning with common prefix removal"""
    if not artist or not album:
        return album
    
    artist_lower = artist.lower().strip()
    album_lower = album.lower().strip()
    
    # Enhanced patterns to clean (more comprehensive)
    separators = [' - ', ' – ', ' — ', ': ', ' : ', '_ ', ' _ ', ' | ', ' / ']
    
    cleaned_album = album
    for sep in separators:
        pattern = f"{artist_lower}{sep}"
        if album_lower.startswith(pattern):
            cleaned_album = album[len(pattern):]
            break
    
    # Additional cleanup patterns
    if cleaned_album == album:  # No separator match, try other patterns
        # Pattern: "ArtistName AlbumTitle" (space separated)
        if album_lower.startswith(artist_lower + ' ') and len(album) > len(artist) + 1:
            potential_clean = album[len(artist) + 1:]
            # Only use if the remaining part looks like an album title
            if len(potential_clean) > 3 and not potential_clean[0].islower():
                cleaned_album = potential_clean
    
    # Final cleaning: remove extra whitespace and punctuation
    cleaned_album = cleaned_album.strip(' -–—_:|/')
    
    # Validation: don't return empty or too-short results
    if not cleaned_album or len(cleaned_album) < 2:
        return album
    
    # Don't clean if it removes more than 70% of the original
    if len(cleaned_album) < len(album) * 0.3:
        return album
    
    return cleaned_album

def get_popularity_stats(db_paths, days=None):
    """Get artist and album popularity statistics from successful transfers"""
    artist_stats = defaultdict(lambda: {'count': 0, 'bytes': 0})
    album_stats = defaultdict(lambda: {'count': 0, 'bytes': 0})
    
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Detect database format
            db_format = check_database_format(db_path)
            
            if db_format == 'new':
                success_condition = "StateDescription='Completed, Succeeded'"
            else:
                success_condition = "State LIKE 'Completed, Succeeded'"
            
            # Create WHERE clause for time filtering
            where_clause = f"WHERE {success_condition} AND Direction = 'Download'"  # Track what users download
            params = []
    
            if days is not None:
                where_clause += " AND RequestedAt >= ?"
                cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
                params.append(cutoff_date)
            
            query = f"""
                SELECT Filename, Size 
                FROM Transfers 
                {where_clause}
            """
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            for filename, size in rows:
                # Use smart left-to-right parsing to extract artist and album
                artist, album = parse_media_path(filename)
                if artist and album:
                    # Update artist stats
                    artist_stats[artist]['count'] += 1
                    artist_stats[artist]['bytes'] += size
                    
                    # Update album stats
                    album_key = (artist, album)
                    album_stats[album_key]['count'] += 1
                    album_stats[album_key]['bytes'] += size
            
            conn.close()
            
        except sqlite3.Error as e:
            print(f"Database error for {db_path}: {e}")
            continue
    
    return dict(artist_stats), dict(album_stats)

def main():
    # Launch GUI application
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()