from app.utils.logger import get_logger, log_stage

logger = get_logger("decision")

MAE_TIE_THRESHOLD = 0.03  # 3%


def select_best_model(
    metrics: dict,
    preference: str,
    file_hash: str = "",
) -> dict:
    with log_stage(logger, "decision", file_hash=file_hash):
        ets_metrics = metrics["AutoETS"]
        arima_metrics = metrics["AutoARIMA"]
        ma_metrics = metrics["Moving Average"]
        trend_metrics = metrics["Linear Trend"]

        ets_mae = ets_metrics["mae"]
        arima_mae = arima_metrics["mae"]

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

        # Generate summaries
        summary1 = _generate_selected_summary(selected_metrics["mae"])
        summary2 = _generate_comparison_summary(
            selected, selected_metrics, alt_metrics, ma_metrics, trend_metrics
        )

        logger.info(
            f"Selected: {selected} (MAE={selected_metrics['mae']:.2f}), "
            f"preference={preference}, tie={mae_diff_ratio < MAE_TIE_THRESHOLD}",
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


def _generate_selected_summary(mae: float) -> str:
    return (
        f"This model was selected because it delivered the strongest historical performance. "
        f"On average, past projections varied by approximately {mae:.2f} units. "
        f"The forecast follows your established trend and seasonal patterns, "
        f"providing stable and consistent projections."
    )


def _generate_comparison_summary(
    selected: str,
    selected_metrics: dict,
    alt_metrics: dict,
    ma_metrics: dict,
    trend_metrics: dict,
) -> str:
    selected_mae = selected_metrics["mae"]

    def pct_improvement(baseline_mae: float) -> str:
        if baseline_mae == 0 or baseline_mae == float("inf"):
            return "N/A"
        improvement = ((baseline_mae - selected_mae) / baseline_mae) * 100
        return f"{improvement:.1f}%"

    ma_pct = pct_improvement(ma_metrics["mae"])
    trend_pct = pct_improvement(trend_metrics["mae"])
    alt_pct = pct_improvement(alt_metrics["mae"])
    alt_name = "AutoARIMA" if selected == "AutoETS" else "AutoETS"

    return (
        f"The selected model reduced average variation (MAE) by {ma_pct} compared to Moving Average "
        f"and {trend_pct} compared to Linear Trend. It also outperformed the alternative statistical "
        f"model ({alt_name}) by {alt_pct}, delivering the most consistent results overall."
    )
