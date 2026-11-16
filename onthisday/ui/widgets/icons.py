"""Small icons Qt's standard set lacks, drawn in the theme's colours."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap


def gear_icon(color: str, size: int = 64) -> QIcon:
    """A settings gear: eight teeth around a ring."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = QPointF(size / 2, size / 2)
    outer, inner, hole = size * 0.46, size * 0.34, size * 0.14
    teeth = 8
    gear = QPainterPath()
    for index in range(teeth * 4):
        # Each tooth: two points on the outer radius, then two on the inner one.
        angle = (index - 0.5) * math.pi * 2 / (teeth * 4)
        radius = outer if index % 4 in (0, 1) else inner
        point = QPointF(center.x() + radius * math.cos(angle), center.y() + radius * math.sin(angle))
        gear.moveTo(point) if index == 0 else gear.lineTo(point)
    gear.closeSubpath()
    gear.addEllipse(center, hole, hole)  # odd-even fill leaves it hollow
    painter.fillPath(gear, QColor(color))
    painter.end()
    return QIcon(pixmap)
