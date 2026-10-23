"""Generate three synthetic PDFs for the Docling spike (no real data)."""

import io
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
styles = getSampleStyleSheet()
body = "ABC Company keeps controlled documents in a local folder. " * 6

story = [Paragraph("Quality Manual", styles["Title"])]
for number, title in enumerate(["Scope", "Document control", "Records"], start=1):
    story.append(Paragraph(f"{number}. {title}", styles["Heading1"]))
    story.append(Paragraph(body, styles["BodyText"]))
    story.append(Paragraph(f"{number}.1 Responsibilities", styles["Heading2"]))
    story.append(Paragraph(body, styles["BodyText"]))
SimpleDocTemplate(str(out / "headings.pdf"), pagesize=A4).build(story)

rows = [["Code", "Title", "Owner", "Revision", "Retention"]]
rows += [[f"QP-{n:02d}", f"Procedure {n}", "QA", str(n % 3), f"{n + 1} years"] for n in range(1, 9)]
rows.append(["", "Merged cell row spanning title and owner", "", "", "-"])
table = Table(rows, repeatRows=1)
table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("SPAN", (1, -1), (2, -1)),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
SimpleDocTemplate(str(out / "table.pdf"), pagesize=A4).build(
    [Paragraph("Document register", styles["Heading1"]), Spacer(1, 12), table,
     Spacer(1, 12), Paragraph("Two-column note: " + body, styles["BodyText"])])

long_story = []
for chapter in range(1, 31):
    long_story.append(Paragraph(f"{chapter}. Chapter {chapter}", styles["Heading1"]))
    long_story += [Paragraph(body, styles["BodyText"]) for _ in range(3)]
    long_story.append(Table(rows[:6], style=[("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    long_story.append(PageBreak())
SimpleDocTemplate(str(out / "long30.pdf"), pagesize=A4).build(long_story)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

image = Image.new("L", (1240, 1754), 255)
draw = ImageDraw.Draw(image)
try:
    font = ImageFont.truetype("DejaVuSans.ttf", 40)
    small = ImageFont.truetype("DejaVuSans.ttf", 28)
except OSError:
    font = small = ImageFont.load_default()
draw.text((100, 120), "Inspection Record", font=font, fill=0)
for line, text in enumerate(["Equipment: Pump P-01", "Date: 2026-01-15", "Result: Pass", "Inspector: ABC"]):
    draw.text((100, 260 + line * 60), text, font=small, fill=0)
image = image.rotate(1.5, fillcolor=255)
buffer = io.BytesIO()
image.save(buffer, format="PNG")
buffer.seek(0)
pdf = canvas.Canvas(str(out / "scanned.pdf"), pagesize=A4)
pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
pdf.save()
print("written", sorted(p.name for p in out.glob("*.pdf")))
