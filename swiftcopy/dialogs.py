"""Collision and error dialogs."""
from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .engine import Prompt, format_size


def _when(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%m/%d/%Y  %I:%M %p")


class CollisionDialog(QDialog):
    """'A file with this name already exists' - returns (answer, apply_all)."""

    def __init__(self, prompt: Prompt, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File already exists")
        self.setMinimumWidth(640)
        self.answer = "cancel"
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        title = QLabel(f"<b>{os.path.basename(prompt.target)}</b> already exists in the destination.")
        title.setWordWrap(True)
        lay.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        newer_src = prompt.src_mtime > prompt.dst_mtime + 2
        rows = [
            ("", "<b>Size</b>", "<b>Modified</b>"),
            ("<b>Copying</b>", format_size(prompt.src_size),
             _when(prompt.src_mtime) + ("  (newer)" if newer_src else "")),
            ("<b>Existing</b>", format_size(prompt.dst_size),
             _when(prompt.dst_mtime) + ("" if newer_src else "  (newer)")),
        ]
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                grid.addWidget(QLabel(text), r, c)
        lay.addLayout(grid)

        path = QLabel(prompt.target)
        path.setObjectName("muted")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(path)

        self.all_box = QCheckBox("Do this for all conflicts in this transfer")
        lay.addWidget(self.all_box)

        buttons = QHBoxLayout()
        for label, answer, primary in [
            ("Overwrite", "overwrite", True),
            ("Overwrite if newer", "newer", False),
            ("Keep both", "rename", False),
            ("Skip", "skip", False),
            ("Cancel all", "cancel", False),
        ]:
            b = QPushButton(label)
            if primary:
                b.setObjectName("primary")
                b.setDefault(True)
            b.clicked.connect(lambda _=False, a=answer: self._done(a))
            buttons.addWidget(b)
        lay.addLayout(buttons)

    def _done(self, answer: str) -> None:
        self.answer = answer
        self.accept()

    def result_tuple(self):
        return self.answer, self.all_box.isChecked()


class ErrorDialog(QDialog):
    def __init__(self, prompt: Prompt, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Couldn't copy a file")
        self.setMinimumWidth(500)
        self.answer = "cancel"
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        head = QLabel(f"<b>{os.path.basename(prompt.item.src)}</b> couldn't be copied.")
        head.setWordWrap(True)
        lay.addWidget(head)
        msg = QLabel(prompt.message)
        msg.setObjectName("error")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        path = QLabel(prompt.item.src)
        path.setObjectName("muted")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(path)

        self.all_box = QCheckBox("Skip every file that fails in this transfer")
        lay.addWidget(self.all_box)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for label, answer, primary in [("Retry", "retry", True), ("Skip", "skip", False),
                                       ("Cancel all", "cancel", False)]:
            b = QPushButton(label)
            if primary:
                b.setObjectName("primary")
                b.setDefault(True)
            b.clicked.connect(lambda _=False, a=answer: self._done(a))
            buttons.addWidget(b)
        lay.addLayout(buttons)

    def _done(self, answer: str) -> None:
        self.answer = answer
        self.accept()

    def result_tuple(self):
        if self.all_box.isChecked() and self.answer == "retry":
            return "retry", False
        return self.answer, self.all_box.isChecked()
