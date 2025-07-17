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
import mplcursors

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
        self.createTabs()
        
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
        
    def createTabs(self):
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Create summary stats tab
        self.createSummaryTab()
        
        # Create visual stats tab
        self.createVisualTab()
        
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

        self.summaryLayout.addLayout(summarySection)

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

        self.summaryLayout.addLayout(usersSection)

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
        self.amountsFigure = Figure(figsize=(12, 4))
        self.amountsCanvas = FigureCanvas(self.amountsFigure)
        
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
        self.ratiosFigure = Figure(figsize=(12, 4))
        self.ratiosCanvas = FigureCanvas(self.ratiosFigure)
        
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
        
        # Add interactive cursors to amounts graph
        if lines:
            cursor = mplcursors.cursor([line[0] for line in lines], hover=True)
            cursor.connect('add', lambda sel: self.format_amounts_tooltip(sel, lines))
        
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
        
        # Add interactive cursors to ratios graph
        if ratio_lines:
            cursor = mplcursors.cursor([line[0] for line in ratio_lines], hover=True)
            cursor.connect('add', lambda sel: self.format_ratios_tooltip(sel, ratio_lines))
        
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
        """Format tooltip for amounts graph"""
        try:
            # Get the index from the selection - mplcursors uses different ways to access index
            if hasattr(sel.target, 'index'):
                index = int(sel.target.index)
            elif hasattr(sel, 'index'):
                index = int(sel.index)
            else:
                # Try to get index from the target coordinates
                target_x = sel.target[0]
                # Find closest date
                dates = [mdates.date2num(d) for d in self.timeSeriesData['dates']]
                index = min(range(len(dates)), key=lambda i: abs(dates[i] - target_x))
            
            if index >= len(self.timeSeriesData['dates']):
                sel.annotation.set_text('Index out of range')
                return
            
            date = self.timeSeriesData['dates'][index]
            
            # Find which line was selected
            line_obj = sel.artist
            for line, data_key, label in lines:
                if line == line_obj:
                    if data_key == 'total_errors':
                        # Special case for total errors (calculated)
                        upload_errors = self.timeSeriesData['upload_errors'][index]
                        download_errors = self.timeSeriesData['download_errors'][index]
                        total_errors = upload_errors + download_errors
                        value = total_errors
                    else:
                        value = self.timeSeriesData[data_key][index]
                    
                    # Format the tooltip
                    date_str = date.strftime('%Y-%m-%d')
                    sel.annotation.set_text(f'{label}\nDate: {date_str}\nValue: {value:,}')
                    return
            
            # If we couldn't find the line, show basic info
            sel.annotation.set_text(f'Date: {date.strftime("%Y-%m-%d")}')
            
        except (AttributeError, IndexError, ValueError, TypeError) as e:
            # More detailed error info for debugging
            sel.annotation.set_text(f'Error: {str(e)[:50]}')
    
    def format_ratios_tooltip(self, sel, lines):
        """Format tooltip for ratios graph"""
        try:
            # Get the index from the selection - mplcursors uses different ways to access index
            if hasattr(sel.target, 'index'):
                index = int(sel.target.index)
            elif hasattr(sel, 'index'):
                index = int(sel.index)
            else:
                # Try to get index from the target coordinates
                target_x = sel.target[0]
                # Find closest date
                dates = [mdates.date2num(d) for d in self.timeSeriesData['dates']]
                index = min(range(len(dates)), key=lambda i: abs(dates[i] - target_x))
            
            if index >= len(self.timeSeriesData['dates']):
                sel.annotation.set_text('Index out of range')
                return
            
            date = self.timeSeriesData['dates'][index]
            
            # Find which line was selected
            line_obj = sel.artist
            for line, data_key, label, unit in lines:
                if line == line_obj:
                    if 'speeds' in data_key:
                        # Convert from bytes/s to MB/s for display
                        value = self.timeSeriesData[data_key][index] / (1024*1024)
                        value_str = f'{value:.2f} {unit}'
                    else:
                        # Error rates
                        value = self.timeSeriesData[data_key][index]
                        value_str = f'{value:.2f}{unit}'
                    
                    # Format the tooltip
                    date_str = date.strftime('%Y-%m-%d')
                    sel.annotation.set_text(f'{label}\nDate: {date_str}\nValue: {value_str}')
                    return
            
            # If we couldn't find the line, show basic info
            sel.annotation.set_text(f'Date: {date.strftime("%Y-%m-%d")}')
            
        except (AttributeError, IndexError, ValueError, TypeError) as e:
            # More detailed error info for debugging
            sel.annotation.set_text(f'Error: {str(e)[:50]}')
    
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
        
        # Get time series data and update graphs
        self.timeSeriesData = get_time_series_data(self.db_paths, days)
        self.updateGraphs()

def main():
    # Launch GUI application
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()