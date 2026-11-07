"""A small add/remove list editor for the Settings dialog (blocked sites and blocked apps). Qt only."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QLineEdit, QListWidget, QVBoxLayout, QWidget

import blocklist
from widgets import LINE, RAISED, SURFACE, TEXT, button, label


class _Entry(QLineEdit):
    """Enter adds the entry instead of reaching the dialog's default Save button."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ListEditor(QWidget):
    """Edits a list of normalized entries. Nothing is stored here; the dialog saves with the other settings."""

    def __init__(self, name, placeholder, normalize, invalid_message, parent=None):
        super().__init__(parent)
        self.normalize = normalize
        self.invalid_message = invalid_message
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.entry = _Entry()
        self.setFocusProxy(self.entry)      # the caption's buddy lands in the text box
        self.entry.setAccessibleName(f"New {name}")
        self.entry.setPlaceholderText(placeholder)
        self.entry.setMaxLength(300)
        self.add_button = button("Add", self.add_pending)
        self.add_button.setAutoDefault(False)
        self.add_button.setAccessibleName(f"Add {name}")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.entry, 1)
        row.addWidget(self.add_button)
        layout.addLayout(row)

        self.message = label("", "error", True)
        self.message.hide()
        layout.addWidget(self.message)

        self.list = QListWidget()
        self.list.setAccessibleName(f"Blocked {name} list")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(96)
        self.list.setMaximumHeight(150)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 5px 8px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {RAISED}; color: {TEXT}; }}")
        layout.addWidget(self.list)

        self.remove_button = button("Remove selected", self.remove_selected)
        self.remove_button.setAutoDefault(False)
        self.remove_button.setAccessibleName(f"Remove selected {name}")
        self.remove_button.setEnabled(False)
        layout.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.entry.returnPressed.connect(self.add_pending)
        self.entry.textChanged.connect(lambda *_: self.message.hide())
        self.list.itemSelectionChanged.connect(lambda: self.remove_button.setEnabled(bool(self.list.selectedItems())))

    def tab_widgets(self):
        return [self.entry, self.add_button, self.list, self.remove_button]

    def set_items(self, values):
        self.list.clear()
        self.list.addItems(values)

    def items(self):
        return [self.list.item(row).text() for row in range(self.list.count())]

    def add_pending(self):
        """Add the typed entry; returns False (with a message) when it isn't valid. Empty text is fine."""
        text = self.entry.text().strip()
        if not text:
            return True
        entry = self.normalize(text)
        if entry is None:
            self.message.setText(self.invalid_message)
            self.message.show()
            return False
        if len(self.items()) >= blocklist.MAX_ENTRIES and entry not in self.items():
            self.message.setText(f"The list is full ({blocklist.MAX_ENTRIES} entries). Remove one first.")
            self.message.show()
            return False
        self.set_items(sorted({*self.items(), entry}))
        self.entry.clear()
        self.message.hide()
        return True

    def remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
