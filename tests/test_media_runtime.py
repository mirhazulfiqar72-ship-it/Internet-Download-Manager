import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from idm.media_runtime import runtime_options, verify_runtime
from idm.browser_formats import probe_formats

assert verify_runtime()['ok']
with patch('sys.frozen', True, create=True), patch('sys.executable', 'C:/IDM/InternetDownloadManager.exe'), patch('pathlib.Path.is_file', return_value=True):
    assert runtime_options()['js_runtimes']['node']['path'].replace('\\', '/') == 'C:/IDM/node.exe'
info = {'title': 'Test', 'formats': [{'height': 2160, 'url': 'https://example.com/video', 'vcodec': 'vp9'}]}
with patch('yt_dlp.YoutubeDL') as ydl, patch('idm.media_selection.prepare_format_sizes', side_effect=OSError('cache unavailable')):
    ydl.return_value.__enter__.return_value.extract_info.return_value = info
    result = probe_formats('https://www.youtube.com/watch?v=uu2XnaQ3axk')
    assert result['ok'] and result['formats'] == [{'quality': '2160', 'type': 'MKV'}], result
with patch('yt_dlp.YoutubeDL', side_effect=RuntimeError('Specific extractor failure')):
    assert 'Specific extractor failure' in probe_formats('https://www.youtube.com/watch?v=uu2XnaQ3axk')['error']
print('Runtime, quality-cache isolation and extraction error checks passed')
