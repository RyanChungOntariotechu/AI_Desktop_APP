"""
Chat Functionality
-------------------
Everything related to talking to the Groq LLM, running tool calls, and
driving the always-on wake-word voice loop. No Qt widgets are touched
here directly -- only Qt signals are emitted, so this module has no UI
concerns.
"""

import os
import json
import asyncio
import threading
import tempfile

import openwakeword
import edge_tts
from dotenv import load_dotenv
from groq import Groq
from RealtimeSTT import AudioToTextRecorder

from PySide6.QtCore import QThread, Signal

from tools import TOOLS_SCHEMA, TOOL_FUNCTIONS, mark_pending_actions_ready

openwakeword.utils.download_models()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "wake_word", "hey_nes_ou.onnx")

# edge-tts hits Microsoft's free Edge Read Aloud endpoint -- no API key
# and no token quota, unlike Groq's TTS. Full voice list via
# `edge-tts --list-voices` in a terminal.
TTS_VOICE = "en-US-AvaNeural"

# llama-3.1-8b-instant was deprecated by Groq (shut down Aug 16, 2026).
# openai/gpt-oss-20b is their recommended replacement -- see
# https://console.groq.com/docs/deprecations for current status.
CHAT_MODEL = "openai/gpt-oss-20b"


class AppState:
    """Shared state between the Qt main thread and the background worker
    thread(s) -- deliberately not a QObject, just plain data + a lock."""

    def __init__(self):
        self.client = None
        self.messages = None
        self.recorder = None
        self.running = True
        self.muted = False
        # True once the wake word has fired and we're in an open back-and-forth
        # -- follow-up turns don't need the wake word again while this is set.
        self.in_conversation = False
        self.chat_lock = threading.Lock()


class ChatWorker(QThread):
    """Owns setup + the always-on voice listen loop. Runs off the Qt
    main thread so recorder.text() (blocking) never freezes the UI."""

    message = Signal(str, str)  # speaker, text
    status = Signal(str)
    stopped = Signal()
    wake_word_detected = Signal()
    speech_ready = Signal(str)  # path to a synthesized WAV file, ready to play

    # Phrases that end an open conversation and drop back to wake-word mode.
    # Matched against the transcript with trailing punctuation stripped.
    # Kept short/simple since these get said in normal speech at the tail
    # end of a mic pickup, where longer phrases are more likely to get
    # clipped or mis-transcribed. Add/remove entries here to tune it --
    # just be aware that very common words (e.g. plain "ok") risk closing
    # the conversation by accident if you say them mid-chat.
    CLOSE_PHRASES = ("thanks", "thank you", "thanks nesu", "thank you nesu")

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        # Guards against on_wakeword_detected firing more than once for a
        # single detection -- some STT backends can call this callback a
        # few times in quick succession around one utterance. Reset every
        # time a wake-word-mode recorder is (re)built, so it's exactly one
        # sound per "waiting for wake word" cycle.
        self._wake_fired = False

    # ---------- Recorder setup ----------

    def _build_recorder(self, wake_word_mode=True):
        """wake_word_mode=True: normal gated behavior, waits for "nesu".
        wake_word_mode=False: no wake word required, transcribes as soon as
        voice activity is detected -- used for the open-conversation window
        so follow-up turns don't need the wake word repeated."""
        kwargs = dict(
            model="base.en",
            language="en",
            spinner=False,
        )
        if wake_word_mode:
            self._wake_fired = False
            kwargs.update(
                wakeword_backend="oww",
                wake_words="nesu",
                openwakeword_model_paths="wake_word/hey_nes_ou.onnx",
                openwakeword_inference_framework="onnx",
                wake_word_activation_delay=0,
                wake_word_timeout=5,
                wake_word_buffer_duration=0.2,
                wake_words_sensitivity=0.3,
                on_wakeword_detected=self._on_wake_word_detected,
            )
        return AudioToTextRecorder(**kwargs)

    def _on_wake_word_detected(self):
        """Called by RealtimeSTT, likely from its own internal audio
        thread -- not the QThread's run() call stack. Emitting a Qt
        Signal here is safe from any thread; that's what Signals are
        for. Only the print + emit happen once per cycle, guarded by
        _wake_fired."""
        if self._wake_fired:
            return
        self._wake_fired = True
        print(">>> WAKE WORD DETECTED <<<")
        self.wake_word_detected.emit()

    # ---------- Thread entry point ----------

    def run(self):
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            self.message.emit("System", "GROQ_API_KEY not set in environment.")
            return

        self.state.client = Groq(api_key=api_key)
        self.state.messages = [
            {
                "role": "system",
                "content": (
                    "My name is Ryan. You control his computer via tools. Only call a tool "
                    "when he clearly asks for that action -- never guess or invent an app "
                    "name, file name, or folder name that he didn't say.\n\n"
                    "Trigger words -> tool:\n"
                    "- open/launch/start an app -> open_application\n"
                    "- close/quit/exit an app -> close_application\n"
                    "- search the web, or 'search <term>' -> search_web\n"
                    "- screenshot / screen capture / capture the screen -> take_screenshot "
                    "immediately. No confirmation, no folder name needed.\n"
                    "- create a folder -> if no name given, ask for one first, never invent "
                    "one. Then request_create_folder, then confirm_create_folder once he "
                    "confirms.\n"
                    "- create a file -> if no file name given, ask for one first, never "
                    "invent one. A folder is optional -- if he doesn't mention one, it goes "
                    "in the top level of the workspace. Never ask him to spell out an "
                    "extension: infer the type from context (e.g. 'python file', 'notes', "
                    "'spreadsheet') and pass that as file_type, defaulting to plain text if "
                    "no type is given. Then request_create_file, then confirm_create_file "
                    "once he confirms.\n\n"
                    "\"Workspace\" refers to this app's local storage folder on disk -- it is "
                    "NOT the name of an application. Never call open_application or "
                    "close_application with 'workspace' (or anything like 'Workspace Editor') "
                    "as the app_name; that tool is only for apps registered in Manage Apps.\n\n"
                    "For anything else, just respond conversationally."
                ),
            }
        ]
        self.status.emit("Loading speech recognizer...")
        self.state.recorder = self._build_recorder()
        self.message.emit("System", "Say the wake word!")
        self.status.emit("Listening for wake word...")

        if self.state.muted:
            try:
                self.state.recorder.set_microphone(False)
            except AttributeError:
                pass

        self.listen_loop()

    # ---------- Voice loop ----------

    def listen_loop(self):
        while self.state.running:
            if self.state.in_conversation:
                self.status.emit("Listening (say 'Thanks Nesu' to pause)...")
            else:
                self.status.emit("Listening for wake word...")

            user_input = self.state.recorder.text()
            if not user_input:
                continue

            if self.state.muted:
                continue

            self.message.emit("You", user_input)
            normalized = user_input.strip().lower().rstrip(".!?")

            if normalized == "exit":
                self.state.running = False
                self.status.emit("Stopped.")
                break

            if normalized in self.CLOSE_PHRASES:
                self.message.emit("Nesu", "Anytime! Say the wake word when you need me again.")
                self._end_conversation()
                continue

            reply = self.send_to_chat(user_input)
            self.message.emit("Nesu", reply)

            # Only switch modes once, on the turn that opens the
            # conversation -- no rebuild on every single turn after that.
            if not self.state.in_conversation:
                self._start_conversation()

        if self.state.recorder is not None:
            self.state.recorder.shutdown()
        self.stopped.emit()

    def _start_conversation(self):
        """Called once the wake word has fired and gotten a reply. Swaps in
        a recorder that doesn't require the wake word, so the person can
        keep talking without saying "nesu" again each turn."""
        print("Entering conversation mode (wake word no longer required)...")
        try:
            self.state.recorder.shutdown()
            self.state.recorder = self._build_recorder(wake_word_mode=False)
            self.state.in_conversation = True
        except Exception as e:
            print(f"CONVERSATION MODE SWITCH FAILED: {e}")
            self.message.emit("System", f"Couldn't switch to conversation mode: {e}")

    def _end_conversation(self):
        """Called when the user says "Thanks Nesu" (or a variant). This is
        the "temporary shutdown" -- it drops back to requiring the wake
        word, but keeps the app and the outer loop running."""
        print("Leaving conversation mode (wake word required again)...")
        try:
            self.state.recorder.shutdown()
            self.state.recorder = self._build_recorder(wake_word_mode=True)
            self.state.in_conversation = False
        except Exception as e:
            print(f"RETURN TO WAKE-WORD MODE FAILED: {e}")
            self.message.emit("System", f"Couldn't return to wake-word mode: {e}")
            self.state.running = False

    # ---------- Text-to-speech ----------

    def _synthesize_speech(self, text):
        """Calls edge-tts and writes the result to a temp MP3 file (edge-tts
        only outputs MP3, not WAV -- QMediaPlayer handles that fine, unlike
        the QSoundEffect used for the wake/listening-off cues). Runs
        synchronously on whatever thread calls it (the worker thread, via
        send_to_chat) via asyncio.run(), same as the old Groq call just
        added latency there. Returns the file path, or None if synthesis
        failed, so a TTS outage never blocks the text reply from showing up."""
        if not text.strip():
            return None

        fd, path = tempfile.mkstemp(prefix="nesu_reply_", suffix=".mp3")
        os.close(fd)
        try:
            asyncio.run(edge_tts.Communicate(text, TTS_VOICE).save(path))
        except Exception as e:
            print(f"TTS SYNTHESIS FAILED: {e}")
            self.message.emit("System", f"Couldn't generate speech: {e}")
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        return path

    # ---------- Core chat / tool-calling logic ----------

    def send_to_chat(self, user_input):
        """Safe to call from any thread; guarded by state.chat_lock.
        Does not touch any Qt widgets directly."""
        with self.state.chat_lock:
            try:
                self.state.messages.append({"role": "user", "content": user_input})

                # Must happen once per genuine new user message, before any
                # tool calls run -- this is the only place that's allowed to
                # make a pending folder request confirmable.
                mark_pending_actions_ready()

                response = self.state.client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=self.state.messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                )
                msg = response.choices[0].message

                while msg.tool_calls:
                    self.state.messages.append(msg.model_dump(exclude_unset=True))
                    for tool_call in msg.tool_calls:
                        fn_name = tool_call.function.name
                        try:
                            args = json.loads(tool_call.function.arguments or "{}")
                            if not isinstance(args, dict):
                                args = {}
                        except json.JSONDecodeError:
                            args = {}
                        fn = TOOL_FUNCTIONS.get(fn_name)
                        result = fn(**args) if fn else f"Unknown tool: {fn_name}"
                        self.state.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(result),
                        })

                    response = self.state.client.chat.completions.create(
                        model=CHAT_MODEL,
                        messages=self.state.messages,
                        tools=TOOLS_SCHEMA,
                        tool_choice="auto",
                    )
                    msg = response.choices[0].message

                reply = msg.content or ""
                self.state.messages.append({"role": "assistant", "content": reply})

                audio_path = self._synthesize_speech(reply)
                if audio_path:
                    self.speech_ready.emit(audio_path)

                return reply
            except Exception as e:
                return f"Error: {e}"