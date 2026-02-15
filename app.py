import sys
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QFileDialog, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QTextEdit, QDialog, QDialogButtonBox, QLabel, QLineEdit,
    QMessageBox, QColorDialog, QInputDialog, QGraphicsTextItem
)

# ----------------------------
# DB
# ----------------------------
DB_PATH = Path(__file__).with_name("deathnote.db")


def db_conn():
    return sqlite3.connect(DB_PATH)


def db_init():
    with db_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS board_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,          -- 'card' | 'image' | 'text' | 'draw'
            x REAL NOT NULL,
            y REAL NOT NULL,
            w REAL NOT NULL,
            h REAL NOT NULL,
            z INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL        -- JSON
        )
        """)


def db_insert_item(item_type: str, x: float, y: float, w: float, h: float, payload: dict, z: int = 0) -> int:
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO board_items(type, x, y, w, h, z, payload) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (item_type, x, y, w, h, z, json.dumps(payload, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def db_update_geom(item_id: int, x: float, y: float, w: float, h: float):
    with db_conn() as conn:
        conn.execute(
            "UPDATE board_items SET x=?, y=?, w=?, h=? WHERE id=?",
            (float(x), float(y), float(w), float(h), int(item_id)),
        )


def db_update_payload(item_id: int, payload: dict):
    with db_conn() as conn:
        conn.execute(
            "UPDATE board_items SET payload=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), int(item_id)),
        )


def db_delete(item_id: int):
    with db_conn() as conn:
        conn.execute("DELETE FROM board_items WHERE id=?", (int(item_id),))


def db_load_all():
    with db_conn() as conn:
        rows = conn.execute("SELECT id, type, x, y, w, h, z, payload FROM board_items ORDER BY z, id").fetchall()
    out = []
    for r in rows:
        out.append({
            "id": int(r[0]),
            "type": r[1],
            "x": float(r[2]),
            "y": float(r[3]),
            "w": float(r[4]),
            "h": float(r[5]),
            "z": int(r[6]),
            "payload": json.loads(r[7]) if r[7] else {},
        })
    return out


# ----------------------------
# Dialog: create card
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
# Base: draggable + resizable (corner)
# ----------------------------
class DraggableResizableItem(QGraphicsItem):
    HANDLE_SIZE = 14

    def __init__(self, item_id: int | None):
        super().__init__()
        self.item_id = item_id

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
            new_w = max(100, self._start_w + delta.x())
            new_h = max(70, self._start_h + delta.y())
            self._set_size(new_w, new_h)
            self._persist()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._persist()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._persist()
        return super().itemChange(change, value)

    def _persist(self):
        if not self.item_id:
            return
        x, y = self.pos().x(), self.pos().y()
        w, h = self._get_size()
        db_update_geom(self.item_id, x, y, w, h)

    def _get_size(self) -> tuple[float, float]:
        raise NotImplementedError

    def _set_size(self, w: float, h: float) -> None:
        raise NotImplementedError


# ----------------------------
# Card item
# ----------------------------
@dataclass
class CardData:
    title: str
    desc: str
    progress: int = 0


class CardItem(DraggableResizableItem):
    def __init__(self, item_id: int | None, data: CardData, w=300, h=190):
        super().__init__(item_id)
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
        margin = 14
        bar_h = 14
        y = self._h - margin - bar_h
        return QRectF(margin, y, self._w - 2 * margin, bar_h)

    def paint(self, painter: QPainter, option, widget=None):
        rect = self.boundingRect()
        painter.setRenderHint(QPainter.Antialiasing, True)

        card_bg = QColor("#1a1a1a")
        card_border = QColor("#3a3a3a")
        if self.isSelected():
            card_border = QColor("#7a7a7a")

        painter.setPen(QPen(card_border, 2))
        painter.setBrush(QBrush(card_bg))
        painter.drawRoundedRect(rect, 18, 18)

        painter.setPen(QPen(QColor("#f0f0f0")))
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(14, 12, self._w - 28, 22), Qt.TextSingleLine, self.data.title)

        desc_font = QFont()
        desc_font.setPointSize(9)
        painter.setFont(desc_font)
        painter.setPen(QPen(QColor("#d0d0d0")))
        painter.drawText(QRectF(14, 38, self._w - 28, self._h - 92), Qt.TextWordWrap, self.data.desc)

        painter.setPen(QPen(QColor("#bdbdbd")))
        painter.drawText(QRectF(14, self._h - 48, self._w - 28, 16),
                         Qt.TextSingleLine, f"Прогресс: {self.data.progress}%")

        bar = self._progress_rect()
        painter.setPen(QPen(QColor("#2f2f2f"), 1))
        painter.setBrush(QBrush(QColor("#0f0f0f")))
        painter.drawRoundedRect(bar, 7, 7)

        fill_w = bar.width() * (self.data.progress / 100.0)
        fill = QRectF(bar.x(), bar.y(), fill_w, bar.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#3a7bd5")))
        painter.drawRoundedRect(fill, 7, 7)

        handle = self._handle_rect(rect)
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setBrush(QBrush(QColor("#232323")))
        painter.drawRect(handle)

    def mousePressEvent(self, event):
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
        if self.item_id:
            db_update_payload(self.item_id, {
                "title": self.data.title,
                "desc": self.data.desc,
                "progress": self.data.progress,
            })


# ----------------------------
# Image item
# ----------------------------
class ImageItem(DraggableResizableItem):
    def __init__(self, item_id: int | None, pixmap: QPixmap, path: str, w=None, h=None):
        super().__init__(item_id)
        self.path = path
        self._original = pixmap

        if w is None or h is None:
            w0 = max(160, pixmap.width())
            h0 = max(160, pixmap.height())
            scale = min(1.0, 520 / max(w0, h0))
            w, h = w0 * scale, h0 * scale

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

        if self.isSelected():
            painter.setPen(QPen(QColor("#9a9a9a"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

        handle = self._handle_rect(rect)
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setBrush(QBrush(QColor("#232323")))
        painter.drawRect(handle)


# ----------------------------
# Text item (direct typing)
# ----------------------------
class BoardTextItem(QGraphicsTextItem):
    """
    Текст прямо на доске:
    - появляется по клику
    - сразу в режиме ввода
    - двигается мышкой
    - сохраняется (текст + цвет + позиция)
    """
    def __init__(self, item_id: int | None, text_color: QColor, html: str = ""):
        super().__init__()
        self.item_id = item_id
        self.setDefaultTextColor(text_color)
        if html:
            self.setHtml(html)

        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setTextInteractionFlags(Qt.TextEditorInteraction)

    def focusOutEvent(self, event):
        # сохранить при выходе из режима редактирования
        self._persist_payload()
        super().focusOutEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._persist_geom()
        return super().itemChange(change, value)

    def _persist_geom(self):
        if not self.item_id:
            return
        br = self.boundingRect()
        db_update_geom(self.item_id, self.pos().x(), self.pos().y(), br.width(), br.height())

    def _persist_payload(self):
        if not self.item_id:
            return
        payload = {
            "html": self.toHtml(),
            "color": self.defaultTextColor().name()
        }
        db_update_payload(self.item_id, payload)


# ----------------------------
# Custom view: modes + zoom
# ----------------------------
class BoardView(QGraphicsView):
    MODE_SELECT = "select"
    MODE_DRAW = "draw"
    MODE_TEXT = "text"
    MODE_ERASE = "erase"

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.mode = self.MODE_SELECT

        self._drawing = False
        self._current_path = None
        self._current_path_item = None

        self.draw_color = QColor("#111111")
        self.draw_width = 3

        self.setDragMode(QGraphicsView.RubberBandDrag)

        # callbacks
        self.on_new_text_at = None          # (scene_pos) -> None
        self.on_draw_finished = None        # (path_item, path, color, width) -> None
        self.on_erase_at = None             # (scene_pos) -> None

        self._zoom = 1.0

    def set_mode(self, mode: str):
        self.mode = mode
        if mode == self.MODE_SELECT:
            self.setDragMode(QGraphicsView.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.NoDrag)

    def _pen(self) -> QPen:
        return QPen(self.draw_color, self.draw_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def wheelEvent(self, event):
        # Ctrl + wheel -> zoom
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.15 if angle > 0 else 1 / 1.15
            self._zoom *= factor
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.mode == self.MODE_DRAW:
            self._drawing = True
            p = self.mapToScene(event.pos())
            self._current_path = QPainterPath(p)
            self._current_path_item = self.scene().addPath(self._current_path, self._pen())
            self._current_path_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self._current_path_item.setFlag(QGraphicsItem.ItemIsMovable, False)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self.mode == self.MODE_TEXT:
            p = self.mapToScene(event.pos())
            if self.on_new_text_at:
                self.on_new_text_at(p)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self.mode == self.MODE_ERASE:
            p = self.mapToScene(event.pos())
            if self.on_erase_at:
                self.on_erase_at(p)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing and self.mode == self.MODE_DRAW and self._current_path is not None:
            p = self.mapToScene(event.pos())
            self._current_path.lineTo(p)
            self._current_path_item.setPath(self._current_path)
            event.accept()
            return

        if self.mode == self.MODE_ERASE and (event.buttons() & Qt.LeftButton):
            p = self.mapToScene(event.pos())
            if self.on_erase_at:
                self.on_erase_at(p)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drawing and self.mode == self.MODE_DRAW:
            self._drawing = False
            if self.on_draw_finished and self._current_path is not None and self._current_path_item is not None:
                self.on_draw_finished(self._current_path_item, self._current_path, self.draw_color, self.draw_width)
            self._current_path = None
            self._current_path_item = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ----------------------------
# Main window
# ----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeathNote — Интерактивная доска")
        self.resize(1320, 840)

        root = QWidget()
        self.setCentralWidget(root)
        main = QHBoxLayout(root)

        # left panel
        left = QVBoxLayout()

        btn_select = QPushButton("🖱️ Режим: Выделение")
        btn_draw = QPushButton("✏️ Режим: Рисование")
        btn_text = QPushButton("📝 Режим: Текст")
        btn_erase = QPushButton("🧽 Режим: Ластик")
        left.addWidget(btn_select)
        left.addWidget(btn_draw)
        left.addWidget(btn_text)
        left.addWidget(btn_erase)

        left.addWidget(QLabel("—"))

        btn_draw_color = QPushButton("🎨 Цвет кисти")
        btn_draw_width = QPushButton("📏 Толщина кисти")
        btn_text_color = QPushButton("🔤 Цвет текста")
        btn_apply_text_color = QPushButton("✅ Применить цвет к выделенному тексту")
        left.addWidget(btn_draw_color)
        left.addWidget(btn_draw_width)
        left.addWidget(btn_text_color)
        left.addWidget(btn_apply_text_color)

        left.addWidget(QLabel("—"))

        btn_add_card = QPushButton("➕ Добавить карточку")
        btn_add_img = QPushButton("🖼️ Добавить картинку")
        btn_delete = QPushButton("🗑️ Удалить выбранное")
        btn_bg = QPushButton("🎨 Цвет фона")
        left.addWidget(btn_add_card)
        left.addWidget(btn_add_img)
        left.addWidget(btn_delete)
        left.addWidget(btn_bg)

        left.addStretch(1)

        # scene/view
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 3400, 2200)
        self.view = BoardView(self.scene)

        main.addLayout(left, 0)
        main.addWidget(self.view, 1)

        # background + defaults
        self.bg_color = QColor("#111111")
        self.current_text_color = QColor("#f2f2f2")

        self.apply_theme()

        # callbacks
        self.view.on_new_text_at = self.add_text_at
        self.view.on_draw_finished = self.save_draw_path
        self.view.on_erase_at = self.erase_at

        # wire modes
        btn_select.clicked.connect(lambda: self.view.set_mode(BoardView.MODE_SELECT))
        btn_draw.clicked.connect(lambda: self.view.set_mode(BoardView.MODE_DRAW))
        btn_text.clicked.connect(lambda: self.view.set_mode(BoardView.MODE_TEXT))
        btn_erase.clicked.connect(lambda: self.view.set_mode(BoardView.MODE_ERASE))

        # wire tools
        btn_draw_color.clicked.connect(self.pick_draw_color)
        btn_draw_width.clicked.connect(self.pick_draw_width)
        btn_text_color.clicked.connect(self.pick_text_color)
        btn_apply_text_color.clicked.connect(self.apply_text_color_to_selected)

        # objects
        btn_add_card.clicked.connect(self.add_card)
        btn_add_img.clicked.connect(self.add_image)
        btn_delete.clicked.connect(self.delete_selected)
        btn_bg.clicked.connect(self.pick_bg)

        self.load_from_db()

    def apply_theme(self):
        self.setStyleSheet("""
            QWidget { background: #0f0f0f; color: #eaeaea; }
            QPushButton {
                background: #1b1b1b;
                border: 1px solid #2b2b2b;
                padding: 9px;
                text-align: left;
                border-radius: 10px;
            }
            QPushButton:hover { background: #222222; }
        """)
        self.scene.setBackgroundBrush(self.bg_color)

    # ---------- pickers ----------
    def pick_bg(self):
        c = QColorDialog.getColor(self.bg_color, self, "Выбери цвет фона")
        if c.isValid():
            self.bg_color = c
            self.scene.setBackgroundBrush(self.bg_color)

    def pick_draw_color(self):
        c = QColorDialog.getColor(self.view.draw_color, self, "Выбери цвет кисти")
        if c.isValid():
            self.view.draw_color = c

    def pick_draw_width(self):
        v, ok = QInputDialog.getInt(self, "Толщина кисти", "Пиксели:", self.view.draw_width, 1, 40, 1)
        if ok:
            self.view.draw_width = v

    def pick_text_color(self):
        c = QColorDialog.getColor(self.current_text_color, self, "Выбери цвет текста")
        if c.isValid():
            self.current_text_color = c

    def apply_text_color_to_selected(self):
        changed = 0
        for it in self.scene.selectedItems():
            if isinstance(it, BoardTextItem):
                it.setDefaultTextColor(self.current_text_color)
                it._persist_payload()
                changed += 1
        if changed == 0:
            QMessageBox.information(self, "Инфо", "Выдели текст на доске, чтобы применить цвет.")

    # ---------- load/save ----------
    def load_from_db(self):
        self.scene.clear()
        for rec in db_load_all():
            t = rec["type"]
            p = rec["payload"]

            if t == "card":
                data = CardData(
                    title=p.get("title", "Без названия"),
                    desc=p.get("desc", ""),
                    progress=int(p.get("progress", 0)),
                )
                item = CardItem(rec["id"], data, w=rec["w"], h=rec["h"])
                item.setPos(rec["x"], rec["y"])
                self.scene.addItem(item)

            elif t == "image":
                path = p.get("path")
                if not path:
                    continue
                pix = QPixmap(path)
                if pix.isNull():
                    continue
                item = ImageItem(rec["id"], pix, path=path, w=rec["w"], h=rec["h"])
                item.setPos(rec["x"], rec["y"])
                self.scene.addItem(item)

            elif t == "text":
                html = p.get("html", "")
                color = QColor(p.get("color", "#f2f2f2"))
                item = BoardTextItem(rec["id"], color, html=html)
                item.setPos(rec["x"], rec["y"])
                self.scene.addItem(item)

            elif t == "draw":
                pts = p.get("points", [])
                width = float(p.get("width", 3))
                color = QColor(p.get("color", "#111111"))

                if len(pts) < 2:
                    continue
                path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
                for x, y in pts[1:]:
                    path.lineTo(QPointF(x, y))

                pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                path_item = self.scene.addPath(path, pen)
                # связываем с БД id, чтобы ластик мог удалять
                path_item.setData(0, rec["id"])

    # ---------- create items ----------
    def add_card(self):
        dlg = CardDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        title, desc = dlg.get_data()
        if not title:
            QMessageBox.warning(self, "Ошибка", "Название не может быть пустым.")
            return

        data = {"title": title, "desc": desc, "progress": 0}
        x, y, w, h = 60.0, 60.0, 300.0, 190.0
        item_id = db_insert_item("card", x, y, w, h, data)

        item = CardItem(item_id, CardData(title=title, desc=desc, progress=0), w=w, h=h)
        item.setPos(x, y)
        self.scene.addItem(item)
        item.setSelected(True)
        self.view.centerOn(item)

    def add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбери изображение", "", "Изображения (*.png *.jpg *.jpeg *.webp)"
        )
        if not path:
            return

        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить картинку.")
            return

        tmp = ImageItem(None, pix, path=path)
        w, h = tmp._get_size()

        x, y = 120.0, 120.0
        item_id = db_insert_item("image", x, y, w, h, {"path": path})

        item = ImageItem(item_id, pix, path=path, w=w, h=h)
        item.setPos(x, y)
        self.scene.addItem(item)
        item.setSelected(True)
        self.view.centerOn(item)

    def add_text_at(self, scene_pos: QPointF):
        # создаём текст сразу в режиме печати
        x, y = float(scene_pos.x()), float(scene_pos.y())
        # размер текста хранить не обязательно — берём boundingRect позже
        item_id = db_insert_item("text", x, y, 1.0, 1.0, {"html": "", "color": self.current_text_color.name()})

        item = BoardTextItem(item_id, self.current_text_color, html="")
        item.setPos(x, y)
        self.scene.addItem(item)

        item.setSelected(True)
        item.setFocus(Qt.MouseFocusReason)
        self.view.centerOn(item)

    def save_draw_path(self, path_item, path: QPainterPath, color: QColor, width: int):
        # превращаем stroke в список точек
        pts = []
        for i in range(path.elementCount()):
            el = path.elementAt(i)
            pts.append([float(el.x), float(el.y)])

        if len(pts) < 2:
            self.scene.removeItem(path_item)
            return

        br = path.boundingRect()
        payload = {"points": pts, "width": width, "color": color.name()}
        draw_id = db_insert_item("draw", br.x(), br.y(), br.width(), br.height(), payload)

        # помечаем item, чтобы ластик мог удалить и из сцены, и из БД
        path_item.setData(0, draw_id)

    # ---------- eraser ----------
    def erase_at(self, scene_pos: QPointF):
        # удаляем только линии рисования (QGraphicsPathItem), которые рядом с курсором
        # (простая логика: всё, что "под курсором" в маленьком радиусе)
        r = 8.0
        hit = self.scene.items(QRectF(scene_pos.x() - r, scene_pos.y() - r, r * 2, r * 2))
        for it in hit:
            # QGraphicsPathItem тип напрямую не импортируем, проверяем по наличию data(0)
            draw_id = it.data(0)
            if draw_id:
                db_delete(int(draw_id))
                self.scene.removeItem(it)
                return  # стираем по одному за шаг (приятнее)

    # ---------- delete selected ----------
    def delete_selected(self):
        for it in list(self.scene.selectedItems()):
            # карточки/картинки имеют item_id
            if hasattr(it, "item_id") and getattr(it, "item_id"):
                db_delete(int(it.item_id))
                self.scene.removeItem(it)
                continue

            # текст
            if isinstance(it, BoardTextItem) and it.item_id:
                db_delete(int(it.item_id))
                self.scene.removeItem(it)
                continue


def main():
    db_init()
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
