import os
import subprocess
import urllib.parse
import webbrowser
import json
import datetime

from PIL import ImageGrab

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


# ============================================================
# Local workspace sandbox
# ============================================================
# All folder/file creation is confined to this one folder, which lives
# right next to tools.py and is created automatically if missing. Nothing
# the voice assistant creates can end up anywhere else on disk.
WORKSPACE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")
)
os.makedirs(WORKSPACE_DIR, exist_ok=True)


def _resolve_in_workspace(relative_path: str) -> str:
    """Resolve a user-given path relative to WORKSPACE_DIR and guarantee it
    can't land outside it -- blocks '..' traversal, absolute paths, and
    drive letters (e.g. 'C:\\Windows'). Raises ValueError if the resolved
    path would escape the workspace."""
    # Normalize to forward slashes first so '..' and drive-letter checks
    # are consistent regardless of which OS separator the caller used --
    # otherwise a backslash traversal could slip through on a host where
    # '\\' isn't the native separator.
    cleaned = (relative_path or "").replace("\\", "/").strip().strip("/")

    if os.path.isabs(cleaned) or (len(cleaned) >= 2 and cleaned[1] == ":"):
        raise ValueError(
            f"'{relative_path}' looks like an absolute path -- I can only "
            "create things inside the local workspace folder."
        )

    candidate = os.path.normpath(os.path.join(WORKSPACE_DIR, cleaned))

    # Belt-and-suspenders: even if the join above behaved unexpectedly,
    # this is the actual gate. Requires the separator right after the
    # prefix so a sibling folder like 'workspace2' can't slip through.
    if candidate != WORKSPACE_DIR and not candidate.startswith(WORKSPACE_DIR + os.sep):
        raise ValueError(
            f"'{relative_path}' would land outside the workspace folder."
        )

    return candidate


SCREENSHOTS_SUBDIR = "Screenshots"


def take_screenshot(file_name: str = "") -> str:
    """Capture the current screen and save it as a PNG inside the
    workspace's Screenshots folder. Runs immediately -- no confirmation
    step, since capturing the screen doesn't touch or overwrite anything
    that already exists elsewhere. If file_name is omitted, a timestamped
    name is used automatically so repeated screenshots never overwrite
    each other; if a given name collides with an existing file, a number
    is appended instead of overwriting it."""
    try:
        screenshots_dir = _resolve_in_workspace(SCREENSHOTS_SUBDIR)
    except ValueError as e:
        return str(e)
    os.makedirs(screenshots_dir, exist_ok=True)

    base = (file_name or "").strip()
    if base:
        # file_name is meant to be a bare filename, not a path -- strip any
        # directory components (including '..') so it can't be used to
        # escape the Screenshots subfolder the way a path segment could.
        base = os.path.basename(base.replace("\\", "/"))
        base, _ = os.path.splitext(base)  # extension is always .png regardless of what's said
        base = base.strip()
    if not base:
        base = "screenshot_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    full_path = os.path.join(screenshots_dir, f"{base}.png")
    counter = 1
    while os.path.exists(full_path):
        full_path = os.path.join(screenshots_dir, f"{base}_{counter}.png")
        counter += 1
    display = os.path.relpath(full_path, WORKSPACE_DIR)

    try:
        image = ImageGrab.grab()
        try:
            image.save(full_path)
        finally:
            image.close()
        return f"Screenshot saved as '{display}' in the workspace."
    except Exception as e:
        return f"Failed to take screenshot: {e}"


# "ready" is deliberately NOT set true by request_create_folder /
# request_create_file themselves. It's only flipped on by
# mark_pending_actions_ready(), which the app calls once per genuine new
# user message -- never from inside the automatic tool-calling loop.
# That's what stops the model from staging something and then immediately
# "confirming" it itself within the same turn.

pending_folder = {"path": None, "display": None, "ready": False}


def request_create_folder(directory_name: str) -> str:
    try:
        resolved = _resolve_in_workspace(directory_name)
    except ValueError as e:
        return str(e)

    display = os.path.relpath(resolved, WORKSPACE_DIR)
    pending_folder["path"] = resolved
    pending_folder["display"] = display
    pending_folder["ready"] = False
    return f"You want to create a folder called '{display}' in the workspace -- say confirm to go ahead."


def mark_pending_folder_ready():
    """Only takes effect if a request was already pending from a PREVIOUS
    turn, so it can't be used to confirm a folder in the same turn that
    staged it."""
    if pending_folder["path"]:
        pending_folder["ready"] = True


def confirm_create_folder() -> str:
    if not pending_folder["path"]:
        return "There's no folder pending confirmation."
    if not pending_folder["ready"]:
        return "I haven't gotten your confirmation yet -- please tell me to go ahead first."

    path = pending_folder["path"]
    display = pending_folder["display"]
    try:
        # makedirs (not mkdir) so a nested request like "Projects/Scraper"
        # creates any missing parent folders too, still confined to the
        # workspace since `path` was already validated above.
        os.makedirs(path, exist_ok=False)
        pending_folder["path"] = None
        pending_folder["display"] = None
        pending_folder["ready"] = False
        return f"Folder '{display}' has been created successfully in the workspace."
    except FileExistsError:
        return f"'{display}' already exists in the workspace."
    except PermissionError:
        return f"Permission denied: unable to create '{display}'."
    except Exception as e:
        return f"An error occurred: {e}"


# ============================================================
# File creation (with extension inference so voice doesn't have to
# spell out ".py" / ".txt" / etc.)
# ============================================================

# Keyword -> extension. Checked as an exact match first, then as a
# substring, so both a bare "python" and a phrase like "python script"
# resolve the same way. Extend this list as new file types come up.
TYPE_EXTENSIONS = {
    "python": ".py", "py": ".py",
    "text": ".txt", "txt": ".txt", "note": ".txt", "notes": ".txt",
    "markdown": ".md", "md": ".md",
    "word": ".docx", "doc": ".docx", "document": ".docx",
    "excel": ".xlsx", "spreadsheet": ".xlsx", "xlsx": ".xlsx",
    "csv": ".csv",
    "javascript": ".js", "js": ".js",
    "html": ".html", "web page": ".html", "webpage": ".html",
    "json": ".json", "config": ".json",
    "powerpoint": ".pptx", "slides": ".pptx", "presentation": ".pptx",
    "pdf": ".pdf",
}
DEFAULT_EXTENSION = ".txt"


def infer_extension(hint: str):
    """Best-effort mapping from a spoken word/phrase to a file extension.
    Returns None if nothing matches, rather than guessing."""
    if not hint:
        return None
    text = hint.strip().lower()
    if text in TYPE_EXTENSIONS:
        return TYPE_EXTENSIONS[text]
    for keyword, ext in TYPE_EXTENSIONS.items():
        if keyword in text:
            return ext
    return None


def _resolve_filename(file_name: str, file_type: str = "") -> str:
    """Decide the final filename. If the name already has an extension
    (e.g. the model already said 'scraper.py'), trust it as-is. Otherwise
    infer from the file_type hint, then from the name itself, then fall
    back to the default extension -- so the person never has to say
    'dot py' out loud."""
    name = file_name.strip()
    base, ext = os.path.splitext(name)
    if ext:
        return name
    inferred = infer_extension(file_type) or infer_extension(name)
    return f"{base or name}{inferred or DEFAULT_EXTENSION}"


pending_file = {"path": None, "display": None, "ready": False}


def request_create_file(file_name: str, directory_name: str = "", file_type: str = "") -> str:
    """Stage a file for creation inside the workspace, pending confirmation.
    directory_name is optional -- leave it blank to create the file at the
    top level of the workspace. file_type is an optional hint ('python',
    'text', 'word document', etc.) used only to pick the extension -- if
    file_name already includes one (e.g. 'scraper.py'), file_type is
    ignored."""
    try:
        resolved_dir = _resolve_in_workspace(directory_name)
    except ValueError as e:
        return str(e)

    resolved_name = _resolve_filename(file_name, file_type)
    full_path = os.path.join(resolved_dir, resolved_name)
    display = os.path.relpath(full_path, WORKSPACE_DIR)

    pending_file["path"] = full_path
    pending_file["display"] = display
    pending_file["ready"] = False
    return f"You want to create '{display}' in the workspace -- say confirm to go ahead."


def mark_pending_file_ready():
    """Same rule as mark_pending_folder_ready: only takes effect for a
    request staged in a PREVIOUS turn."""
    if pending_file["path"]:
        pending_file["ready"] = True


def confirm_create_file() -> str:
    if not pending_file["path"]:
        return "There's no file pending confirmation."
    if not pending_file["ready"]:
        return "I haven't gotten your confirmation yet -- please tell me to go ahead first."

    path = pending_file["path"]
    display = pending_file["display"]
    directory = os.path.dirname(path)

    if directory and not os.path.isdir(directory):
        # Deliberately NOT cleared: once the missing folder gets created
        # (e.g. via request_create_folder / confirm_create_folder), saying
        # "confirm" again will pick this same staged file back up.
        return (
            f"The folder for '{display}' doesn't exist in the workspace yet -- "
            "create that first, then say confirm again."
        )

    if os.path.exists(path):
        return f"'{display}' already exists in the workspace."

    try:
        with open(path, "x"):
            pass
        pending_file["path"] = None
        pending_file["display"] = None
        pending_file["ready"] = False
        return f"File '{display}' has been created successfully in the workspace."
    except PermissionError:
        return f"Permission denied: unable to create '{display}'."
    except Exception as e:
        return f"An error occurred: {e}"


def mark_pending_actions_ready():
    """Call this exactly once, at the very start of handling each new
    top-level user message (voice or typed) -- before any tool calls for
    that message are processed. Marks any already-staged folder/file
    request as eligible for confirmation this turn."""
    mark_pending_folder_ready()
    mark_pending_file_ready()


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
            "description": (
                "Stage a folder for creation inside the app's local workspace folder, "
                "pending confirmation. Nested paths like 'Projects/Scraper' are allowed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_name": {
                        "type": "string",
                        "description": "Name (or nested path) of the folder to create, relative to the workspace.",
                    }
                },
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
    {
        "type": "function",
        "function": {
            "name": "request_create_file",
            "description": (
                "Stage a file for creation inside the app's local workspace folder, pending "
                "confirmation. Do not ask the user to spell out a file extension -- infer it "
                "from context (e.g. 'python file', 'notes', 'spreadsheet') and pass that as "
                "file_type, or include the extension directly in file_name if the user "
                "already said one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "The file's name, with or without an extension.",
                    },
                    "directory_name": {
                        "type": "string",
                        "description": (
                            "Subfolder (relative to the workspace) the file should be created "
                            "in. Leave blank for the top level of the workspace."
                        ),
                    },
                    "file_type": {
                        "type": "string",
                        "description": (
                            "Optional type hint used to pick the extension when file_name "
                            "doesn't include one, e.g. 'python', 'text', 'markdown', "
                            "'word document', 'spreadsheet', 'csv', 'javascript', 'html', "
                            "'json', 'presentation', 'pdf'. Leave blank for a plain text file."
                        ),
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_create_file",
            "description": "Actually create the file previously staged with request_create_file.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": (
                "Capture the current screen and save it as a PNG inside the workspace's "
                "Screenshots folder. Runs immediately -- no confirmation needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": (
                            "Optional name for the screenshot, without an extension. If "
                            "omitted, a timestamped name is generated automatically."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "open_application": open_application,
    "close_application": close_application,
    "search_web": search_web,
    "request_create_folder": request_create_folder,
    "confirm_create_folder": confirm_create_folder,
    "request_create_file": request_create_file,
    "confirm_create_file": confirm_create_file,
    "take_screenshot": take_screenshot,
}