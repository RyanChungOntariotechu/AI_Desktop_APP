import os
import json
import threading
import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
from dotenv import load_dotenv
from groq import Groq
from RealtimeSTT import AudioToTextRecorder
from tools import TOOLS_SCHEMA, TOOL_FUNCTIONS, APP_PATHS, save_app_paths

class DynoBynoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DynoByno: Desktop AI Assistant")
        self.root.geometry("600x700")

        # --- Top button bar ---
        button_bar = tk.Frame(root)
        button_bar.pack(fill="x", padx=10, pady=(10, 0))

        manage_btn = tk.Button(button_bar, text="Manage Apps", command=self.open_manage_apps)
        manage_btn.pack(side="left")

        self.muted = False
        self.mute_btn = tk.Button(
            button_bar, text="Mute Mic", command=self.toggle_mute
        )
        self.mute_btn.pack(side="left", padx=(10, 0))

        self.chat_display = scrolledtext.ScrolledText(
            root, wrap=tk.WORD, state="disabled", font=("Segoe UI", 11)
        )
        self.chat_display.pack(fill="both", expand=True, padx=10, pady=10)

        # --- Text input row (fallback for when voice fails) ---
        input_frame = tk.Frame(root)
        input_frame.pack(fill="x", padx=10, pady=(0, 5))

        self.input_entry = tk.Entry(input_frame, font=("Segoe UI", 11))
        self.input_entry.pack(side="left", fill="both", expand=True)
        self.input_entry.bind("<Return>", self.on_send_clicked)

        self.send_btn = tk.Button(input_frame, text="Send", command=self.on_send_clicked)
        self.send_btn.pack(side="left", padx=(5, 0))

        self.status_label = tk.Label(root, text="Initializing...", anchor="w")
        self.status_label.pack(fill="x", padx=10, pady=(0, 10))

        self.messages = None
        self.recorder = None
        self.running = True

        # Guards self.chat since both the voice-listen thread and the
        # text-input thread can send messages to it.
        self.chat_lock = threading.Lock()

        threading.Thread(target=self.setup_and_run, daemon=True).start()

    # ---------- Mute logic ----------

    def toggle_mute(self):
        self.muted = not self.muted

        # Try to actually disable audio capture at the recorder level.
        if self.recorder is not None:
            try:
                self.recorder.set_microphone(not self.muted)
            except AttributeError:
                # Older/newer RealtimeSTT versions may not expose this method.
                # We still fall back to ignoring transcriptions in listen_loop.
                pass
            except Exception as e:
                self.append_message("System", f"Couldn't toggle microphone hardware: {e}")

        if self.muted:
            self.mute_btn.config(text="Unmute Mic")
            self.set_status("Muted.")
            self.append_message("System", "Microphone muted.")
        else:
            self.mute_btn.config(text="Mute Mic")
            self.set_status("Listening...")
            self.append_message("System", "Microphone unmuted.")

    # ---------- Manage Apps window ----------

    def open_manage_apps(self):
        win = tk.Toplevel(self.root)
        win.title("Manage Apps")
        win.geometry("450x400")
        win.transient(self.root)

        list_frame = tk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=10, pady=10)

        listbox = tk.Listbox(list_frame)
        listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(list_frame, command=listbox.yview)
        scrollbar.pack(side="right", fill="y")
        listbox.config(yscrollcommand=scrollbar.set)

        def refresh_listbox():
            listbox.delete(0, tk.END)
            for name, path in APP_PATHS.items():
                listbox.insert(tk.END, f"{name}  ->  {path}")

        refresh_listbox()

        form_frame = tk.Frame(win)
        form_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Label(form_frame, text="Word to say:").grid(row=0, column=0, sticky="w")
        name_entry = tk.Entry(form_frame, width=20)
        name_entry.grid(row=0, column=1, sticky="we", padx=5)

        tk.Label(form_frame, text="App path:").grid(row=1, column=0, sticky="w")
        path_entry = tk.Entry(form_frame, width=20)
        path_entry.grid(row=1, column=1, sticky="we", padx=5, pady=5)

        def browse_file():
            filepath = filedialog.askopenfilename(
                title="Select application executable",
                filetypes=[("Executable files", "*.exe"), ("All files", "*.*")],
            )
            if filepath:
                path_entry.delete(0, tk.END)
                path_entry.insert(0, filepath)

        browse_btn = tk.Button(form_frame, text="Browse...", command=browse_file)
        browse_btn.grid(row=1, column=2, padx=5)

        form_frame.columnconfigure(1, weight=1)

        action_frame = tk.Frame(win)
        action_frame.pack(fill="x", padx=10, pady=(0, 10))

        def add_app():
            name = name_entry.get().strip().lower()
            path = path_entry.get().strip()
            if not name or not path:
                messagebox.showwarning("Missing info", "Please enter both a word and a path.")
                return
            APP_PATHS[name] = path
            save_app_paths(APP_PATHS)
            refresh_listbox()
            name_entry.delete(0, tk.END)
            path_entry.delete(0, tk.END)
            self.append_message("System", f"Added app '{name}' -> {path}")

        def remove_selected():
            selection = listbox.curselection()
            if not selection:
                return
            entry_text = listbox.get(selection[0])
            name = entry_text.split("  ->  ")[0]
            if name in APP_PATHS:
                del APP_PATHS[name]
                save_app_paths(APP_PATHS)
                refresh_listbox()
                self.append_message("System", f"Removed app '{name}'")

        add_btn = tk.Button(action_frame, text="Add App", command=add_app)
        add_btn.pack(side="left")

        remove_btn = tk.Button(action_frame, text="Remove Selected", command=remove_selected)
        remove_btn.pack(side="left", padx=10)

    # ---------- Chat / voice logic ----------

    def append_message(self, speaker, text):
        def _update():
            self.chat_display.configure(state="normal")
            self.chat_display.insert(tk.END, f"{speaker}: {text}\n\n")
            self.chat_display.configure(state="disabled")
            self.chat_display.see(tk.END)
        self.root.after(0, _update)

    def set_status(self, text):
        self.root.after(0, lambda: self.status_label.config(text=text))

    # ---------- Typed input handling ----------

    def on_send_clicked(self, event=None):
        """Called from the Tk main thread when Send is clicked or Enter is pressed."""
        text = self.input_entry.get().strip()
        if not text:
            return
        self.input_entry.delete(0, tk.END)

        if self.messages is None:
            self.append_message("System", "Still starting up, please wait a moment.")
            return

        # Do the actual API call off the main thread so the UI doesn't freeze.
        threading.Thread(target=self.handle_typed_message, args=(text,), daemon=True).start()

    def handle_typed_message(self, text):
        self.append_message("You", text)

        if text.strip().lower() == "exit.":
            self.set_status("Stopped.")
            self.running = False
            return

        self.send_to_chat(text)
        if self.running:
            self.set_status("Listening..." if not self.muted else "Muted.")
    def send_to_chat(self, user_input):
        self.set_status("Thinking...")
        try:
            with self.chat_lock:
                self.messages.append({"role": "user", "content": user_input})

                response = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=self.messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                )
                msg = response.choices[0].message

                while msg.tool_calls:
                    self.messages.append(msg.model_dump(exclude_unset=True))
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
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(result),
                        })

                    response = self.client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=self.messages,
                        tools=TOOLS_SCHEMA,
                        tool_choice="auto",
                    )
                    msg = response.choices[0].message

                reply = msg.content or ""
                self.messages.append({"role": "assistant", "content": reply})
        except Exception as e:
            reply = f"Error: {e}"

        self.append_message("DynoByno", reply)
        return reply

    def setup_and_run(self):
        load_dotenv()
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            self.append_message("System", "GROQ_API_KEY not set in environment.")
            return

        self.client = Groq(api_key=api_key)
        self.messages = [
            {
                "role": "system",
                "content": (
                    "My name is Ryan. You control his computer via tools. "
                    "If he asks you to open an app, call open_application. "
                    "If he asks you to close, quit, or exit an app, call close_application. "
                    "If he asks you to search the web/internet for something, or just says "
                    "'search <term>', call search_web with that term. "
                    "If he asks you to create a folder, call request_create_folder, then "
                    "confirm_create_folder once he confirms. "
                    "Otherwise just respond conversationally."
                ),
            }
        ]

        self.set_status("Loading speech recognizer...")
        self.recorder = AudioToTextRecorder(model="tiny.en", language="en", spinner=False)

        if self.muted:
            try:
                self.recorder.set_microphone(False)
            except AttributeError:
                pass

        self.listen_loop()

    def listen_loop(self):
        while self.running:
            if self.muted:
                self.set_status("Muted.")
            else:
                self.set_status("Listening...")

            user_input = self.recorder.text()
            if not user_input:
                continue

            # If muted, discard whatever was transcribed and don't respond.
            # (Covers the case where set_microphone() isn't supported.)
            if self.muted:
                continue

            self.append_message("You", user_input)

            if user_input.strip().lower() == "exit.":
                self.set_status("Stopped.")
                break

            self.send_to_chat(user_input)

        self.recorder.shutdown()

 
if __name__ == "__main__":
    root = tk.Tk()
    app = DynoBynoApp(root)
    root.mainloop()