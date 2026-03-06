import base64
import io
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.utils.logger import get_logger, log_stage

logger = get_logger("visualization")

# Dark theme colors matching frontend (tuxedo style)
BG_COLOR = "#000000"          # pure black
CARD_COLOR = "#0a0a0a"        # near-black
GRID_COLOR = "#1a1a1a"        # very dark grey
TEXT_COLOR = "#ffffff"          # pure white
ACCENT = "#10b981"             # emerald-500 (primary/green)
ALT_COLOR = "#38bdf8"          # sky-400 (brighter blue for secondary)
MA_COLOR = "#ef4444"           # red-500 (Moving Average Excel)
EXCEL_ETS_COLOR = "#f97316"    # orange-500 (ETS Excel)
HISTORICAL_COLOR = "#94a3b8"   # slate-400
CONFIDENCE_ALPHA = 0.15

# Display name mapping
DISPLAY_NAMES = {
    "AutoETS": "ETS",
    "AutoARIMA": "ARIMA",
}


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
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _apply_dark_theme(ax: plt.Axes, fig: plt.Figure) -> None:
    fig.set_facecolor(BG_COLOR)
    ax.set_facecolor(CARD_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=10, width=0.5)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, alpha=0.4, linewidth=0.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    # Format Y axis: white, bold, comma-separated numbers
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f"{x:,.0f}"))
    ax.tick_params(axis="both", which="major", labelsize=10)
    # Make tick labels bold
    for label in ax.get_xticklabels():
        label.set_fontweight("bold")
    for label in ax.get_yticklabels():
        label.set_fontweight("bold")
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

    # Ensure minimum 12 predictions with >=25% forecast space
    forecast_dates = forecasts["ds"]
    total_points = len(dates) + len(forecast_dates)

    # Trim historical data if forecast occupies <25% of graph space
    min_forecast_ratio = 0.25
    if len(forecast_dates) / total_points < min_forecast_ratio:
        max_historical = int(len(forecast_dates) / min_forecast_ratio) - len(forecast_dates)
        max_historical = max(max_historical, len(forecast_dates))  # at least equal to forecast
        dates = dates.iloc[-max_historical:]
        values = values.iloc[-max_historical:]

    # Historical line (no data points/scatter)
    ax.plot(dates, values, color=HISTORICAL_COLOR, linewidth=1.5, label="Historical")

    # Forecast
    pred_col = [c for c in forecasts.columns if selected_model in c and "lo" not in c and "hi" not in c][0]
    lo_col = [c for c in forecasts.columns if selected_model in c and "lo" in c]
    hi_col = [c for c in forecasts.columns if selected_model in c and "hi" in c]

    forecast_values = forecasts[pred_col]

    # Prediction line: green, same thickness as historical (rigid/linear style)
    ax.plot(forecast_dates, forecast_values, color=ACCENT, linewidth=1.5, label="Forecast")

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
            linewidth=1.5,
            linestyle="--",
            alpha=0.5,
        )

    selected_display = DISPLAY_NAMES.get(selected_model, selected_model)
    ax.set_title(f"Forecast \u2014 {selected_display}", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("")
    # No Y axis label (removed "Value")

    # Legend: bottom-center
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=3,
        fontsize=9,
        facecolor=CARD_COLOR,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR,
        framealpha=0.9,
    )

    return _fig_to_base64(fig)


def _compute_excel_ets_forecast(y_vals: np.ndarray, forecast_horizon: int, forecast_dates) -> np.ndarray:
    """Compute Excel-style Forecast.ETS (additive trend, no seasonal)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                y_vals, trend="add", seasonal=None,
                initialization_method="estimated",
            ).fit(optimized=True, use_brute=False)
            return model.forecast(forecast_horizon)
        except Exception:
            return np.full(forecast_horizon, np.mean(y_vals))


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

    forecast_dates = forecasts["ds"]
    total_points = len(dates) + len(forecast_dates)

    # Trim historical data if forecast occupies <25% of graph space
    min_forecast_ratio = 0.25
    if len(forecast_dates) / total_points < min_forecast_ratio:
        max_historical = int(len(forecast_dates) / min_forecast_ratio) - len(forecast_dates)
        max_historical = max(max_historical, len(forecast_dates))
        dates = dates.iloc[-max_historical:]
        values = values.iloc[-max_historical:]

    # Historical data (no scatter points)
    ax.plot(dates, values, color=HISTORICAL_COLOR, linewidth=1.5, alpha=0.7, label="Historical")

    # Determine display names and roles
    selected_display = DISPLAY_NAMES.get(selected_model, selected_model)
    alt_display = DISPLAY_NAMES.get(alternative_model, alternative_model)

    # Selected model (Primary) with confidence band - GREEN
    sel_col = [c for c in forecasts.columns if selected_model in c and "lo" not in c and "hi" not in c][0]
    lo_col = [c for c in forecasts.columns if selected_model in c and "lo" in c]
    hi_col = [c for c in forecasts.columns if selected_model in c and "hi" in c]

    ax.plot(forecast_dates, forecasts[sel_col], color=ACCENT, linewidth=1.5,
            label=f"{selected_display} (Primary Model)")
    if lo_col and hi_col:
        ax.fill_between(
            forecast_dates, forecasts[lo_col[0]], forecasts[hi_col[0]],
            color=ACCENT, alpha=CONFIDENCE_ALPHA,
        )

    # Alternative model (Secondary) - BRIGHTER BLUE
    alt_col = [c for c in forecasts.columns if alternative_model in c and "lo" not in c and "hi" not in c]
    if alt_col:
        ax.plot(forecast_dates, forecasts[alt_col[0]], color=ALT_COLOR, linewidth=1.5,
                label=f"{alt_display} (Secondary Model)")

    # Moving Average (Excel) - RED, flat line
    y_vals = historical_df["y"].values  # use full historical for computation
    window = min(forecast_horizon, len(y_vals))
    ma_value = np.mean(y_vals[-window:])
    ax.plot(forecast_dates, np.full(len(forecast_dates), ma_value),
            color=MA_COLOR, linewidth=1.5, linestyle=":", label="Moving Average (Excel)")

    # ETS (Excel) - ORANGE, actual ETS forecast
    excel_ets_forecast = _compute_excel_ets_forecast(y_vals, forecast_horizon, forecast_dates)
    ax.plot(forecast_dates, excel_ets_forecast,
            color=EXCEL_ETS_COLOR, linewidth=1.5, linestyle="-.", label="ETS (Excel)")

    ax.set_title("Model Comparison", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("")
    # No Y axis label

    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, -0.28),
        ncol=5,
        fontsize=8,
        facecolor=CARD_COLOR,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT_COLOR,
        framealpha=0.9,
    )

    return _fig_to_base64(fig)
