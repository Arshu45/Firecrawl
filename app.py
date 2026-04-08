from datetime import datetime, date
from decimal import Decimal
import uuid

import httpx
import pandas as pd
import streamlit as st

from config.settings import CLIENT_BRAND, API_URL, CHAT_HISTORY_WINDOW
from database.db_client import DBClient

SUGGESTED_QUERIES = [
    f"What is Myntra doing in Footwear?",
    f"What category trends do we see in Beauty?",
    f"What should {CLIENT_BRAND} do against Myntra in Fashion?",
    f"Show me Nykaa's active offers in Beauty",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_primitive(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    normalized = [{key: _to_primitive(val) for key, val in row.items()} for row in rows]
    return pd.DataFrame(normalized)


def _recent_history_payload() -> list[dict]:
    """Send only the recent window so follow-up queries keep context without bloating tokens."""
    return st.session_state.messages[-CHAT_HISTORY_WINDOW:]


def _scrape_freshness(scraped_date) -> tuple[str, str]:
    """
    Returns (label_str, color_hex) based on how old the scraped_date is.
    green  = today
    amber  = 1 day old
    red    = 2+ days old
    """
    if scraped_date is None:
        return "No data loaded yet", "#888888"
    try:
        if hasattr(scraped_date, "date"):
            d = scraped_date.date()
        elif isinstance(scraped_date, str):
            d = date.fromisoformat(scraped_date)
        else:
            d = scraped_date
        days_old = (date.today() - d).days
        label = d.isoformat()
        if days_old == 0:
            return f"✅ {label} (today)", "#00C897"
        elif days_old == 1:
            return f"🟡 {label} (1 day ago)", "#FFC107"
        else:
            return f"🔴 {label} ({days_old} days ago — consider re-running the pipeline)", "#FF4B4B"
    except Exception:
        return str(scraped_date), "#888888"


def _strategy_alerts(competitor_matrix: pd.DataFrame, internal_by_category: pd.DataFrame) -> list[str]:
    """
    Returns a list of alert strings where a competitor's avg discount exceeds
    Westside's by > 15 percentage points in any category.
    """
    alerts = []
    if competitor_matrix.empty or internal_by_category.empty:
        return alerts

    internal_lookup = internal_by_category.set_index("category")["avg_discount"].to_dict()

    for category, grp in competitor_matrix.groupby("category"):
        westside_avg = internal_lookup.get(category)
        if westside_avg is None:
            continue
        westside_avg = float(westside_avg or 0)
        for _, row in grp.iterrows():
            comp_avg = float(row.get("avg_discount") or 0)
            if comp_avg - westside_avg >= 15:
                alerts.append(
                    f"**{row['competitor']}** is ahead of {CLIENT_BRAND} by "
                    f"**{comp_avg - westside_avg:.0f}%** average discount in **{category}** "
                    f"({comp_avg:.0f}% vs {westside_avg:.0f}%)"
                )
    return alerts


# ── Data fetch ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def fetch_dashboard_data() -> dict:
    with DBClient() as db:
        latest_scrape = db.execute_one(
            """
            SELECT MAX(scraped_date) AS latest_scraped_date
            FROM promotions
            """
        )
        latest_scraped_date = latest_scrape["latest_scraped_date"] if latest_scrape else None

        overview = db.execute_one(
            """
            SELECT
                (SELECT COUNT(*) FROM competitors) AS competitors_tracked,
                (SELECT COUNT(*) FROM promotions) AS competitor_offers,
                (SELECT COUNT(*) FROM internal_promotions) AS internal_offers,
                (SELECT COUNT(DISTINCT category) FROM promotions WHERE category IS NOT NULL) AS categories_tracked
            """
        )

        competitor_by_category = db.execute(
            """
            SELECT
                category,
                COUNT(*) AS offer_count,
                ROUND(AVG(discount_max), 2) AS avg_discount
            FROM promotions
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY offer_count DESC, category
            """
        )

        competitor_matrix = db.execute(
            """
            SELECT
                c.name AS competitor,
                p.category,
                COUNT(*) AS offer_count,
                ROUND(AVG(p.discount_max), 2) AS avg_discount,
                MAX(p.discount_max) AS deepest_discount
            FROM promotions p
            JOIN competitors c ON p.competitor_id = c.id
            WHERE p.category IS NOT NULL
            GROUP BY c.name, p.category
            ORDER BY p.category, avg_discount DESC NULLS LAST
            """
        )

        internal_by_category = db.execute(
            """
            SELECT
                category,
                COUNT(*) AS offer_count,
                ROUND(AVG(discount_max), 2) AS avg_discount,
                MAX(discount_max) AS deepest_discount
            FROM internal_promotions
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY offer_count DESC, category
            """
        )

        recent_competitor_offers = db.execute(
            """
            SELECT
                c.name AS competitor,
                p.offer_title,
                p.category,
                p.promo_type,
                p.discount_max,
                p.scraped_date
            FROM promotions p
            JOIN competitors c ON p.competitor_id = c.id
            ORDER BY p.scraped_date DESC, p.discount_max DESC NULLS LAST
            LIMIT 20
            """
        )

        recent_internal_offers = db.execute(
            """
            SELECT
                offer_title,
                category,
                promo_type,
                discount_max,
                valid_until,
                scraped_date
            FROM internal_promotions
            ORDER BY scraped_date DESC, discount_max DESC NULLS LAST
            LIMIT 20
            """
        )

    return {
        "latest_scraped_date": latest_scraped_date,
        "overview": overview or {},
        "competitor_by_category": _rows_to_df(competitor_by_category),
        "competitor_matrix": _rows_to_df(competitor_matrix),
        "internal_by_category": _rows_to_df(internal_by_category),
        "recent_competitor_offers": _rows_to_df(recent_competitor_offers),
        "recent_internal_offers": _rows_to_df(recent_internal_offers),
    }


# ── Dashboard ──────────────────────────────────────────────────────────────────

def render_dashboard() -> None:
    st.subheader("📊 Insights Dashboard")
    st.caption("Live market intelligence from PostgreSQL — competitor promotions and internal readiness.")

    try:
        data = fetch_dashboard_data()
    except Exception as exc:
        st.error(f"Could not load dashboard data from PostgreSQL. Details: {exc}")
        return

    overview               = data["overview"]
    latest_scraped_date    = data["latest_scraped_date"]
    competitor_by_category = data["competitor_by_category"]
    competitor_matrix      = data["competitor_matrix"]
    internal_by_category   = data["internal_by_category"]
    recent_competitor_offers = data["recent_competitor_offers"]
    recent_internal_offers   = data["recent_internal_offers"]

    # ── Freshness banner ─────────────────────────────────────────────
    freshness_label, freshness_color = _scrape_freshness(latest_scraped_date)
    st.markdown(
        f"<div style='padding:8px 14px; border-radius:6px; background:{freshness_color}22; "
        f"border-left:4px solid {freshness_color}; margin-bottom:12px;'>"
        f"<span style='color:{freshness_color}; font-weight:600;'>Latest competitor scrape: {freshness_label}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Strategy Alerts ──────────────────────────────────────────────
    alerts = _strategy_alerts(competitor_matrix, internal_by_category)
    if alerts:
        with st.expander(f"🚨 Strategy Alerts ({len(alerts)} gap{'s' if len(alerts) > 1 else ''} detected)", expanded=True):
            for alert in alerts:
                st.markdown(f"- {alert}")
            st.caption("These categories require immediate attention. Use the Chat tab to get a strategic recommendation.")

    # ── KPI metrics ──────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🏢 Competitors Tracked", int(overview.get("competitors_tracked") or 0))
    col2.metric("📋 Competitor Offers",   int(overview.get("competitor_offers")   or 0))
    col3.metric(f"🏷️ {CLIENT_BRAND} Offers", int(overview.get("internal_offers") or 0))
    col4.metric("🗂️ Categories",           int(overview.get("categories_tracked") or 0))

    # ── Internal data CTA ────────────────────────────────────────────
    internal_count = int(overview.get("internal_offers") or 0)
    if internal_count == 0:
        st.markdown(
            f"""
            <div style='padding:14px 18px; border-radius:8px; background:#FF4B4B18;
                        border:1px solid #FF4B4B55; margin:12px 0;'>
                <b style='color:#FF4B4B;'>⚠️ {CLIENT_BRAND} internal promotions not loaded</b><br>
                <span style='color:#ccc; font-size:0.9em;'>
                Recommendation quality is limited without internal data.
                Run: <code>python main.py --sync-internal</code> to pull from the internal MySQL database.
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if competitor_matrix.empty:
        st.warning("No competitor promotion data found yet. Run: `python main.py` to scrape and load competitor data.")
        return

    # ── Category selector ────────────────────────────────────────────
    st.divider()
    categories = sorted(competitor_matrix["category"].dropna().unique().tolist())
    selected_category = st.selectbox("🔍 Category Focus", categories, index=0 if categories else None)

    filtered_competitor_matrix = competitor_matrix[competitor_matrix["category"] == selected_category].copy()
    filtered_internal          = internal_by_category[internal_by_category["category"] == selected_category].copy()

    # ── Competitor vs Westside side-by-side ──────────────────────────
    market_col, internal_col = st.columns([2, 1])

    with market_col:
        st.markdown(f"**🏁 Competitor Snapshot — {selected_category}**")
        competitor_chart_df = filtered_competitor_matrix[["competitor", "avg_discount"]].set_index("competitor")
        if not competitor_chart_df.empty:
            st.bar_chart(competitor_chart_df, color="#4C9BE8")
        st.dataframe(
            filtered_competitor_matrix.rename(columns={
                "competitor"      : "Competitor",
                "category"        : "Category",
                "offer_count"     : "Offer Count",
                "avg_discount"    : "Avg Discount (%)",
                "deepest_discount": "Deepest Discount (%)",
            }),
            width="stretch",
            hide_index=True,
        )

    with internal_col:
        st.markdown(f"**🏷️ {CLIENT_BRAND} Readiness — {selected_category}**")
        if filtered_internal.empty:
            st.info(
                f"No internal offers synced for **{selected_category}** yet.\n\n"
                f"Run `python main.py --sync-internal` to populate."
            )
        else:
            st.dataframe(
                filtered_internal.rename(columns={
                    "category"        : "Category",
                    "offer_count"     : "Offer Count",
                    "avg_discount"    : "Avg Discount (%)",
                    "deepest_discount": "Deepest Discount (%)",
                }),
                width="stretch",
                hide_index=True,
            )

    # ── Market overview charts ───────────────────────────────────────
    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("**📦 Offer Volume by Category (All Competitors)**")
        category_volume = competitor_by_category[["category", "offer_count"]].set_index("category")
        if not category_volume.empty:
            st.bar_chart(category_volume, color="#A78BFA")

    with right:
        st.markdown("**💸 Average Discount by Category (All Competitors)**")
        category_discount = competitor_by_category[["category", "avg_discount"]].set_index("category")
        if not category_discount.empty:
            st.bar_chart(category_discount, color="#34D399")

    # ── Recent offers tables ─────────────────────────────────────────
    st.divider()
    st.markdown("**📄 Recent Competitor Offers**")
    competitor_filter_options = ["All"] + sorted(recent_competitor_offers["competitor"].dropna().unique().tolist())
    selected_competitor = st.selectbox("Filter by Competitor", competitor_filter_options, index=0)
    displayed_competitor_offers = recent_competitor_offers.copy()
    if selected_competitor != "All":
        displayed_competitor_offers = displayed_competitor_offers[
            displayed_competitor_offers["competitor"] == selected_competitor
        ]
    if selected_category:
        displayed_competitor_offers = displayed_competitor_offers[
            displayed_competitor_offers["category"] == selected_category
        ]
    st.dataframe(displayed_competitor_offers, width="stretch", hide_index=True)

    st.markdown(f"**📄 Recent {CLIENT_BRAND} Offers**")
    if recent_internal_offers.empty:
        st.info(
            f"No {CLIENT_BRAND} offers loaded yet. "
            f"Run `python main.py --sync-internal` to pull from MySQL."
        )
    else:
        displayed_internal_offers = recent_internal_offers.copy()
        if selected_category:
            displayed_internal_offers = displayed_internal_offers[
                displayed_internal_offers["category"] == selected_category
            ]
        st.dataframe(displayed_internal_offers, width="stretch", hide_index=True)


# ── Chat ───────────────────────────────────────────────────────────────────────

def _send_chat_message(prompt: str) -> None:
    """Appends user message, calls API, and appends assistant response."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()


def render_chat() -> None:
    st.subheader("💬 AI Pricing Strategist")
    st.caption(
        "Ask questions in plain English. The agent will query the database and provide "
        "data-backed strategic recommendations."
    )

    # ── Session state init ────────────────────────────────────────────
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None

    # ── Controls row ─────────────────────────────────────────────────
    ctrl_col, sid_col = st.columns([1, 3])
    with ctrl_col:
        if st.button("🔄 New Conversation", width="stretch"):
            st.session_state.messages = []
            st.session_state.session_id = str(uuid.uuid4())
            st.session_state.pending_prompt = None
            st.rerun()
    with sid_col:
        st.caption(f"Session: `{st.session_state.session_id}`")

    # ── Suggested queries (shown only on empty conversation) ──────────
    if not st.session_state.messages:
        st.markdown("**💡 Suggested Questions — click to ask:**")
        cols = st.columns(2)
        for i, query in enumerate(SUGGESTED_QUERIES):
            with cols[i % 2]:
                if st.button(query, key=f"suggestion_{i}", width="stretch"):
                    st.session_state.pending_prompt = query
                    st.rerun()

        st.divider()

    # ── Render message history ────────────────────────────────────────
    # chat_container = st.container(height=600, border=False)
    has_messages = bool(st.session_state.messages)
    if has_messages:
        chat_container = st.container(height=500, border=False)
    else:
        chat_container = st.container(border=False)
    for message in st.session_state.messages:
        with chat_container.chat_message(message["role"]):
            st.markdown(message["content"])

    # ── Handle pending prompt (from suggestion buttons) ───────────────
    active_prompt = st.session_state.get("pending_prompt")
    if active_prompt:
        st.session_state.pending_prompt = None
        with chat_container.chat_message("user"):
            st.markdown(active_prompt)
        with chat_container.chat_message("assistant"):
            with st.spinner("🔍 Analyzing market data — querying database and reasoning through strategy..."):
                try:
                    response = httpx.post(
                        API_URL,
                        json={
                            "message"   : active_prompt,
                            "session_id": st.session_state.session_id,
                            "history"   : _recent_history_payload(),
                        },
                        timeout=120.0,
                    )
                    if response.status_code == 200:
                        answer = response.json().get("response", "Error reading response")
                    else:
                        answer = f"Server Error ({response.status_code}): {response.text}"
                except httpx.RequestError as exc:
                    answer = (
                        f"⚠️ Could not connect to the API backend at port 8000. "
                        f"Is the FastAPI server running?\n\n`uvicorn api.server:app --reload`\n\nDetails: {exc}"
                    )
            st.markdown(answer)

        st.session_state.messages.append({"role": "user",      "content": active_prompt})
        st.session_state.messages.append({"role": "assistant", "content": answer})

    # ── Chat input ────────────────────────────────────────────────────
    if prompt := st.chat_input("Ask about competitor trends, category gaps, or what we should do..."):
        with chat_container.chat_message("user"):
            st.markdown(prompt)
        with chat_container.chat_message("assistant"):
            with st.spinner("🔍 Analyzing market data — querying database and reasoning through strategy..."):
                try:
                    response = httpx.post(
                        API_URL,
                        json={
                            "message"   : prompt,
                            "session_id": st.session_state.session_id,
                            "history"   : _recent_history_payload(),
                        },
                        timeout=120.0,
                    )
                    if response.status_code == 200:
                        answer = response.json().get("response", "Error reading response")
                    else:
                        answer = f"Server Error ({response.status_code}): {response.text}"
                except httpx.RequestError as exc:
                    answer = (
                        f"⚠️ Could not connect to the API backend at port 8000. "
                        f"Is the FastAPI server running?\n\n`uvicorn api.server:app --reload`\n\nDetails: {exc}"
                    )
            st.markdown(answer)

        st.session_state.messages.append({"role": "user",      "content": prompt})
        st.session_state.messages.append({"role": "assistant", "content": answer})


# ── Page config & layout ───────────────────────────────────────────────────────

st.set_page_config(
    page_title=f"{CLIENT_BRAND} Promotion Intelligence",
    page_icon="🛍️",
    layout="wide",
)

# ── Global header ─────────────────────────────────────────────────────────────
st.markdown(
    f"""
    <div style='display:flex; align-items:center; gap:14px; padding-bottom:4px;'>
        <div style='font-size:2.2rem;'>🛍️</div>
        <div>
            <div style='font-size:1.6rem; font-weight:700; line-height:1.1;'>
                {CLIENT_BRAND} Promotion Intelligence
            </div>
            <div style='color:#9CA3AF; font-size:0.9rem; margin-top:2px;'>
                Real-time competitor monitoring · AI-powered pricing strategy · Data-driven recommendations
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.divider()

dashboard_tab, chat_tab = st.tabs(["📊 Dashboard", "💬 Chat"])

with dashboard_tab:
    render_dashboard()

with chat_tab:
    render_chat()
