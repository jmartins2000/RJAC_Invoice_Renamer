import sys

# Log output must never break the app: Windows consoles may not encode characters like "✓" or "—",
# and a failing print() inside a try block would turn a successful rename into a "failure".
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")
    except Exception:
        pass
