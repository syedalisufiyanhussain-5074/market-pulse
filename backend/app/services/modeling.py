import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing
import pmdarima as pm

from app.utils.logger import get_logger, log_stage

logger = get_logger("modeling")

ETS_TREND_OPTIONS = ["add", "mul", None]
ETS_SEASONAL_OPTIONS = ["add", "mul", None]


def _calc_n_windows(y_len: int) -> int:
    max_windows = 3 if y_len > 200 else 5
    n_windows = min(max_windows, y_len // 3)
    return max(1, n_windows)


def fit_ets(
    df: pd.DataFrame,
    seasonal_period: int | None,
    forecast_horizon: int,
    file_hash: str = "",
) -> tuple:
    """Fit ETS model and return (cv_results, forecast, conf_intervals)."""
    with log_stage(logger, "ets_fitting", file_hash=file_hash):
        y = df["y"].values
        n_windows = _calc_n_windows(len(y))
        return _fit_auto_ets(y, seasonal_period, forecast_horizon, n_windows)


def fit_arima(
    df: pd.DataFrame,
    seasonal_period: int | None,
    forecast_horizon: int,
    file_hash: str = "",
) -> tuple:
    """Fit ARIMA model and return (cv_results, forecast, conf_intervals)."""
    with log_stage(logger, "arima_fitting", file_hash=file_hash):
        y = df["y"].values
        n_windows = _calc_n_windows(len(y))
        return _fit_auto_sarima(y, seasonal_period, forecast_horizon, n_windows)


def build_forecast_df(
    df: pd.DataFrame,
    freq: str,
    forecast_horizon: int,
    ets_result: tuple,
    arima_result: tuple,
    file_hash: str = "",
) -> dict:
    """Combine ETS + ARIMA results into forecasts DataFrame + cv_results."""
    ets_cv, ets_forecast, ets_conf = ets_result
    arima_cv, arima_forecast, arima_conf = arima_result

    dates = df["ds"].values
    last_date = pd.Timestamp(dates[-1])
    forecast_dates = pd.date_range(
        start=last_date, periods=forecast_horizon + 1, freq=freq
    )[1:]

    forecasts = pd.DataFrame({
        "ds": forecast_dates,
        "AutoETS": ets_forecast,
        "AutoETS-lo-80": ets_conf[0],
        "AutoETS-hi-80": ets_conf[1],
        "AutoARIMA": arima_forecast,
        "AutoARIMA-lo-80": arima_conf[0],
        "AutoARIMA-hi-80": arima_conf[1],
    })

    cv_results = _build_cv_results(ets_cv, arima_cv)

    logger.info(
        f"Models fitted. Forecast horizon: {forecast_horizon}",
        extra={"file_hash": file_hash},
    )

    return {
        "forecasts": forecasts,
        "cv_results": cv_results,
    }


def run_models(
    df: pd.DataFrame,
    freq: str,
    seasonal_period: int | None,
    forecast_horizon: int,
    file_hash: str = "",
) -> dict:
    """Convenience wrapper that fits both models and builds results."""
    with log_stage(logger, "modeling", file_hash=file_hash, row_count=len(df)):
        ets_result = fit_ets(df, seasonal_period, forecast_horizon, file_hash)
        arima_result = fit_arima(df, seasonal_period, forecast_horizon, file_hash)
        return build_forecast_df(df, freq, forecast_horizon, ets_result, arima_result, file_hash)


def _fit_auto_ets(
    y: np.ndarray,
    seasonal_period: int | None,
    horizon: int,
    n_windows: int,
) -> tuple:
    best_model = None
    best_aic = float("inf")

    sp = seasonal_period if seasonal_period and seasonal_period > 1 else None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        for trend in ETS_TREND_OPTIONS:
            seasonal_options = ETS_SEASONAL_OPTIONS if sp else [None]
            for seasonal in seasonal_options:
                try:
                    model = ExponentialSmoothing(
                        y,
                        trend=trend,
                        seasonal=seasonal,
                        seasonal_periods=sp,
                        initialization_method="estimated",
                    ).fit(optimized=True, use_brute=False)

                    if model.aic < best_aic:
                        best_aic = model.aic
                        best_model = (trend, seasonal)
                except Exception:
                    continue

    # Cross-validation
    cv_results = _rolling_cv_ets(y, best_model, sp, horizon, n_windows)

    # Final forecast
    try:
        trend, seasonal = best_model if best_model else (None, None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            final_model = ExponentialSmoothing(
                y, trend=trend, seasonal=seasonal,
                seasonal_periods=sp, initialization_method="estimated",
            ).fit(optimized=True, use_brute=False)

        forecast = final_model.forecast(horizon)
        residual_std = np.std(final_model.resid)
        if np.isnan(residual_std) or residual_std == 0:
            residual_std = max(float(np.std(y)), 1e-10)
    except Exception as e:
        logger.warning(f"Final ETS fit failed, falling back to naive mean: {e}")
        forecast = np.full(horizon, float(np.mean(y)))
        residual_std = max(float(np.std(y)), 1e-10)

    # Expanding confidence intervals: wider as horizon increases
    steps = np.arange(1, horizon + 1)
    widths = 1.28 * residual_std * np.sqrt(steps)  # 80% CI, grows with sqrt(h)
    ci_lo = forecast - widths
    ci_hi = forecast + widths

    return cv_results, forecast, (ci_lo, ci_hi)


def _fit_auto_sarima(
    y: np.ndarray,
    seasonal_period: int | None,
    horizon: int,
    n_windows: int,
) -> tuple:
    seasonal = seasonal_period is not None and seasonal_period > 1
    m = seasonal_period if seasonal else 1

    # Short-circuit for zero-variance (stagnant) data — no model needed
    if np.std(y) < 1e-10:
        mean_val = float(np.mean(y))
        forecast = np.full(horizon, mean_val)
        n_cv = min(horizon, len(y))
        cv_results = [{"y": float(y[-n_cv + j]), "AutoARIMA": mean_val} for j in range(n_cv)]
        ci_lo = np.full(horizon, mean_val)
        ci_hi = np.full(horizon, mean_val)
        return cv_results, forecast, (ci_lo, ci_hi)

    # Reduce search space for larger datasets
    large = len(y) > 200
    max_pq = 2 if large else 3

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arima_model = pm.auto_arima(
                y,
                seasonal=seasonal,
                m=m,
                max_p=max_pq,
                max_q=max_pq,
                max_P=1,
                max_Q=1,
                max_d=2,
                max_D=1,
                stepwise=True,
                suppress_warnings=True,
                error_action="ignore",
            )

        # Cross-validation
        order = arima_model.order
        seasonal_order = arima_model.seasonal_order
        cv_results = _rolling_cv_sarima(y, order, seasonal_order, horizon, n_windows)

        # Final forecast with confidence intervals
        forecast, conf_int = arima_model.predict(n_periods=horizon, return_conf_int=True, alpha=0.20)
        ci_lo = conf_int[:, 0]
        ci_hi = conf_int[:, 1]
    except Exception as e:
        logger.warning(f"AutoARIMA failed, falling back to naive mean: {e}")
        mean_val = float(np.mean(y))
        forecast = np.full(horizon, mean_val)
        residual_std = max(float(np.std(y)), 1e-10)
        steps = np.arange(1, horizon + 1)
        widths = 1.28 * residual_std * np.sqrt(steps)
        ci_lo = forecast - widths
        ci_hi = forecast + widths
        n_cv = min(horizon, len(y))
        cv_results = [{"y": float(y[-n_cv + j]), "AutoARIMA": mean_val} for j in range(n_cv)]

    return cv_results, forecast, (ci_lo, ci_hi)


def _rolling_cv_ets(
    y: np.ndarray,
    model_params: tuple | None,
    sp: int | None,
    horizon: int,
    n_windows: int,
) -> list[dict]:
    results = []
    n = len(y)
    step = max(1, horizon)
    trend, seasonal = model_params if model_params else (None, None)

    for i in range(n_windows):
        test_end = n - i * step
        test_start = test_end - horizon
        if test_start < max(horizon, 2):
            break

        train = y[:test_start]
        actual = y[test_start:test_end]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                model = ExponentialSmoothing(
                    train, trend=trend, seasonal=seasonal,
                    seasonal_periods=sp, initialization_method="estimated",
                ).fit(optimized=True, use_brute=False)
                pred = model.forecast(horizon)
            except Exception:
                fallback = float(np.mean(train)) if len(train) > 0 else float(np.mean(y))
                pred = np.full(horizon, fallback)

        for j in range(len(actual)):
            results.append({"y": actual[j], "AutoETS": pred[j]})

    return results


def _rolling_cv_sarima(
    y: np.ndarray,
    order: tuple,
    seasonal_order: tuple,
    horizon: int,
    n_windows: int,
) -> list[dict]:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    results = []
    n = len(y)
    step = max(1, horizon)

    for i in range(n_windows):
        test_end = n - i * step
        test_start = test_end - horizon
        if test_start < max(horizon, 2):
            break

        train = y[:test_start]
        actual = y[test_start:test_end]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                maxiter = 30 if len(y) > 200 else 50
                model = SARIMAX(
                    train, order=order, seasonal_order=seasonal_order,
                    enforce_stationarity=False, enforce_invertibility=False,
                ).fit(disp=False, maxiter=maxiter)
                pred = model.forecast(horizon)
            except Exception:
                fallback = float(np.mean(train)) if len(train) > 0 else float(np.mean(y))
                pred = np.full(horizon, fallback)

        for j in range(len(actual)):
            results.append({"y": actual[j], "AutoARIMA": pred[j]})

    return results


def _build_cv_results(ets_cv: list[dict], arima_cv: list[dict]) -> pd.DataFrame:
    # Merge CV results - they may have different lengths
    max_len = max(len(ets_cv), len(arima_cv))

    y_vals = []
    ets_preds = []
    arima_preds = []

    for i in range(max_len):
        if i < len(ets_cv):
            y_vals.append(ets_cv[i]["y"])
            ets_preds.append(ets_cv[i]["AutoETS"])
        else:
            y_vals.append(arima_cv[i]["y"])
            ets_preds.append(np.nan)

        if i < len(arima_cv):
            arima_preds.append(arima_cv[i]["AutoARIMA"])
        else:
            arima_preds.append(np.nan)

    return pd.DataFrame({
        "y": y_vals,
        "AutoETS": ets_preds,
        "AutoARIMA": arima_preds,
    })
