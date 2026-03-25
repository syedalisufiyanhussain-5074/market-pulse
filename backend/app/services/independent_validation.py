"""Independent Validation: R-inspired model fitting for cross-checking Python predictions.

Uses R's forecast package default parameters (replicated in pure Python):
- ETS: includes damped trend search, prefers AICc
- ARIMA: AICc, broader search (max_p/q=5), underfit detection with one-shot retry
- Moving Average / ETS (Excel): identical to Python (no R-specific differences)
"""

import warnings

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing
import pmdarima as pm

from app.services.evaluation import _compute_metrics
from app.services.modeling import _has_seasonality
from app.utils.logger import get_logger

logger = get_logger("independent_validation")

MODEL_ORDER = ["AutoETS", "AutoARIMA", "Moving Average (Excel)", "ETS (Excel)"]


def _aicc(aic: float, n: int, k: int) -> float:
    """Compute AICc (corrected AIC) from AIC, sample size n, and number of params k."""
    if n - k - 1 <= 0:
        return float("inf")
    return aic + (2 * k * (k + 1)) / (n - k - 1)


def fit_ind_ets(y: np.ndarray, sp: int | None, horizon: int) -> np.ndarray:
    """Fit ETS with R-inspired defaults: damped trend search + AICc selection."""
    best_forecast = None
    best_aicc = float("inf")

    seasonal_period = sp if sp and sp > 1 else None
    trend_options = ["add", "mul", None]
    seasonal_options = ["add", "mul", None] if seasonal_period else [None]
    damped_options = [True, False]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        for trend in trend_options:
            for seasonal in seasonal_options:
                for damped in damped_options:
                    # Damped only makes sense with a trend
                    if damped and trend is None:
                        continue
                    if not damped and trend is not None:
                        # Also try non-damped (already covered by damped=False)
                        pass

                    try:
                        model = ExponentialSmoothing(
                            y,
                            trend=trend,
                            damped_trend=damped if trend else False,
                            seasonal=seasonal,
                            seasonal_periods=seasonal_period,
                            initialization_method="estimated",
                        ).fit(optimized=True, use_brute=False)

                        n = len(y)
                        k = len(model.params)
                        aicc = _aicc(model.aic, n, k)

                        if aicc < best_aicc:
                            best_aicc = aicc
                            best_forecast = model.forecast(horizon)
                    except Exception:
                        continue

    if best_forecast is None:
        return np.full(horizon, float(np.mean(y)))

    return best_forecast


def _is_underfitting(y: np.ndarray, forecast: np.ndarray) -> bool:
    """Flag if forecast is near-constant but data has clear trend."""
    tail = y[-min(12, len(y)):]
    diffs = np.diff(tail)
    trend_strength = abs(np.mean(diffs)) / (np.std(diffs) + 1e-10)
    forecast_range = np.ptp(forecast)
    data_range = np.ptp(tail)
    is_flat = forecast_range < 0.05 * data_range if data_range > 0 else False
    return is_flat and trend_strength > 1.5


def _fit_arima_once(y: np.ndarray, seasonal: bool, m: int, horizon: int,
                    max_d: int = 1, trend: str | None = None,
                    with_intercept: bool = True) -> np.ndarray | None:
    """Single ARIMA fit attempt with given constraints."""
    # Disable seasonal when insufficient data for seasonal differencing
    if seasonal and len(y) <= m:
        seasonal = False
        m = 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            kwargs = dict(
                seasonal=seasonal,
                m=m,
                max_p=5,
                max_q=5,
                max_P=2,
                max_Q=2,
                max_d=max_d,
                max_D=1,
                information_criterion="aicc",
                stepwise=True,
                approximation=False,
                with_intercept=with_intercept,
                suppress_warnings=True,
                error_action="ignore",
            )
            if trend is not None:
                kwargs["trend"] = trend
            model = pm.auto_arima(y, **kwargs)
            return model.predict(n_periods=horizon)
    except ValueError as e:
        # Seasonal differencing test failure — retry non-seasonal
        if seasonal:
            logger.info(f"Independent ARIMA seasonal ValueError: {e}. Retrying non-seasonal.")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = pm.auto_arima(
                        y, seasonal=False, max_p=5, max_q=5, max_d=max_d,
                        information_criterion="aicc", stepwise=True,
                        approximation=False, with_intercept=with_intercept,
                        suppress_warnings=True, error_action="ignore",
                    )
                    logger.info(f"Independent ARIMA non-seasonal retry succeeded: order={model.order}")
                    return model.predict(n_periods=horizon)
            except Exception:
                pass
        logger.warning(f"Independent ARIMA fit failed with ValueError: {e}")
        return None
    except Exception as e:
        logger.warning(f"Independent ARIMA fit failed with {type(e).__name__}: {e}")
        return None


def fit_ind_arima(y: np.ndarray, sp: int | None, horizon: int) -> tuple[np.ndarray, str | None]:
    """Fit ARIMA with R-inspired defaults: AICc, full search, underfit detection.

    Returns (forecast, status_override). status_override is None normally,
    or "Weak (Model Limitation)" if underfit persists after retry.
    """
    seasonal = sp is not None and sp > 1
    m = sp if seasonal else 1

    # Skip seasonal modeling if data lacks seasonal patterns
    if seasonal and not _has_seasonality(y, m):
        logger.info("Independent ARIMA: no seasonal pattern detected, using non-seasonal")
        seasonal = False
        m = 1

    # First attempt: max_d=1, with_intercept=True, no approximation
    forecast = _fit_arima_once(y, seasonal, m, horizon, max_d=1, with_intercept=True)

    if forecast is not None and _is_underfitting(y, forecast):
        logger.info("Independent ARIMA underfit detected, retrying with max_d=2, trend='ct'")
        retry = _fit_arima_once(y, seasonal, m, horizon, max_d=2, trend="ct", with_intercept=True)
        if retry is not None:
            if _is_underfitting(y, retry):
                logger.info("Independent ARIMA still underfitting after retry — marking as Model Limitation")
                return retry, "Weak (Model Limitation)"
            return retry, None
        # Retry failed entirely, use original
        return forecast, "Weak (Model Limitation)"

    if forecast is None:
        return np.full(horizon, float(np.mean(y))), "Weak (Model Limitation)"

    return forecast, None


def fit_ind_ma(y: np.ndarray, horizon: int) -> np.ndarray:
    """Moving Average baseline — identical to Python implementation."""
    window = min(horizon, len(y) - horizon)
    if window > 0:
        ma_val = float(np.mean(y[-window:]))
    else:
        ma_val = float(np.mean(y))
    return np.full(horizon, ma_val)


def fit_ind_excel_ets(y: np.ndarray, horizon: int) -> np.ndarray:
    """ETS (Excel) baseline — identical to Python implementation."""
    if len(y) < horizon + 4:
        return np.full(horizon, float(np.mean(y)))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            model = ExponentialSmoothing(
                y, trend="add", seasonal=None,
                initialization_method="estimated",
            ).fit(optimized=True, use_brute=False)
            return model.forecast(horizon)
        except Exception:
            return np.full(horizon, float(np.mean(y)))


def run_independent_models(
    y: np.ndarray,
    sp: int | None,
    horizon: int,
) -> tuple[dict[str, list[float]], dict[str, str | None]]:
    """Run all 4 models with R-inspired defaults.

    Returns (forecasts_dict, status_overrides_dict).
    status_overrides contains non-None values only for models with limitations.
    """
    raw_forecasts = {}
    status_overrides = {}

    raw_forecasts["AutoETS"] = fit_ind_ets(y, sp, horizon)
    status_overrides["AutoETS"] = None

    arima_forecast, arima_status = fit_ind_arima(y, sp, horizon)
    raw_forecasts["AutoARIMA"] = arima_forecast
    status_overrides["AutoARIMA"] = arima_status

    raw_forecasts["Moving Average (Excel)"] = fit_ind_ma(y, horizon)
    status_overrides["Moving Average (Excel)"] = None

    raw_forecasts["ETS (Excel)"] = fit_ind_excel_ets(y, horizon)
    status_overrides["ETS (Excel)"] = None

    # Round all values
    result = {}
    for name in MODEL_ORDER:
        vals = raw_forecasts[name]
        result[name] = [round(float(v), 2) if not np.isnan(v) else None for v in vals]

    return result, status_overrides


def compute_independent_metrics(
    y: np.ndarray,
    horizon: int,
    ind_forecasts: dict[str, list[float]],
) -> dict[str, dict]:
    """Compute MAE, SMAPE, MFE for each independent model using last `horizon` actuals."""
    if len(y) < horizon + 1:
        return {name: {"mae": float("inf"), "smape": float("inf"), "mfe": 0.0} for name in MODEL_ORDER}

    actuals = y[-horizon:]
    metrics = {}
    for name in MODEL_ORDER:
        preds = np.array(ind_forecasts[name], dtype=float)
        metrics[name] = _compute_metrics(actuals, preds[:len(actuals)])
    return metrics


def compute_python_metrics(
    y: np.ndarray,
    horizon: int,
    py_forecasts: dict[str, list[float]],
) -> dict[str, dict]:
    """Compute MAE, SMAPE, MFE for each Python model using last `horizon` actuals.

    Mirrors compute_independent_metrics so both sides are evaluated identically.
    """
    if len(y) < horizon + 1:
        return {name: {"mae": float("inf"), "smape": float("inf"), "mfe": 0.0} for name in MODEL_ORDER}

    actuals = y[-horizon:]
    metrics = {}
    for name in MODEL_ORDER:
        preds = np.array(py_forecasts[name], dtype=float)
        metrics[name] = _compute_metrics(actuals, preds[:len(actuals)])
    return metrics


def compute_variance(
    ind_forecasts: dict[str, list[float]],
    py_forecasts: dict[str, list[float]],
    status_overrides: dict[str, str | None] | None = None,
) -> dict[str, dict]:
    """Compute Var, Var_%, and Status for each model.

    Convention: (MP − R) / MP × 100. Positive = MP predicted higher.
    """
    result = {}
    for name in MODEL_ORDER:
        ind_vals = ind_forecasts.get(name, [])
        py_vals = py_forecasts.get(name, [])

        if not ind_vals or not py_vals:
            result[name] = {"var": [], "var_pct": [], "status": "Weak"}
            continue

        var_list = []
        var_pct_list = []
        for iv, pv in zip(ind_vals, py_vals):
            if iv is None or pv is None:
                var_list.append(None)
                var_pct_list.append(None)
                continue
            diff = round(pv - iv, 2)
            pct = round((pv - iv) / pv * 100, 2) if abs(pv) >= 1e-6 else 0.0
            var_list.append(diff)
            var_pct_list.append(pct)

        # Status based on average absolute Var_%
        valid_pcts = [abs(p) for p in var_pct_list if p is not None]
        avg_abs_pct = np.mean(valid_pcts) if valid_pcts else 0.0

        # Apply status override only when variance is genuinely high (>10%)
        # If variance is low, the models agree — override should not mask that
        override = (status_overrides or {}).get(name)
        if override and avg_abs_pct > 10:
            status = override
        elif avg_abs_pct < 5:
            status = "Strong"
        elif avg_abs_pct <= 10:
            status = "Moderate"
        else:
            status = "Weak"

        result[name] = {"var": var_list, "var_pct": var_pct_list, "status": status}

    return result


# Only models that use genuinely different fitting logic between MP and R
_INDEPENDENT_MODELS = ["AutoETS", "AutoARIMA"]


def compute_agreement_score(
    variance_data: dict[str, dict],
    observation_count: int = 0,
    was_downsampled: bool = False,
) -> dict:
    """Agreement Score = 100 − avg(abs(Var_%)) across genuinely independent models.

    MA and ETS Excel use identical implementations on both sides,
    so they are excluded to avoid inflating the score.

    Returns dict with: score, warnings (list of strings), skip_score (bool).
    """
    warnings = []

    # Frequency alignment: if data was downsampled, score may be unreliable
    if was_downsampled:
        warnings.append(
            "Frequency mismatch: data was downsampled before forecasting. "
            "Agreement Score may not be comparable — marked as 'Not Comparable'."
        )
        return {"score": None, "warnings": warnings, "skip_score": True}

    # Low-observation warning
    if 0 < observation_count < 10:
        warnings.append(
            f"Validation reliability is low for datasets with <10 observations "
            f"(this dataset has {observation_count})."
        )

    all_pcts = []
    for name in _INDEPENDENT_MODELS:
        pcts = variance_data.get(name, {}).get("var_pct", [])
        all_pcts.extend([abs(p) for p in pcts if p is not None])

    if not all_pcts:
        score = 100.0
    else:
        score = round(max(0, 100 - np.mean(all_pcts)), 2)

    # ARIMA divergence note for noisy data
    for name in _INDEPENDENT_MODELS:
        pcts = variance_data.get(name, {}).get("var_pct", [])
        weak_count = sum(1 for p in pcts if p is not None and abs(p) > 10)
        if weak_count > 0 and "ARIMA" in name:
            warnings.append(
                "ARIMA forecasts may vary across implementations on noisy data "
                "due to different model order selection."
            )
            break

    return {"score": score, "warnings": warnings, "skip_score": False}
