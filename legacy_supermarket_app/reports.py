import io
from datetime import date

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

PURPLE = colors.HexColor("#6d28d9")
LIGHT_PURPLE = colors.HexColor("#ede9fe")


def _table(headers, rows, col_widths=None):
    data = [headers] + rows
    table = Table(data, colWidths=col_widths)
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
    """Renders a full_report() payload into a PDF and returns the raw bytes."""
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
        Paragraph("Infinity Mart Insights — Summary Report", title_style),
        Paragraph(f"Scope: {report['scope']}", styles["Normal"]),
        Paragraph(f"Generated: {date.today().isoformat()} by {generated_by}", styles["Normal"]),
        Spacer(1, 0.25 * inch),
    ]

    stats = report["summary"]
    story.append(Paragraph("Key Metrics", heading_style))
    story.append(_table(
        ["Metric", "Value"],
        [
            ["Total Revenue", f"${stats['total_revenue']:.2f}"],
            ["Transactions", str(stats["total_transactions"])],
            ["Avg. Basket Size", f"${stats['avg_basket']:.2f}"],
            ["Reward Points Issued", str(stats["total_reward_points"])],
        ],
        col_widths=[3 * inch, 3 * inch],
    ))
    story.append(Spacer(1, 0.25 * inch))

    if stats["top_products"]:
        story.append(Paragraph("Top Products", heading_style))
        story.append(_table(
            ["Product", "Revenue"],
            [[p["product_name"], f"${p['total_price']:.2f}"] for p in stats["top_products"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    if stats["sales_by_branch"]:
        story.append(Paragraph("Revenue by Branch", heading_style))
        story.append(_table(
            ["Branch", "Revenue"],
            [[r["branch"], f"${r['total_price']:.2f}"] for r in stats["sales_by_branch"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    if stats["sales_by_category"]:
        story.append(Paragraph("Revenue by Category", heading_style))
        story.append(_table(
            ["Category", "Revenue"],
            [[r["product_category"], f"${r['total_price']:.2f}"] for r in stats["sales_by_category"]],
            col_widths=[4 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    day_stats = report["day_stats"]
    if day_stats["revenue_by_day"]:
        story.append(Paragraph("Revenue by Day of Week", heading_style))
        story.append(_table(
            ["Day", "Revenue", "Transactions"],
            [[d["day_of_week"], f"${d['total_revenue']:.2f}", str(d["transactions"])] for d in day_stats["revenue_by_day"]],
            col_widths=[2 * inch, 2 * inch, 2 * inch],
        ))
        story.append(Paragraph(
            f"Busiest day: {day_stats['best_day']} · Slowest day: {day_stats['worst_day']}",
            styles["Normal"],
        ))
        story.append(Spacer(1, 0.25 * inch))

    tiers = report["tiers"]
    if tiers["tiers"]:
        story.append(Paragraph("Membership Tier Summary", heading_style))
        story.append(_table(
            ["Tier", "Transactions", "Revenue"],
            [[t["tier"], str(t["transactions"]), f"${t['revenue']:.2f}"] for t in tiers["tiers"]],
            col_widths=[2 * inch, 2 * inch, 2 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    products = report.get("products", {})
    if products.get("best_sellers"):
        story.append(Paragraph("Product Report — Best Sellers", heading_style))
        story.append(_table(
            ["Product", "Revenue", "Qty Sold"],
            [[p["product_name"], f"${p['revenue']:.2f}", str(p["quantity_sold"])] for p in products["best_sellers"]],
            col_widths=[3 * inch, 1.5 * inch, 1.5 * inch],
        ))
        story.append(Spacer(1, 0.2 * inch))
    if products.get("least_sellers"):
        story.append(Paragraph("Product Report — Least Sellers", heading_style))
        story.append(_table(
            ["Product", "Revenue", "Qty Sold"],
            [[p["product_name"], f"${p['revenue']:.2f}", str(p["quantity_sold"])] for p in products["least_sellers"]],
            col_widths=[3 * inch, 1.5 * inch, 1.5 * inch],
        ))
        story.append(Spacer(1, 0.2 * inch))
    if products.get("category_performance"):
        story.append(Paragraph("Product Category Performance", heading_style))
        story.append(_table(
            ["Category", "Revenue", "Qty Sold"],
            [[c["product_category"], f"${c['revenue']:.2f}", str(c["quantity_sold"])] for c in products["category_performance"]],
            col_widths=[3 * inch, 1.5 * inch, 1.5 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    inventory = report.get("inventory", {})
    if inventory.get("available"):
        story.append(Paragraph("Inventory Report", heading_style))
        story.append(_table(
            ["Metric", "Value"],
            [
                ["Products Tracked", str(inventory["total_products"])],
                ["Low Stock", str(inventory["low_stock_count"])],
                ["Out of Stock", str(inventory["out_of_stock_count"])],
            ],
            col_widths=[3 * inch, 3 * inch],
        ))
        story.append(Spacer(1, 0.25 * inch))

    membership = report.get("membership", {})
    if membership.get("available"):
        story.append(Paragraph("Membership & Loyalty Report", heading_style))
        story.append(_table(
            ["Metric", "Value"],
            [
                ["Member Transactions", str(membership["member_transactions"])],
                ["Reward Points Earned", str(membership["reward_points_earned"])],
            ],
            col_widths=[3 * inch, 3 * inch],
        ))
        if membership.get("purchases_by_membership"):
            story.append(Spacer(1, 0.1 * inch))
            story.append(_table(
                ["Customer Type", "Transactions", "Revenue"],
                [[m["customer_type"], str(m["transactions"]), f"${m['revenue']:.2f}"] for m in membership["purchases_by_membership"]],
                col_widths=[2 * inch, 2 * inch, 2 * inch],
            ))
        story.append(Spacer(1, 0.25 * inch))

    regional = report.get("regional", {})
    if regional.get("available"):
        story.append(Paragraph("Regional / Branch Report", heading_style))
        story.append(Paragraph(f"Top-performing branch: {regional['top_branch']}", styles["Normal"]))
        story.append(Spacer(1, 0.1 * inch))
        story.append(_table(
            ["Location", "Revenue", "Transactions"],
            [[r["city"], f"${r['revenue']:.2f}", str(r["transactions"])] for r in regional["by_location"]],
            col_widths=[3 * inch, 1.5 * inch, 1.5 * inch],
        ))

    doc.build(story)
    return buffer.getvalue()


def build_summary_excel(report):
    """Renders a full_report() payload into a multi-sheet Excel workbook and returns raw bytes."""
    stats = report["summary"]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([
            {"Metric": "Scope", "Value": report["scope"]},
            {"Metric": "Total Revenue", "Value": stats["total_revenue"]},
            {"Metric": "Transactions", "Value": stats["total_transactions"]},
            {"Metric": "Avg. Basket Size", "Value": stats["avg_basket"]},
            {"Metric": "Reward Points Issued", "Value": stats["total_reward_points"]},
        ]).to_excel(writer, sheet_name="Summary", index=False)

        if stats["top_products"]:
            pd.DataFrame(stats["top_products"]).to_excel(writer, sheet_name="Top Products", index=False)
        if stats["sales_by_branch"]:
            pd.DataFrame(stats["sales_by_branch"]).to_excel(writer, sheet_name="Revenue by Branch", index=False)
        if stats["sales_by_category"]:
            pd.DataFrame(stats["sales_by_category"]).to_excel(writer, sheet_name="Revenue by Category", index=False)
        if report["day_stats"]["revenue_by_day"]:
            pd.DataFrame(report["day_stats"]["revenue_by_day"]).to_excel(writer, sheet_name="Day of Week", index=False)
        if report["tiers"]["tiers"]:
            pd.DataFrame(report["tiers"]["tiers"]).to_excel(writer, sheet_name="Membership Tiers", index=False)

        products = report.get("products", {})
        if products.get("best_sellers"):
            pd.DataFrame(products["best_sellers"]).to_excel(writer, sheet_name="Best Sellers", index=False)
        if products.get("least_sellers"):
            pd.DataFrame(products["least_sellers"]).to_excel(writer, sheet_name="Least Sellers", index=False)
        if products.get("category_performance"):
            pd.DataFrame(products["category_performance"]).to_excel(writer, sheet_name="Category Performance", index=False)

        inventory = report.get("inventory", {})
        if inventory.get("available"):
            pd.DataFrame(inventory["products"]).to_excel(writer, sheet_name="Inventory", index=False)
            if inventory["low_stock"]:
                pd.DataFrame(inventory["low_stock"]).to_excel(writer, sheet_name="Low Stock", index=False)
            if inventory["out_of_stock"]:
                pd.DataFrame(inventory["out_of_stock"]).to_excel(writer, sheet_name="Out of Stock", index=False)

        membership = report.get("membership", {})
        if membership.get("available") and membership.get("purchases_by_membership"):
            pd.DataFrame(membership["purchases_by_membership"]).to_excel(writer, sheet_name="Membership Purchases", index=False)

        regional = report.get("regional", {})
        if regional.get("available"):
            pd.DataFrame(regional["by_branch"]).to_excel(writer, sheet_name="Sales by Branch", index=False)
            pd.DataFrame(regional["by_location"]).to_excel(writer, sheet_name="Sales by Location", index=False)

    return buffer.getvalue()
