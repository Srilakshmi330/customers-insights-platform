"""Recommendation engine with two real recommendation techniques (not just
popularity counting):

- Collaborative filtering: item-item similarity built from the customer x
  product purchase matrix (products bought by overlapping sets of customers
  are "similar"). Powers both personalized recommendations for a customer
  and a "bought together" view of similar products.
- Content-based filtering: item-item similarity built from product
  attributes (category + price), independent of purchase history. Useful
  for new products with no sales yet, and for comparing a product against
  its true peers regardless of who's bought it.

Also provides trending products (highest recent unit sales).

This module has no Streamlit dependency — streamlit_app.py wraps these calls
with st.cache_data for performance."""
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import text

from schema import connection


def _purchase_matrix():
    """product x customer matrix of completed-order quantities."""
    with connection() as conn:
        df = pd.read_sql_query(
            text("""
                SELECT oi.product_id, o.customer_id, SUM(oi.quantity) AS qty
                FROM order_items oi JOIN orders o ON o.id = oi.order_id
                WHERE o.status = 'completed'
                GROUP BY oi.product_id, o.customer_id
            """),
            conn,
        )
    if df.empty:
        return pd.DataFrame()
    matrix = df.pivot_table(index="product_id", columns="customer_id", values="qty", fill_value=0)
    matrix.index.name = "product_id"
    return matrix


def _product_info():
    """One row per product with everything needed to display a recommendation:
    name, vendor, price, category — used both as content-based features and
    to label results for the UI."""
    with connection() as conn:
        return pd.read_sql_query(
            text("""
                SELECT p.id AS product_id, p.name AS product_name, p.vendor_id,
                       v.name AS vendor_name, p.unit_price,
                       COALESCE(c.name, 'Uncategorized') AS category
                FROM products p
                JOIN vendors v ON v.id = p.vendor_id
                LEFT JOIN categories c ON c.id = p.category_id
            """),
            conn,
        )


def _attach_product_info(df):
    if df.empty:
        return df
    info = _product_info()
    return df.merge(info, on="product_id", how="left")


def collaborative_similarity_matrix():
    """Returns a product x product cosine-similarity DataFrame, or None if
    there isn't enough purchase history yet (fewer than 2 products with
    completed-order history)."""
    matrix = _purchase_matrix()
    if matrix.empty or matrix.shape[0] < 2:
        return None
    sim = cosine_similarity(matrix.values)
    return pd.DataFrame(sim, index=matrix.index, columns=matrix.index)


def content_similarity_matrix(vendor_id=None):
    """Returns a product x product cosine-similarity DataFrame based on
    category + normalized price, optionally restricted to one vendor's
    catalog. Works even for brand-new products with zero sales."""
    df = _product_info()
    if vendor_id is not None:
        df = df[df["vendor_id"] == vendor_id]
    if len(df) < 2:
        return None, df

    cat_dummies = pd.get_dummies(df["category"])
    price_range = df["unit_price"].max() - df["unit_price"].min()
    price_norm = (
        (df["unit_price"] - df["unit_price"].min()) / price_range
        if price_range > 0 else df["unit_price"] * 0
    )
    features = pd.concat(
        [cat_dummies.reset_index(drop=True), price_norm.reset_index(drop=True).rename("price_norm")],
        axis=1,
    )
    sim = cosine_similarity(features.values)
    sim_df = pd.DataFrame(sim, index=df["product_id"].values, columns=df["product_id"].values)
    return sim_df, df


def similar_products_collaborative(product_id, top_n=8):
    """'Customers who bought this also bought' — item-item collaborative
    filtering similarity, platform-wide (so a vendor can see if a similar
    product exists elsewhere too)."""
    sim_df = collaborative_similarity_matrix()
    if sim_df is None or product_id not in sim_df.index:
        return pd.DataFrame()
    scores = sim_df[product_id].drop(index=product_id, errors="ignore")
    scores = scores[scores > 0].sort_values(ascending=False).head(top_n)
    if scores.empty:
        return pd.DataFrame()
    result = scores.rename("similarity").reset_index().rename(columns={"index": "product_id"})
    return _attach_product_info(result)


def similar_products_content(product_id, top_n=8, vendor_id=None):
    """Attribute-based similarity (category + price) — works even for
    products with no purchase history yet."""
    sim_df, _ = content_similarity_matrix(vendor_id=vendor_id)
    if sim_df is None or product_id not in sim_df.index:
        return pd.DataFrame()
    scores = sim_df[product_id].drop(index=product_id, errors="ignore")
    scores = scores.sort_values(ascending=False).head(top_n)
    if scores.empty:
        return pd.DataFrame()
    result = scores.rename("similarity").reset_index().rename(columns={"index": "product_id"})
    return _attach_product_info(result)


def recommend_for_customer(customer_id, top_n=8, vendor_id=None):
    """Item-based collaborative recommendation: for every product this
    customer has already bought, look up its similar products (via the
    item-item similarity matrix), sum the scores across all of them, exclude
    anything already purchased, and return the top N. Optionally restricted
    to a single vendor's catalog (for a vendor's own recommendation page)."""
    sim_df = collaborative_similarity_matrix()
    if sim_df is None:
        return pd.DataFrame()

    with connection() as conn:
        bought = pd.read_sql_query(
            text("""
                SELECT DISTINCT oi.product_id FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.customer_id = :cid AND o.status = 'completed'
            """),
            conn, params={"cid": customer_id},
        )
    bought_ids = [p for p in bought["product_id"] if p in sim_df.index] if not bought.empty else []
    if not bought_ids:
        return pd.DataFrame()

    scores = sim_df.loc[bought_ids].sum(axis=0)
    scores = scores.drop(index=[p for p in bought_ids if p in scores.index], errors="ignore")

    if vendor_id is not None:
        info = _product_info()
        allowed = set(info.loc[info["vendor_id"] == vendor_id, "product_id"])
        scores = scores[scores.index.isin(allowed)]

    scores = scores[scores > 0].sort_values(ascending=False).head(top_n)
    if scores.empty:
        return pd.DataFrame()
    result = scores.rename("score").reset_index().rename(columns={"index": "product_id"})
    return _attach_product_info(result)


def trending_products(days=7, top_n=10, vendor_id=None):
    """Products with the highest unit sales in the last `days` days."""
    vendor_clause = "AND oi.vendor_id = :vendor_id" if vendor_id is not None else ""
    params = {"top_n": top_n}
    if vendor_id is not None:
        params["vendor_id"] = vendor_id

    with connection() as conn:
        df = pd.read_sql_query(
            text(f"""
                SELECT oi.product_id, p.name AS product_name, v.name AS vendor_name,
                       SUM(oi.quantity) AS units_sold
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                JOIN products p ON p.id = oi.product_id
                JOIN vendors v ON v.id = oi.vendor_id
                WHERE o.status = 'completed'
                  AND o.order_date >= NOW() - INTERVAL '{days} days'
                  {vendor_clause}
                GROUP BY oi.product_id, p.name, v.name
                ORDER BY units_sold DESC
                LIMIT :top_n
            """),
            conn, params=params,
        )
    return df
