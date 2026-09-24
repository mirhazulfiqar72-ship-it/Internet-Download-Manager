"""Check the actual windowed executable without requiring YouTube network access."""
import json
from pathlib import Path
import subprocess
import tempfile

exe = Path('dist/InternetDownloadManager/InternetDownloadManager.exe').resolve()
with tempfile.TemporaryDirectory() as tmp:
    report = Path(tmp) / 'runtime.json'
    subprocess.run([str(exe), '--verify-media-runtime', str(report)], check=True, timeout=60)
    result = json.loads(report.read_text(encoding='utf-8'))
    assert result.get('ok'), result
    print('Frozen executable runtime and solver verified:', result)
