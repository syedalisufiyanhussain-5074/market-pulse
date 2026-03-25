import math

from app.utils.logger import get_logger, log_stage

logger = get_logger("decision")

MAE_TIE_THRESHOLD = 0.03  # 3%

# Display name mapping
DISPLAY_NAMES = {
    "AutoETS": "ETS",
    "AutoARIMA": "ARIMA",
}


def select_best_model(
    metrics: dict,
    preference: str,
    file_hash: str = "",
    model_params: dict | None = None,
    seasonal_period: int | None = None,
    has_seasonality: bool = False,
) -> dict:
    with log_stage(logger, "decision", file_hash=file_hash):
        ets_metrics = metrics["AutoETS"]
        arima_metrics = metrics["AutoARIMA"]
        ma_metrics = metrics["Moving Average (Excel)"]
        excel_ets_metrics = metrics["ETS (Excel)"]

        ets_mae = ets_metrics["mae"] if not math.isnan(ets_metrics["mae"]) else float("inf")
        arima_mae = arima_metrics["mae"] if not math.isnan(arima_metrics["mae"]) else float("inf")

        # Step 0: Structural check — disqualify random walk ARIMA on seasonal data
        # ARIMA(0,1,0) with no seasonal component is a random walk that cannot
        # forecast patterns. If data is genuinely seasonal and ETS captured it,
        # prefer ETS regardless of MAE.
        arima_disqualified = False
        arima_order = (model_params or {}).get("arima", {}).get("order", (0, 0, 0))
        arima_seasonal = (model_params or {}).get("arima", {}).get("seasonal_order", (0, 0, 0, 0))
        ets_seasonal = (model_params or {}).get("ets", {}).get("seasonal")
        is_random_walk = (tuple(arima_order) == (0, 1, 0) and
                          arima_seasonal[0] == 0 and arima_seasonal[1] == 0 and arima_seasonal[2] == 0)

        if is_random_walk and has_seasonality and ets_seasonal is not None:
            logger.info(
                f"ARIMA(0,1,0) cannot forecast seasonal patterns — deferring to seasonal ETS "
                f"(ETS seasonal={ets_seasonal})",
                extra={"file_hash": file_hash},
            )
            selected, alternative = "AutoETS", "AutoARIMA"
            selected_metrics, alt_metrics = ets_metrics, arima_metrics
            arima_disqualified = True

        if not arima_disqualified:
            # Step 1: Select model with lowest MAE
            if ets_mae <= arima_mae:
                selected, alternative = "AutoETS", "AutoARIMA"
                selected_metrics, alt_metrics = ets_metrics, arima_metrics
            else:
                selected, alternative = "AutoARIMA", "AutoETS"
                selected_metrics, alt_metrics = arima_metrics, ets_metrics

            # Step 2: If MAE difference < 3%, use preference tie-breaking
            mae_diff_ratio = abs(ets_mae - arima_mae) / max(ets_mae, arima_mae, 1e-10)
            if mae_diff_ratio < MAE_TIE_THRESHOLD:
                selected, selected_metrics, alternative, alt_metrics = _apply_preference(
                    ets_metrics, arima_metrics, preference
                )

        # Generate summaries with display names
        selected_display = DISPLAY_NAMES.get(selected, selected)
        alt_display = DISPLAY_NAMES.get(alternative, alternative)

        summary1 = _generate_selected_summary(
            selected_metrics["mae"], selected_metrics["smape"]
        )
        summary2 = _generate_comparison_summary(
            selected_display, selected_metrics, alt_display, alt_metrics,
            ma_metrics, excel_ets_metrics
        )

        log_reason = "arima_disqualified" if arima_disqualified else (
            f"tie={mae_diff_ratio < MAE_TIE_THRESHOLD}" if not arima_disqualified else ""
        )
        logger.info(
            f"Selected: {selected} (MAE={selected_metrics['mae']:.2f}), "
            f"preference={preference}, {log_reason}",
            extra={"file_hash": file_hash},
        )

        return {
            "selected_model": selected,
            "alternative_model": alternative,
            "selected_metrics": selected_metrics,
            "alternative_metrics": alt_metrics,
            "summary1": summary1,
            "summary2": summary2,
        }


def _apply_preference(
    ets_metrics: dict, arima_metrics: dict, preference: str
) -> tuple:
    if preference == "conservative":
        # Prefer negative MFE (under-predicts)
        if ets_metrics["mfe"] <= arima_metrics["mfe"]:
            return "AutoETS", ets_metrics, "AutoARIMA", arima_metrics
        return "AutoARIMA", arima_metrics, "AutoETS", ets_metrics
    else:
        # Capacity-buffered: prefer positive MFE (over-predicts)
        if ets_metrics["mfe"] >= arima_metrics["mfe"]:
            return "AutoETS", ets_metrics, "AutoARIMA", arima_metrics
        return "AutoARIMA", arima_metrics, "AutoETS", ets_metrics


def _generate_selected_summary(mae: float, smape: float) -> str:
    return (
        f"This model was selected because it matched your historical data most accurately. "
        f"On average, its forecasts differed from actual values by about {mae:,.0f} points "
        f"(\u2248{smape:.1f}%), indicating strong accuracy relative to the overall scale of the data. "
        f"By capturing the underlying trend and seasonal patterns, it provides stable and "
        f"dependable projections for future planning."
    )


def update_comparison_summary(
    decision: dict, metrics: dict, forecast_deviation_pct: dict
) -> None:
    """Re-generate summary2 using Forecast Deviation % from final forecasts."""
    selected_display = DISPLAY_NAMES.get(decision["selected_model"], decision["selected_model"])
    alt_display = DISPLAY_NAMES.get(decision["alternative_model"], decision["alternative_model"])
    decision["summary2"] = _generate_comparison_summary(
        selected_display, decision["selected_metrics"],
        alt_display, decision["alternative_metrics"],
        metrics["Moving Average (Excel)"], metrics["ETS (Excel)"],
        forecast_deviation_pct=forecast_deviation_pct,
    )


def _generate_comparison_summary(
    selected_display: str,
    selected_metrics: dict,
    alt_display: str,
    alt_metrics: dict,
    ma_metrics: dict,
    excel_ets_metrics: dict,
    forecast_deviation_pct: dict | None = None,
) -> str:
    if forecast_deviation_pct:
        # Forecast Deviation %: divergence from primary model's forecast
        alt_internal = "AutoARIMA" if selected_display == "ETS" else "AutoETS"
        alt_pct_val = forecast_deviation_pct.get(alt_internal, 0.0)
        ma_pct_val = forecast_deviation_pct.get("Moving Average (Excel)", 0.0)
        ets_pct_val = forecast_deviation_pct.get("ETS (Excel)", 0.0)
        alt_pct = f"{alt_pct_val:.1f}%"
        ma_pct = f"{ma_pct_val:.1f}%"
        excel_ets_pct = f"{ets_pct_val:.1f}%"
    else:
        # Fallback: CV-based MAE comparison
        selected_mae = selected_metrics["mae"]

        def pct_change(baseline_mae: float) -> tuple[float, str]:
            if selected_mae == 0 and baseline_mae == 0:
                return 0.0, "0.0%"
            if baseline_mae == 0 or baseline_mae == float("inf"):
                return 0.0, "N/A"
            improvement = ((baseline_mae - selected_mae) / baseline_mae) * 100
            return improvement, f"{abs(improvement):.1f}%"

        ma_pct_val, ma_pct = pct_change(ma_metrics["mae"])
        ets_pct_val, excel_ets_pct = pct_change(excel_ets_metrics["mae"])
        alt_pct_val, alt_pct = pct_change(alt_metrics["mae"])

    if forecast_deviation_pct:
        # Deviation %: unbounded divergence metric — use "differs by" wording
        return (
            f"The {selected_display} model matched your historical data more accurately. "
            f"Its forecast differs from Moving Average (Excel) by {ma_pct}, "
            f"from ETS (Excel) by {excel_ets_pct}, and from the alternative statistical "
            f"model, {alt_display}, by {alt_pct}, delivering the most consistent "
            f"results overall."
        )

    # MAE fallback: bounded 0-100% improvement — "reduced by" wording is safe
    ma_phrase = f"reduced average variation by {ma_pct}" if ma_pct_val >= 0 else f"showed {ma_pct} higher average variation than"
    ets_phrase = f"{excel_ets_pct}" if ets_pct_val >= 0 else f"{excel_ets_pct} higher variation than"
    alt_verb = "outperformed" if alt_pct_val >= 0 else "was outperformed by"

    return (
        f"The {selected_display} model matched your historical data more accurately and "
        f"{ma_phrase} compared to Moving Average (Excel) and "
        f"{ets_phrase} compared to ETS (Excel). It also {alt_verb} the alternative "
        f"statistical model, {alt_display}, by {alt_pct}, delivering the most consistent "
        f"results overall."
    )
