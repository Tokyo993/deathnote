from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton,
    QListWidget, QLineEdit
)
import db


class EventsTab(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Event title")
        layout.addWidget(self.title_input)

        add_btn = QPushButton("Add Event")
        add_btn.clicked.connect(self.add_event)
        layout.addWidget(add_btn)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.refresh()

    def add_event(self):
        title = self.title_input.text().strip()
        if not title:
            return

        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO events(title) VALUES(?)",
                (title,)
            )

        self.title_input.clear()
        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        with db.get_conn() as conn:
            rows = conn.execute("SELECT id, title FROM events").fetchall()

        for r in rows:
            self.list_widget.addItem(r[1])
