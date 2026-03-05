import base64
import io
from datetime import datetime

from fpdf import FPDF

from app.utils.logger import get_logger, log_stage

logger = get_logger("pdf_export")


class MarketPulsePDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(148, 163, 184)  # slate-400
        self.cell(0, 8, "Market Pulse - Forecast Report", align="R", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(148, 163, 184)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


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
        pdf = MarketPulsePDF()
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)

        # Page 1: Title page
        pdf.add_page()
        pdf.ln(30)
        pdf.set_font("Helvetica", "B", 28)
        pdf.set_text_color(16, 185, 129)  # emerald-500
        pdf.cell(0, 15, "Market Pulse", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 14)
        pdf.set_text_color(100, 116, 139)  # slate-500
        pdf.cell(0, 10, "Forecast Report", align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(20)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(51, 65, 85)  # slate-700

        _add_info_row(pdf, "Selected Model", selected_model)
        _add_info_row(pdf, "MAE", f"{mae_value:.2f}")
        _add_info_row(pdf, "Forecast Horizon", f"{forecast_horizon} periods")
        _add_info_row(pdf, "Generated", datetime.now().strftime("%B %d, %Y at %H:%M"))

        # Page 2: Graph 1 + Summary 1
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(30, 41, 59)  # slate-800
        pdf.cell(0, 12, "Selected Model Forecast", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        _embed_chart(pdf, chart1_base64)
        pdf.ln(8)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(71, 85, 105)  # slate-600
        pdf.multi_cell(0, 6, summary1)

        # Page 3: Graph 2 + Summary 2
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(30, 41, 59)
        pdf.cell(0, 12, "Model Comparison", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        _embed_chart(pdf, chart2_base64)
        pdf.ln(8)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(71, 85, 105)
        pdf.multi_cell(0, 6, summary2)

        return pdf.output()


def _add_info_row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(60, 8, label + ":", new_x="RIGHT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 8, value, new_x="LMARGIN", new_y="NEXT")


def _embed_chart(pdf: FPDF, chart_base64: str) -> None:
    img_bytes = base64.b64decode(chart_base64)
    img_stream = io.BytesIO(img_bytes)
    pdf.image(img_stream, x=10, w=190)
