import calendar

from PySide6.QtCharts import QBarCategoryAxis, QBarSet, QChart, QChartView, QStackedBarSeries, QValueAxis
from PySide6.QtCore import QMargins, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QStackedWidget,
    QToolTip, QVBoxLayout, QWidget,
)

from ...core.models import AnalyticsResult
from ..theme.colors import Palette
from ..widgets.common import EmptyState, PageHeader


class InsightCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setProperty("role", "surface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(5)
        caption = QLabel(title)
        caption.setProperty("muted", True)
        self.value = QLabel("—")
        self.value.setProperty("role", "insightValue")
        self.detail = QLabel()
        self.detail.setProperty("subtle", True)
        self.detail.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def set_value(self, value: str, detail: str) -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class MediaByYearChart(QChartView):
    def __init__(self, colors: Palette, parent=None):
        super().__init__(parent)
        self._colors = colors
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(265)
        self.setAccessibleName("Photo and video counts by capture year")

    def set_data(self, result: AnalyticsResult) -> None:
        chart = QChart()
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.legend().setVisible(False)

        if not result.media_by_year:
            self.setChart(chart)
            self.setMinimumWidth(620)
            self.set_theme_colors(self._colors)
            return

        photos = QBarSet("Photos")
        videos = QBarSet("Videos")
        for entry in result.media_by_year:
            photos.append(entry.photos)
            videos.append(entry.videos)
        series = QStackedBarSeries()
        series.append(photos)
        series.append(videos)
        chart.addSeries(series)

        years = [str(entry.year) for entry in result.media_by_year]
        categories = QBarCategoryAxis()
        categories.append(years)
        if len(years) > 12:
            categories.setLabelsAngle(-45)
        values = QValueAxis()
        maximum = max((entry.total for entry in result.media_by_year), default=1)
        values.setRange(0, max(1, maximum * 1.12))
        values.setLabelFormat("%d")
        values.applyNiceNumbers()
        chart.addAxis(categories, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(values, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(categories)
        series.attachAxis(values)

        photos.hovered.connect(lambda active, index: self._show_tooltip(active, index, "Photos", result))
        videos.hovered.connect(lambda active, index: self._show_tooltip(active, index, "Videos", result))
        self.setChart(chart)
        self.setMinimumWidth(max(620, len(years) * 48 + 90))
        self.set_theme_colors(self._colors)

    def set_theme_colors(self, colors: Palette) -> None:
        self._colors = colors
        self.setBackgroundBrush(QBrush(QColor(colors.surface)))
        chart = self.chart()
        if not chart:
            return
        text = QBrush(QColor(colors.text))
        muted = QBrush(QColor(colors.text_muted))
        grid = QPen(QColor(colors.border))
        chart.setTitleBrush(text)
        chart.legend().setLabelBrush(muted)
        if not chart.series():
            return
        series = chart.series()[0]
        sets = series.barSets()
        if len(sets) == 2:
            sets[0].setColor(QColor(colors.accent))
            sets[1].setColor(QColor(colors.success))
        for axis in chart.axes():
            axis.setLabelsBrush(muted)
            axis.setTitleBrush(muted)
            axis.setGridLinePen(grid)
            axis.setLinePen(grid)

    @staticmethod
    def _show_tooltip(active: bool, index: int, kind: str, result: AnalyticsResult) -> None:
        if not active or not 0 <= index < len(result.media_by_year):
            QToolTip.hideText()
            return
        entry = result.media_by_year[index]
        count = entry.photos if kind == "Photos" else entry.videos
        QToolTip.showText(QCursor.pos(), f"{entry.year} · {kind}: {count:,} · Total: {entry.total:,}")


class LoadingState(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "surface")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        title = QLabel("Loading Library Insights…")
        title.setProperty("role", "section")
        detail = QLabel("Reading the current folder’s media index")
        detail.setProperty("muted", True)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedWidth(240)
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(detail, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(progress, alignment=Qt.AlignmentFlag.AlignCenter)


class LibraryInsightsPage(QWidget):
    back_requested = Signal()
    choose_folder_requested = Signal()
    rescan_requested = Signal()
    retry_requested = Signal()

    def __init__(self, colors: Palette, parent=None):
        super().__init__(parent)
        self._colors = colors
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)
        header = PageHeader("Library Insights", "A snapshot of the indexed media in your current folder")
        back = QPushButton("Back")
        back.setProperty("variant", "ghost")
        back.clicked.connect(self.back_requested)
        header.actions.addWidget(back)
        outer.addWidget(header)

        self.states = QStackedWidget()
        self.no_folder = EmptyState(
            "No media folder selected", "Choose a photo and video folder to see Library Insights.", "Choose Folder"
        )
        self.no_folder.action_requested.connect(self.choose_folder_requested)
        self.empty = EmptyState(
            "Your media index is empty", "Rescan the selected folder to discover photos and videos.", "Rescan Library"
        )
        self.empty.action_requested.connect(self.rescan_requested)
        self.loading = LoadingState()
        self.error = EmptyState(
            "Library Insights are unavailable", "The media index could not be read. Try again or rescan the library.", "Try Again"
        )
        self.error.action_requested.connect(self.retry_requested)
        self.content = self._build_content()
        for widget in (self.no_folder, self.empty, self.loading, self.error, self.content):
            self.states.addWidget(widget)
        outer.addWidget(self.states, 1)
        self.show_no_folder()

    def _build_content(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 20)
        layout.setSpacing(16)
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        self.cards = {
            "photos": InsightCard("Indexed photos"),
            "videos": InsightCard("Indexed videos"),
            "total": InsightCard("All indexed media"),
            "day": InsightCard("Busiest calendar day"),
            "year": InsightCard("Largest year"),
            "month": InsightCard("Most active month"),
        }
        for index, card in enumerate(self.cards.values()):
            cards.addWidget(card, index // 3, index % 3)
            cards.setColumnStretch(index % 3, 1)
        layout.addLayout(cards)

        chart_surface = QFrame()
        chart_surface.setProperty("role", "surface")
        chart_layout = QVBoxLayout(chart_surface)
        chart_layout.setContentsMargins(12, 12, 12, 8)
        self.chart_title = QLabel("Media by year")
        self.chart_title.setProperty("role", "section")
        self.chart_note = QLabel()
        self.chart_note.setProperty("muted", True)
        chart_layout.addWidget(self.chart_title)
        chart_layout.addWidget(self.chart_note)
        self.chart = MediaByYearChart(self._colors)
        chart_scroll = QScrollArea()
        chart_scroll.setWidget(self.chart)
        chart_scroll.setWidgetResizable(False)
        chart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        chart_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chart_scroll.setMinimumHeight(286)
        chart_layout.addWidget(chart_scroll)
        layout.addWidget(chart_surface)
        layout.addStretch()
        scroll.setWidget(body)
        return scroll

    def show_no_folder(self) -> None:
        self.states.setCurrentWidget(self.no_folder)

    def show_loading(self) -> None:
        self.states.setCurrentWidget(self.loading)

    def show_error(self) -> None:
        self.states.setCurrentWidget(self.error)

    def set_result(self, result: AnalyticsResult) -> None:
        if result.combined_total == 0:
            self.states.setCurrentWidget(self.empty)
            return
        day = f"{calendar.month_name[result.busiest_day[0]]} {result.busiest_day[1]}" if result.busiest_day else "—"
        month = calendar.month_name[result.most_active_month] if result.most_active_month else "—"
        self.cards["photos"].set_value(f"{result.total_photos:,}", "Every indexed photo")
        self.cards["videos"].set_value(f"{result.total_videos:,}", "Every indexed video")
        self.cards["total"].set_value(f"{result.combined_total:,}", "Photos and videos combined")
        self.cards["day"].set_value(day, f"{result.busiest_day_count:,} media items")
        year = str(result.largest_year) if result.largest_year is not None else "—"
        self.cards["year"].set_value(year, f"{result.largest_year_count:,} media items")
        self.cards["month"].set_value(month, f"{result.most_active_month_count:,} media items")
        self._update_chart_note(bool(result.media_by_year))
        self.chart.set_data(result)
        self.states.setCurrentWidget(self.content)

    def set_theme_colors(self, colors: Palette) -> None:
        self._colors = colors
        self._update_chart_note(bool(self.chart.chart().series()))
        self.chart.set_theme_colors(colors)

    def _update_chart_note(self, has_years: bool) -> None:
        if not has_years:
            self.chart_note.setText("No capture years are available for the indexed media.")
            return
        self.chart_note.setText(
            f'<span style="color:{self._colors.accent}">■</span> Photos&nbsp;&nbsp;&nbsp;'
            f'<span style="color:{self._colors.success}">■</span> Videos'
        )
