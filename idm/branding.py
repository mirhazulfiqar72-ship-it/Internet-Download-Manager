import os, sys
from pathlib import Path
from PySide6.QtGui import QIcon


def resource_path(*parts):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def app_icon():
    """Return the bundled original application icon."""
    for name in ('app_icon.ico', 'app_icon.png', 'app_icon_64.png'):
        p = resource_path('assets', name)
        if p.exists():
            icon = QIcon(str(p))
            if not icon.isNull():
                return icon
    return QIcon()
