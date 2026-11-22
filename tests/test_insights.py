"""Library Insights: the Media by year chart."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from onthisday.core.models import AnalyticsResult, YearMediaCount
from onthisday.ui.pages.insights_page import LibraryInsightsPage
from onthisday.ui.theme.colors import LIGHT

APP = QApplication.instance() or QApplication([])


def result(years: int) -> AnalyticsResult:
    by_year = tuple(YearMediaCount(2000 + index, 5 + index, 1) for index in range(years))
    total = sum(entry.total for entry in by_year)
    return AnalyticsResult(total - years, years, total, (4, 18), 12, 2020, 9, by_year, 4, 30)


class ChartWidthTests(unittest.TestCase):
    def setUp(self):
        self.page = LibraryInsightsPage(LIGHT)
        self.addCleanup(self.page.close)
        self.page.resize(1380, 820)
        self.page.show()
        APP.processEvents()

    def viewport_width(self) -> int:
        return self.page.chart.parentWidget().width()

    def test_a_few_years_fill_the_card(self):
        self.page.set_result(result(7))
        APP.processEvents()
        self.assertEqual(self.page.chart.width(), self.viewport_width())

    def test_many_years_keep_their_width_and_scroll(self):
        self.page.set_result(result(30))
        APP.processEvents()
        self.assertGreater(self.page.chart.width(), self.viewport_width())


if __name__ == "__main__":
    unittest.main()
