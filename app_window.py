# app_window.py
"""
Native desktop window that renders the live dashboard.
Runs the SSE-style event bus in-process — no localhost, no browser.
"""
import json
import threading
import webview  # pywebview


class DashboardAPI:
    """JS calls these methods from the window. Python pushes events here too."""

    def __init__(self):
        self.window = None

    def set_window(self, w):
        self.window = w

    def push_event(self, event: dict):
        """Called from Python thread → evaluates JS in the window."""
        if not self.window:
            return
        payload = json.dumps(event)
        try:
            # call JS function evaluate_event(json) defined in index.html
            self.window.evaluate_js(f"window.__onEvent && window.__onEvent({payload})")
        except Exception as e:
            print(f"[app_window] push failed: {e}")

    def on_ready(self):
        """Called by JS once the page loads."""
        print("[app_window] frontend ready")


api = DashboardAPI()


def _wire_bus():
    from src.lib.events import bus

    def on_event(ev):
        api.push_event(ev)

    bus.subscribe(on_event)

    # also replay history so anything that already happened shows up
    for ev in bus.snapshot():
        api.push_event(ev)


def open_dashboard(title="Open Architect — Live"):
    """Call this once at startup. Blocks on the main thread."""
    from pathlib import Path

    html_path = Path(__file__).parent / "web" / "static" / "index.html"

    window = webview.create_window(
        title,
        url=str(html_path),
        js_api=api,
        width=1000,
        height=760,
        background_color="#0d1117",
    )
    api.set_window(window)
    _wire_bus()

    # start blocking
    webview.start(debug=False)


def open_dashboard_in_thread(title="Open Architect — Live"):
    t = threading.Thread(target=open_dashboard, args=(title,), daemon=True)
    t.start()
    return t