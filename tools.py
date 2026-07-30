import os
import subprocess
import urllib.parse
import webbrowser
import json

APPS_FILE = "apps.json"
DEFAULT_APP_PATHS = {}


def load_app_paths():
    if os.path.exists(APPS_FILE):
        try:
            with open(APPS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_APP_PATHS)


def save_app_paths(app_paths):
    with open(APPS_FILE, "w") as f:
        json.dump(app_paths, f, indent=2)


APP_PATHS = load_app_paths()


def open_application(app_name: str) -> str:
    key = app_name.strip().lower()
    path = APP_PATHS.get(key)
    if not path:
        return f"I don't know how to open '{app_name}'."
    try:
        os.startfile(path)
        return f"Opened {app_name}."
    except Exception as e:
        return f"Failed to open {app_name}: {e}"


def close_application(app_name: str) -> str:
    key = app_name.strip().lower()
    path = APP_PATHS.get(key)
    if not path:
        return f"I don't know how to close '{app_name}'."

    exe_name = os.path.basename(path)
    if not exe_name:
        return f"I don't have a valid executable name for '{app_name}'."

    try:
        result = subprocess.run(
            ["taskkill", "/IM", exe_name, "/F"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Closed {app_name}."
        else:
            detail = (result.stderr or result.stdout or "").strip()
            return f"Couldn't close {app_name}: {detail or 'process not found.'}"
    except FileNotFoundError:
        return "Couldn't close the app: 'taskkill' is not available on this system."
    except Exception as e:
        return f"Failed to close {app_name}: {e}"


def search_web(search_term: str) -> str:
    query = search_term.strip()
    if not query:
        return "I didn't catch what you wanted me to search for."
    try:
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        webbrowser.open(url)
        return f"Searching the web for '{query}'."
    except Exception as e:
        return f"Failed to search for '{query}': {e}"


pending_folder = {"name": None}


def request_create_folder(directory_name: str) -> str:
    pending_folder["name"] = directory_name.strip()
    return f"You want to create a folder called '{directory_name.strip()}'. Should I go ahead?"


def confirm_create_folder() -> str:
    name = pending_folder["name"]
    if not name:
        return "There's no folder pending confirmation."
    try:
        os.mkdir(name)
        pending_folder["name"] = None
        return f"Folder '{name}' has been created successfully."
    except FileExistsError:
        return f"Directory '{name}' already exists."
    except PermissionError:
        return f"Permission denied: unable to create '{name}'."
    except Exception as e:
        return f"An error occurred: {e}"


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open a registered application by its name.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string", "description": "The name of the app to open."}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_application",
            "description": "Close a running application that was registered via Manage Apps.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string", "description": "The name of the app to close."}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Open the default browser and search the web for a term.",
            "parameters": {
                "type": "object",
                "properties": {"search_term": {"type": "string", "description": "What to search for."}},
                "required": ["search_term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_create_folder",
            "description": "Stage a folder name for creation, pending confirmation.",
            "parameters": {
                "type": "object",
                "properties": {"directory_name": {"type": "string", "description": "Name of folder to create."}},
                "required": ["directory_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_create_folder",
            "description": "Actually create the folder previously staged with request_create_folder.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_FUNCTIONS = {
    "open_application": open_application,
    "close_application": close_application,
    "search_web": search_web,
    "request_create_folder": request_create_folder,
    "confirm_create_folder": confirm_create_folder,
}