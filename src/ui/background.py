"""Run slow work off the UI thread and deliver the result back on the UI thread.

Tk must only be touched from the main thread (on macOS, `after()` called from another
thread is silently dropped), so the UI thread polls the result instead.
"""
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=4)


def run(widget, work, on_done, poll_ms=50):
    """Calls work() in a thread, then on_done(result) on the UI thread.
    If work raises, on_done receives the exception instance."""
    future = _pool.submit(work)

    def check():
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        if future.done():
            try:
                result = future.result()
            except Exception as e:  # pass errors through to the caller
                result = e
            on_done(result)
        else:
            widget.after(poll_ms, check)

    widget.after(poll_ms, check)
    return future


class Mailbox:
    """For progress updates: worker threads put callables, the UI thread runs them."""

    def __init__(self, widget, poll_ms=50):
        import queue
        self._q = queue.Queue()
        self._widget = widget
        self._poll_ms = poll_ms
        widget.after(poll_ms, self._drain)

    def post(self, fn):
        self._q.put(fn)

    def _drain(self):
        import queue
        try:
            if not self._widget.winfo_exists():
                return
        except Exception:
            return
        try:
            while True:
                self._q.get_nowait()()
        except queue.Empty:
            pass
        self._widget.after(self._poll_ms, self._drain)
