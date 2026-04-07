"""
Layer 7 — Streamlit UI
5-screen Retail Promotion Intelligence Dashboard.
"""

import json
import logging
import sys
import os

# Ensure project root is on PYTHONPATH when running via: streamlit run ui/app.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import streamlit as st

from config.settings import COMPETITOR_SITES, VALID_CATEGORIES


# ── In-UI Log Handler ──────────────────────────────────────────────────────
# Captures every logger.* call from every module into st.session_state.
# This makes all backend logs visible in the sidebar "📟 Logs" panel.

class _StreamlitLogHandler(logging.Handler):
    """Appends log records to st.session_state.log_lines so they appear in the UI."""
    MAX_LINES = 300

    def emit(self, record: logging.LogRecord):
        try:
            if "log_lines" not in st.session_state:
                st.session_state.log_lines = []
            line = self.format(record)
            st.session_state.log_lines.append(line)
            if len(st.session_state.log_lines) > self.MAX_LINES:
                st.session_state.log_lines = st.session_state.log_lines[-self.MAX_LINES:]
        except Exception:
            pass


# Install once on the root logger — picks up all loggers in all modules
_root_logger = logging.getLogger()
if not any(isinstance(h, _StreamlitLogHandler) for h in _root_logger.handlers):
    _sl_handler = _StreamlitLogHandler()
    _sl_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                          datefmt="%H:%M:%S")
    )
    _sl_handler.setLevel(logging.DEBUG)
    _root_logger.addHandler(_sl_handler)
    if _root_logger.level == logging.NOTSET:
        _root_logger.setLevel(logging.INFO)


# ── Page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title = "Retail Promotion Intelligence",
    page_icon  = "🏷️",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        border-right: 1px solid #334155;
    }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }
    [data-testid="stSidebar"] .stRadio label { font-size: 0.95rem; padding: 4px 0; }

    /* Main background */
    .main { background: #0f172a; color: #e2e8f0; }
    .block-container { padding-top: 2rem; }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 16px;
    }
    [data-testid="stMetricLabel"] { color: #94a3b8 !important; font-size: 0.8rem; }
    [data-testid="stMetricValue"] { color: #f1f5f9 !important; font-size: 1.6rem; font-weight: 700; }

    /* Urgency badges */
    .badge-high     { background:#dc2626; color:#fff; padding:4px 14px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }
    .badge-medium   { background:#d97706; color:#fff; padding:4px 14px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }
    .badge-low      { background:#16a34a; color:#fff; padding:4px 14px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }
    .badge-none     { background:#475569; color:#fff; padding:4px 14px; border-radius:20px; font-weight:600; font-size:0.85rem; display:inline-block; }

    /* Recommendation card */
    .rec-card { background:#1e293b; border:1px solid #334155; border-radius:12px; padding:20px 24px; margin:10px 0; }
    .rec-label { color:#94a3b8; font-size:0.75rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px; }
    .rec-text  { color:#e2e8f0; font-size:0.95rem; line-height:1.6; }

    /* Narrative card */
    .narrative-card { background:#1e293b; border-left:3px solid #6366f1; border-radius:8px; padding:16px 20px; color:#cbd5e1; font-size:0.9rem; line-height:1.7; }

    /* Log box — pipeline screen */
    .log-box { background:#0f172a; border:1px solid #334155; border-radius:8px; padding:12px 16px; font-family:monospace; font-size:0.82rem; color:#94a3b8; max-height:300px; overflow-y:auto; }

    /* Sidebar log panel */
    .sidebar-log { background:#0a0f1a; border:1px solid #1e293b; border-radius:6px; padding:8px 10px;
                   font-family:'Courier New',monospace; font-size:0.72rem; color:#64748b;
                   max-height:260px; overflow-y:auto; white-space:pre-wrap; word-break:break-all; }
    .log-info    { color:#60a5fa; }
    .log-warn    { color:#fbbf24; }
    .log-error   { color:#f87171; }

    /* Chat tool tag */
    .tool-tag { color:#64748b; font-size:0.75rem; margin-top:4px; }

    /* Highlight */
    .high-discount { background:#78350f22 !important; }
</style>
""", unsafe_allow_html=True)


# ── Sidebar navigation ─────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏷️ Promo Intel")
    st.markdown("**Retail Promotion Intelligence**")
    st.markdown("---")
    screen = st.radio(
        "Navigate",
        [
            "📋 Promotions Table",
            "📊 Market Insights",
            "💡 Recommendations",
            "⚙️ Run Pipeline",
            "🤖 AI Assistant",
        ],
        label_visibility="collapsed",
    )
    st.markdown("---")

    # ── System Logs panel ─────────────────────────────────────────────────
    log_lines: list[str] = st.session_state.get("log_lines", [])
    log_count = len(log_lines)

    with st.expander(f"📟 System Logs ({log_count})", expanded=False):
        col_a, col_b = st.columns([3, 1])
        with col_b:
            if st.button("🗑", key="clear_logs", help="Clear logs"):
                st.session_state.log_lines = []
                st.rerun()

        if log_lines:
            # Colour-code by level using HTML spans
            coloured_lines = []
            for line in log_lines[-80:]:           # last 80 lines in panel
                ll = line.lower()
                if "[error]" in ll or "[critical]" in ll:
                    cls = "log-error"
                elif "[warning]" in ll or "[warn]" in ll:
                    cls = "log-warn"
                else:
                    cls = "log-info"
                # Escape HTML special chars
                safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                coloured_lines.append(f'<span class="{cls}">{safe}</span>')

            st.markdown(
                '<div class="sidebar-log">' + "<br>".join(coloured_lines) + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("No logs yet — run the pipeline or generate a narrative.")

    st.markdown("---")
    st.markdown("<small style='color:#475569'>Powered by Firecrawl + Groq</small>", unsafe_allow_html=True)


# ── DB helper (safe — returns empty on error) ──────────────────────────────

@st.cache_resource(show_spinner=False)
def get_db():
    try:
        from database.db_client import DBClient
        return DBClient()
    except Exception:
        return None


def db_query(query: str, params=None) -> list[dict]:
    db = get_db()
    if db is None:
        return []
    try:
        return db.execute(query, params)
    except Exception:
        return []


def get_providers() -> list[str]:
    rows = db_query("SELECT DISTINCT name FROM competitors ORDER BY name")
    return [r["name"] for r in rows] if rows else list(COMPETITOR_SITES.keys())


def get_categories() -> list[str]:
    rows = db_query("SELECT DISTINCT category FROM promotions WHERE category IS NOT NULL ORDER BY category")
    return [r["category"] for r in rows] if rows else VALID_CATEGORIES


# ══════════════════════════════════════════════════════════════════════════
# Screen 1 — Promotions Table
# ══════════════════════════════════════════════════════════════════════════

if screen == "📋 Promotions Table":
    st.title("📋 Live Competitor Promotions")

    providers  = get_providers()
    categories = get_categories()

    col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1.5])
    with col1:
        sel_providers = st.multiselect("Provider", providers, default=providers[:2] if providers else [])
    with col2:
        sel_categories = st.multiselect("Category", categories)
    with col3:
        sel_user_type = st.selectbox("User Type", ["All", "new", "existing", "all"])
    with col4:
        days = st.slider("Days", 1, 30, 7)

    # Build query
    where  = ["p.scraped_date >= CURRENT_DATE - %(days)s"]
    params: dict = {"days": days}

    if sel_providers:
        where.append("c.name = ANY(%(providers)s)")
        params["providers"] = sel_providers
    if sel_categories:
        where.append("p.category = ANY(%(categories)s)")
        params["categories"] = sel_categories
    if sel_user_type != "All":
        where.append("p.user_type = %(user_type)s")
        params["user_type"] = sel_user_type

    where_sql = " AND ".join(where)

    rows = db_query(
        f"""
        SELECT
            p.offer_title, p.brand, p.category, p.promo_type,
            p.discount_min, p.discount_max, p.flat_value, p.coupon_code,
            p.user_type, p.scraped_date, c.name AS competitor
        FROM promotions p
        JOIN competitors c ON c.id = p.competitor_id
        WHERE {where_sql}
        ORDER BY p.scraped_date DESC, p.discount_max DESC NULLS LAST
        LIMIT 500
        """,
        params,
    )

    if rows:
        df = pd.DataFrame(rows)
        st.markdown(f"**{len(df)} offers found**")

        def highlight_high(row):
            if (row.get("discount_max") or 0) > 60:
                return ["background-color: #78350f33"] * len(row)
            return [""] * len(row)

        styled = df.style.apply(highlight_high, axis=1)
        st.dataframe(styled, width="stretch", height=480)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Export CSV", csv, "promotions.csv", "text/csv")
    else:
        st.info("🔍 No promotions found. Run the pipeline first (⚙️ Run Pipeline).")


# ══════════════════════════════════════════════════════════════════════════
# Screen 2 — Market Insights
# ══════════════════════════════════════════════════════════════════════════

elif screen == "📊 Market Insights":
    st.title("📊 Market Intelligence")

    categories = get_categories()
    col1, col2 = st.columns([2, 1])
    with col1:
        sel_cat = st.selectbox("Category", categories)
    with col2:
        days = st.slider("Days lookback", 1, 30, 7)

    left, right = st.columns([0.6, 0.4])

    with left:
        st.subheader("Average Discount by Category")
        cat_data = db_query(
            """
            SELECT p.category,
                   ROUND(AVG(COALESCE(p.discount_max, p.discount_min))::numeric, 1) AS avg_discount,
                   COUNT(*) AS offer_count
            FROM promotions p
            WHERE p.scraped_date >= CURRENT_DATE - %(days)s
              AND (p.discount_max IS NOT NULL OR p.discount_min IS NOT NULL)
              AND p.category IS NOT NULL
            GROUP BY p.category
            ORDER BY avg_discount DESC
            """,
            {"days": days},
        )
        if cat_data:
            df_cat = pd.DataFrame(cat_data).set_index("category")
            df_cat["avg_discount"] = df_cat["avg_discount"].astype(float)
            st.bar_chart(df_cat["avg_discount"])
        else:
            st.info("No discount data available.")

        st.subheader(f"Top Competitors — {sel_cat}")
        comp_data = db_query(
            """
            SELECT c.name AS competitor,
                   ROUND(AVG(COALESCE(p.discount_max, p.discount_min))::numeric, 1) AS avg_discount,
                   COUNT(*) AS offer_count
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.category    = %(category)s
              AND p.scraped_date >= CURRENT_DATE - %(days)s
              AND (p.discount_max IS NOT NULL OR p.discount_min IS NOT NULL)
            GROUP BY c.name
            ORDER BY avg_discount DESC
            LIMIT 5
            """,
            {"category": sel_cat, "days": days},
        )
        if comp_data:
            df_comp = pd.DataFrame(comp_data).set_index("competitor")
            df_comp["avg_discount"] = df_comp["avg_discount"].astype(float)
            st.bar_chart(df_comp["avg_discount"])
        else:
            st.info(f"No data for {sel_cat}.")

    with right:
        st.subheader("Market Narrative")
        if st.button("🔄 Generate Narrative"):
            with st.spinner("Generating…"):
                try:
                    from insights.insights_engine import run_insight
                    result = run_insight("avg_discount_by_category", {"days": days})
                    narrative = result.get("narrative", "No narrative generated.")
                except Exception as e:
                    narrative = f"Error: {e}"
            st.markdown(f'<div class="narrative-card">{narrative}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="narrative-card">Click "Generate Narrative" to get an AI summary.</div>', unsafe_allow_html=True)

        st.subheader("Coupon Code Availability")
        coupon_data = db_query(
            """
            SELECT c.name AS competitor,
                   COUNT(*) FILTER (WHERE p.coupon_code IS NOT NULL) AS with_coupon,
                   COUNT(*) AS total,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE p.coupon_code IS NOT NULL) / COUNT(*), 1) AS pct
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.scraped_date >= CURRENT_DATE - %(days)s
            GROUP BY c.name
            ORDER BY pct DESC
            """,
            {"days": days},
        )
        if coupon_data:
            st.dataframe(pd.DataFrame(coupon_data), width="stretch")
        else:
            st.info("No coupon data.")

        st.subheader("User Targeting Breakdown")
        ut_data = db_query(
            """
            SELECT c.name AS competitor, p.user_type, COUNT(*) AS count
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.scraped_date >= CURRENT_DATE - %(days)s
            GROUP BY c.name, p.user_type
            ORDER BY c.name, count DESC
            """,
            {"days": days},
        )
        if ut_data:
            st.dataframe(pd.DataFrame(ut_data), width="stretch")
        else:
            st.info("No targeting data.")


# ══════════════════════════════════════════════════════════════════════════
# Screen 3 — Recommendation
# ══════════════════════════════════════════════════════════════════════════

elif screen == "💡 Recommendations":
    st.title("💡 Pricing Recommendation Engine")

    categories = get_categories()

    with st.form("rec_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            category = st.selectbox("Category", categories)
        with c2:
            our_discount = st.number_input("Our Current Discount (%)", 0.0, 100.0, 30.0, step=1.0)
        with c3:
            our_margin = st.number_input("Our Margin in Category (%)", 0.0, 100.0, 35.0, step=1.0)
        submitted = st.form_submit_button("🎯 Get Recommendation", width="stretch")

    if submitted:
        with st.spinner("Analysing market and generating recommendation…"):
            try:
                from recommendations.recommendation_engine import get_recommendation
                rec = get_recommendation(category, our_discount, our_margin)
            except Exception as e:
                st.error(f"Error: {e}")
                rec = None

        if rec:
            rule  = rec["rule"]
            expl  = rec["explanation"]
            mdata = rec["market_data"]
            urg   = rule["urgency"]

            badge_class = f"badge-{urg}"
            badge_text  = {"high": "🔴 URGENT", "medium": "🟠 MEDIUM", "low": "🟢 LOW", "none": "⚪ HOLD"}.get(urg, urg.upper())

            st.markdown(f'<span class="{badge_class}">{badge_text}</span> &nbsp; <b>{rule["label"]}</b>', unsafe_allow_html=True)
            st.markdown("---")

            r1, r2 = st.columns(2)
            with r1:
                st.markdown('<div class="rec-card">'
                            f'<div class="rec-label">Situation</div>'
                            f'<div class="rec-text">{expl["situation"] or "—"}</div>'
                            '</div>', unsafe_allow_html=True)
                st.markdown('<div class="rec-card">'
                            f'<div class="rec-label">Recommendation</div>'
                            f'<div class="rec-text">{expl["recommendation"] or "—"}</div>'
                            '</div>', unsafe_allow_html=True)
                st.markdown('<div class="rec-card">'
                            f'<div class="rec-label">Reasoning</div>'
                            f'<div class="rec-text">{expl["reasoning"] or "—"}</div>'
                            '</div>', unsafe_allow_html=True)

            with r2:
                st.metric("Market Average Discount", f'{mdata["market_avg"]}%')
                st.metric("Top Competitor", mdata["top_competitor"])
                st.metric("Suggested Discount", f'{rule["suggested_discount"]}%')
                st.metric("Estimated Margin After Change", f'{rule["margin_impact"]}%',
                          delta=f'{round(rule["margin_impact"] - our_margin, 1)}%')
                st.metric("Gap vs Market", f'{rule["gap"]}%')


# ══════════════════════════════════════════════════════════════════════════
# Screen 4 — Run Pipeline
# ══════════════════════════════════════════════════════════════════════════

elif screen == "⚙️ Run Pipeline":
    st.title("⚙️ Data Pipeline Control")

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Select Competitors")
        selected = {}
        for provider in COMPETITOR_SITES:
            selected[provider] = st.checkbox(provider, value=(provider in ["Myntra", "Meesho"]))

        skip_db = st.checkbox("Skip DB load (dry run)", value=False)
        run_btn = st.button("▶ Run Pipeline", type="primary", width="stretch")

    with col_right:
        st.subheader("Pipeline Log")
        log_area    = st.empty()
        metrics_area = st.empty()

        # Live system log feed (auto-updates from the sidebar handler)
        st.subheader("Detailed Module Logs")
        st.caption("All INFO/WARNING/ERROR messages from every backend module appear here in real time.")
        live_log_area = st.empty()

    # Continuously update the live log area from session state
    def _refresh_live_logs():
        lines = st.session_state.get("log_lines", [])
        if lines:
            live_log_area.markdown(
                '<div class="log-box">'
                + "<br>".join(
                    line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    for line in lines[-100:]
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        else:
            live_log_area.caption("No module logs yet.")

    _refresh_live_logs()

    if run_btn:
        chosen = [p for p, v in selected.items() if v]
        if not chosen:
            st.warning("Select at least one competitor.")
        else:
            ui_logs: list[str] = []

            def log(msg: str):
                ui_logs.append(msg)
                log_area.markdown(
                    '<div class="log-box">' + "<br>".join(ui_logs) + '</div>',
                    unsafe_allow_html=True,
                )
                _refresh_live_logs()   # sync module logs alongside

            log(f"🚀 Pipeline starting for: {', '.join(chosen)}")

            total_inserted = 0
            total_skipped  = 0
            total_offers   = 0

            for provider in chosen:
                try:
                    from ingestion.firecrawl_fetcher import fetch_promotions
                    from config.settings import COMPETITOR_SITES as CS
                    url = CS[provider]

                    log(f"⏳ [{provider}] Fetching {url}…")
                    page = fetch_promotions(url, provider)
                    log(f"✅ [{provider}] {page['char_count']:,} chars scraped")
                    _refresh_live_logs()

                    log(f"🔬 [{provider}] Extracting offers with Groq…")
                    from extraction.groq_extractor import extract_offers
                    raw = extract_offers(page)
                    log(f"✅ [{provider}] {raw['total_offers']} raw offers extracted")
                    _refresh_live_logs()

                    log(f"🧹 [{provider}] Processing…")
                    from processing.post_processor import process_provider
                    clean = process_provider(raw)
                    total_offers += clean["total_clean"]
                    log(f"✅ [{provider}] {clean['total_clean']}/{clean['total_raw']} offers kept ({clean['dropped']} dropped)")
                    _refresh_live_logs()

                    if not skip_db:
                        log(f"💾 [{provider}] Loading to DB…")
                        from database.loader import load_promotions
                        summary = load_promotions(clean)
                        total_inserted += summary["inserted"]
                        total_skipped  += summary["skipped"]
                        log(f"✅ [{provider}] inserted:{summary['inserted']} skipped:{summary['skipped']}")
                        _refresh_live_logs()

                except Exception as e:
                    log(f"❌ [{provider}] Error: {e}")

            log("🎉 Pipeline complete!")
            _refresh_live_logs()
            metrics_area.markdown(
                f"""
                | Metric | Value |
                |--------|-------|
                | Providers run | {len(chosen)} |
                | Total clean offers | {total_offers} |
                | DB inserted | {total_inserted} |
                | DB skipped | {total_skipped} |
                """,
            )


# ══════════════════════════════════════════════════════════════════════════
# Screen 5 — AI Assistant
# ══════════════════════════════════════════════════════════════════════════

elif screen == "🤖 AI Assistant":
    st.title("🤖 Ask Promo Intel AI")
    st.caption("Ask anything about competitor promotions or how to respond to market moves")

    examples = [
        "What is Myntra doing in footwear this week?",
        "Which category has the highest market discount right now?",
        "Ajio launched 70% off ethnic wear. What should we do?",
        "Show me all offers with coupon codes",
    ]

    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.sidebar:
        if st.button("🗑 Clear Chat"):
            st.session_state.messages = []
            st.rerun()

    if not st.session_state.messages:
        st.markdown("**Try asking:**")
        cols = st.columns(2)
        for i, ex in enumerate(examples):
            if cols[i % 2].button(ex, key=f"ex_{i}", width="stretch"):
                st.session_state.messages.append({"role": "user", "content": ex})
                st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("tool_used"):
                st.markdown(
                    f'<div class="tool-tag">🔧 tool used: {msg["tool_used"]}</div>',
                    unsafe_allow_html=True,
                )

    if prompt := st.chat_input("Ask about competitor promotions…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    from chatbot.chat_engine import chat
                    history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages[:-1]
                    ]
                    result   = chat(prompt, history)
                    response = result["response"]
                    tool     = result.get("tool_used", "")
                except Exception as e:
                    response = f"❌ Error: {e}"
                    tool     = ""

            st.markdown(response)
            if tool:
                st.markdown(
                    f'<div class="tool-tag">🔧 tool used: {tool}</div>',
                    unsafe_allow_html=True,
                )

        st.session_state.messages.append({
            "role"     : "assistant",
            "content"  : response,
            "tool_used": tool,
        })
