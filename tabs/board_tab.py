from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton,
    QFileDialog, QGraphicsView, QGraphicsScene
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem
from PySide6.QtCore import Qt
import db
import json


class DraggableImage(QGraphicsPixmapItem):
    def __init__(self, item_id, pixmap):
        super().__init__(pixmap)
        self.item_id = item_id
        self.setFlags(
            QGraphicsPixmapItem.ItemIsMovable |
            QGraphicsPixmapItem.ItemIsSelectable |
            QGraphicsPixmapItem.ItemSendsGeometryChanges
        )

    def itemChange(self, change, value):
        if change == QGraphicsPixmapItem.ItemPositionHasChanged:
            pos = self.pos()
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE board_items SET x=?, y=? WHERE id=?",
                    (pos.x(), pos.y(), self.item_id)
                )
        return super().itemChange(change, value)


class BoardTab(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        add_img_btn = QPushButton("Add Image")
        add_img_btn.clicked.connect(self.add_image)
        layout.addWidget(add_img_btn)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        layout.addWidget(self.view)

        self.load_items()

    def add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select image", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return

        pix = QPixmap(path)
        if pix.isNull():
            return

        payload = json.dumps({"path": path})

        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO board_items(type, x, y, payload) VALUES(?, ?, ?, ?)",
                ("image", 20, 20, payload)
            )
            item_id = cur.lastrowid

        item = DraggableImage(item_id, pix)
        item.setPos(20, 20)
        self.scene.addItem(item)

    def load_items(self):
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, type, x, y, payload FROM board_items"
            ).fetchall()

        for r in rows:
            if r[1] == "image":
                data = json.loads(r[4])
                pix = QPixmap(data["path"])
                if not pix.isNull():
                    item = DraggableImage(r[0], pix)
                    item.setPos(r[2], r[3])
                    self.scene.addItem(item)
