"""Use the packaged JavaScript runtime for YouTube extraction."""
from pathlib import Path
import shutil
import sys


def runtime_options():
    bundled = Path(sys.executable).parent / 'node.exe'
    node = str(bundled) if getattr(sys, 'frozen', False) and bundled.is_file() else shutil.which('node')
    return {'js_runtimes': {'node': {'path': node}}} if node else {}


def verify_runtime():
    """Offline build check, including data files inside the frozen application."""
    import yt_dlp
    import yt_dlp_ejs.yt.solver
    assert yt_dlp_ejs.yt.solver.core() and yt_dlp_ejs.yt.solver.lib()
    with yt_dlp.YoutubeDL({**runtime_options(), 'quiet': True}) as ydl:
        runtime = ydl._js_runtimes.get('node')
        assert runtime and runtime.info, 'Bundled Node runtime is unavailable'
        return {'ok': True, 'runtime': str(runtime.info)}
