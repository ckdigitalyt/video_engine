"""
chart_provider.py — Chart/Timeline/DataViz asset provider.

Generates matplotlib charts and timelines when the EditorialPlanner
determines that a concept is best shown as data visualization rather
than stock footage.

Implements the AssetProvider interface for transparent routing via
AssetIntentRouter.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

from src.providers.asset_provider import AssetProvider


class ChartProvider(AssetProvider):
    """Generates charts and data visualizations as video assets.

    Falls back gracefully: returns [] when matplotlib is not available
    or when the query doesn't match a chart template.
    """

    def __init__(self, output_dir: str = "cache/charts"):
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)
        self._last_chart: str = ""

    def search(self, query: str, **kwargs: Any) -> list[dict]:
        """Generate a chart/timeline from query.

        Returns a single-result list with the rendered chart video, or
        [] if the query doesn't match a chart template.
        """
        if not self._is_chart_request(query):
            return []

        safe_name = self._slugify(query)
        output_path = os.path.join(self._output_dir, f"{safe_name}.mp4")

        if os.path.exists(output_path):
            self._last_chart = output_path
            return [self._make_result(output_path, query)]

        try:
            chart_path = self._render_chart(query, output_path)
            if chart_path:
                self._last_chart = chart_path
                return [self._make_result(chart_path, query)]
        except Exception as e:
            print(f"[ChartProvider] Failed to render chart '{query}': {e}")

        return []

    def download(self, url: str, output_path: str) -> str:
        src = url if os.path.exists(url) else self._last_chart
        if not src or not os.path.exists(src):
            raise FileNotFoundError(f"Chart not found: {url}")
        import shutil
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        shutil.copy2(src, output_path)
        return output_path

    def _is_chart_request(self, query: str) -> bool:
        chart_keywords = [
            "chart", "graph", "timeline", "diagram", "plot", "data viz",
            "comparison", "distribution", "curves", "trend", "bar chart",
            "pie chart", "line graph", "scatter plot", "histogram",
        ]
        q = query.lower()
        return any(kw in q for kw in chart_keywords)

    def _render_chart(self, query: str, output_path: str) -> str | None:
        """Render a chart as a video file using matplotlib."""

        # Determine chart type from query
        q = query.lower()

        # Generate the chart as a static image first, then convert to video
        png_path = output_path.replace(".mp4", ".png")

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=100)
        fig.patch.set_facecolor("#000011")

        if "timeline" in q or "bar" in q:
            # Horizontal bar timeline
            categories = ["Step 1", "Step 2", "Step 3", "Step 4", "Step 5"]
            values = np.random.uniform(1, 10, len(categories))
            bars = ax.barh(categories, values, color="#4169E1", edgecolor="#FFFFFF", linewidth=0.5)
            ax.set_xlabel("Progression", color="white")
            ax.set_facecolor("#0a0a2e")
            ax.tick_params(colors="white")
            for spine in ax.spines.values():
                spine.set_color("#333333")
        elif "distribution" in q or "histogram" in q or "normal" in q:
            # Normal distribution
            x = np.linspace(-4, 4, 200)
            y = np.exp(-x**2 / 2) / np.sqrt(2 * np.pi)
            ax.plot(x, y, color="#FFD700", linewidth=3)
            ax.fill_between(x, y, alpha=0.3, color="#FFD700")
            ax.set_facecolor("#0a0a2e")
            ax.tick_params(colors="white")
            for spine in ax.spines.values():
                spine.set_color("#333333")
        elif "pie" in q:
            # Pie chart
            sizes = [25, 25, 20, 15, 10, 5]
            labels = ["A", "B", "C", "D", "E", "F"]
            colors_chart = ["#FF6B35", "#4169E1", "#32CD32", "#FFD700", "#FF1493", "#8A2BE2"]
            wedges, texts, autotexts = ax.pie(
                sizes, labels=labels, colors=colors_chart, autopct="%1.0f%%",
                startangle=90, textprops={"color": "white", "fontsize": 14},
            )
            ax.set_facecolor("#000011")
        elif "comparison" in q or "comparison" in q:
            # Grouped bar chart
            categories = ["A", "B", "C", "D"]
            x = np.arange(len(categories))
            width = 0.35
            values1 = np.random.uniform(1, 10, len(categories))
            values2 = np.random.uniform(1, 10, len(categories))
            ax.bar(x - width/2, values1, width, label="Before", color="#4169E1")
            ax.bar(x + width/2, values2, width, label="After", color="#FF6B35")
            ax.set_xticks(x)
            ax.set_xticklabels(categories, color="white")
            ax.legend(facecolor="#0a0a2e", edgecolor="#333333", labelcolor="white")
            ax.set_facecolor("#0a0a2e")
            ax.tick_params(colors="white")
            for spine in ax.spines.values():
                spine.set_color("#333333")
        elif "curve" in q or "growth" in q or "exponential" in q:
            # Exponential growth / compound interest curve
            x = np.linspace(0, 10, 100)
            y = np.exp(x * 0.5)
            ax.plot(x, y, color="#32CD32", linewidth=3)
            ax.fill_between(x, 0, y, alpha=0.2, color="#32CD32")
            ax.set_facecolor("#0a0a2e")
            ax.tick_params(colors="white")
            for spine in ax.spines.values():
                spine.set_color("#333333")
        else:
            # Generic data plot
            x = np.linspace(0, 10, 100)
            for i in range(3):
                ax.plot(x, np.sin(x + i * 2) * (3 - i), linewidth=2, alpha=0.8)
            ax.set_facecolor("#0a0a2e")
            ax.tick_params(colors="white")
            for spine in ax.spines.values():
                spine.set_color("#333333")

        # Title
        title_words = query[:60]
        ax.set_title(title_words, color="white", fontsize=18, pad=20)

        plt.tight_layout()
        fig.savefig(png_path, dpi=100, facecolor="#000011", edgecolor="none")
        plt.close(fig)

        # Convert to video with ffmpeg
        import subprocess
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", png_path,
            "-c:v", "libx264", "-t", "8", "-pix_fmt", "yuv420p",
            "-vf", "scale=1920:1080",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and os.path.exists(output_path):
            # Clean up PNG
            try:
                os.remove(png_path)
            except OSError:
                pass
            return output_path

        return None

    @staticmethod
    def _slugify(text: str) -> str:
        import re
        s = text.lower().strip()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s[:60].strip("_")

    @staticmethod
    def _make_result(path: str, query: str) -> dict:
        return {
            "url": path,
            "provider": "chart",
            "asset_type": "chart",
            "duration": 8.0,
            "width": 1920,
            "height": 1080,
            "search_query": query,
            "score": 0.90,
        }
