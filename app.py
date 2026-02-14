import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QFileDialog, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QInputDialog, QTextEdit, QDialog, QDialogButtonBox, QLabel, QLineEdit
)


# ----------------------------
# Dialog: create/edit card
# ----------------------------
class CardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новая карточка")

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Название:"))
        self.title_edit = QLineEdit()
        layout.addWidget(self.title_edit)

        layout.addWidget(QLabel("Описание:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(120)
        layout.addWidget(self.desc_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        return self.title_edit.text().strip(), self.desc_edit.toPlainText().strip()


# ----------------------------
# Base: draggable + resizable item (simple corner resize)
# ----------------------------
class DraggableResizableItem(QGraphicsItem):
    """
    MVP-resize:
    - Drag anywhere to move
    - Resize by dragging bottom-right corner zone (resize handle)
    """
    HANDLE_SIZE = 14

    def __init__(self):
        super().__init__()
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

        self._resizing = False
        self._resize_start_pos = QPointF()
        self._start_w = 0.0
        self._start_h = 0.0

    def _handle_rect(self, rect: QRectF) -> QRectF:
        return QRectF(
            rect.right() - self.HANDLE_SIZE,
            rect.bottom() - self.HANDLE_SIZE,
            self.HANDLE_SIZE,
            self.HANDLE_SIZE
        )

    def hoverMoveEvent(self, event):
        if self._handle_rect(self.boundingRect()).contains(event.pos()):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._handle_rect(self.boundingRect()).contains(event.pos()):
            self._resizing = True
            self._resize_start_pos = event.pos()
            self._start_w, self._start_h = self._get_size()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.pos() - self._resize_start_pos
            new_w = max(80, self._start_w + delta.x())
            new_h = max(60, self._start_h + delta.y())
            self._set_size(new_w, new_h)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # abstract-ish
    def _get_size(self) -> tuple[float, float]:
        raise NotImplementedError

    def _set_size(self, w: float, h: float) -> None:
        raise NotImplementedError


# ----------------------------
# Card item with progress bar (interactive)
# ----------------------------
@dataclass
class CardData:
    title: str
    desc: str
    progress: int = 0  # 0..100


class CardItem(DraggableResizableItem):
    def __init__(self, data: CardData, w=260, h=170):
        super().__init__()
        self.data = data
        self._w = float(w)
        self._h = float(h)

        self._dragging_progress = False

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def _get_size(self):
        return self._w, self._h

    def _set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._w, self._h = float(w), float(h)

    def _progress_rect(self) -> QRectF:
        # progress bar near bottom
        margin = 12
        bar_h = 14
        y = self._h - margin - bar_h
        return QRectF(margin, y, self._w - 2 * margin, bar_h)

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.boundingRect()

        # background
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg = QColor("#1a1a1a")
        border = QColor("#3a3a3a")
        if self.isSelected():
            border = QColor("#6a6a6a")

        painter.setPen(QPen(border, 2))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(rect, 10, 10)

        # title
        painter.setPen(QPen(QColor("#eaeaea")))
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(12, 10, self._w - 24, 22), Qt.TextSingleLine, self.data.title)

        # desc
        desc_font = QFont()
        desc_font.setPointSize(9)
        desc_font.setBold(False)
        painter.setFont(desc_font)
        painter.setPen(QPen(QColor("#cfcfcf")))
        painter.drawText(QRectF(12, 36, self._w - 24, self._h - 80), Qt.TextWordWrap, self.data.desc)

        # progress label
        painter.setPen(QPen(QColor("#bdbdbd")))
        painter.drawText(QRectF(12, self._h - 44, self._w - 24, 16),
                         Qt.TextSingleLine, f"Прогресс: {self.data.progress}%")

        # progress bar
        bar = self._progress_rect()
        painter.setPen(QPen(QColor("#2f2f2f"), 1))
        painter.setBrush(QBrush(QColor("#101010")))
        painter.drawRoundedRect(bar, 6, 6)

        fill_w = bar.width() * (self.data.progress / 100.0)
        fill = QRectF(bar.x(), bar.y(), fill_w, bar.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#4a90e2")))
        painter.drawRoundedRect(fill, 6, 6)

        # resize handle
        handle = self._handle_rect(rect)
        painter.setPen(QPen(QColor("#6a6a6a"), 1))
        painter.setBrush(QBrush(QColor("#2a2a2a")))
        painter.drawRect(handle)

    def mousePressEvent(self, event):
        # progress interaction
        if event.button() == Qt.LeftButton and self._progress_rect().contains(event.pos()):
            self._dragging_progress = True
            self._set_progress_from_pos(event.pos().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_progress:
            self._set_progress_from_pos(event.pos().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging_progress:
            self._dragging_progress = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_progress_from_pos(self, x: float):
        bar = self._progress_rect()
        v = (x - bar.x()) / max(1.0, bar.width())
        v = max(0.0, min(1.0, v))
        self.data.progress = int(round(v * 100))
        self.update()


# ----------------------------
# Image item (draggable + resizable by corner)
# ----------------------------
class ImageItem(DraggableResizableItem):
    def __init__(self, pixmap: QPixmap, w=None, h=None):
        super().__init__()
        self._original = pixmap
        if w is None or h is None:
            w = max(120, pixmap.width())
            h = max(120, pixmap.height())
            # ограничим стартовый размер, чтобы не было гигантских фоток
            scale = min(1.0, 420 / max(w, h))
            w, h = w * scale, h * scale

        self._w = float(w)
        self._h = float(h)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def _get_size(self):
        return self._w, self._h

    def _set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._w, self._h = float(w), float(h)

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.boundingRect()

        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scaled = self._original.scaled(int(self._w), int(self._h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(0, 0, scaled)

        # selection border
        if self.isSelected():
            painter.setPen(QPen(QColor("#aaaaaa"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        # resize handle
        handle = self._handle_rect(rect)
        painter.setPen(QPen(QColor("#6a6a6a"), 1))
        painter.setBrush(QBrush(QColor("#2a2a2a")))
        painter.drawRect(handle)


# ----------------------------
# Main window: one board + russian UI
# ----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MyAsana — Доска")
        self.resize(1200, 760)

        root = QWidget()
        self.setCentralWidget(root)

        main = QHBoxLayout(root)

        # left panel
        left = QVBoxLayout()
        btn_add_card = QPushButton("➕ Добавить карточку")
        btn_add_img = QPushButton("🖼️ Добавить картинку")
        btn_delete = QPushButton("🗑️ Удалить выбранное")
        left.addWidget(btn_add_card)
        left.addWidget(btn_add_img)
        left.addWidget(btn_delete)
        left.addStretch(1)

        # board
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 2000, 1200)  # большая область
        self.view = QGraphicsView(self.scene)
        self.view.setDragMode(QGraphicsView.RubberBandDrag)

        main.addLayout(left, 0)
        main.addWidget(self.view, 1)

        self.apply_dark_theme()

        # actions
        btn_add_card.clicked.connect(self.add_card)
        btn_add_img.clicked.connect(self.add_image)
        btn_delete.clicked.connect(self.delete_selected)

    def apply_dark_theme(self):
        self.setStyleSheet("""
            QWidget { background: #0f0f0f; color: #eaeaea; }
            QPushButton { background: #1e1e1e; border: 1px solid #2e2e2e; padding: 8px; text-align: left; }
            QPushButton:hover { background: #262626; }
        """)
        self.scene.setBackgroundBrush(QColor("#111111"))

    def add_card(self):
        dlg = CardDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        title, desc = dlg.get_data()
        if not title:
            return

        item = CardItem(CardData(title=title, desc=desc, progress=0))
        item.setPos(40, 40)
        self.scene.addItem(item)

    def add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбери изображение", "", "Изображения (*.png *.jpg *.jpeg *.webp)"
        )
        if not path:
            return
        pix = QPixmap(path)
        if pix.isNull():
            return

        item = ImageItem(pix)
        item.setPos(80, 80)
        self.scene.addItem(item)

    def delete_selected(self):
        for it in self.scene.selectedItems():
            self.scene.removeItem(it)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
