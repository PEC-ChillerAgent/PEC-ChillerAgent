"""Chart helpers kept separate from the Streamlit presentation layer."""

from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd


def plot_temperature_trends(frame: pd.DataFrame, *, title: str = "Chiller temperature trends"):
    """Return a matplotlib figure for temperature channels when available."""

    columns = [column for column in ["TEI_K", "TEO_K", "TCI_K", "TCO_K"] if column in frame]
    if not columns:
        raise ValueError("No temperature columns available for plotting.")
    x = frame["timestamp"] if "timestamp" in frame else frame.index
    figure, axis = plt.subplots(figsize=(10, 4))
    for column in columns:
        axis.plot(x, frame[column], label=column)
    axis.set_title(title)
    axis.set_ylabel("Temperature (K)")
    axis.legend(loc="best")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    return figure


def plot_actual_vs_predicted(frame: pd.DataFrame, actual: str, predicted: str, *, title: Optional[str] = None):
    """Return an actual-versus-predicted scatter figure."""

    data = frame[[actual, predicted]].dropna()
    if data.empty:
        raise ValueError(f"No complete rows for {actual} and {predicted}.")
    figure, axis = plt.subplots(figsize=(5, 5))
    axis.scatter(data[actual], data[predicted], s=12, alpha=0.5)
    low = min(data[actual].min(), data[predicted].min())
    high = max(data[actual].max(), data[predicted].max())
    axis.plot([low, high], [low, high], linestyle="--", color="black")
    axis.set_xlabel(f"Measured: {actual}")
    axis.set_ylabel(f"Predicted: {predicted}")
    axis.set_title(title or f"{actual}: measured vs predicted")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    return figure
