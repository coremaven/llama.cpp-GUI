#!/usr/bin/env python3
"""
llama.cpp Server GUI
A graphical interface for managing llama.cpp server instances
"""

import sys
import os
import json
import subprocess
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QTextEdit,
    QFileDialog,
    QGroupBox,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QIcon, QAction


class ServerOutputReader(QThread):
    """Thread to read server output without blocking the GUI"""

    output_received = pyqtSignal(str)

    def __init__(self, process):
        super().__init__()
        self.process = process
        self.running = True

    def run(self):
        """Read output from the process"""
        import select

        while self.running:
            if self.process.poll() is not None:
                # Process has terminated, read any remaining output
                self.read_remaining_output()
                break

            # Use select to check if there's data available (non-blocking)
            try:
                readable, _, _ = select.select(
                    [self.process.stdout, self.process.stderr], [], [], 0.1
                )

                if self.process.stdout in readable:
                    output = self.process.stdout.readline()
                    if output:
                        self.output_received.emit(output.strip())

                if self.process.stderr in readable:
                    error = self.process.stderr.readline()
                    if error:
                        # Don't prefix with [ERROR] - llama.cpp uses stderr for normal logging
                        self.output_received.emit(error.strip())
            except (ValueError, OSError):
                # File descriptor closed
                break

    def read_remaining_output(self):
        """Read any remaining output after process termination"""
        try:
            # Read remaining stdout
            for line in self.process.stdout:
                if line:
                    self.output_received.emit(line.strip())

            # Read remaining stderr
            for line in self.process.stderr:
                if line:
                    # Don't prefix with [ERROR] - llama.cpp uses stderr for normal logging
                    self.output_received.emit(line.strip())
        except (ValueError, OSError):
            pass

    def stop(self):
        """Stop reading output"""
        self.running = False


class LlamaServerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config_file = Path.home() / ".llama_server_gui_config.json"
        self.server_process = None
        self.output_reader = None
        self.config = self.load_config()
        self.health_check_timer = None

        self.init_ui()
        self.load_last_profile()

        # Auto-start if enabled
        if self.auto_start_checkbox.isChecked():
            QTimer.singleShot(500, self.start_server)

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("llama.cpp Server Manager")
        self.setMinimumSize(900, 700)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Profile management
        profile_group = self.create_profile_section()
        main_layout.addWidget(profile_group)

        # Section 1: Server binary selection
        binary_group = self.create_binary_section()
        main_layout.addWidget(binary_group)

        # Section 2: Model selection
        model_group = self.create_model_section()
        main_layout.addWidget(model_group)

        # Section 3: Server options
        options_group = self.create_options_section()
        main_layout.addWidget(options_group)

        # Control buttons
        control_layout = self.create_control_buttons()
        main_layout.addLayout(control_layout)

        # Log viewer
        log_group = self.create_log_section()
        main_layout.addWidget(log_group)

        # System tray
        self.create_system_tray()

        self.update_button_states()

    def create_profile_section(self):
        """Create profile management section"""
        group = QGroupBox("Profile Management")
        layout = QHBoxLayout()

        layout.addWidget(QLabel("Profile:"))

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.currentTextChanged.connect(self.on_profile_selected)
        layout.addWidget(self.profile_combo)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self.load_selected_profile)
        load_btn.setMaximumWidth(60)
        layout.addWidget(load_btn)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_current_profile)
        save_btn.setMaximumWidth(60)
        layout.addWidget(save_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self.delete_profile)
        delete_btn.setMaximumWidth(80)
        layout.addWidget(delete_btn)

        layout.addStretch()

        self.auto_start_checkbox = QCheckBox("Auto-start on launch")
        layout.addWidget(self.auto_start_checkbox)

        group.setLayout(layout)
        self.update_profile_list()
        return group

    def create_binary_section(self):
        """Create server binary selection section"""
        group = QGroupBox("1. Server Binary")
        layout = QHBoxLayout()

        self.binary_path_edit = QLineEdit()
        self.binary_path_edit.setPlaceholderText(
            "Path to llama.cpp server binary (e.g., llama-server)"
        )
        layout.addWidget(self.binary_path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_binary)
        layout.addWidget(browse_btn)

        group.setLayout(layout)
        return group

    def create_model_section(self):
        """Create model selection section"""
        group = QGroupBox("2. Model Selection")
        layout = QHBoxLayout()

        self.model_path_edit = QLineEdit()
        self.model_path_edit.setPlaceholderText("Path to model file (e.g., model.gguf)")
        layout.addWidget(self.model_path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_model)
        layout.addWidget(browse_btn)

        group.setLayout(layout)
        return group

    def create_options_section(self):
        """Create server options section"""
        group = QGroupBox("3. Server Options")
        layout = QVBoxLayout()

        # Row 1: Host and Port
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Host:"))
        self.host_edit = QLineEdit("127.0.0.1")
        self.host_edit.setMaximumWidth(150)
        row1.addWidget(self.host_edit)

        row1.addWidget(QLabel("Port:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8080)
        self.port_spin.setMaximumWidth(100)
        row1.addWidget(self.port_spin)

        row1.addStretch()
        layout.addLayout(row1)

        # Row 2: Context length and GPU layers
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Context Length:"))
        self.context_spin = QSpinBox()
        self.context_spin.setRange(128, 1048576)
        self.context_spin.setValue(2048)
        self.context_spin.setSingleStep(512)
        self.context_spin.setMaximumWidth(100)
        row2.addWidget(self.context_spin)

        row2.addWidget(QLabel("GPU Layers (ngl):"))
        self.ngl_spin = QSpinBox()
        self.ngl_spin.setRange(-1, 999)
        self.ngl_spin.setValue(33)
        self.ngl_spin.setMaximumWidth(100)
        row2.addWidget(self.ngl_spin)

        row2.addStretch()
        layout.addLayout(row2)

        # Row 3: Threads and batch size
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Threads:"))
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 256)
        self.threads_spin.setValue(8)
        self.threads_spin.setMaximumWidth(100)
        row3.addWidget(self.threads_spin)

        row3.addWidget(QLabel("Batch Size:"))
        self.batch_spin = QSpinBox()
        self.batch_spin.setRange(1, 2048)
        self.batch_spin.setValue(512)
        self.batch_spin.setMaximumWidth(100)
        row3.addWidget(self.batch_spin)

        row3.addStretch()
        layout.addLayout(row3)

        # Row 4: Additional options
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Additional Arguments:"))
        self.additional_args_edit = QLineEdit()
        self.additional_args_edit.setPlaceholderText("e.g., --numa --mlock")
        row4.addWidget(self.additional_args_edit)
        layout.addLayout(row4)

        group.setLayout(layout)
        return group

    def create_control_buttons(self):
        """Create start/stop control buttons"""
        layout = QHBoxLayout()

        self.start_btn = QPushButton("Start Server")
        self.start_btn.clicked.connect(self.start_server)
        self.start_btn.setMinimumHeight(40)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Server")
        self.stop_btn.clicked.connect(self.stop_server)
        self.stop_btn.setMinimumHeight(40)
        layout.addWidget(self.stop_btn)

        return layout

    def create_log_section(self):
        """Create log viewer section"""
        group = QGroupBox("Server Logs")
        layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(200)
        layout.addWidget(self.log_text)

        clear_btn = QPushButton("Clear Logs")
        clear_btn.clicked.connect(self.log_text.clear)
        layout.addWidget(clear_btn)

        group.setLayout(layout)
        return group

    def create_system_tray(self):
        """Create system tray icon"""
        self.tray_icon = QSystemTrayIcon(self)

        # Try to use a default icon, fallback if not available
        icon = QApplication.style().standardIcon(
            QApplication.style().StandardPixmap.SP_ComputerIcon
        )
        self.tray_icon.setIcon(icon)

        # Tray menu
        tray_menu = QMenu()

        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        start_action = QAction("Start Server", self)
        start_action.triggered.connect(self.start_server)
        tray_menu.addAction(start_action)

        stop_action = QAction("Stop Server", self)
        stop_action.triggered.connect(self.stop_server)
        tray_menu.addAction(stop_action)

        tray_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    def tray_icon_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()

    def browse_binary(self):
        """Browse for server binary"""
        # Use last binary folder if available, otherwise home directory
        last_dir = self.config.get("last_binary_dir", str(Path.home()))

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select llama.cpp Server Binary",
            last_dir,
            "Executable Files (*);;All Files (*)",
        )

        if file_path:
            self.binary_path_edit.setText(file_path)
            # Save the directory for next time
            self.config["last_binary_dir"] = str(Path(file_path).parent)
            self.save_config()

    def browse_model(self):
        """Browse for model file"""
        # Use last model folder if available, otherwise home directory
        last_dir = self.config.get("last_model_dir", str(Path.home()))

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Model File", last_dir, "GGUF Files (*.gguf);;All Files (*)"
        )

        if file_path:
            self.model_path_edit.setText(file_path)
            # Save the directory for next time
            self.config["last_model_dir"] = str(Path(file_path).parent)
            self.save_config()

    def start_server(self):
        """Start the llama.cpp server"""
        binary_path = self.binary_path_edit.text().strip()
        model_path = self.model_path_edit.text().strip()

        if not binary_path:
            QMessageBox.warning(self, "Error", "Please select a server binary")
            return

        if not os.path.exists(binary_path):
            QMessageBox.warning(
                self, "Error", f"Server binary not found: {binary_path}"
            )
            return

        if not model_path:
            QMessageBox.warning(self, "Error", "Please select a model file")
            return

        if not os.path.exists(model_path):
            QMessageBox.warning(self, "Error", f"Model file not found: {model_path}")
            return

        if self.server_process is not None and self.server_process.poll() is None:
            QMessageBox.warning(self, "Error", "Server is already running")
            return

        # Build command
        cmd = [
            binary_path,
            "-m",
            model_path,
            "--host",
            self.host_edit.text(),
            "--port",
            str(self.port_spin.value()),
            "-c",
            str(self.context_spin.value()),
            "-ngl",
            str(self.ngl_spin.value()),
            "-t",
            str(self.threads_spin.value()),
            "-b",
            str(self.batch_spin.value()),
        ]

        # Add additional arguments
        additional_args = self.additional_args_edit.text().strip()
        if additional_args:
            cmd.extend(additional_args.split())

        self.log_text.append(f"Starting server with command:\n{' '.join(cmd)}\n")

        try:
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            # Start output reader thread
            self.output_reader = ServerOutputReader(self.server_process)
            self.output_reader.output_received.connect(self.append_log)
            self.output_reader.start()

            self.log_text.append("Server process launched, checking health...\n")
            self.update_button_states()

            # Start health monitoring - check if server crashes shortly after startup
            self.health_check_timer = QTimer()
            self.health_check_timer.timeout.connect(self.check_server_health)
            self.health_check_attempts = 0
            self.health_check_timer.start(500)  # Check every 500ms

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start server:\n{str(e)}")
            self.log_text.append(f"Error starting server: {str(e)}\n")
            self.server_process = None
            self.update_button_states()

    def stop_server(self):
        """Stop the llama.cpp server"""
        if not self.server_process or self.server_process.poll() is not None:
            QMessageBox.warning(self, "Error", "Server is not running")
            self.update_button_states()  # Fix button states if they're out of sync
            return

        self.log_text.append("Stopping server...\n")

        # Stop health check timer if running
        if self.health_check_timer:
            self.health_check_timer.stop()

        # Disable stop button while stopping
        self.stop_btn.setEnabled(False)

        # Stop the output reader thread
        if self.output_reader:
            self.output_reader.stop()

        # Terminate the process
        self.server_process.terminate()

        # Use a timer to check if process has stopped (non-blocking)
        self.stop_timer = QTimer()
        self.stop_timer.timeout.connect(self.check_server_stopped)
        self.stop_attempts = 0
        self.stop_timer.start(200)  # Check every 200ms

    def check_server_stopped(self):
        """Check if server has stopped (called by timer)"""
        if self.server_process.poll() is not None:
            # Process has terminated
            self.stop_timer.stop()
            self.cleanup_after_stop("Server stopped successfully!\n")
        else:
            self.stop_attempts += 1
            if self.stop_attempts >= 25:  # 25 * 200ms = 5 seconds
                # Force kill after 5 seconds
                self.log_text.append("Server not responding, forcing kill...\n")
                self.server_process.kill()
                self.stop_timer.stop()
                # Wait a bit more for kill to take effect
                QTimer.singleShot(
                    500, lambda: self.cleanup_after_stop("Server killed (forced)\n")
                )

    def cleanup_after_stop(self, message):
        """Clean up after server has stopped"""
        self.log_text.append(message)

        # Wait for output reader thread to finish
        if self.output_reader:
            self.output_reader.wait(1000)  # Wait max 1 second
            self.output_reader = None

        self.server_process = None
        self.update_button_states()
        self.tray_icon.showMessage(
            "llama.cpp Server",
            "Server stopped",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def check_server_health(self):
        """Monitor server health after startup"""
        if not self.server_process:
            # Server was manually stopped
            if self.health_check_timer:
                self.health_check_timer.stop()
            return

        poll_result = self.server_process.poll()

        if poll_result is not None:
            # Process has terminated (crashed)
            if self.health_check_timer:
                self.health_check_timer.stop()

            # Get exit code
            exit_code = poll_result

            self.log_text.append(
                f"\n[ERROR] Server process terminated unexpectedly with exit code {exit_code}\n"
            )

            # Stop output reader
            if self.output_reader:
                self.output_reader.stop()
                self.output_reader.wait(1000)
                self.output_reader = None

            self.server_process = None
            self.update_button_states()

            # Show error dialog
            QMessageBox.critical(
                self,
                "Server Failed",
                f"The llama-server process crashed with exit code {exit_code}.\n\n"
                "This usually means:\n"
                "- Invalid model file or format\n"
                "- Insufficient memory (GPU or RAM)\n"
                "- Wrong parameters (e.g., too many GPU layers)\n"
                "- Binary/model compatibility issue\n\n"
                "Check the logs below for details.",
            )

            self.tray_icon.showMessage(
                "llama.cpp Server",
                "Server crashed - check logs",
                QSystemTrayIcon.MessageIcon.Critical,
                3000,
            )
        else:
            # Server is still running
            self.health_check_attempts += 1

            # Stop checking after 6 attempts (3 seconds) - server is stable
            if self.health_check_attempts >= 6:
                self.health_check_timer.stop()
                self.log_text.append("Server is running and healthy\n")
                self.tray_icon.showMessage(
                    "llama.cpp Server",
                    "Server started successfully",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )

    def append_log(self, text):
        """Append text to log viewer"""
        self.log_text.append(text)
        # Auto-scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_button_states(self):
        """Update button enabled/disabled states"""
        is_running = (
            self.server_process is not None and self.server_process.poll() is None
        )
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)

    def get_current_settings(self):
        """Get current settings as dictionary"""
        return {
            "binary_path": self.binary_path_edit.text(),
            "model_path": self.model_path_edit.text(),
            "host": self.host_edit.text(),
            "port": self.port_spin.value(),
            "context": self.context_spin.value(),
            "ngl": self.ngl_spin.value(),
            "threads": self.threads_spin.value(),
            "batch": self.batch_spin.value(),
            "additional_args": self.additional_args_edit.text(),
            "auto_start": self.auto_start_checkbox.isChecked(),
        }

    def apply_settings(self, settings):
        """Apply settings to UI"""
        self.log_text.append("Applying settings to UI fields...\n")

        self.binary_path_edit.setText(settings.get("binary_path", ""))
        self.model_path_edit.setText(settings.get("model_path", ""))
        self.host_edit.setText(settings.get("host", "127.0.0.1"))
        self.port_spin.setValue(settings.get("port", 8080))
        self.context_spin.setValue(settings.get("context", 2048))
        self.ngl_spin.setValue(settings.get("ngl", 33))
        self.threads_spin.setValue(settings.get("threads", 8))
        self.batch_spin.setValue(settings.get("batch", 512))
        self.additional_args_edit.setText(settings.get("additional_args", ""))
        self.auto_start_checkbox.setChecked(settings.get("auto_start", False))

        self.log_text.append("Settings applied to UI\n")

    def save_current_profile(self):
        """Save current settings as a profile"""
        from PyQt6.QtWidgets import QInputDialog

        current_name = self.profile_combo.currentText()
        profile_name, ok = QInputDialog.getText(
            self,
            "Save Profile",
            "Profile name:",
            text=current_name if current_name else "",
        )

        if ok and profile_name:
            # Get current settings from UI
            settings = self.get_current_settings()

            # Debug: log what we're saving
            self.log_text.append(f"Saving profile '{profile_name}' with settings:\n")
            self.log_text.append(f"  Binary: {settings['binary_path']}\n")
            self.log_text.append(f"  Model: {settings['model_path']}\n")
            self.log_text.append(
                f"  Port: {settings['port']}, Context: {settings['context']}, NGL: {settings['ngl']}\n"
            )

            # Save to config
            self.config["profiles"][profile_name] = settings
            self.config["last_profile"] = profile_name
            self.save_config()

            # Update profile list and select the saved profile
            self.update_profile_list()

            # Temporarily block signals, set the text, then unblock and manually trigger load
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentText(profile_name)
            self.profile_combo.blockSignals(False)

            # Show confirmation
            self.log_text.append(f"Profile '{profile_name}' saved successfully\n")

    def on_profile_selected(self, profile_name):
        """Called when profile selection changes in dropdown (auto-load)"""
        if profile_name and profile_name in self.config["profiles"]:
            self.log_text.append(f"Auto-loading profile '{profile_name}'...\n")
            self.load_profile(profile_name)
        else:
            # Empty selection or invalid profile
            pass

    def load_selected_profile(self):
        """Load the currently selected profile (manual load via button)"""
        profile_name = self.profile_combo.currentText()
        if not profile_name:
            QMessageBox.warning(
                self, "No Profile Selected", "Please select a profile to load"
            )
            return

        if profile_name not in self.config["profiles"]:
            QMessageBox.warning(
                self, "Profile Not Found", f"Profile '{profile_name}' not found"
            )
            return

        self.log_text.append(f"Manually loading profile '{profile_name}'...\n")
        self.load_profile(profile_name)

    def load_profile(self, profile_name):
        """Load a profile"""
        if profile_name and profile_name in self.config["profiles"]:
            settings = self.config["profiles"][profile_name]

            # Debug: log what we're loading
            self.log_text.append(f"Loading profile '{profile_name}' with settings:\n")
            self.log_text.append(f"  Binary: {settings.get('binary_path', 'N/A')}\n")
            self.log_text.append(f"  Model: {settings.get('model_path', 'N/A')}\n")
            self.log_text.append(
                f"  Port: {settings.get('port', 'N/A')}, Context: {settings.get('context', 'N/A')}, NGL: {settings.get('ngl', 'N/A')}\n"
            )

            self.apply_settings(settings)
            self.config["last_profile"] = profile_name
            self.save_config()
            self.log_text.append(f"Profile '{profile_name}' loaded successfully\n")

    def load_last_profile(self):
        """Load the last used profile"""
        last_profile = self.config.get("last_profile")
        if last_profile and last_profile in self.config["profiles"]:
            self.profile_combo.setCurrentText(last_profile)

    def delete_profile(self):
        """Delete the current profile"""
        profile_name = self.profile_combo.currentText()
        if not profile_name:
            return

        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Are you sure you want to delete profile '{profile_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            del self.config["profiles"][profile_name]
            if self.config.get("last_profile") == profile_name:
                self.config["last_profile"] = None
            self.save_config()
            self.update_profile_list()

    def update_profile_list(self):
        """Update the profile combo box"""
        current = self.profile_combo.currentText()

        # Block signals to prevent triggering load_profile during update
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(sorted(self.config["profiles"].keys()))
        if current in self.config["profiles"]:
            self.profile_combo.setCurrentText(current)
        self.profile_combo.blockSignals(False)

    def load_config(self):
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")

        return {"profiles": {}, "last_profile": None}

    def save_config(self):
        """Save configuration to file"""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=2)
            # Debug: log what we saved
            if hasattr(self, "log_text"):
                profile_count = len(self.config.get("profiles", {}))
                self.log_text.append(f"Config saved: {profile_count} profile(s)\n")
        except Exception as e:
            print(f"Error saving config: {e}")
            if hasattr(self, "log_text"):
                self.log_text.append(f"Error saving config: {e}\n")

    def closeEvent(self, event):
        """Handle window close event"""
        if self.server_process is not None and self.server_process.poll() is None:
            reply = QMessageBox.question(
                self,
                "Server Running",
                "The server is still running. Do you want to:\n\n"
                "Yes - Minimize to tray\n"
                "No - Stop server and quit\n"
                "Cancel - Do nothing",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )

            if reply == QMessageBox.StandardButton.Yes:
                event.ignore()
                self.hide()
            elif reply == QMessageBox.StandardButton.No:
                # Force kill when closing (no need to wait gracefully)
                if self.output_reader:
                    self.output_reader.stop()
                self.server_process.kill()
                if self.output_reader:
                    self.output_reader.wait(1000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def quit_application(self):
        """Quit the application"""
        if self.server_process is not None and self.server_process.poll() is None:
            # Force kill when quitting (no need to wait gracefully)
            if self.output_reader:
                self.output_reader.stop()
            self.server_process.kill()
            if self.output_reader:
                self.output_reader.wait(1000)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("llama.cpp Server Manager")
    app.setQuitOnLastWindowClosed(False)

    window = LlamaServerGUI()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
