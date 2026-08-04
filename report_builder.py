"""Builds the PDF and Excel exports for the Generate Reports page."""
import io
from datetime import date

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PURPLE = colors.HexColor("#6d28d9")
LIGHT_PURPLE = colors.HexColor("#ede9fe")


def _table(headers, rows, col_widths=None):
    table = Table([headers] + rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_PURPLE]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_summary_pdf(report, generated_by):
    """report: {total_revenue, order_count, vendor_count, product_count,
    customer_count, top_vendors: [{vendor, revenue}], top_products: [{product, revenue}],
    low_stock: [{name, vendor, stock_quantity}]}. Returns PDF bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.textColor = PURPLE
    heading_style = styles["Heading2"]
    heading_style.textColor = PURPLE

    story = [
        Paragraph("Infinity Mart — Summary Report", title_style),
        Paragraph(f"Generated: {date.today().isoformat()} by {generated_by}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph("Key Metrics", heading_style),
        _table(
            ["Metric", "Value"],
            [
                ["Total Revenue", f"${report['total_revenue']:.2f}"],
                ["Orders", str(report["order_count"])],
                ["Vendors", str(report["vendor_count"])],
                ["Products", str(report["product_count"])],
                ["Customers", str(report["customer_count"])],
            ],
            col_widths=[3 * inch, 3 * inch],
        ),
        Spacer(1, 0.25 * inch),
    ]

    if report["top_vendors"]:
        story.append(Paragraph("Top Vendors by Revenue", heading_style))
        story.append(_table(
            ["Vendor", "Revenue"],
            [[v["vendor"], f"${v['revenue']:.2f}"] for v in report["top_vendors"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    if report["top_products"]:
        story.append(Paragraph("Top Products by Revenue", heading_style))
        story.append(_table(
            ["Product", "Revenue"],
            [[p["product"], f"${p['revenue']:.2f}"] for p in report["top_products"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    if report["low_stock"]:
        story.append(Paragraph("Low / Out of Stock Products", heading_style))
        story.append(_table(
            ["Product", "Vendor", "Stock"],
            [[p["name"], p["vendor"], str(int(p["stock_quantity"]))] for p in report["low_stock"]],
            col_widths=[3 * inch, 2 * inch, 1 * inch],
        ))

    doc.build(story)
    return buffer.getvalue()


def build_summary_excel(report):
    """Same report payload as build_summary_pdf. Returns .xlsx bytes."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([
            {"Metric": "Total Revenue", "Value": report["total_revenue"]},
            {"Metric": "Orders", "Value": report["order_count"]},
            {"Metric": "Vendors", "Value": report["vendor_count"]},
            {"Metric": "Products", "Value": report["product_count"]},
            {"Metric": "Customers", "Value": report["customer_count"]},
        ]).to_excel(writer, sheet_name="Summary", index=False)

        if report["top_vendors"]:
            pd.DataFrame(report["top_vendors"]).to_excel(writer, sheet_name="Top Vendors", index=False)
        if report["top_products"]:
            pd.DataFrame(report["top_products"]).to_excel(writer, sheet_name="Top Products", index=False)
        if report["low_stock"]:
            pd.DataFrame(report["low_stock"]).to_excel(writer, sheet_name="Low Stock", index=False)

    return buffer.getvalue()
