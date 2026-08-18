# NESU
A Windows Desktop Voice Assistant app with wake-word activation, tool-calling, TTS, built on Pyside6 and Groq

# Features
- Wake word "Hey Nesu"
- Open and closes Applications
- Search Web
- Take Screenshots
- Create Files or folders in a workspace
- TTS

Feature Details
- Wake Word activation - Listens in the background for the keyword "Hey Nesu" no push to talk
- Hands-free follow ups - Conversations can start and end without touching the keyboard
- Speech-to-text and Text-to-Speech 
- Tool-Calling through Groq
- Manage Apps through apps.json file
- Mute toggle
- Typed input fallback if mic quality fails

# Project Structure
- Main.py - Entry point
- Main_window.py - Layout of the UI, dialogs, Widgets (Manage Apps, chat display status panels)
- Chat_worker.py - Wake-word/STT loop, Groq chat and tool-calling, TTS synthesis
- tools.py - Tools Implementation
- apps.json - Registered apps and paths

# Tools Used
- Pyside6 (GUI,Widgets,Multimedia playback)
- Python-dotenv (Loading the Groq API Key)
- groq (Chat completion + tool calling
- RealtimeSTT (Speech to text recorder)
- openwakeword (wake-word detection model)
- edge-tts (TTS synthesis)
- Pillow (Screenshot Capture)
# Dependencies
pip install PySide6 python-dotenv groq RealtimeSTT openwakeword edge-tts Pillow

# Setup
1. Requirements
- Windows (uses os.startfile and taskkill for app control)
- Python 3.10+
2. Install Dependencies
  pip install PySide6 python-dotenv groq RealtimeSTT openwakeword edge-tts Pillow
3. Configure your API key

Create a .env file in the project root:

GROQ_API_KEY=your_groq_api_key_here
(Warning: Please hide your API keys)

4. Register your apps

Either use the Manage Apps button in the app, or edit apps.json directly:

5. Run it
bash
python main.py

-----------------------------------------------------------------------------------------------------------------
# Notes

File and folder creation is sandboxed to a local workspace/ folder — the assistant can't write anywhere else on disk, and traversal attempts (.., absolute paths, drive letters) are blocked.
Creating a file or folder is a two-step process: the assistant stages the request, then waits for you to explicitly confirm on your next turn before anything is written — it can't stage and confirm its own request in the same turn.
Screenshots run immediately without confirmation, since they don't modify anything that already exists.

Known issues / to do
No cross-platform support yet — open_application/close_application rely on Windows-specific calls (os.startfile, taskkill).
