#!/usr/bin/env python3
import sys
import os
import json
import requests
import datetime
import matplotlib.pyplot as plt
from functools import lru_cache

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLineEdit, QLabel, QDoubleSpinBox,
    QMessageBox, QTextBrowser, QSplitter
)
from PyQt5.QtGui import QColor, QFont, QPixmap
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

FINNHUB_API_KEY = "d0suae9r01qid5qbgqjgd0suae9r01qid5qbgqk0"
REQUEST_TIMEOUT = 10  # seconds

class StockDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stock Portfolio Dashboard")
        self.setGeometry(100, 100, 1400, 850)

        self.holdings = []
        self.editing_index = None
        self.logo_label = QLabel()
        self.website_label = QLabel()
        self.website_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.website_label.setOpenExternalLinks(True)
        
        # Cache for API responses (symbol -> data, timestamp)
        self.quote_cache = {}
        self.profile_cache = {}
        self.cache_duration = 60  # Cache valid for 60 seconds

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.create_input_form()
        self.create_table()
        self.create_button_row()
        self.create_news_section()
        self.create_chart_and_logo_section()
        self.create_summary_box()

        self.load_holdings()

    def create_input_form(self):
        form_layout = QHBoxLayout()

        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("Ticker Symbol (e.g., AAPL)")
        form_layout.addWidget(self.symbol_input)

        self.shares_input = QDoubleSpinBox()
        self.shares_input.setDecimals(6)
        self.shares_input.setSingleStep(0.000001)
        self.shares_input.setMaximum(1000000.0)
        form_layout.addWidget(QLabel("Shares:"))
        form_layout.addWidget(self.shares_input)

        self.cost_input = QLineEdit()
        self.cost_input.setPlaceholderText("Cost Basis per Share")
        form_layout.addWidget(self.cost_input)

        self.add_button = QPushButton("Add Stock")
        self.add_button.clicked.connect(self.add_or_update_stock)
        form_layout.addWidget(self.add_button)

        self.layout.addLayout(form_layout)

    def create_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Symbol", "Shares", "Cost Basis", "Price",
            "Open", "High", "Low", "Prev Close", "Value", "P/L", "Exchange", "Industry"
        ])
        self.table.setStyleSheet("QTableWidget { font-family: monospace; font-size: 12pt; }")
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.show_news_for_selected)
        self.table.itemSelectionChanged.connect(self.show_logo_for_selected)
        self.layout.addWidget(self.table)

    def create_button_row(self):
        button_layout = QHBoxLayout()

        refresh_button = QPushButton("Refresh Prices")
        refresh_button.clicked.connect(self.refresh_prices)
        button_layout.addWidget(refresh_button)

        edit_button = QPushButton("Edit Selected Stock")
        edit_button.clicked.connect(self.edit_selected_stock)
        button_layout.addWidget(edit_button)

        delete_button = QPushButton("Delete Selected Stock")
        delete_button.clicked.connect(self.delete_selected_row)
        button_layout.addWidget(delete_button)

        clear_button = QPushButton("Clear All Stocks")
        clear_button.clicked.connect(self.clear_all_stocks)
        button_layout.addWidget(clear_button)

        self.layout.addLayout(button_layout)

    def create_news_section(self):
        self.news_box = QTextBrowser()
        self.news_box.setOpenExternalLinks(True)
        self.news_box.setFixedHeight(180)
        self.news_box.setStyleSheet("font-family: sans-serif; font-size: 10pt;")
        self.layout.addWidget(QLabel("Latest News:"))
        self.layout.addWidget(self.news_box)

    def create_chart_and_logo_section(self):
        splitter = QSplitter(Qt.Horizontal)

        self.logo_label.setFixedSize(200, 200)
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setText("Company Logo")

        logo_widget = QWidget()
        logo_layout = QVBoxLayout()
        logo_layout.addWidget(self.logo_label)
        logo_layout.addWidget(self.website_label)
        logo_widget.setLayout(logo_layout)

        self.figure_pie = Figure(figsize=(6, 4))
        self.canvas_pie = FigureCanvas(self.figure_pie)

        pie_widget = QWidget()
        pie_layout = QVBoxLayout()
        pie_layout.addWidget(self.canvas_pie)
        pie_widget.setLayout(pie_layout)

        splitter.addWidget(logo_widget)
        splitter.addWidget(pie_widget)
        splitter.setSizes([300, 800])
        self.layout.addWidget(splitter)

    def update_pie_chart(self, values):
        self.figure_pie.clear()
        ax = self.figure_pie.add_subplot(111)
        if values:
            labels = [v['symbol'] for v in values]
            sizes = [v['value'] for v in values]
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140)
            ax.axis('equal')
        else:
            ax.text(0.5, 0.5, 'No Data', ha='center')
        self.canvas_pie.draw()

    def show_logo_for_selected(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            self.logo_label.clear()
            self.logo_label.setText("Company Logo")
            self.website_label.clear()
            return
        row = selected_items[0].row()
        if row < 0 or row >= len(self.holdings):
            return

        symbol = self.holdings[row]['symbol']
        profile = self.get_profile(symbol)
        logo_url = profile.get("logo")
        website_url = profile.get("weburl")

        if logo_url:
            try:
                response = requests.get(logo_url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                self.logo_label.setPixmap(pixmap.scaled(self.logo_label.size(), Qt.KeepAspectRatio))
            except requests.exceptions.RequestException as e:
                print(f"Error loading logo: {e}")
                self.logo_label.setText("No Logo Available")
        else:
            self.logo_label.setText("No Logo Available")

        if website_url:
            self.website_label.setText(f"<a href=\"{website_url}\">Visit Company Website</a>")
        else:
            self.website_label.setText("Website not available")

    def create_summary_box(self):
        self.summary_label = QLabel("Total Value: $0.00 | Total P/L: $0.00")
        self.summary_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.summary_label.setFont(font)
        self.layout.addWidget(self.summary_label)

    def update_summary(self, total_value, total_pl):
        color = "green" if total_pl > 0 else "red" if total_pl < 0 else "gray"
        self.summary_label.setText(
            f'<span style="color: black;">Total Value:</span> '
            f'<span style="color: green;">${total_value:,.2f}</span> '
            f'<span style="color: black;">| Total P/L:</span> '
            f'<span style="color: {color};">${total_pl:+,.2f}</span>'
        )

    def fetch_news(self, symbol):
        try:
            today = datetime.date.today()
            from_date = today - datetime.timedelta(days=7)
            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={today}&token={FINNHUB_API_KEY}"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            headlines = []
            for article in data[:5]:
                title = article.get("headline", "No Title")
                link = article.get("url", "")
                if title and link:
                    headlines.append(f"<a href=\"{link}\">{title}</a>")

            return headlines or ["No news articles found."]
        except requests.exceptions.Timeout:
            print(f"Timeout fetching news for {symbol}")
            return ["<b>Error:</b> Request timed out"]
        except requests.exceptions.RequestException as e:
            print(f"Error fetching news for {symbol}: {e}")
            return [f"<b>Error fetching news:</b> {e}"]

    def show_news_for_selected(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            self.news_box.setText("")
            return

        row = selected_items[0].row()
        if row < 0 or row >= len(self.holdings):
            return

        symbol = self.holdings[row]["symbol"]
        headlines = self.fetch_news(symbol)
        self.news_box.setText(f"<b>News for {symbol}:</b><br><br>" + "<br><br>".join(headlines))

    def get_quote(self, symbol):
        # Check cache first
        now = datetime.datetime.now()
        if symbol in self.quote_cache:
            data, timestamp = self.quote_cache[symbol]
            if (now - timestamp).total_seconds() < self.cache_duration:
                return data
        
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            self.quote_cache[symbol] = (data, now)
            return data
        except requests.exceptions.RequestException as e:
            print(f"Error fetching quote for {symbol}: {e}")
            return {}

    def get_profile(self, symbol):
        # Check cache first
        now = datetime.datetime.now()
        if symbol in self.profile_cache:
            data, timestamp = self.profile_cache[symbol]
            if (now - timestamp).total_seconds() < self.cache_duration:
                return data
        
        try:
            url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={FINNHUB_API_KEY}"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            self.profile_cache[symbol] = (data, now)
            return data
        except requests.exceptions.RequestException as e:
            print(f"Error fetching profile for {symbol}: {e}")
            return {}

    def add_or_update_stock(self):
        symbol = self.symbol_input.text().strip().upper()
        shares = self.shares_input.value()
        try:
            cost_basis = float(self.cost_input.text())
        except ValueError:
            return

        stock = {"symbol": symbol, "shares": shares, "cost": cost_basis}
        if self.editing_index is not None:
            self.holdings[self.editing_index] = stock
            self.editing_index = None
            self.add_button.setText("Add Stock")
        else:
            self.holdings.append(stock)

        self.clear_inputs()
        self.update_table()
        self.save_holdings()

    def edit_selected_stock(self):
        selected = self.table.currentRow()
        if selected >= 0 and selected < len(self.holdings):
            stock = self.holdings[selected]
            self.symbol_input.setText(stock["symbol"])
            self.shares_input.setValue(float(stock["shares"]))
            self.cost_input.setText(str(stock["cost"]))
            self.editing_index = selected
            self.add_button.setText("Update Stock")
        else:
            QMessageBox.warning(self, "No Selection", "Please select a stock to edit.")

    def delete_selected_row(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a stock to delete.")
            return

        row = selected_items[0].row()
        if 0 <= row < len(self.holdings):
            symbol = self.holdings[row]['symbol']
            reply = QMessageBox.question(
                self, 'Confirm Deletion',
                f"Are you sure you want to delete {symbol}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                del self.holdings[row]
                self.update_table()
                self.save_holdings()

    def clear_all_stocks(self):
        if not self.holdings:
            QMessageBox.information(self, "Nothing to Clear", "Your portfolio is already empty.")
            return

        reply = QMessageBox.question(
            self, "Clear All?",
            "Are you sure you want to delete ALL stocks from your portfolio?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.holdings.clear()
            self.update_table()
            self.save_holdings()

    def update_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.holdings))
        for i, stock in enumerate(self.holdings):
            self.table.setItem(i, 0, QTableWidgetItem(stock["symbol"]))
            shares = stock["shares"]
            shares_str = f"{shares:,.6f}" if shares % 1 else f"{shares:,.2f}"
            self.table.setItem(i, 1, QTableWidgetItem(shares_str))
            self.table.setItem(i, 2, QTableWidgetItem(f"${stock['cost']:.2f}"))
            for col in range(3, 12):
                item = QTableWidgetItem("...")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, col, item)
        self.update_pie_chart([])

    def refresh_prices(self):
        pie_data = []
        total_value = 0.0
        total_pl = 0.0

        for i, stock in enumerate(self.holdings):
            symbol = stock["symbol"]
            try:
                quote = self.get_quote(symbol)
                profile = self.get_profile(symbol)
                
                # Validate quote data
                if not quote or 'c' not in quote:
                    raise ValueError("Invalid quote data")

                price = quote['c']
                open_price = quote.get('o', 0)
                high_price = quote.get('h', 0)
                low_price = quote.get('l', 0)
                prev_close = quote.get('pc', 0)
                exchange = profile.get('exchange', 'N/A')
                industry = profile.get('finnhubIndustry', 'N/A')

                value = price * stock["shares"]
                pl = (price - stock["cost"]) * stock["shares"]

                total_value += value
                total_pl += pl

                values = [price, open_price, high_price, low_price, prev_close, value, pl, exchange, industry]
                for j, val in enumerate(values):
                    if j in [7, 8]:
                        item = QTableWidgetItem(val)
                    else:
                        item = QTableWidgetItem(f"${val:,.2f}" if isinstance(val, (int, float)) else str(val))
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        if j == 6:
                            item.setForeground(QColor("green" if val > 0 else "red" if val < 0 else "gray"))
                    self.table.setItem(i, j + 3, item)

                pie_data.append({"symbol": symbol, "value": value})
            except Exception as e:
                print(f"Error fetching data for {symbol}: {e}")
                for col in range(3, 12):
                    item = QTableWidgetItem("Error")
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(i, col, item)

        self.update_pie_chart(pie_data)
        self.update_summary(total_value, total_pl)

    def clear_inputs(self):
        self.symbol_input.clear()
        self.cost_input.clear()
        self.shares_input.setValue(0)
        self.add_button.setText("Add Stock")

    def save_holdings(self):
        with open("holdings.json", "w") as f:
            json.dump(self.holdings, f)

    def load_holdings(self):
        if os.path.exists("holdings.json"):
            with open("holdings.json", "r") as f:
                self.holdings = json.load(f)
                self.update_table()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StockDashboard()
    window.show()
    sys.exit(app.exec_())
