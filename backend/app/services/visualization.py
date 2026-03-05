import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from app.utils.logger import get_logger, log_stage

logger = get_logger("visualization")

# Dark theme colors matching frontend
BG_COLOR = "#020617"       # slate-950
CARD_COLOR = "#0f172a"     # slate-900
GRID_COLOR = "#1e293b"     # slate-800
TEXT_COLOR = "#f8fafc"      # slate-50
ACCENT = "#10b981"         # emerald-500
ACCENT_LIGHT = "#34d399"   # emerald-400
ALT_COLOR = "#6366f1"      # indigo-500
MA_COLOR = "#f59e0b"       # amber-500
TREND_COLOR = "#ef4444"    # red-500
CONFIDENCE_ALPHA = 0.20
HISTORICAL_COLOR = "#94a3b8"  # slate-400


def generate_charts(
    historical_df: pd.DataFrame,
    forecasts: pd.DataFrame,
    selected_model: str,
    alternative_model: str,
    forecast_horizon: int,
    file_hash: str = "",
) -> dict:
    with log_stage(logger, "visualization", file_hash=file_hash):
        chart1 = _generate_selected_chart(
            historical_df, forecasts, selected_model, forecast_horizon
        )
        chart2 = _generate_comparison_chart(
            historical_df, forecasts, selected_model, alternative_model, forecast_horizon
        )
        return {"chart1_base64": chart1, "chart2_base64": chart2}


def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _apply_dark_theme(ax: plt.Axes, fig: plt.Figure) -> None:
    fig.set_facecolor(BG_COLOR)
    ax.set_facecolor(CARD_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, alpha=0.3, linewidth=0.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate(rotation=30)


def _generate_selected_chart(
    historical_df: pd.DataFrame,
    forecasts: pd.DataFrame,
    selected_model: str,
    forecast_horizon: int,
) -> str:
    fig, ax = plt.subplots(figsize=(12, 5))
    _apply_dark_theme(ax, fig)

    dates = historical_df["ds"]
    values = historical_df["y"]

    # Historical data with small datapoints
    ax.plot(dates, values, color=HISTORICAL_COLOR, linewidth=1.2, label="Historical")
    ax.scatter(dates, values, color=HISTORICAL_COLOR, s=8, zorder=3, alpha=0.6)

    # Forecast
    forecast_dates = forecasts["ds"]
    pred_col = [c for c in forecasts.columns if selected_model in c and "lo" not in c and "hi" not in c][0]
    lo_col = [c for c in forecasts.columns if selected_model in c and "lo" in c]
    hi_col = [c for c in forecasts.columns if selected_model in c and "hi" in c]

    forecast_values = forecasts[pred_col]
    ax.plot(forecast_dates, forecast_values, color=ACCENT, linewidth=2, label="Forecast")

    # Confidence band
    if lo_col and hi_col:
        ax.fill_between(
            forecast_dates,
            forecasts[lo_col[0]],
            forecasts[hi_col[0]],
            color=ACCENT,
            alpha=CONFIDENCE_ALPHA,
            label="80% Confidence",
        )

    # Connect historical to forecast
    if len(dates) > 0 and len(forecast_dates) > 0:
        ax.plot(
            [dates.iloc[-1], forecast_dates.iloc[0]],
            [values.iloc[-1], forecast_values.iloc[0]],
            color=ACCENT,
            linewidth=2,
            linestyle="--",
            alpha=0.5,
        )

    ax.set_title(f"Forecast — {selected_model}", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("")
    ax.set_ylabel("Value", fontsize=10)
    ax.legend(loc="upper left", fontsize=9, facecolor=CARD_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)

    return _fig_to_base64(fig)


def _generate_comparison_chart(
    historical_df: pd.DataFrame,
    forecasts: pd.DataFrame,
    selected_model: str,
    alternative_model: str,
    forecast_horizon: int,
) -> str:
    fig, ax = plt.subplots(figsize=(12, 5))
    _apply_dark_theme(ax, fig)

    dates = historical_df["ds"]
    values = historical_df["y"]

    # Historical data
    ax.plot(dates, values, color=HISTORICAL_COLOR, linewidth=1, alpha=0.6, label="Historical")

    forecast_dates = forecasts["ds"]

    # Selected model with confidence band
    sel_col = [c for c in forecasts.columns if selected_model in c and "lo" not in c and "hi" not in c][0]
    lo_col = [c for c in forecasts.columns if selected_model in c and "lo" in c]
    hi_col = [c for c in forecasts.columns if selected_model in c and "hi" in c]

    ax.plot(forecast_dates, forecasts[sel_col], color=ACCENT, linewidth=2, label=f"{selected_model} (selected)")
    if lo_col and hi_col:
        ax.fill_between(
            forecast_dates, forecasts[lo_col[0]], forecasts[hi_col[0]],
            color=ACCENT, alpha=CONFIDENCE_ALPHA,
        )

    # Alternative model (no confidence band)
    alt_col = [c for c in forecasts.columns if alternative_model in c and "lo" not in c and "hi" not in c]
    if alt_col:
        ax.plot(forecast_dates, forecasts[alt_col[0]], color=ALT_COLOR, linewidth=1.5, linestyle="--",
                label=alternative_model)

    # Moving Average baseline (flat line across forecast range)
    y_vals = values.values
    window = min(forecast_horizon, len(y_vals))
    ma_value = np.mean(y_vals[-window:])
    ax.plot(forecast_dates, np.full(len(forecast_dates), ma_value),
            color=MA_COLOR, linewidth=1.2, linestyle=":", label="Moving Average")

    # Linear Trend baseline
    x = np.arange(len(y_vals))
    if len(x) >= 2:
        coeffs = np.polyfit(x, y_vals, 1)
        x_forecast = np.arange(len(y_vals), len(y_vals) + forecast_horizon)
        trend_values = np.polyval(coeffs, x_forecast)
        ax.plot(forecast_dates, trend_values, color=TREND_COLOR, linewidth=1, linestyle="-.",
                label="Linear Trend")

    ax.set_title("Model Comparison", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("")
    ax.set_ylabel("Value", fontsize=10)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.25),
        ncol=5,
        fontsize=8,
        facecolor=CARD_COLOR,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR,
        framealpha=0.9,
    )

    return _fig_to_base64(fig)
