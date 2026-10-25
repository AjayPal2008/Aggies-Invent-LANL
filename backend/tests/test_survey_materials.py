from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from backend.survey_materials import extract_pdf


def test_pdf_passages_keep_source_and_page(tmp_path):
    pdf = tmp_path / "sample.pdf"
    canvas = Canvas(str(pdf))
    canvas.drawString(30, 750, "Equipment Basics STUDENT MANUAL")
    canvas.showPage()
    canvas.drawString(30, 750, "Table of contents")
    canvas.showPage()
    passage = "A pressure gauge is an instrument that displays the pressure inside a system and provides information for understanding the condition of the equipment."
    canvas.drawString(30, 750, passage)
    canvas.save()
    resource = extract_pdf(pdf)
    point = resource["data"]["key_points"][0]
    assert resource["data"]["title"] == "Equipment Basics"
    assert point["explanation"] == passage
    assert passage in resource["raw"]
    assert point["page"] == 3
    assert resource["data"]["document"] == "sample.pdf"

