import base64
import io
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from app.utils.logger import get_logger, log_stage

logger = get_logger("pdf_export")

# Display name mapping
DISPLAY_NAMES = {
    "AutoETS": "ETS",
    "AutoARIMA": "ARIMA",
}

LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo-vertical.png"
HEADER_COLOR = (100, 100, 100)  # dark grey
FOOTER_COLOR = (100, 100, 100)  # dark grey


class MarketPulsePDF(FPDF):
    def __init__(self, selected_model: str = ""):
        super().__init__()
        self._selected_display = DISPLAY_NAMES.get(selected_model, selected_model)

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*HEADER_COLOR)
        self.cell(0, 7, "Market Pulse - Forecast Report", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*HEADER_COLOR)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*FOOTER_COLOR)
        # Page number: bottom-center
        self.cell(0, 8, f"Page {self.page_no()}", align="C")
        # Timestamp: bottom-right, same line
        self.set_y(-12)
        timestamp = datetime.now().strftime("%B %d, %Y at %H:%M")
        self.cell(0, 8, timestamp, align="R")


def generate_pdf(
    selected_model: str,
    mae_value: float,
    forecast_horizon: int,
    summary1: str,
    summary2: str,
    chart1_base64: str,
    chart2_base64: str,
    file_hash: str = "",
) -> bytes:
    with log_stage(logger, "pdf_export", file_hash=file_hash):
        selected_display = DISPLAY_NAMES.get(selected_model, selected_model)
        pdf = MarketPulsePDF(selected_model)
        pdf.set_auto_page_break(auto=True, margin=15)

        # ── Page 1: Title + Graph 1 + Summary 1 ──
        pdf.add_page()

        # Logo
        if LOGO_PATH.exists():
            pdf.image(str(LOGO_PATH), x=70, y=20, w=70)
            pdf.ln(65)
        else:
            pdf.ln(15)
            pdf.set_font("Helvetica", "B", 24)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(0, 12, "Market Pulse", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)

        # Tagline
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 6, "See Tomorrow, Today.", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Report name
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 8, "Forecast Report", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)

        # Three report details (no "Generated")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(80, 80, 80)
        _add_info_row(pdf, "Selected Model", selected_display)
        _add_info_row(pdf, "MAE", f"{mae_value:,.2f}")
        _add_info_row(pdf, "Forecast Horizon", f"{forecast_horizon} periods")
        pdf.ln(6)

        # Graph 1 header
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 8, f"Primary Model: {selected_display}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        _embed_chart(pdf, chart1_base64)
        pdf.ln(5)

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 5, _sanitize(summary1))

        # ── Page 2: Graph 2 + Summary 2 ──
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 8, "Model Comparison", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        _embed_chart(pdf, chart2_base64)
        pdf.ln(5)

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 5, _sanitize(summary2))

        return pdf.output()


def _add_info_row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(55, 7, label + ":", new_x="RIGHT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")


def _sanitize(text: str) -> str:
    """Replace Unicode chars unsupported by Helvetica with ASCII equivalents."""
    replacements = {
        "\u2013": "-",   # en dash
        "\u2014": "--",  # em dash
        "\u2248": "~",   # approximately
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _embed_chart(pdf: FPDF, chart_base64: str) -> None:
    img_bytes = base64.b64decode(chart_base64)
    img_stream = io.BytesIO(img_bytes)
    pdf.image(img_stream, x=10, w=190)
