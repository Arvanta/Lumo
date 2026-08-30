# -*- coding: utf-8 -*-
"""Headless smoke test for the MPV Player UI (no mpv engine available)."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# make sure mpv import fails gracefully (it should - not installed here)
import main as m
assert m.MPV_AVAILABLE is False, "mpv should NOT be available in the sandbox"

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer

# silence modal dialogs in headless mode
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

app = QApplication(sys.argv)
win = m.PlayerWindow()
win.show()
win.setFocus()

# exercise some code paths without an engine
win.toggle_fullscreen()
win.toggle_fullscreen()
win.change_volume(5)
win.seek_relative(2)
win.toggle_pause()
win._poll_activity()
win.seek_bar.set_duration(3600)
win.seek_bar.set_position(120)
win.seek_bar.set_ranges([(0, 900), (1200, 2000)])
win.seek_bar._show_tip(50)
win.seek_bar._hide_tip()
win.drop_banner.show(); win.drop_banner.hide()

# icons
for kind in ["play", "pause", "replay", "volume", "muted",
             "fullscreen", "fullscreen_exit", "settings", "cc", "open"]:
    assert not m.make_icon(kind).isNull(), kind

# settings dialog construction
dlg = m.SettingsDialog(win, ["Arial", "Verdana"], win.cfg)
vals = dlg.values()
assert "seek_step" in vals
dlg.deleteLater()

# quit after a moment
def finish():
    win.close()
    app.quit()

QTimer.singleShot(300, finish)
rc = app.exec_()
print("SMOKE TEST OK  rc=", rc)
