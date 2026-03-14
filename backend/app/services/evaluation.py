import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.utils.logger import get_logger, log_stage

logger = get_logger("evaluation")


def evaluate_models(
    cv_results: pd.DataFrame,
    historical_df: pd.DataFrame,
    forecast_horizon: int,
    file_hash: str = "",
) -> dict:
    with log_stage(logger, "evaluation", file_hash=file_hash):
        # Use only the last CV window (first forecast_horizon entries) so that
        # AutoETS/AutoARIMA are evaluated on the same test set as MA and Excel ETS
        # (both use y[-forecast_horizon:]).  This makes MAE values comparable.
        n = min(forecast_horizon, len(cv_results))
        actuals = cv_results["y"].values[:n]

        # Evaluate AutoETS
        ets_col = [c for c in cv_results.columns if "AutoETS" in c and "lo" not in c and "hi" not in c]
        ets_preds = cv_results[ets_col[0]].values[:n] if ets_col else np.zeros(n)
        ets_metrics = _compute_metrics(actuals, ets_preds)

        # Evaluate AutoARIMA
        arima_col = [c for c in cv_results.columns if "AutoARIMA" in c and "lo" not in c and "hi" not in c]
        arima_preds = cv_results[arima_col[0]].values[:n] if arima_col else np.zeros(n)
        arima_metrics = _compute_metrics(actuals, arima_preds)

        # Compute baseline metrics from historical data
        y_values = historical_df["y"].values
        ma_metrics = _compute_moving_average_metrics(y_values, forecast_horizon)
        excel_ets_metrics, excel_ets_forecast = _compute_excel_ets_metrics(y_values, forecast_horizon)

        metrics = {
            "AutoETS": ets_metrics,
            "AutoARIMA": arima_metrics,
            "Moving Average (Excel)": ma_metrics,
            "ETS (Excel)": excel_ets_metrics,
        }

        logger.info(
            f"Evaluation complete - ETS MAE: {ets_metrics['mae']:.2f}, "
            f"ARIMA MAE: {arima_metrics['mae']:.2f}",
            extra={"file_hash": file_hash},
        )

        return metrics, excel_ets_forecast


def _compute_metrics(actuals: np.ndarray, predictions: np.ndarray) -> dict:
    errors = actuals - predictions
    abs_errors = np.abs(errors)

    mae = float(np.mean(abs_errors))

    # SMAPE
    denominator = np.abs(actuals) + np.abs(predictions)
    smape_values = np.where(denominator == 0, 0, 2 * abs_errors / denominator)
    smape = float(np.mean(smape_values) * 100)

    # MFE (Mean Forecast Error) - positive means under-forecasting
    mfe = float(np.mean(errors))

    return {"mae": round(mae, 2), "smape": round(smape, 2), "mfe": round(mfe, 2)}


def _compute_moving_average_metrics(y: np.ndarray, horizon: int) -> dict:
    if len(y) < horizon + 1:
        return {"mae": float("inf"), "smape": float("inf"), "mfe": 0.0}

    # Use last `horizon` values as test, moving average of prior values as prediction
    test = y[-horizon:]
    window = min(horizon, len(y) - horizon)
    if window <= 0:
        return {"mae": float("inf"), "smape": float("inf"), "mfe": 0.0}
    ma_pred = np.full(horizon, np.mean(y[-horizon - window : -horizon]))

    return _compute_metrics(test, ma_pred)


def _compute_excel_ets_metrics(y: np.ndarray, horizon: int) -> tuple[dict, np.ndarray]:
    """Compute metrics for Excel-style Forecast.ETS and return forecast for reuse."""
    if len(y) < horizon + 4:
        return {"mae": float("inf"), "smape": float("inf"), "mfe": 0.0}, np.full(horizon, np.mean(y))

    train = y[:-horizon]
    test = y[-horizon:]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                train, trend="add", seasonal=None,
                initialization_method="estimated",
            ).fit(optimized=True, use_brute=False)
            # Refit on full data for the forecast that gets passed to charts
            full_model = ExponentialSmoothing(
                y, trend="add", seasonal=None,
                initialization_method="estimated",
            ).fit(optimized=True, use_brute=False)
            pred = model.forecast(horizon)
            full_forecast = full_model.forecast(horizon)
        except Exception:
            pred = np.full(horizon, np.mean(train))
            full_forecast = np.full(horizon, np.mean(y))

    return _compute_metrics(test, pred), full_forecast
