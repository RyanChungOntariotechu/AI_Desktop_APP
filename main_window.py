"""
User Interface
---------------
All Qt widgets, layout, and dialogs for the DynoByno desktop app. This
module knows how to display a ChatWorker's output and how to send typed
input to it, but contains no LLM / tool-calling logic itself.
"""

import threading
import html
import os
from pathlib import Path

from PySide6.QtCore import Signal, Slot, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLineEdit, QLabel, QDialog, QListWidget,
    QFormLayout, QFileDialog, QMessageBox, 
)
from PySide6.QtGui import QFont, QColor, QIcon
from PySide6.QtCore import Qt
from tools import APP_PATHS, save_app_paths
from chat_worker import AppState, ChatWorker

# Color Scheme for the UI
BG_APP = "#1f1a1c"      # main/middle content area
BG_PANEL = "#261f22"    # chat log, list items, inputs
BG_SIDE = "#161213"     # sidebar / bottom bar
TEXT = "#fbeceb"        # primary text
TEXT_DIM = "#c2a5a2"    # secondary/status text
TEXT_FAINT = "#836c6a"  # section labels, placeholders
ACCENT = "#ff6f61"      # focus rings, selection, primary actions — also "You"
ACCENT_SOFT = "rgba(255, 111, 97, 45)"   # selection fill
BORDER = "rgba(255, 255, 255, 18)"       # hairline borders

#Different Color Schemes for the different systems talking (You, System and Nesu)
USER_COLOR = ACCENT          
SYSTEM_COLOR = "#e8b96a"     
ASSISTANT_COLOR = "#7fd1ae"  
SPEAKER_COLORS = {
    "You": USER_COLOR,
    "System": SYSTEM_COLOR,
    "Nesu": ASSISTANT_COLOR,
}
#Sound Directory
SOUNDS_DIR = Path(__file__).resolve().parent / "sound"

#Allows us to Manage the Apps we add for app calling 
class ManageAppsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Apps")
        self.resize(450, 400)

        layout = QVBoxLayout(self)

        self.listbox = QListWidget()
        layout.addWidget(self.listbox)

        form = QFormLayout()
        self.name_entry = QLineEdit()

        path_row = QHBoxLayout()
        self.path_entry = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)
        path_row.addWidget(self.path_entry)
        path_row.addWidget(browse_btn)

        #How I call for my Apps
        form.addRow("Word to say:", self.name_entry)
        form.addRow("App path:", path_row)
        layout.addLayout(form)

        #Adds App - User Interface
        action_row = QHBoxLayout()
        add_btn = QPushButton("Add App")
        add_btn.clicked.connect(self.add_app)

        #Removes App - User Interface
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_selected)
        action_row.addWidget(add_btn)
        action_row.addWidget(remove_btn)
        layout.addLayout(action_row)

        self.refresh_listbox()

    #Refresh the list for managed apps
    def refresh_listbox(self):
        self.listbox.clear()
        for name, path in APP_PATHS.items():
            self.listbox.addItem(f"{name}  ->  {path}")

    #Allows us to browse our files for more apps (Ideally I don't want only .exe)
    def browse_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select application executable", "", "Executable files (*.exe);;All files (*.*)"
        )
        if filepath:
            self.path_entry.setText(filepath)

    #Allows me to add an app using both the path and a name
    def add_app(self):
        name = self.name_entry.text().strip().lower()
        path = self.path_entry.text().strip()
        if not name or not path:
            QMessageBox.warning(self, "Missing info", "Please enter both a word and a path.")
            return
        APP_PATHS[name] = path
        save_app_paths(APP_PATHS)
        self.refresh_listbox()
        self.name_entry.clear()
        self.path_entry.clear()
        if self.parent() is not None:
            self.parent().append_message("System", f"Added app '{name}' -> {path}")

    #Allows me to remove an app
    def remove_selected(self):
        item = self.listbox.currentItem()
        if item is None:
            return
        name = item.text().split("  ->  ")[0]
        if name in APP_PATHS:
            del APP_PATHS[name]
            save_app_paths(APP_PATHS)
            self.refresh_listbox()
            if self.parent() is not None:
                self.parent().append_message("System", f"Removed app '{name}'")

#UI for the main application
class MainWindow(QMainWindow):
    message_signal = Signal(str, str)
    status_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nesu")
        self.resize(1100,900)

        self.state = AppState()

        central = QWidget()
        outer_layout = QVBoxLayout(central)

        header_label = QLabel("Nesu")
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet(f"""
            QLabel {{
                color: {TEXT};
                font-family: 'Segoe UI';
                font-size: 24px;
                font-weight: 600;
                padding: 10px 0px;
            }}
        """)
        outer_layout.addWidget(header_label)

        columns_layout = QHBoxLayout()
        outer_layout.addLayout(columns_layout)
        outer_layout.setStretch(1, 1)
        central.setStyleSheet(f"""
        QWidget {{
            background-color: {BG_APP};
        }}
        QLabel {{
            color: {TEXT_DIM};
            font-family: 'Segoe UI';
            font-size: 14px;
        }}
        QLineEdit {{
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 6px 10px;
            background-color: {BG_PANEL};
            color: {TEXT};
            font-size: 14px;
        }}
        QLineEdit:focus {{
            border: 1px solid {ACCENT};
        }}
        QPushButton {{
            color: {TEXT};
            background-color: {BG_PANEL};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 8px 14px;
            font-family: 'Segoe UI';
            font-size: 13px;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {ACCENT_SOFT};
            border: 1px solid {ACCENT};
            color: {ACCENT};
        }}
        QPushButton:pressed {{
            background-color: {BG_SIDE};
        }}
        """)
        self.setCentralWidget(central)
        
        # Left Column (Manage Apps and Basic UI )
        
        left_col = QVBoxLayout()

        apps_title = QLabel("Apps")
        apps_title.setAlignment(Qt.AlignCenter)
        apps_title.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_FAINT};
                font-family: 'Segoe UI';
                font-size: 13px;
                font-weight: 600;
                letter-spacing: 1px;
                padding: 4px;
            }}
        """)

        left_col.addWidget(apps_title) 
        
        self.apps_list = QListWidget()
        self.refresh_apps_list()
        left_col.addWidget(self.apps_list)
        self.apps_list.setStyleSheet(f"""
            QListWidget {{
                border: none;
                background-color: transparent;
                font-family: 'Segoe UI';
                font-size: 15px;
                color: {TEXT_DIM};
    
            }}
            
            QListWidget::item {{
                border-radius: 6px;
                padding: 6px;
                margin: 2px;
                background-color: transparent;
                outline: none;
                border: none;
            }}
            QListWidget::item:selected {{
                border: 1px solid {ACCENT};
                background-color: {ACCENT_SOFT};
                color: {ACCENT};
                outline: none;
            }}
        """)
        self.apps_list.setFocusPolicy(Qt.NoFocus)
        for i in range(self.apps_list.count()):
             self.apps_list.item(i).setTextAlignment(Qt.AlignCenter)
        self.apps_list.setMaximumHeight(200)

        manage_btn = QPushButton("+ Manage")
        manage_btn.clicked.connect(self.open_manage_apps)
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.setStyleSheet(f"""
            QPushButton {{
                color: {TEXT_DIM};
                background-color: {BG_SIDE};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 14px;
                font-family: 'Segoe UI';
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {BG_PANEL};
                color: {TEXT};
            }}
            QPushButton:pressed {{
                background-color: #0f0d0e;
            }}
        """)
        left_col.addWidget(manage_btn)
        left_col.addStretch(10)
        

        # Middle Column (Chat display, mute button, chat input, and send button)
        middle_col = QVBoxLayout()
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        middle_col.addWidget(self.chat_display)
        self.chat_display.setStyleSheet(f"""
            QTextEdit {{
                border: 1px solid {BORDER};
                border-radius: 10px;
                color: {TEXT};
                padding: 10px;
                background-color: {BG_PANEL};
                selection-background-color: {ACCENT};
                selection-color: #1a1112;
                font-family: 'Segoe UI';
                font-size: 19px;
            }}
            """)
        input_row = QHBoxLayout()

        self.mute_btn = QPushButton("Mute Mic")
        self.mute_btn.clicked.connect(self.toggle_mute)
        input_row.addWidget(self.mute_btn)

        self.input_entry = QLineEdit()
        self.input_entry.returnPressed.connect(self.on_send_clicked)
        input_row.addWidget(self.input_entry)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.on_send_clicked)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                color: #1a1112;
                background-color: {ACCENT};
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
                font-family: 'Segoe UI';
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #ff8a7e;
            }}
            QPushButton:pressed {{
                background-color: #e85c4f;
            }}
        """)
        input_row.addWidget(send_btn)
        middle_col.addLayout(input_row)

        # Right Column (The Status for Nesu)
        right_col = QVBoxLayout()
        self.status_label = QLabel("Initializing...")
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_DIM};
                font-family: 'Segoe UI';
                font-size: 13px;
                padding: 4px;
            }}
        """)
        right_col.addWidget(self.status_label)

        right_col.addStretch()

        # ---------- Assemble ----------
        columns_layout.addLayout(left_col, 1)   # 12.5% — narrower
        columns_layout.addLayout(middle_col, 6) # 75% — main content
        columns_layout.addLayout(right_col, 1)  # 12.5% — narrower

        # Wire up cross-thread signals before starting the worker.
        self.message_signal.connect(self.append_message)
        self.status_signal.connect(self.set_status)

        # Wake word, Activation Sound
        self.wake_word_player = QMediaPlayer()
        self.wake_word_audio_output = QAudioOutput()
        self.wake_word_player.setAudioOutput(self.wake_word_audio_output)
        self.wake_word_player.setSource(QUrl.fromLocalFile(str(SOUNDS_DIR / "Activation.mp3")))
        self.wake_word_audio_output.setVolume(0.8)

        #De-Activation Sound
        self.listening_off_player = QMediaPlayer()
        self.listening_off_audio_output = QAudioOutput()
        self.listening_off_player.setAudioOutput(self.listening_off_audio_output)
        self.listening_off_player.setSource(QUrl.fromLocalFile(str(SOUNDS_DIR / "De-Activation.mp3")))
        self.listening_off_audio_output.setVolume(0.8)

        # Nesu's spoken replies (from chat_worker.py's Groq TTS call) --
        # kept separate from the short UI sound effects above since this
        # one plays a different file every turn and needs cleanup after.
        self.tts_player = QMediaPlayer()
        self.tts_audio_output = QAudioOutput()
        self.tts_player.setAudioOutput(self.tts_audio_output)
        self.tts_audio_output.setVolume(0.9)
        self._tts_temp_path = None
        self.tts_player.mediaStatusChanged.connect(self._on_tts_status_changed)
        self.tts_player.errorOccurred.connect(self._on_tts_player_error)

        # --- Background worker (voice loop) ---
        self.worker = ChatWorker(self.state)
        self.worker.message.connect(self.append_message)
        self.worker.status.connect(self.set_status)
        self.worker.stopped.connect(self.on_worker_stopped)
        self.worker.speech_ready.connect(self.play_tts_audio)
        # Same pattern for wake-word detection and listening deactivation —
        # add `wake_word_detected = Signal()` and `listening_deactivated =
        # Signal()` to ChatWorker and emit them at the right points in the
        # voice loop; this picks them up automatically, no further UI
        # changes needed.
        worker_wake_signal = getattr(self.worker, "wake_word_detected", None)
        if worker_wake_signal is not None:
            worker_wake_signal.connect(self.play_wake_sound)
        worker_listening_off_signal = getattr(self.worker, "listening_deactivated", None)
        if worker_listening_off_signal is not None:
            worker_listening_off_signal.connect(self.play_listening_off_sound)
        self.worker.start()
    # ---------- Mute logic (runs on the GUI thread; direct calls are fine) ----------

    def toggle_mute(self):
        self.state.muted = not self.state.muted

        if self.state.recorder is not None:
            try:
                self.state.recorder.set_microphone(not self.state.muted)
            except AttributeError:
                # Older/newer RealtimeSTT versions may not expose this method.
                # We still fall back to ignoring transcriptions in listen_loop.
                pass
            except Exception as e:
                self.append_message("System", f"Couldn't toggle microphone hardware: {e}")

        if self.state.muted:
            self.mute_btn.setText("Unmute Mic")
            self.set_status("Muted.")
            self.append_message("System", "Microphone muted.")
            self.play_listening_off_sound()
        else:
            self.mute_btn.setText("Mute Mic")
            self.set_status("Listening...")
            self.append_message("System", "Microphone unmuted.")

    # ---------- Manage Apps window ----------

    def open_manage_apps(self):
        dialog = ManageAppsDialog(self)
        dialog.exec()
    def refresh_apps_list(self):
        self.apps_list.clear()
        for name in list(APP_PATHS.keys())[:5]:
            self.apps_list.addItem(name)
    # ---------- Chat display helpers (Qt slots -- GUI thread only) ----------

    @Slot(str, str)
    def append_message(self, speaker, text):
        color = SPEAKER_COLORS.get(speaker, ASSISTANT_COLOR)
        safe_speaker = html.escape(speaker)
        safe_text = html.escape(text).replace("\n", "<br>")
        self.chat_display.append(
            f'<div style="margin-bottom:8px;">'
            f'<span style="color:{color}; font-weight:600;">{safe_speaker}:</span> '
            f'<span style="color:{TEXT};">{safe_text}</span>'
            f'</div>'
        )

    @Slot(str)
    def set_status(self, text):
        self.status_label.setText(text)

    @Slot()
    def play_wake_sound(self):
        self.wake_word_player.setPosition(0)
        self.wake_word_player.play()

    @Slot()
    def play_listening_off_sound(self):
        self.listening_off_player.setPosition(0)
        self.listening_off_player.play()

    @Slot(str)
    def play_tts_audio(self, path):
        # A new reply arriving mid-playback just cuts the old one off --
        # setSource() while playing stops the current audio automatically.
        self._tts_temp_path = path
        self.tts_player.setSource(QUrl.fromLocalFile(path))
        self.tts_player.play()

    def _on_tts_status_changed(self, status):
        # Native QMediaPlayer signal, already emitted on the GUI thread --
        # no @Slot decorator/cross-thread handling needed here.
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._tts_temp_path:
            try:
                os.remove(self._tts_temp_path)
            except OSError:
                pass
            self._tts_temp_path = None

    def _on_tts_player_error(self, error, error_string):
        # Native QMediaPlayer signal -- fires for things like a missing
        # codec/backend, a bad file, or no audio output device.
        print(f"TTS PLAYBACK ERROR: {error_string}")
        self.append_message("System", f"Couldn't play speech: {error_string}")

    @Slot()
    def on_worker_stopped(self):
        self.set_status("Stopped.")

    # ---------- Typed input handling ----------

    def on_send_clicked(self):
        text = self.input_entry.text().strip()
        if not text:
            return
        self.input_entry.clear()

        if self.state.messages is None:
            self.append_message("System", "Still starting up, please wait a moment.")
            return

        # Do the actual API call off the GUI thread so the UI doesn't freeze.
        threading.Thread(target=self.handle_typed_message, args=(text,), daemon=True).start()

    def handle_typed_message(self, text):
        """Runs on a plain Python thread -- must go through signals, not
        direct widget calls, to update the UI safely."""
        self.message_signal.emit("You", text)

        if text.strip().lower() == "exit.":
            self.state.running = False
            self.status_signal.emit("Stopped.")
            return

        reply = self.worker.send_to_chat(text)
        self.message_signal.emit("Nesu", reply)
        if self.state.running:
            self.status_signal.emit("Muted." if self.state.muted else "Listening...")

    def closeEvent(self, event):
        self.state.running = False
        super().closeEvent(event)