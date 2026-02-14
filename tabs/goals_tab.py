from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton,
    QListWidget, QLineEdit, QSlider, QLabel
)
from PySide6.QtCore import Qt
import db


class GoalsTab(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Goal title")
        layout.addWidget(self.title_input)

        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 100)
        layout.addWidget(self.progress_slider)

        add_btn = QPushButton("Add Goal")
        add_btn.clicked.connect(self.add_goal)
        layout.addWidget(add_btn)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.refresh()

    def add_goal(self):
        title = self.title_input.text().strip()
        if not title:
            return

        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO goals(title, progress) VALUES(?, ?)",
                (title, self.progress_slider.value())
            )

        self.title_input.clear()
        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        with db.get_conn() as conn:
            rows = conn.execute("SELECT id, title, progress FROM goals").fetchall()

        for r in rows:
            self.list_widget.addItem(f"{r[1]} ({r[2]}%)")
