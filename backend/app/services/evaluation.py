import numpy as np
import pandas as pd

from app.utils.logger import get_logger, log_stage

logger = get_logger("evaluation")


def evaluate_models(
    cv_results: pd.DataFrame,
    historical_df: pd.DataFrame,
    forecast_horizon: int,
    file_hash: str = "",
) -> dict:
    with log_stage(logger, "evaluation", file_hash=file_hash):
        actuals = cv_results["y"].values

        # Evaluate AutoETS
        ets_col = [c for c in cv_results.columns if "AutoETS" in c and "lo" not in c and "hi" not in c]
        ets_preds = cv_results[ets_col[0]].values if ets_col else np.zeros_like(actuals)
        ets_metrics = _compute_metrics(actuals, ets_preds)

        # Evaluate AutoARIMA
        arima_col = [c for c in cv_results.columns if "AutoARIMA" in c and "lo" not in c and "hi" not in c]
        arima_preds = cv_results[arima_col[0]].values if arima_col else np.zeros_like(actuals)
        arima_metrics = _compute_metrics(actuals, arima_preds)

        # Compute baseline metrics from historical data
        y_values = historical_df["y"].values
        ma_metrics = _compute_moving_average_metrics(y_values, forecast_horizon)
        trend_metrics = _compute_linear_trend_metrics(y_values, forecast_horizon)

        metrics = {
            "AutoETS": ets_metrics,
            "AutoARIMA": arima_metrics,
            "Moving Average": ma_metrics,
            "Linear Trend": trend_metrics,
        }

        logger.info(
            f"Evaluation complete - ETS MAE: {ets_metrics['mae']:.2f}, "
            f"ARIMA MAE: {arima_metrics['mae']:.2f}",
            extra={"file_hash": file_hash},
        )

        return metrics


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
    ma_pred = np.full(horizon, np.mean(y[-horizon - window : -horizon]))

    return _compute_metrics(test, ma_pred)


def _compute_linear_trend_metrics(y: np.ndarray, horizon: int) -> dict:
    if len(y) < horizon + 2:
        return {"mae": float("inf"), "smape": float("inf"), "mfe": 0.0}

    train = y[:-horizon]
    test = y[-horizon:]

    x_train = np.arange(len(train))
    coeffs = np.polyfit(x_train, train, 1)

    x_test = np.arange(len(train), len(train) + horizon)
    trend_pred = np.polyval(coeffs, x_test)

    return _compute_metrics(test, trend_pred)
