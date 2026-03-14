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
) -> dict:
    with log_stage(logger, "decision", file_hash=file_hash):
        ets_metrics = metrics["AutoETS"]
        arima_metrics = metrics["AutoARIMA"]
        ma_metrics = metrics["Moving Average (Excel)"]
        excel_ets_metrics = metrics["ETS (Excel)"]

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


def _generate_selected_summary(mae: float, smape: float) -> str:
    return (
        f"This model was selected because it matched your historical data most accurately. "
        f"On average, its forecasts differed from actual values by about {mae:,.0f} points "
        f"(\u2248{smape:.1f}%), indicating strong accuracy relative to the overall scale of the data. "
        f"By capturing the underlying trend and seasonal patterns, it provides stable and "
        f"dependable projections for future planning."
    )


def _generate_comparison_summary(
    selected_display: str,
    selected_metrics: dict,
    alt_display: str,
    alt_metrics: dict,
    ma_metrics: dict,
    excel_ets_metrics: dict,
) -> str:
    selected_mae = selected_metrics["mae"]

    def pct_change(baseline_mae: float) -> tuple[float, str]:
        if selected_mae == 0 and baseline_mae == 0:
            return 0.0, "0.0%"  # Both models are perfect
        if baseline_mae == 0 or baseline_mae == float("inf"):
            return 0.0, "N/A"
        improvement = ((baseline_mae - selected_mae) / baseline_mae) * 100
        return improvement, f"{abs(improvement):.1f}%"

    ma_val, ma_pct = pct_change(ma_metrics["mae"])
    ets_val, excel_ets_pct = pct_change(excel_ets_metrics["mae"])
    alt_val, alt_pct = pct_change(alt_metrics["mae"])

    # Use "reduced" for positive improvement, "with higher variation of" for negative
    ma_phrase = f"reduced average variation by {ma_pct}" if ma_val >= 0 else f"showed {ma_pct} higher average variation than"
    ets_phrase = f"{excel_ets_pct}" if ets_val >= 0 else f"{excel_ets_pct} higher variation than"
    alt_verb = "outperformed" if alt_val >= 0 else "was outperformed by"

    return (
        f"The {selected_display} model matched your historical data more accurately and "
        f"{ma_phrase} compared to Moving Average (Excel) and "
        f"{ets_phrase} compared to ETS (Excel). It also {alt_verb} the alternative "
        f"statistical model, {alt_display}, by {alt_pct}, delivering the most consistent "
        f"results overall."
    )
