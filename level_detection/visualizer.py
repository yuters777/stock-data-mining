"""
Visualization Module for BSU Detection.

Creates candlestick charts with horizontal level lines.
"""

from pathlib import Path
from typing import List, Optional

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

from .bsu_detector import Level, LevelType
from .config import Config, DEFAULT_CONFIG


class LevelVisualizer:
    """
    Visualizes OHLCV data with detected levels.

    Creates candlestick charts with horizontal lines for
    support/resistance levels.
    """

    # Color scheme
    COLORS = {
        "bullish": "#26A69A",  # Green for up candles
        "bearish": "#EF5350",  # Red for down candles
        "resistance": "#FF5252",  # Red for resistance levels
        "support": "#4CAF50",  # Green for support levels
        "mirror": "#2196F3",  # Blue for mirror levels
        "background": "#1E1E1E",  # Dark background
        "grid": "#333333",  # Grid color
        "text": "#FFFFFF",  # Text color
    }

    def __init__(self, config: Config = DEFAULT_CONFIG):
        """
        Initialize visualizer with configuration.

        Args:
            config: Configuration parameters
        """
        self.config = config

    def plot_candlestick(
        self,
        df: pd.DataFrame,
        levels: Optional[List[Level]] = None,
        ticker: str = "",
        figsize: tuple = (16, 10),
        save_path: Optional[Path] = None,
        show_volume: bool = True,
        date_range: Optional[tuple] = None,
    ) -> plt.Figure:
        """
        Plot candlestick chart with optional level lines.

        Args:
            df: DataFrame with OHLCV data (Date, Open, High, Low, Close, Volume)
            levels: Optional list of Level objects to plot
            ticker: Ticker symbol for title
            figsize: Figure size tuple
            save_path: Optional path to save the figure
            show_volume: Whether to show volume subplot
            date_range: Optional tuple (start_date, end_date) to filter data

        Returns:
            Matplotlib Figure object
        """
        df = df.copy()

        # Filter by date range if specified
        if date_range:
            start, end = date_range
            df = df[(df["Date"] >= start) & (df["Date"] <= end)]

        if df.empty:
            raise ValueError("No data available for the specified date range")

        # Set up figure
        if show_volume:
            fig, (ax1, ax2) = plt.subplots(
                2, 1, figsize=figsize, height_ratios=[3, 1],
                facecolor=self.COLORS["background"]
            )
        else:
            fig, ax1 = plt.subplots(
                1, 1, figsize=figsize,
                facecolor=self.COLORS["background"]
            )
            ax2 = None

        ax1.set_facecolor(self.COLORS["background"])

        # Plot candlesticks
        self._plot_candles(ax1, df)

        # Plot levels if provided
        if levels:
            self._plot_levels(ax1, df, levels)

        # Configure main axis
        ax1.set_ylabel("Price ($)", color=self.COLORS["text"], fontsize=12)
        ax1.tick_params(colors=self.COLORS["text"])
        ax1.grid(True, alpha=0.3, color=self.COLORS["grid"])
        ax1.set_xlim(df["Date"].min(), df["Date"].max())

        # Set title
        title = f"{ticker} Daily Chart with BSU Levels" if ticker else "Daily Chart with BSU Levels"
        ax1.set_title(title, color=self.COLORS["text"], fontsize=14, fontweight="bold")

        # Format x-axis
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")

        # Plot volume if requested
        if show_volume and ax2 is not None:
            self._plot_volume(ax2, df)

        # Add legend
        self._add_legend(ax1, levels)

        plt.tight_layout()

        # Save if path provided
        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=150, facecolor=self.COLORS["background"])

        return fig

    def _plot_candles(self, ax: plt.Axes, df: pd.DataFrame) -> None:
        """
        Plot candlestick bodies and wicks.

        Args:
            ax: Matplotlib axes
            df: DataFrame with OHLCV data
        """
        width = 0.6  # Candle body width
        width2 = 0.1  # Wick width

        for i, row in df.iterrows():
            date = row["Date"]
            open_price = row["Open"]
            high = row["High"]
            low = row["Low"]
            close = row["Close"]

            # Determine candle color
            if close >= open_price:
                color = self.COLORS["bullish"]
                body_bottom = open_price
                body_height = close - open_price
            else:
                color = self.COLORS["bearish"]
                body_bottom = close
                body_height = open_price - close

            # Plot candle body
            rect = Rectangle(
                (mdates.date2num(date) - width / 2, body_bottom),
                width,
                body_height if body_height > 0 else 0.001,  # Minimum height for doji
                facecolor=color,
                edgecolor=color,
            )
            ax.add_patch(rect)

            # Plot wicks
            ax.plot(
                [date, date],
                [low, high],
                color=color,
                linewidth=1,
            )

    def _plot_levels(
        self, ax: plt.Axes, df: pd.DataFrame, levels: List[Level]
    ) -> None:
        """
        Plot horizontal lines for detected levels.

        Args:
            ax: Matplotlib axes
            df: DataFrame with OHLCV data (for x-axis bounds)
            levels: List of Level objects to plot
        """
        x_min = df["Date"].min()
        x_max = df["Date"].max()

        for level in levels:
            # Determine color and style based on level type
            if level.level_type == LevelType.MIRROR:
                color = self.COLORS["mirror"]
                linestyle = "-"
                linewidth = 2
            elif level.level_type == LevelType.RESISTANCE:
                color = self.COLORS["resistance"]
                linestyle = "--"
                linewidth = 1.5
            else:  # SUPPORT
                color = self.COLORS["support"]
                linestyle = "--"
                linewidth = 1.5

            # Adjust alpha based on score
            alpha = min(0.5 + (level.score / 30), 1.0)

            # Draw horizontal line from level date to end
            level_date = level.date if level.date >= x_min else x_min
            ax.hlines(
                level.price,
                level_date,
                x_max,
                colors=color,
                linestyles=linestyle,
                linewidth=linewidth,
                alpha=alpha,
            )

            # Add price label
            ax.annotate(
                f"${level.price:.2f} ({level.score})",
                xy=(x_max, level.price),
                xytext=(5, 0),
                textcoords="offset points",
                fontsize=8,
                color=color,
                alpha=alpha,
                va="center",
            )

    def _plot_volume(self, ax: plt.Axes, df: pd.DataFrame) -> None:
        """
        Plot volume bars.

        Args:
            ax: Matplotlib axes
            df: DataFrame with OHLCV data
        """
        ax.set_facecolor(self.COLORS["background"])

        colors = [
            self.COLORS["bullish"] if row["Close"] >= row["Open"]
            else self.COLORS["bearish"]
            for _, row in df.iterrows()
        ]

        ax.bar(df["Date"], df["Volume"], color=colors, alpha=0.7, width=0.8)
        ax.set_ylabel("Volume", color=self.COLORS["text"], fontsize=10)
        ax.tick_params(colors=self.COLORS["text"])
        ax.grid(True, alpha=0.3, color=self.COLORS["grid"])

        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    def _add_legend(self, ax: plt.Axes, levels: Optional[List[Level]]) -> None:
        """
        Add legend to the chart.

        Args:
            ax: Matplotlib axes
            levels: Optional list of levels to determine legend items
        """
        legend_elements = [
            mpatches.Patch(color=self.COLORS["bullish"], label="Bullish"),
            mpatches.Patch(color=self.COLORS["bearish"], label="Bearish"),
        ]

        if levels:
            legend_elements.extend([
                plt.Line2D([0], [0], color=self.COLORS["resistance"],
                          linestyle="--", label="Resistance"),
                plt.Line2D([0], [0], color=self.COLORS["support"],
                          linestyle="--", label="Support"),
                plt.Line2D([0], [0], color=self.COLORS["mirror"],
                          linestyle="-", linewidth=2, label="Mirror Level"),
            ])

        ax.legend(
            handles=legend_elements,
            loc="upper left",
            facecolor=self.COLORS["background"],
            edgecolor=self.COLORS["grid"],
            labelcolor=self.COLORS["text"],
        )

    def plot_level_statistics(
        self,
        levels: List[Level],
        figsize: tuple = (12, 8),
        save_path: Optional[Path] = None,
    ) -> plt.Figure:
        """
        Plot statistics about detected levels.

        Args:
            levels: List of Level objects
            figsize: Figure size tuple
            save_path: Optional path to save the figure

        Returns:
            Matplotlib Figure object
        """
        if not levels:
            raise ValueError("No levels to plot")

        fig, axes = plt.subplots(2, 2, figsize=figsize, facecolor=self.COLORS["background"])

        # Score distribution
        ax1 = axes[0, 0]
        ax1.set_facecolor(self.COLORS["background"])
        scores = [level.score for level in levels]
        ax1.hist(scores, bins=range(min(scores), max(scores) + 2),
                color=self.COLORS["bullish"], edgecolor=self.COLORS["text"], alpha=0.7)
        ax1.set_xlabel("Score", color=self.COLORS["text"])
        ax1.set_ylabel("Count", color=self.COLORS["text"])
        ax1.set_title("Level Score Distribution", color=self.COLORS["text"])
        ax1.tick_params(colors=self.COLORS["text"])

        # Level type distribution
        ax2 = axes[0, 1]
        ax2.set_facecolor(self.COLORS["background"])
        type_counts = {}
        for level in levels:
            type_name = level.level_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

        colors = [
            self.COLORS["resistance"] if t == "R"
            else self.COLORS["support"] if t == "S"
            else self.COLORS["mirror"]
            for t in type_counts.keys()
        ]
        ax2.bar(type_counts.keys(), type_counts.values(), color=colors)
        ax2.set_xlabel("Level Type", color=self.COLORS["text"])
        ax2.set_ylabel("Count", color=self.COLORS["text"])
        ax2.set_title("Level Type Distribution", color=self.COLORS["text"])
        ax2.tick_params(colors=self.COLORS["text"])

        # Levels per ticker
        ax3 = axes[1, 0]
        ax3.set_facecolor(self.COLORS["background"])
        ticker_counts = {}
        for level in levels:
            ticker_counts[level.ticker] = ticker_counts.get(level.ticker, 0) + 1

        ax3.bar(ticker_counts.keys(), ticker_counts.values(),
               color=self.COLORS["bullish"], alpha=0.7)
        ax3.set_xlabel("Ticker", color=self.COLORS["text"])
        ax3.set_ylabel("Count", color=self.COLORS["text"])
        ax3.set_title("Levels per Ticker", color=self.COLORS["text"])
        ax3.tick_params(colors=self.COLORS["text"])
        plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha="right")

        # Touches distribution
        ax4 = axes[1, 1]
        ax4.set_facecolor(self.COLORS["background"])
        touches = [level.touches for level in levels]
        ax4.hist(touches, bins=range(max(touches) + 2),
                color=self.COLORS["mirror"], edgecolor=self.COLORS["text"], alpha=0.7)
        ax4.set_xlabel("Number of Touches", color=self.COLORS["text"])
        ax4.set_ylabel("Count", color=self.COLORS["text"])
        ax4.set_title("Level Touches Distribution", color=self.COLORS["text"])
        ax4.tick_params(colors=self.COLORS["text"])

        plt.tight_layout()

        if save_path:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=150, facecolor=self.COLORS["background"])

        return fig
