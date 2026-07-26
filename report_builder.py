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


def _report_doc():
    """Shared PDF document + story scaffold for the per-category reports
    (Sales/Inventory/Vendor/Customer), so each one doesn't repeat the same
    margin/style boilerplate as build_summary_pdf."""
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
    return buffer, doc, styles, title_style, heading_style


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


# ---------- Step 17: separate Sales / Inventory / Vendor / Customer reports ----------

def build_sales_report_pdf(data, generated_by):
    """data: {total_revenue, gmv, order_count, completed_order_count, aov,
    by_status: [{status, count}], by_payment: [{payment_method, revenue}],
    monthly: [{month, revenue}]}."""
    buffer, doc, styles, title_style, heading_style = _report_doc()
    story = [
        Paragraph("Infinity Mart — Sales Report", title_style),
        Paragraph(f"Generated: {date.today().isoformat()} by {generated_by}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph("Key Metrics", heading_style),
        _table(
            ["Metric", "Value"],
            [
                ["GMV", f"${data['gmv']:.2f}"],
                ["Revenue", f"${data['total_revenue']:.2f}"],
                ["Orders", str(data["order_count"])],
                ["Completed Orders", str(data["completed_order_count"])],
                ["Average Order Value", f"${data['aov']:.2f}"],
            ],
            col_widths=[3 * inch, 3 * inch],
        ),
        Spacer(1, 0.25 * inch),
    ]

    if data["by_status"]:
        story.append(Paragraph("Orders by Status", heading_style))
        story.append(_table(
            ["Status", "Orders"],
            [[r["status"], str(int(r["count"]))] for r in data["by_status"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    if data["by_payment"]:
        story.append(Paragraph("Revenue by Payment Method", heading_style))
        story.append(_table(
            ["Payment Method", "Revenue"],
            [[r["payment_method"], f"${r['revenue']:.2f}"] for r in data["by_payment"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    if data["monthly"]:
        story.append(Paragraph("Revenue by Month", heading_style))
        story.append(_table(
            ["Month", "Revenue"],
            [[r["month"], f"${r['revenue']:.2f}"] for r in data["monthly"]],
            col_widths=[4 * inch, 2 * inch],
        ))

    doc.build(story)
    return buffer.getvalue()


def build_inventory_report_pdf(data, generated_by):
    """data: {product_count, total_stock, low_stock_count, out_of_stock_count,
    low_stock: [{product, vendor, stock_quantity, reorder_level}]}."""
    buffer, doc, styles, title_style, heading_style = _report_doc()
    story = [
        Paragraph("Infinity Mart — Inventory Report", title_style),
        Paragraph(f"Generated: {date.today().isoformat()} by {generated_by}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph("Key Metrics", heading_style),
        _table(
            ["Metric", "Value"],
            [
                ["Products", str(data["product_count"])],
                ["Total Stock (units)", str(data["total_stock"])],
                ["Low Stock Items", str(data["low_stock_count"])],
                ["Out of Stock Items", str(data["out_of_stock_count"])],
            ],
            col_widths=[3 * inch, 3 * inch],
        ),
        Spacer(1, 0.25 * inch),
    ]

    if data["low_stock"]:
        story.append(Paragraph("Low / Out of Stock Products", heading_style))
        story.append(_table(
            ["Product", "Vendor", "Stock", "Reorder Level"],
            [
                [p["product"], p["vendor"], str(int(p["stock_quantity"])), str(int(p["reorder_level"]))]
                for p in data["low_stock"]
            ],
            col_widths=[2.5 * inch, 2 * inch, 1 * inch, 1 * inch],
        ))

    doc.build(story)
    return buffer.getvalue()


def build_vendor_report_pdf(data, generated_by):
    """data: {vendor_count, total_revenue, avg_fulfillment_pct, avg_refund_pct,
    vendors: [{vendor, revenue, orders, avg_rating, fulfillment_pct, refund_pct}]}."""
    buffer, doc, styles, title_style, heading_style = _report_doc()
    story = [
        Paragraph("Infinity Mart — Vendor Report", title_style),
        Paragraph(f"Generated: {date.today().isoformat()} by {generated_by}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph("Key Metrics", heading_style),
        _table(
            ["Metric", "Value"],
            [
                ["Vendors", str(data["vendor_count"])],
                ["Total Revenue", f"${data['total_revenue']:.2f}"],
                ["Avg Fulfillment %", f"{data['avg_fulfillment_pct']:.1f}%"],
                ["Avg Refund %", f"{data['avg_refund_pct']:.1f}%"],
            ],
            col_widths=[3 * inch, 3 * inch],
        ),
        Spacer(1, 0.25 * inch),
    ]

    if data["vendors"]:
        story.append(Paragraph("Vendor Performance (top 20 by revenue)", heading_style))
        story.append(_table(
            ["Vendor", "Revenue", "Orders", "Avg Rating", "Fulfillment %", "Refund %"],
            [
                [
                    v["vendor"], f"${v['revenue']:.2f}", str(int(v["orders"])),
                    f"{v['avg_rating']:.2f}", f"{v['fulfillment_pct']:.1f}%", f"{v['refund_pct']:.1f}%",
                ]
                for v in data["vendors"][:20]
            ],
            col_widths=[1.8 * inch, 1.1 * inch, 0.7 * inch, 0.9 * inch, 0.9 * inch, 0.8 * inch],
        ))

    doc.build(story)
    return buffer.getvalue()


def build_customer_report_pdf(data, generated_by):
    """data: {customer_count, new_customers, returning_customers, retention_pct,
    churn_pct, clv, segments: [{segment, customers, avg_spend, avg_orders}]}."""
    buffer, doc, styles, title_style, heading_style = _report_doc()
    story = [
        Paragraph("Infinity Mart — Customer Report", title_style),
        Paragraph(f"Generated: {date.today().isoformat()} by {generated_by}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph("Key Metrics", heading_style),
        _table(
            ["Metric", "Value"],
            [
                ["Total Customers", str(data["customer_count"])],
                ["New Customers (30d)", str(data["new_customers"])],
                ["Returning Customers (30d)", str(data["returning_customers"])],
                ["Retention %", f"{data['retention_pct']:.1f}%"],
                ["Churn %", f"{data['churn_pct']:.1f}%"],
                ["CLV (lifetime avg)", f"${data['clv']:.2f}"],
            ],
            col_widths=[3.2 * inch, 2.8 * inch],
        ),
        Spacer(1, 0.25 * inch),
    ]

    if data["segments"]:
        story.append(Paragraph("Customer Segments", heading_style))
        story.append(_table(
            ["Segment", "Customers", "Avg Spend", "Avg Orders"],
            [
                [s["segment"], str(int(s["customers"])), f"${s['avg_spend']:.2f}", f"{s['avg_orders']:.1f}"]
                for s in data["segments"]
            ],
            col_widths=[2 * inch, 1.5 * inch, 1.5 * inch, 1 * inch],
        ))

    doc.build(story)
    return buffer.getvalue()
