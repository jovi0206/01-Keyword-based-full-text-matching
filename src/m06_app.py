import html
import tempfile
from collections import defaultdict
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from m01_jats_parser import (
    parse_jats,
    load_pubmed_documents_from_readme_text,
)
from m02_text_processor import process_document
from m03_position_mapper import map_document_positions
from m04_index_builder import build_index
from m05_query_engine import search_query


# ============================================================
# MODULE 06 — STREAMLIT WEB APP V2
# ============================================================
# UX:
# Single Upload (TXT/XML auto-detect) → Build Index → Sticky Search
# → Search Summary → Inline Article Results with Match Highlighting
#
# M01 ~ M05 interfaces are unchanged.
# M06 isolates per-file failures during upload/build.
# ============================================================

st.set_page_config(
    page_title="Keyword-based Full-Text Matching",
    page_icon="🔎",
    layout="wide",
)


# UI feature switches. Set to True if the selected-file detail panel is needed later.
SHOW_SELECTED_FILES_DETAILS = False


# ============================================================
# VISUAL SYSTEM — NATURAL GREEN LIGHT UI
#
# UI 微調方式：
# 先修改下方 CSS 的「UI TUNING ZONE」即可。
# 一般不需要再往下找 class；寬度、高度、字體與主要色彩都集中在 :root。
# ============================================================
# Design goals:
# 1. High readability on notebook + classroom projector
# 2. Linen-white background with forest-green visual hierarchy
# 3. Results-first visual structure: Retrieval → Matching → Verification
# 4. No decorative charts; use clear KPI cards and progressive disclosure
# ============================================================

st.markdown(
    """
    <style>

    /* ========================================================
       UI TUNING ZONE — 常用微調集中在這裡
       ======================================================== */
    :root {
        /* ---------- 主色盤 ---------- */
        --kfm-forest: #2E4031;
        --kfm-moss: #8FBC8F;
        --kfm-linen: #F4F6F0;
        --kfm-ink: #1C2321;
        --kfm-card: #FFFFFF;
        --kfm-muted: #5F6D63;
        --kfm-border: #D7E0D4;
        --kfm-soft: #E8EEE6;
        --kfm-soft-2: #EEF2EC;

        /* ---------- Exact 強調色 ---------- */
        --kfm-exact-bg: #FFFFFF;
        --kfm-exact-border: #8FBC8F;
        --kfm-exact-value: #1C2321;

        /* ---------- 01 Index KPI：Documents / Indexed Words / Unique Terms ---------- */
        --kfm-index-max-width: 580px;
        --kfm-index-min-height: 190px;
        --kfm-index-padding-y: 14px;
        --kfm-index-padding-x: 22px;
        --kfm-index-radius: 22px;
        --kfm-index-label-size: 2.02rem;
        --kfm-index-value-size: 4.35rem;
        --kfm-index-caption-size: 0.92rem;

        /* ---------- 02 Search Summary：四張 KPI ---------- */
        --kfm-summary-max-width: 400px;
        --kfm-summary-min-height: 190px;
        --kfm-summary-padding-y: 14px;
        --kfm-summary-padding-x: 18px;
        --kfm-summary-radius: 22px;
        --kfm-summary-label-size: 2.02rem;
        --kfm-summary-value-size: 3.55rem;

        /* ---------- 每篇 Search Result：Exact / Related / Total ---------- */
        --kfm-result-min-height: 82px;
        --kfm-result-padding-y: 9px;
        --kfm-result-padding-x: 16px;
        --kfm-result-radius: 15px;
        --kfm-result-label-size: 0.76rem;
        --kfm-result-value-size: 2rem;

        /* ---------- Search Bar ---------- */
        --kfm-search-height: 52px;
        --kfm-search-font-size: 1.12rem;
        --kfm-search-button-font-size: 1.05rem;
        --kfm-search-radius: 999px;
    }


    /* ========================================================
       0. GLOBAL PAGE
       ======================================================== */
    .stApp {
        background: var(--kfm-linen);
        color: var(--kfm-ink);
    }

    [data-testid="stHeader"] {
        background: rgba(244, 246, 240, 0.94);
    }

    [data-testid="stSidebar"] {
        background: var(--kfm-soft-2);
        border-right: 1px solid var(--kfm-border);
    }


    /* ========================================================
       1. HERO — Keyword-based Full-Text Matching
       ======================================================== */
    .kfm-hero {
        background: linear-gradient(
            105deg,
            #1C2321 0%,
            #2E4031 68%,
            #49644D 100%
        );
        color: white;
        border-radius: 16px;
        padding: 22px 28px 20px 28px;
        margin: 4px 0 28px 0;
        box-shadow: 0 8px 22px rgba(28, 35, 33, 0.13);
    }

    .kfm-hero-kicker {
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.11em;
        text-transform: uppercase;
        opacity: 0.84;
        margin-bottom: 5px;
    }

    .kfm-hero-title {
        font-size: clamp(2rem, 3vw, 3rem);
        line-height: 1.08;
        font-weight: 800;
        letter-spacing: -0.02em;
        margin-bottom: 13px;
    }

    .kfm-flow {
        display: flex;
        flex-wrap: wrap;
        gap: 7px;
        align-items: center;
        font-size: 0.92rem;
        opacity: 0.96;
    }

    .kfm-flow-step {
        background: rgba(255,255,255,0.12);
        border: 1px solid rgba(255,255,255,0.24);
        border-radius: 999px;
        padding: 5px 10px;
        font-weight: 600;
    }

    .kfm-flow-arrow {
        opacity: 0.72;
        font-weight: 700;
    }


    /* ========================================================
       2. SECTION HEADER — 01 Load Documents / 02 Search
       ======================================================== */
    .kfm-section {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        margin: 24px 0 12px 0;
    }

    .kfm-section-number {
        flex: 0 0 auto;
        background: var(--kfm-ink);
        color: white;
        border-radius: 9px;
        min-width: 42px;
        height: 42px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1rem;
        font-weight: 800;
    }

    .kfm-section-title {
        color: var(--kfm-ink);
        font-size: 1.65rem;
        line-height: 1.12;
        font-weight: 800;
        margin: 0;
    }

    .kfm-section-subtitle {
        color: var(--kfm-muted);
        font-size: 0.93rem;
        margin-top: 4px;
        line-height: 1.45;
    }

    .kfm-subheading {
        width: 100%;
        background: var(--kfm-forest);
        color: #FFFFFF;
        border-radius: 14px;
        padding: 14px 20px;
        margin: 28px 0 16px 0;
        font-size: 1.75rem;
        line-height: 1.15;
        font-weight: 850;
        box-shadow: 0 5px 14px rgba(46, 64, 49, 0.10);
    }


    /* ========================================================
       3. LOAD DOCUMENTS — File Uploader
       ======================================================== */
    /*
       保留 Streamlit 原生 uploader 行為：
       - 顯示已選檔案
       - 可用 × 刪除單一檔案
       - 不另外覆寫 uploader 內部 layout
    */


    /* ========================================================
       4. BUTTONS — Analyze / Search / Open Article
       ======================================================== */
    .stButton > button,
    .stFormSubmitButton > button {
        border-radius: 9px !important;
        font-weight: 700 !important;
        min-height: 2.75rem;
    }

    button[kind="primary"] {
        background: var(--kfm-forest) !important;
        border-color: var(--kfm-forest) !important;
        color: white !important;
    }

    button[kind="primary"]:hover {
        background: var(--kfm-ink) !important;
        border-color: var(--kfm-ink) !important;
    }


    /* ========================================================
       5. BUILD STATUS — Index Ready
       ======================================================== */
    .kfm-status {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
        background: #EEF4EC;
        border: 1px solid #C8D9C4;
        border-left: 5px solid var(--kfm-forest);
        border-radius: 10px;
        padding: 11px 15px;
        margin: 12px 0 14px 0;
    }

    .kfm-status-title {
        color: var(--kfm-forest);
        font-size: 1.1rem;
        font-weight: 850;
    }

    .kfm-status-meta {
        color: var(--kfm-muted);
        font-size: 1rem;
        font-weight: 700;
    }


    /* ========================================================
       6. INDEX KPI
       Documents / Indexed Words / Unique Terms
       ======================================================== */
    .kfm-index-card {
        background: var(--kfm-card);
        border: 1px solid var(--kfm-border);
        border-top: 7px solid var(--kfm-moss);
        border-radius: var(--kfm-index-radius);
        box-shadow: 0 10px 24px rgba(28, 35, 33, 0.07);
        margin: 6px auto 12px auto;

        max-width: var(--kfm-index-max-width);
        min-height: var(--kfm-index-min-height);
        padding:
            var(--kfm-index-padding-y)
            var(--kfm-index-padding-x);

        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
    }

    .kfm-index-card.primary {
        border-top-color: var(--kfm-forest);
    }

    .kfm-card-label {
        color: var(--kfm-muted);
        font-size: var(--kfm-index-label-size);
        font-weight: 800;
        letter-spacing: 0.015em;
        margin-bottom: 14px;
    }

    .kfm-card-value {
        color: var(--kfm-forest);
        font-size: var(--kfm-index-value-size);
        line-height: 1;
        font-weight: 850;
    }

    .kfm-card-caption {
        color: var(--kfm-muted);
        font-size: var(--kfm-index-caption-size);
        margin-top: 16px;
        line-height: 1.35;
    }


    /* ========================================================
       7. SEARCH BAR
       ======================================================== */
    div[data-testid="stForm"] {
        background: var(--kfm-moss);
        border: 0;
        border-radius: var(--kfm-search-radius);
        padding: 10px 14px 4px 14px;
        box-shadow: 0 8px 20px rgba(46, 64, 49, 0.16);
    }

    /* Search controls: force TextInput / Selectbox / button to the exact same height and pill radius. */
    div[data-testid="stForm"] [data-testid="stTextInput"],
    div[data-testid="stForm"] [data-testid="stSelectbox"],
    div[data-testid="stForm"] .stFormSubmitButton {
        min-height: var(--kfm-search-height) !important;
        height: var(--kfm-search-height) !important;
    }

    /* Streamlit/BaseWeb wraps TextInput in extra layers; size those layers too. */
    div[data-testid="stForm"] [data-testid="stTextInput"] > div,
    div[data-testid="stForm"] [data-testid="stTextInput"] > div > div,
    div[data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="input"],
    div[data-testid="stForm"] [data-testid="stTextInput"] [data-baseweb="base-input"] {
        min-height: var(--kfm-search-height) !important;
        height: var(--kfm-search-height) !important;
        border-radius: var(--kfm-search-radius) !important;
        overflow: hidden !important;
        box-sizing: border-box !important;
    }

    div[data-testid="stForm"] [data-testid="stTextInput"] input {
        min-height: var(--kfm-search-height) !important;
        height: var(--kfm-search-height) !important;
        border-radius: var(--kfm-search-radius) !important;
        border: 0 !important;
        background: var(--kfm-linen) !important;
        color: var(--kfm-ink) !important;
        font-size: var(--kfm-search-font-size) !important;
        padding: 0 20px !important;
        box-sizing: border-box !important;
    }

    div[data-testid="stForm"] [data-testid="stSelectbox"] > div,
    div[data-testid="stForm"] [data-testid="stSelectbox"] > div > div,
    div[data-testid="stForm"] [data-testid="stSelectbox"] [data-baseweb="select"],
    div[data-testid="stForm"] [data-testid="stSelectbox"] [data-baseweb="select"] > div {
        min-height: var(--kfm-search-height) !important;
        height: var(--kfm-search-height) !important;
        border-radius: var(--kfm-search-radius) !important;
        overflow: hidden !important;
        border: 0 !important;
        background: #FFFFFF !important;
        color: var(--kfm-ink) !important;
        box-sizing: border-box !important;
    }

    div[data-testid="stForm"] .stFormSubmitButton > button {
        min-height: var(--kfm-search-height) !important;
        height: var(--kfm-search-height) !important;
        border-radius: var(--kfm-search-radius) !important;
        font-size: var(--kfm-search-button-font-size) !important;
        box-shadow: none !important;
        box-sizing: border-box !important;
    }

    .kfm-search-help {
        color: var(--kfm-muted);
        font-size: 0.92rem;
        margin: 8px 4px 2px 6px;
    }


    /* ========================================================
       8. SEARCH SUMMARY
       Query + Retrieved / Exact / Related / Total
       ======================================================== */
    .kfm-query-line {
        color: var(--kfm-muted);
        font-size: 1.08rem;
        margin: 0.2rem 0 1rem 0;
    }

    .kfm-query-line strong,
    .kfm-query-value {
        color: var(--kfm-ink);
        font-weight: 800;
    }

    .kfm-summary-card {
        background: var(--kfm-card);
        border: 1px solid var(--kfm-border);
        border-top: 7px solid var(--kfm-moss);
        border-radius: var(--kfm-summary-radius);
        box-shadow: 0 10px 24px rgba(28, 35, 33, 0.07);
        margin: 6px auto 12px auto;

        max-width: var(--kfm-summary-max-width);
        min-height: var(--kfm-summary-min-height);
        padding:
            var(--kfm-summary-padding-y)
            var(--kfm-summary-padding-x);

        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
    }

    .kfm-summary-card.primary {
        border-top-color: var(--kfm-forest);
    }

    .kfm-summary-card.exact {
        border-top-color: var(--kfm-exact-border);
        background: var(--kfm-exact-bg);
    }

    .kfm-summary-label {
        color: var(--kfm-muted);
        font-size: var(--kfm-summary-label-size);
        font-weight: 800;
        letter-spacing: 0.015em;
        margin-bottom: 14px;
    }

    .kfm-summary-value {
        color: var(--kfm-forest);
        font-size: var(--kfm-summary-value-size);
        line-height: 1;
        font-weight: 850;
    }

    .kfm-summary-card.exact .kfm-summary-value {
        color: var(--kfm-exact-value);
    }


    /* ========================================================
       9. SEARCH RESULT CARD
       每篇文章內：Exact / Related / Total
       ======================================================== */
    .kfm-result-kpi {
        background: #FFFFFF;
        border: 1px solid var(--kfm-border);
        border-top: 5px solid var(--kfm-moss);
        border-radius: var(--kfm-result-radius);

        min-height: var(--kfm-result-min-height);
        padding:
            var(--kfm-result-padding-y)
            var(--kfm-result-padding-x)
            12px
            var(--kfm-result-padding-x);

        display: flex;
        flex-direction: column;
        justify-content: center;
        box-shadow: 0 5px 14px rgba(28, 35, 33, 0.05);
    }

    .kfm-result-kpi.exact {
        background: var(--kfm-exact-bg);
        border-top-color: var(--kfm-exact-border);
    }

    .kfm-result-label {
        color: var(--kfm-muted);
        font-size: var(--kfm-result-label-size);
        font-weight: 800;
        letter-spacing: 0.025em;
        margin-bottom: 4px;
    }

    .kfm-result-value {
        color: var(--kfm-ink);
        font-size: var(--kfm-result-value-size);
        line-height: 1.02;
        font-weight: 850;
    }

    .kfm-result-kpi.exact .kfm-result-value {
        color: var(--kfm-exact-value);
    }

    .kfm-meta-row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 7px;
        margin: -2px 0 10px 0;
    }

    .kfm-chip {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        background: var(--kfm-soft-2);
        border: 1px solid var(--kfm-border);
        color: var(--kfm-muted);
        padding: 3px 9px;
        font-size: 0.76rem;
        font-weight: 700;
    }

    .kfm-chip.format {
        background: #DDEBDD;
        border-color: #C8D9C4;
        color: var(--kfm-ink);
    }

    .kfm-snippet {
        line-height: 1.68;
        font-size: 1rem;
        margin: 6px 0 11px 0;
        color: var(--kfm-ink);
    }

    .kfm-snippet-exact {
        color: var(--kfm-ink);
        background: var(--kfm-soft);
        border-radius: 3px;
        padding: 0 2px;
        font-weight: 850;
    }

    /* One compact analysis row per result.
       Match cards remain visually dominant; document statistics are muted. */
    .kfm-result-metrics-grid {
        display: grid;
        grid-template-columns:
            minmax(138px, 1.22fr)
            minmax(138px, 1.22fr)
            minmax(138px, 1.22fr)
            minmax(112px, 0.88fr)
            minmax(112px, 0.88fr)
            minmax(96px, 0.74fr)
            minmax(96px, 0.74fr);
        gap: 10px;
        margin: 8px 0 10px 0;
        align-items: stretch;
    }

    .kfm-result-main-card,
    .kfm-result-stat-card {
        border-radius: 13px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-width: 0;
    }

    .kfm-result-main-card {
        background: #FFFFFF;
        border: 1px solid var(--kfm-border);
        border-top: 5px solid var(--kfm-moss);
        min-height: 78px;
        padding: 10px 13px;
        box-shadow: 0 4px 11px rgba(28, 35, 33, 0.045);
    }

    .kfm-result-main-card.exact {
        border-top-color: var(--kfm-exact-border);
        background: var(--kfm-exact-bg);
    }

    .kfm-result-main-label {
        color: var(--kfm-muted);
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.02em;
        margin-bottom: 3px;
        white-space: nowrap;
    }

    .kfm-result-main-value {
        color: var(--kfm-ink);
        font-size: 1.85rem;
        line-height: 1;
        font-weight: 850;
    }

    .kfm-result-stat-card {
        background: #F5F7F2;
        border: 1px solid #E0E5DC;
        min-height: 68px;
        padding: 9px 11px;
        box-shadow: none;
    }

    .kfm-result-stat-label {
        color: #748078;
        font-size: 0.64rem;
        line-height: 1.18;
        font-weight: 750;
        margin-bottom: 4px;
    }

    .kfm-result-stat-value {
        color: #526057;
        font-size: 1.18rem;
        line-height: 1;
        font-weight: 780;
    }

    @media (max-width: 1450px) {
        .kfm-result-metrics-grid {
            grid-template-columns: repeat(3, minmax(150px, 1fr));
        }

        .kfm-result-stat-card {
            min-height: 58px;
        }
    }

    /* ========================================================
       STICKY MAIN SEARCH BAR
       The professor can scroll through all six results and enter
       another query without returning to the top of the page.
       ======================================================== */
    .st-key-search_form {
        position: sticky;
        top: 3.35rem;
        z-index: 9990;
        background: rgba(244, 246, 240, 0.97);
        padding: 8px 0 6px 0;
        margin: -8px 0 4px 0;
        backdrop-filter: blur(7px);
    }

    /* ========================================================
       INLINE ARTICLE IN SEARCH RESULTS
       ======================================================== */
    .kfm-inline-article {
        margin: 14px 0 2px 0;
        padding: 16px 18px 15px 18px;
        background: #FFFFFF;
        border: 1px solid var(--kfm-border);
        border-radius: 12px;
        color: var(--kfm-ink);
    }

    .kfm-inline-heading {
        color: var(--kfm-forest);
        font-size: 1.18rem;
        font-weight: 900;
        margin: 0 0 10px 0;
        padding-bottom: 7px;
        border-bottom: 1px solid var(--kfm-border);
    }

    .kfm-inline-group-heading {
        color: var(--kfm-forest);
        font-size: 1.08rem;
        font-weight: 850;
        margin: 18px 0 8px 0;
    }

    .kfm-inline-paragraph {
        margin: 8px 0 10px 0;
        line-height: 1.72;
        font-size: 1.02rem;
    }

    .kfm-inline-label {
        font-weight: 900;
        color: var(--kfm-ink);
    }

    .kfm-inline-article .match.exact {
        font-weight: 900;
        background: var(--kfm-soft);
        border-radius: 3px;
        padding: 0 2px;
    }

    .kfm-inline-article .match.related {
        font-weight: 850;
        text-decoration: underline dotted var(--kfm-forest);
        text-underline-offset: 3px;
    }


    /* ========================================================
       10. EXPANDERS
       Search Details / Document Statistics / Processing Details
       ======================================================== */
    [data-testid="stExpander"] {
        background: #FFFFFF;
        border-color: var(--kfm-border);
        border-radius: 9px;
    }


    /* ========================================================
       11. DOCUMENT STATISTICS TABLE
       Pure HTML table: avoids Streamlit dataframe / PyArrow dependency
       ======================================================== */
    .kfm-stats-table-wrap {
        width: 100%;
        overflow-x: auto;
        margin: 4px 0 12px 0;
    }

    .kfm-stats-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        background: var(--kfm-card);
        color: var(--kfm-ink);
        font-size: 1.22rem;
        border: 1px solid var(--kfm-border);
        border-radius: 10px;
        overflow: hidden;
    }

    .kfm-stats-table th {
        background: var(--kfm-soft);
        color: var(--kfm-forest);
        font-size: 1.32rem;
        font-weight: 850;
        text-align: left;
        padding: 15px 14px;
        border-bottom: 1px solid var(--kfm-border);
        white-space: nowrap;
    }

    .kfm-stats-table td {
        font-size: 1.22rem;
        padding: 16px 14px;
        border-bottom: 1px solid var(--kfm-border);
        vertical-align: middle;
        line-height: 1.45;
    }

    .kfm-stats-table tbody tr:last-child td {
        border-bottom: 0;
    }

    .kfm-stats-table tbody tr:nth-child(even) {
        background: var(--kfm-soft-2);
    }


    /* ========================================================
       12. ARTICLE RESULT NAVIGATION
       Fixed beside the article so controls remain available
       while the user scrolls through a long document.
       ======================================================== */

    .st-key-prev_result_side,
    .st-key-next_result_side,
    .st-key-back_to_results_side {
        position: fixed;
        z-index: 9998;
        width: 170px;
    }

    .st-key-prev_result_side {
        left: 28px;
        top: 48%;
        transform: translateY(-50%);
    }

    .st-key-next_result_side {
        right: 28px;
        top: 48%;
        transform: translateY(-50%);
    }

    .st-key-back_to_results_side {
        right: 28px;
        top: calc(48% + 116px);
        transform: translateY(-50%);
    }

    .st-key-prev_result_side button,
    .st-key-next_result_side button,
    .st-key-back_to_results_side button {
        width: 170px !important;
        min-height: 46px !important;
        border-radius: 9px !important;
        font-weight: 800 !important;
        box-shadow: 0 7px 18px rgba(28, 35, 33, 0.14);
    }

    .st-key-prev_result_side button,
    .st-key-next_result_side button {
        background: #FFFFFF !important;
        color: var(--kfm-forest) !important;
        border: 1px solid var(--kfm-border) !important;
    }

    .st-key-prev_result_side button:hover,
    .st-key-next_result_side button:hover {
        background: var(--kfm-soft) !important;
        border-color: var(--kfm-moss) !important;
    }

    .st-key-back_to_results_side button {
        background: var(--kfm-forest) !important;
        color: #FFFFFF !important;
        border: 1px solid var(--kfm-forest) !important;
    }

    .kfm-side-result-count-left,
    .kfm-side-result-count-right {
        position: fixed;
        z-index: 9997;
        width: 170px;
        text-align: center;
        color: var(--kfm-muted);
        font-size: 0.92rem;
        font-weight: 800;
        pointer-events: none;
    }

    .kfm-side-result-count-left {
        left: 28px;
        top: calc(48% + 48px);
    }

    .kfm-side-result-count-right {
        right: 28px;
        top: calc(48% + 48px);
    }

    /* On narrower screens, keep controls away from article text. */
    @media (max-width: 1350px) {
        .st-key-prev_result_side,
        .st-key-next_result_side,
        .st-key-back_to_results_side,
        .kfm-side-result-count-left,
        .kfm-side-result-count-right {
            width: 135px;
        }

        .st-key-prev_result_side button,
        .st-key-next_result_side button,
        .st-key-back_to_results_side button {
            width: 135px !important;
            font-size: 0.86rem !important;
        }

        .st-key-prev_result_side,
        .kfm-side-result-count-left {
            left: 10px;
        }

        .st-key-next_result_side,
        .st-key-back_to_results_side,
        .kfm-side-result-count-right {
            right: 10px;
        }
    }


    /* ========================================================
       13. ARTICLE QUICK SEARCH
       Simple Auto Search available directly from Article View.
       ======================================================== */
    .st-key-article_quick_search {
        position: fixed;
        left: 50%;
        bottom: 18px;
        transform: translateX(-50%);
        z-index: 9999;
        width: min(720px, 58vw);
        background: rgba(244, 246, 240, 0.97);
        border: 1px solid var(--kfm-border);
        border-radius: 14px;
        padding: 8px 10px 4px 10px;
        box-shadow: 0 10px 28px rgba(28, 35, 33, 0.18);
        backdrop-filter: blur(6px);
    }

    .st-key-article_quick_search [data-testid="stTextInput"] input {
        min-height: 46px;
        border-radius: 10px !important;
        background: #FFFFFF !important;
        color: var(--kfm-ink) !important;
        font-size: 1rem !important;
    }

    .st-key-article_quick_search .stFormSubmitButton > button {
        min-height: 46px !important;
        border-radius: 10px !important;
        background: var(--kfm-forest) !important;
        border-color: var(--kfm-forest) !important;
        color: #FFFFFF !important;
        font-weight: 800 !important;
    }

    @media (max-width: 1350px) {
        .st-key-article_quick_search {
            width: min(620px, 56vw);
        }
    }


    /* ========================================================
       14. SEARCH RESULT NUMBER
       PubMed-inspired result numbering, adapted to our visual style.
       ======================================================== */
    .kfm-result-number {
        width: 42px;
        height: 42px;
        border-radius: 12px;
        background: var(--kfm-forest);
        color: #FFFFFF;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.05rem;
        font-weight: 900;
        box-shadow: 0 5px 12px rgba(28, 35, 33, 0.12);
        margin-top: 2px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

DEFAULT_SESSION_VALUES = {
    "index_ready": False,
    "processed_documents": [],
    "positioned_documents": [],
    "index_data": None,
    "build_errors": [],
    "build_signature": None,
    "search_result": None,
    "view_mode": "search",
    "selected_document_id": None,
}

for key, value in DEFAULT_SESSION_VALUES.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# BASIC HELPERS
# ============================================================

def render_hero():
    st.markdown(
        """
        <div class="kfm-hero">
            <div class="kfm-hero-kicker">Artificial Intelligence Information Retrieval</div>
            <div class="kfm-hero-title">MATCH</div>
            <div class="kfm-flow">
                <span class="kfm-flow-step">Upload Files</span>
                <span class="kfm-flow-arrow">→</span>
                <span class="kfm-flow-step">Build Index</span>
                <span class="kfm-flow-arrow">→</span>
                <span class="kfm-flow-step">Search</span>
                <span class="kfm-flow-arrow">→</span>
                <span class="kfm-flow-step">Review Results</span>
                <span class="kfm-flow-arrow">→</span>
                <span class="kfm-flow-step">Locate Match</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_header(number, title, subtitle):
    st.markdown(
        f"""
        <div class="kfm-section">
            <div class="kfm-section-number">{html.escape(str(number))}</div>
            <div>
                <div class="kfm-section-title">{html.escape(title)}</div>
                <div class="kfm-section-subtitle">{html.escape(subtitle)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_subheading(title):
    st.markdown(
        f'<div class="kfm-subheading">{html.escape(str(title))}</div>',
        unsafe_allow_html=True,
    )


def render_index_kpi(label, value, caption="", card_class=""):
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))
    safe_caption = html.escape(str(caption))

    st.markdown(
        f'<div class="kfm-index-card {card_class}">'
        f'<div class="kfm-card-label">{safe_label}</div>'
        f'<div class="kfm-card-value">{safe_value}</div>'
        f'<div class="kfm-card-caption">{safe_caption}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_kpi_card(label, value, card_class=""):
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))

    st.markdown(
        f'<div class="kfm-summary-card {card_class}">'
        f'<div class="kfm-summary-label">{safe_label}</div>'
        f'<div class="kfm-summary-value">{safe_value}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_result_kpi(label, value, card_class=""):
    safe_label = html.escape(str(label))
    safe_value = html.escape(str(value))

    st.markdown(
        f'<div class="kfm-result-kpi {card_class}">'
        f'<div class="kfm-result-label">{safe_label}</div>'
        f'<div class="kfm-result-value">{safe_value}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_result_metrics_grid(
    exact_count,
    related_count,
    total_count,
    stats_document,
):
    """Render match metrics prominently and document analysis as muted cards."""

    def main_card(label, value, card_class=""):
        return (
            f'<div class="kfm-result-main-card {card_class}">'
            f'<div class="kfm-result-main-label">{html.escape(str(label))}</div>'
            f'<div class="kfm-result-main-value">{html.escape(str(value))}</div>'
            '</div>'
        )

    def stat_card(label, value):
        return (
            '<div class="kfm-result-stat-card">'
            f'<div class="kfm-result-stat-label">{html.escape(str(label))}</div>'
            f'<div class="kfm-result-stat-value">{html.escape(str(value))}</div>'
            '</div>'
        )

    cards = [
        main_card("Exact Matches", exact_count, "exact"),
        main_card("Related Matches", related_count),
        main_card("Total Matches", total_count),
    ]

    if stats_document:
        cards.extend(
            [
                stat_card(
                    "Characters\n(with spaces)",
                    f"{stats_document['character_count']:,}",
                ),
                stat_card(
                    "Characters\n(without spaces)",
                    f"{stats_document['character_count_without_spaces']:,}",
                ),
                stat_card(
                    "Words",
                    f"{stats_document['computed_word_count']:,}",
                ),
                stat_card(
                    "Sentences",
                    f"{stats_document['sentence_count']:,}",
                ),
            ]
        )

    st.markdown(
        '<div class="kfm-result-metrics-grid">'
        + "".join(cards)
        + '</div>',
        unsafe_allow_html=True,
    )


def render_build_status(loaded_count, skipped_count):
    skipped_text = (
        f"{skipped_count} skipped"
        if skipped_count
        else "All selected files processed"
    )

    st.markdown(
        f"""
        <div class="kfm-status">
            <div class="kfm-status-title">Index Ready</div>
            <div class="kfm-status-meta">
                {loaded_count} documents loaded · {html.escape(skipped_text)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def input_signature(input_files):
    """Track the current single-uploader selection for rebuild warnings."""

    return tuple(
        (
            uploaded_file.name,
            uploaded_file.size,
        )
        for uploaded_file in (input_files or [])
    )


def detect_uploaded_input_type(uploaded_file):
    """Detect XML vs PMID text from file content, with extension fallback."""

    raw = uploaded_file.getvalue()
    stripped = raw.lstrip(b"\xef\xbb\xbf \t\r\n")

    # XML declaration / root element.
    if stripped.startswith(b"<"):
        return "xml"

    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix == ".xml":
        return "xml"

    return "pmid_text"


def get_document_id(document):
    return (
        document.get("pmcid")
        or document.get("pmid")
        or document["filename"]
    )


def build_positioned_document_lookup(positioned_documents):
    return {
        get_document_id(document): document
        for document in positioned_documents
    }


def build_processed_document_lookup(processed_documents):
    return {
        get_document_id(document): document
        for document in processed_documents
    }


# ============================================================
# M01 → M04 BUILD PIPELINE
# ============================================================

def build_input_documents(input_files):
    """Build one index from a mixed TXT/XML upload with auto detection."""

    processed_documents = []
    positioned_documents = []
    errors = []
    accepted_document_ids = set()

    def accept_document(document):
        # M02
        processed = process_document(document)

        # M03
        positioned = map_document_positions(processed)

        document_id = get_document_id(positioned)

        if document_id in accepted_document_ids:
            raise ValueError(
                "Duplicate document ID detected: "
                f"{document_id}"
            )

        accepted_document_ids.add(document_id)
        processed_documents.append(processed)
        positioned_documents.append(positioned)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)

        for file_number, uploaded_file in enumerate(
            input_files or [],
            start=1,
        ):
            try:
                input_type = detect_uploaded_input_type(uploaded_file)

                # ------------------------------------------------
                # XML → M01 auto detector → JATS / BioC /
                # PubMed XML / Generic XML
                # ------------------------------------------------
                if input_type == "xml":
                    safe_name = Path(uploaded_file.name).name
                    file_folder = temp_root / f"{file_number:03d}"
                    file_folder.mkdir(parents=True, exist_ok=True)

                    xml_path = file_folder / safe_name
                    xml_path.write_bytes(uploaded_file.getvalue())

                    document = parse_jats(xml_path)
                    accept_document(document)
                    continue

                # ------------------------------------------------
                # Text → PMID list → PubMed EFetch → PubMed parser
                # ------------------------------------------------
                readme_text = uploaded_file.getvalue().decode(
                    "utf-8-sig",
                    errors="replace",
                )

                pubmed_documents, missing_pmids = (
                    load_pubmed_documents_from_readme_text(
                        readme_text,
                        source_name=uploaded_file.name,
                    )
                )

                for pmid in missing_pmids:
                    errors.append(
                        {
                            "filename": f"PMID {pmid}",
                            "error": (
                                "PubMed record was not returned "
                                "by NCBI EFetch."
                            ),
                        }
                    )

                for document in pubmed_documents:
                    try:
                        accept_document(document)

                    except Exception as error:
                        errors.append(
                            {
                                "filename": (
                                    f"PMID {document.get('pmid', '')}"
                                    or uploaded_file.name
                                ),
                                "error": (
                                    f"{type(error).__name__}: {error}"
                                ),
                            }
                        )

            except Exception as error:
                errors.append(
                    {
                        "filename": uploaded_file.name,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

    # M04 — only documents that passed M01 ~ M03 enter the index.
    index_data = (
        build_index(positioned_documents)
        if positioned_documents
        else None
    )

    return (
        processed_documents,
        positioned_documents,
        index_data,
        errors,
    )


# ============================================================
# DOCUMENT STATISTICS
# ============================================================

def document_stats_rows(processed_documents):
    rows = []

    for document in processed_documents:
        rows.append(
            {
                "PMID": document.get("pmid", ""),
                "File": document["filename"],
                "Format": document.get("source_format", "Unknown"),
                "Characters With Spaces": f"{document['character_count']:,}",
                "Characters Without Spaces": (
                    f"{document['character_count_without_spaces']:,}"
                ),
                "Words": f"{document['computed_word_count']:,}",
                "Sentences": f"{document['sentence_count']:,}",
            }
        )

    return rows


# ============================================================
# SEARCH RESULT HELPERS
# ============================================================

def group_results_by_document(result):
    grouped = defaultdict(list)

    for item in result["exact_results"]:
        grouped[item["document_id"]].append(item)

    for item in result["related_results"]:
        grouped[item["document_id"]].append(item)

    return grouped


def count_match_types(items):
    exact_count = sum(
        1
        for item in items
        if item["match_type"] == "exact"
    )

    related_count = len(items) - exact_count

    return exact_count, related_count


def sort_document_results(grouped):
    return sorted(
        grouped.items(),
        key=lambda pair: (
            -sum(
                1
                for item in pair[1]
                if item["match_type"] == "exact"
            ),
            -len(pair[1]),
            pair[0],
        ),
    )


def choose_document_snippet(items):
    exact_items = [
        item
        for item in items
        if item["match_type"] == "exact"
    ]

    if exact_items:
        return min(
            exact_items,
            key=lambda item: item["char_start"],
        )

    if items:
        return min(
            items,
            key=lambda item: (
                -item["similarity"],
                item["char_start"],
            ),
        )

    return None


def highlight_snippet(context, matched_text, match_type):
    if not context:
        return ""

    if not matched_text:
        return html.escape(context)

    start = context.find(matched_text)

    if start == -1:
        start = context.casefold().find(
            matched_text.casefold()
        )

    if start == -1:
        return html.escape(context)

    end = start + len(matched_text)

    before = html.escape(context[:start])
    matched = html.escape(context[start:end])
    after = html.escape(context[end:])

    if match_type == "exact":
        marked = (
            '<span class="kfm-snippet-exact">'
            f"{matched}"
            "</span>"
        )
    else:
        marked = f"<strong>{matched}</strong>"

    return before + marked + after


# ============================================================
# ARTICLE VIEWER
# ============================================================

FIELD_GROUPS = {
    "author": "Article Information",
    "affiliation": "Article Information",
    "keyword": "Article Information",
    "abstract_section_title": "Abstract",
    "abstract": "Abstract",
    "definition": "Definitions",
    "section_title": "Article Body",
    "body": "Article Body",
    "figure_label": "Figures",
    "figure_caption": "Figures",
    "table_label": "Tables",
    "table_caption": "Tables",
    "table_text": "Tables",
    "acknowledgment": "Acknowledgments",
    "reference": "References",
}


def html_attr(value):
    if value is None:
        value = ""

    return html.escape(
        str(value),
        quote=True,
    )


def prepare_viewer_matches(items):
    ordered_items = sorted(
        items,
        key=lambda item: (
            item["char_start"],
            0 if item["match_type"] == "exact" else 1,
            item["char_end"],
        ),
    )

    prepared = []

    for viewer_index, item in enumerate(ordered_items):
        prepared.append(
            {
                **item,
                "viewer_index": viewer_index,
            }
        )

    return prepared


def build_segment_highlight_html(segment, segment_matches):
    text = segment["text"]

    if not segment_matches:
        return html.escape(text)

    segment_start = segment["global_char_start"]

    candidates = []

    for item in segment_matches:
        local_start = item["char_start"] - segment_start
        local_end = item["char_end"] - segment_start

        if not (
            0 <= local_start < local_end <= len(text)
        ):
            continue

        candidates.append(
            (local_start, local_end, item)
        )

    candidates.sort(
        key=lambda row: (
            row[0],
            0 if row[2]["match_type"] == "exact" else 1,
            -(row[1] - row[0]),
        )
    )

    pieces = []
    cursor = 0

    for local_start, local_end, item in candidates:
        if local_start < cursor:
            continue

        pieces.append(
            html.escape(text[cursor:local_start])
        )

        matched_text = html.escape(
            text[local_start:local_end]
        )

        match_type = item["match_type"]

        score = (
            f"{item['similarity']:.0%}"
            if match_type == "related"
            else "100%"
        )

        # Article Viewer adds viewer_index for Previous/Next navigation.
        # Inline Search Results reuse this highlighter without viewer_index,
        # so the HTML id must be optional.
        viewer_index = item.get("viewer_index")

        match_id_attr = (
            f'id="match-{viewer_index}" '
            if viewer_index is not None
            else ""
        )

        pieces.append(
            (
                '<span '
                f'{match_id_attr}'
                f'class="match {html_attr(match_type)}" '
                f'data-type="{html_attr(match_type)}" '
                f'data-field="{html_attr(item["field"])}" '
                f'data-word="{html_attr(item["word_position"])}" '
                f'data-sentence="{html_attr(item["sentence_position"])}" '
                f'data-char="{html_attr(item["char_start"])}–'
                f'{html_attr(item["char_end"])}" '
                f'data-method="{html_attr(item["match_method"])}" '
                f'data-score="{html_attr(score)}">'
                f"{matched_text}"
                "</span>"
            )
        )

        cursor = local_end

    pieces.append(
        html.escape(text[cursor:])
    )

    return "".join(pieces)


def build_inline_result_article_html(
    document,
    items,
):
    """Render one Search Result article with yellow match highlighting and match navigation."""

    viewer_matches = prepare_viewer_matches(
        items
    )

    matches_by_segment = defaultdict(list)

    for item in viewer_matches:
        matches_by_segment[
            item["segment_id"]
        ].append(item)

    article_parts = []

    source_format = document.get(
        "source_format",
        "Unknown",
    )

    if source_format == "PubMed":
        article_parts.append(
            '<div class="kfm-inline-heading">Abstract</div>'
        )

        for segment in document["segments"]:
            if segment.get("field") != "abstract":
                continue

            segment_html = build_segment_highlight_html(
                segment,
                matches_by_segment.get(
                    segment["segment_id"],
                    [],
                ),
            )

            label = (
                segment.get("label", "")
                or segment.get("nlm_category", "")
                or ""
            ).strip()

            if label:
                display_label = label.title()

                article_parts.append(
                    '<p class="kfm-inline-paragraph">'
                    f'<span class="kfm-inline-label">{html.escape(display_label)}:</span> '
                    f'{segment_html}'
                    '</p>'
                )
            else:
                article_parts.append(
                    '<p class="kfm-inline-paragraph">'
                    f'{segment_html}'
                    '</p>'
                )

    else:
        last_group = None

        for segment in document["segments"]:
            field = segment.get("field", "")

            if field == "title":
                continue

            group = FIELD_GROUPS.get(field)

            if group and group != last_group:
                article_parts.append(
                    '<div class="kfm-inline-group-heading">'
                    f'{html.escape(group)}'
                    '</div>'
                )
                last_group = group

            segment_html = build_segment_highlight_html(
                segment,
                matches_by_segment.get(
                    segment["segment_id"],
                    [],
                ),
            )

            article_parts.append(
                '<p class="kfm-inline-paragraph">'
                f'{segment_html}'
                '</p>'
            )

    article_html = "".join(article_parts)
    total_matches = len(viewer_matches)

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
    margin: 0;
    background: transparent;
    color: #1C2321;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}}
.kfm-inline-shell {{
    background: #FFFFFF;
    border: 1px solid #D7E0D4;
    border-radius: 12px;
    overflow: hidden;
}}
.kfm-inline-nav {{
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    padding: 8px 12px;
    background: rgba(238, 242, 236, 0.97);
    border-bottom: 1px solid #D7E0D4;
}}
.kfm-inline-nav button {{
    border: 1px solid #8FBC8F;
    background: #FFFFFF;
    color: #2E4031;
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 13px;
    font-weight: 800;
    cursor: pointer;
}}
.kfm-inline-nav button:hover {{ background: #E8EEE6; }}
.kfm-inline-nav button:disabled {{ opacity: 0.35; cursor: default; }}
.kfm-match-counter {{
    min-width: 78px;
    text-align: center;
    color: #5F6D63;
    font-size: 13px;
    font-weight: 800;
}}
.kfm-inline-article {{
    padding: 14px 18px 16px 18px;
}}
.kfm-inline-heading {{
    color: #2E4031;
    font-size: 1.18rem;
    font-weight: 900;
    margin: 0 0 10px 0;
    padding-bottom: 7px;
    border-bottom: 1px solid #D7E0D4;
}}
.kfm-inline-group-heading {{
    color: #2E4031;
    font-size: 1.08rem;
    font-weight: 850;
    margin: 18px 0 8px 0;
}}
.kfm-inline-paragraph {{
    margin: 8px 0 10px 0;
    line-height: 1.72;
    font-size: 1.02rem;
}}
.kfm-inline-label {{
    font-weight: 900;
    color: #1C2321;
}}
.match {{
    background: #FFF3B0;
    border: 1px solid #E0B400;
    border-radius: 4px;
    padding: 0 2px;
    font-weight: 900;
}}
.match.related {{
    text-decoration: underline dotted #2E4031;
    text-underline-offset: 3px;
}}
.match.active-match {{
    background: #FFE27A;
    outline: 3px solid #B88900;
    outline-offset: 1px;
}}
</style>
</head>
<body>
<div class="kfm-inline-shell">
    <div class="kfm-inline-nav">
        <button id="prev-match" onclick="previousMatch()">◀ Previous</button>
        <span id="match-counter" class="kfm-match-counter">0 / {total_matches}</span>
        <button id="next-match" onclick="nextMatch()">Next ▶</button>
    </div>
    <div class="kfm-inline-article">
        {article_html}
    </div>
</div>
<script>
let currentIndex = 0;

function getMatches() {{
    return Array.from(document.querySelectorAll('.match'));
}}

function activateCurrentMatch(shouldScroll) {{
    const matches = getMatches();
    const counter = document.getElementById('match-counter');
    const prev = document.getElementById('prev-match');
    const next = document.getElementById('next-match');

    matches.forEach(el => el.classList.remove('active-match'));

    if (matches.length === 0) {{
        counter.textContent = '0 / 0';
        prev.disabled = true;
        next.disabled = true;
        return;
    }}

    if (currentIndex < 0) currentIndex = 0;
    if (currentIndex >= matches.length) currentIndex = matches.length - 1;

    const current = matches[currentIndex];
    current.classList.add('active-match');

    counter.textContent = (currentIndex + 1) + ' / ' + matches.length;
    prev.disabled = currentIndex === 0;
    next.disabled = currentIndex === matches.length - 1;

    if (shouldScroll) {{
        // Scroll only inside this Streamlit component iframe.
        // scrollIntoView() can propagate across the iframe boundary and
        // move the whole Streamlit page, which makes the sticky Next/Previous
        // controls leave the user's viewport.  Use the iframe's own scroll
        // position instead.
        const nav = document.querySelector('.kfm-inline-nav');
        const navHeight = nav ? nav.offsetHeight : 0;
        const rect = current.getBoundingClientRect();
        const currentScrollTop = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
        const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 600;
        const targetTop = (
            currentScrollTop
            + rect.top
            - navHeight
            - (viewportHeight / 2)
            + (rect.height / 2)
        );

        window.scrollTo({{
            top: Math.max(0, targetTop),
            behavior: 'smooth'
        }});
    }}
}}

function previousMatch() {{
    if (currentIndex > 0) {{
        currentIndex -= 1;
        activateCurrentMatch(true);
    }}
}}

function nextMatch() {{
    const matches = getMatches();
    if (currentIndex < matches.length - 1) {{
        currentIndex += 1;
        activateCurrentMatch(true);
    }}
}}

window.addEventListener('load', () => activateCurrentMatch(false));
</script>
</body>
</html>
"""


def estimate_inline_article_height(document):
    """Approximate a comfortable iframe height for the inline article."""

    searchable_segments = [
        segment
        for segment in document.get("segments", [])
        if segment.get("field") != "title"
    ]

    total_characters = sum(
        len(segment.get("text", ""))
        for segment in searchable_segments
    )

    paragraph_count = max(
        1,
        len(searchable_segments),
    )

    estimated_lines = max(
        4,
        total_characters / 115,
    )

    estimated_height = int(
        115
        + estimated_lines * 24
        + paragraph_count * 18
    )

    return max(
        300,
        min(820, estimated_height),
    )

def render_article_segment(field, content_html):
    if field == "title":
        return (
            '<h1 class="article-title">'
            f"{content_html}"
            "</h1>"
        )

    if field == "author":
        return (
            '<div class="author-line">'
            f"{content_html}"
            "</div>"
        )

    if field == "affiliation":
        return (
            '<div class="affiliation">'
            f"{content_html}"
            "</div>"
        )

    if field == "keyword":
        return (
            '<span class="keyword-chip">'
            f"{content_html}"
            "</span>"
        )

    if field in (
        "abstract_section_title",
        "section_title",
    ):
        return (
            '<h3 class="section-title">'
            f"{content_html}"
            "</h3>"
        )

    if field == "definition":
        return (
            '<p class="definition">'
            f"{content_html}"
            "</p>"
        )

    if field in (
        "figure_label",
        "table_label",
    ):
        return (
            '<div class="figure-table-label">'
            f"{content_html}"
            "</div>"
        )

    if field in (
        "figure_caption",
        "table_caption",
    ):
        return (
            '<p class="caption">'
            f"{content_html}"
            "</p>"
        )

    if field == "table_text":
        return (
            '<div class="table-text">'
            f"{content_html}"
            "</div>"
        )

    if field == "reference":
        return (
            '<div class="reference">'
            f"{content_html}"
            "</div>"
        )

    return (
        '<p class="article-paragraph">'
        f"{content_html}"
        "</p>"
    )


def build_article_viewer_html(
    document,
    items,
    query,
):
    viewer_matches = prepare_viewer_matches(items)

    matches_by_segment = defaultdict(list)

    for item in viewer_matches:
        matches_by_segment[
            item["segment_id"]
        ].append(item)

    exact_count, related_count = (
        count_match_types(viewer_matches)
    )

    article_parts = []
    last_group = None

    for segment in document["segments"]:
        field = segment["field"]
        group = FIELD_GROUPS.get(field)

        if group and group != last_group:
            article_parts.append(
                (
                    '<h2 class="group-heading">'
                    f"{html.escape(group)}"
                    "</h2>"
                )
            )
            last_group = group

        if field == "title":
            last_group = None

        segment_html = build_segment_highlight_html(
            segment,
            matches_by_segment.get(
                segment["segment_id"],
                [],
            ),
        )

        article_parts.append(
            render_article_segment(
                field,
                segment_html,
            )
        )

    article_html = "".join(article_parts)
    safe_query = html.escape(query)

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">

<style>
* {{
    box-sizing: border-box;
}}

html {{
    scroll-behavior: smooth;
}}

body {{
    margin: 0;
    background: #F4F6F0;
    color: #1C2321;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Arial,
        sans-serif;
}}

.viewer-shell {{
    max-width: 1100px;
    height: 880px;
    margin: 0 auto;
    background: white;
    box-shadow: 0 0 0 1px #e0e0e0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}}

.toolbar {{
    flex: 0 0 auto;
    z-index: 100;
    background: #2E4031;
    color: white;
    padding: 14px 20px;
    border-bottom: 1px solid #1C2321;
}}

.article-scroll {{
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    background: white;
}}

.toolbar-top {{
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
}}

.query-label {{
    font-size: 14px;
    opacity: 0.85;
}}

.query-text {{
    font-weight: 700;
    margin-right: auto;
}}

.filter-group {{
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}}

.filter-button,
.nav-button {{
    border: 1px solid rgba(255,255,255,0.45);
    background: rgba(255,255,255,0.08);
    color: white;
    border-radius: 6px;
    padding: 7px 11px;
    cursor: pointer;
    font-size: 13px;
}}

.filter-button.active {{
    background: white;
    color: #1C2321;
    font-weight: 700;
}}

.nav-button:disabled {{
    opacity: 0.35;
    cursor: default;
}}

.navigation {{
    margin-top: 10px;
    display: flex;
    align-items: center;
    gap: 10px;
}}

.counter {{
    min-width: 110px;
    text-align: center;
    font-weight: 700;
}}

.current-details {{
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(255,255,255,0.2);
    display: none;
    grid-template-columns:
        repeat(auto-fit, minmax(150px, 1fr));
    gap: 6px 16px;
    font-size: 12px;
    line-height: 1.5;
}}

.current-details.show {{
    display: grid;
}}

.article {{
    padding: 28px 38px 70px 38px;
}}

.article-title {{
    margin: 0 0 18px 0;
    line-height: 1.25;
    color: #1C2321;
    font-size: 30px;
}}

.group-heading {{
    margin-top: 34px;
    margin-bottom: 15px;
    padding-bottom: 7px;
    color: #1C2321;
    border-bottom: 2px solid #e5e9ef;
    font-size: 23px;
}}

.section-title {{
    color: #2E4031;
    margin-top: 25px;
    margin-bottom: 9px;
    font-size: 18px;
}}

.article-paragraph,
.definition,
.caption,
.reference {{
    line-height: 1.72;
    font-size: 16px;
    margin: 10px 0;
}}

.author-line {{
    display: inline-block;
    margin-right: 8px;
    font-weight: 600;
}}

.affiliation {{
    color: #5f6368;
    font-size: 14px;
    margin: 4px 0;
}}

.keyword-chip {{
    display: inline-block;
    background: #E8EEE6;
    border-radius: 12px;
    padding: 4px 9px;
    margin: 3px 5px 3px 0;
    font-size: 13px;
}}

.figure-table-label {{
    margin-top: 16px;
    font-weight: 700;
    color: #2E4031;
}}

.table-text {{
    background: #F4F6F0;
    border: 1px solid #D7E0D4;
    border-radius: 6px;
    padding: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    margin: 10px 0;
}}

.reference {{
    padding-left: 12px;
    border-left: 3px solid #8FBC8F;
    color: #5F6D63;
    font-size: 14px;
}}

.match.exact {{
    color: #1C2321;
    font-weight: 800;
}}

.match.related {{
    font-weight: 800;
    text-decoration: underline dotted #2E4031;
    text-underline-offset: 3px;
}}

.match.active-match {{
    background: #FFF3B0;
    color: #1C2321;
    outline: 3px solid #E0B400;
    border-radius: 4px;
    padding: 1px 3px;
}}

.match.related.active-match {{
    color: #1C2321;
}}
</style>
</head>

<body>

<div class="viewer-shell">

    <div class="toolbar">

        <div class="toolbar-top">

            <span class="query-label">
                Find in article:
            </span>

            <span class="query-text">
                {safe_query}
            </span>

            <div class="filter-group">

                <button
                    id="filter-all"
                    class="filter-button active"
                    onclick="setFilter('all')">
                    All ({len(viewer_matches)})
                </button>

                <button
                    id="filter-exact"
                    class="filter-button"
                    onclick="setFilter('exact')">
                    Exact ({exact_count})
                </button>

                <button
                    id="filter-related"
                    class="filter-button"
                    onclick="setFilter('related')">
                    Related ({related_count})
                </button>

            </div>

        </div>

        <div class="navigation">

            <button
                id="previous-button"
                class="nav-button"
                onclick="previousMatch()">
                ◀ Previous Match
            </button>

            <div
                id="match-counter"
                class="counter">
                0 / 0
            </div>

            <button
                id="next-button"
                class="nav-button"
                onclick="nextMatch()">
                Next Match ▶
            </button>

            <button
                id="details-button"
                class="nav-button"
                onclick="toggleDetails()">
                Details
            </button>

        </div>

        <div class="current-details">

            <div>
                <strong>Type:</strong>
                <span id="detail-type">—</span>
            </div>

            <div>
                <strong>Field:</strong>
                <span id="detail-field">—</span>
            </div>

            <div>
                <strong>Word Position:</strong>
                <span id="detail-word">—</span>
            </div>

            <div>
                <strong>Sentence Position:</strong>
                <span id="detail-sentence">—</span>
            </div>

            <div>
                <strong>Character Position:</strong>
                <span id="detail-char">—</span>
            </div>

            <div>
                <strong>Method:</strong>
                <span id="detail-method">—</span>
            </div>

            <div>
                <strong>Match score:</strong>
                <span id="detail-score">—</span>
            </div>

        </div>

    </div>

    <div
        id="article-scroll"
        class="article-scroll">

        <div class="article">
            {article_html}
        </div>

    </div>

</div>


<script>
let currentFilter = "all";
let currentIndex = 0;

function getAllMatches() {{
    return Array.from(
        document.querySelectorAll(".match")
    );
}}

function getFilteredMatches() {{
    const allMatches = getAllMatches();

    if (currentFilter === "all") {{
        return allMatches;
    }}

    return allMatches.filter(
        element =>
            element.dataset.type === currentFilter
    );
}}

function setFilter(filterName) {{
    currentFilter = filterName;
    currentIndex = 0;

    document.querySelectorAll(
        ".filter-button"
    ).forEach(
        button =>
            button.classList.remove("active")
    );

    const activeButton =
        document.getElementById(
            "filter-" + filterName
        );

    if (activeButton) {{
        activeButton.classList.add("active");
    }}

    activateCurrentMatch(true);
}}

function toggleDetails() {{
    const details =
        document.querySelector(
            ".current-details"
        );

    const button =
        document.getElementById(
            "details-button"
        );

    if (!details || !button) {{
        return;
    }}

    details.classList.toggle(
        "show"
    );

    button.textContent =
        details.classList.contains("show")
        ? "Hide Details"
        : "Details";
}}

function updateDetails(element) {{
    const fields = [
        "type",
        "field",
        "word",
        "sentence",
        "char",
        "method",
        "score"
    ];

    if (!element) {{
        fields.forEach(
            fieldName => {{
                document.getElementById(
                    "detail-" + fieldName
                ).textContent = "—";
            }}
        );
        return;
    }}

    fields.forEach(
        fieldName => {{
            document.getElementById(
                "detail-" + fieldName
            ).textContent =
                element.dataset[fieldName] || "—";
        }}
    );
}}

function scrollMatchInsideArticle(element) {{
    const container =
        document.getElementById(
            "article-scroll"
        );

    if (!container || !element) {{
        return;
    }}

    const elementRect =
        element.getBoundingClientRect();

    const containerRect =
        container.getBoundingClientRect();

    const targetTop =
        container.scrollTop
        + elementRect.top
        - containerRect.top
        - (container.clientHeight / 2)
        + (elementRect.height / 2);

    container.scrollTo(
        {{
            top: Math.max(0, targetTop),
            behavior: "smooth"
        }}
    );
}}

function activateCurrentMatch(shouldScroll) {{
    const matches = getFilteredMatches();

    getAllMatches().forEach(
        element =>
            element.classList.remove(
                "active-match"
            )
    );

    const counter =
        document.getElementById(
            "match-counter"
        );

    const previousButton =
        document.getElementById(
            "previous-button"
        );

    const nextButton =
        document.getElementById(
            "next-button"
        );

    if (matches.length === 0) {{
        currentIndex = 0;
        counter.textContent = "0 / 0";
        previousButton.disabled = true;
        nextButton.disabled = true;
        updateDetails(null);
        return;
    }}

    if (currentIndex >= matches.length) {{
        currentIndex = matches.length - 1;
    }}

    if (currentIndex < 0) {{
        currentIndex = 0;
    }}

    const current = matches[currentIndex];

    current.classList.add(
        "active-match"
    );

    counter.textContent =
        (
            (currentIndex + 1)
            + " / "
            + matches.length
        );

    previousButton.disabled =
        currentIndex === 0;

    nextButton.disabled =
        currentIndex === matches.length - 1;

    updateDetails(current);

    if (shouldScroll) {{
        scrollMatchInsideArticle(
            current
        );
    }}
}}

function previousMatch() {{
    if (currentIndex > 0) {{
        currentIndex -= 1;
        activateCurrentMatch(true);
    }}
}}

function nextMatch() {{
    const matches = getFilteredMatches();

    if (currentIndex < matches.length - 1) {{
        currentIndex += 1;
        activateCurrentMatch(true);
    }}
}}

window.addEventListener(
    "load",
    function() {{
        activateCurrentMatch(true);
    }}
);
</script>

</body>
</html>
"""


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Keyword-based Full-Text Matching")

    st.caption(
        "Educational prototype for PubMed, JATS, BioC, and Generic XML"
    )

    st.divider()

    st.markdown(
        """
**Result display**

Exact → bold  
Related → bold / dotted underline  
Current match → yellow highlight
        """
    )

    with st.expander(
        "Search methods",
        expanded=False,
    ):
        st.markdown(
            """
- Exact Word
- Lexical Variant
- Exact Phrase
- Proximity Phrase
- Exact Sentence
- Ordered Proximity Sentence
- Literal Substring
            """
        )

    st.caption(
        "Auto Search uses positional retrieval first "
        "and falls back to literal substring search only "
        "when no normal match is found."
    )

    st.divider()

    st.caption(
        "Inspired by PubMed / PMC retrieval concepts. "
        "Not a complete PMC ATM / MeSH / UMLS implementation."
    )

    st.divider()

    st.link_button(
        "Project Presentation (PDF)",
        "https://raw.githubusercontent.com/jovi0206/01-Keyword-based-full-text-matching/main/doc/Project1_Presentation.pdf",
        use_container_width=True,
    )


# ============================================================
# HEADER
# ============================================================

render_hero()


# ============================================================
# 1. LOAD DOCUMENTS
# ============================================================

render_section_header(
    "01",
    "Load Documents",
    "Upload PMID TXT/README or XML (PubMed, JATS, BioC, Generic). Input type is detected automatically.",
)

input_files = st.file_uploader(
    "Upload documents",
    type=["txt", "xml"],
    accept_multiple_files=True,
    key="unified_document_uploader",
    label_visibility="collapsed",
)

if input_files:
    st.markdown(
        f"**Selected files:** {len(input_files)}"
    )

    if SHOW_SELECTED_FILES_DETAILS:
        with st.expander(
            "View selected files",
            expanded=False,
        ):
            for uploaded_file in input_files:
                detected_type = (
                    "XML"
                    if detect_uploaded_input_type(uploaded_file) == "xml"
                    else "PMID text"
                )
                st.write(
                    f"- {uploaded_file.name} — {detected_type}"
                )


has_input = bool(input_files)

build_button = st.button(
    "Analyze & Build Index",
    type="primary",
    disabled=not has_input,
)


if build_button:
    with st.spinner(
        "Loading documents and building positional index..."
    ):
        (
            processed_documents,
            positioned_documents,
            index_data,
            errors,
        ) = build_input_documents(
            input_files=input_files,
        )

        st.session_state[
            "processed_documents"
        ] = processed_documents

        st.session_state[
            "positioned_documents"
        ] = positioned_documents

        st.session_state[
            "index_data"
        ] = index_data

        st.session_state[
            "build_errors"
        ] = errors

        st.session_state[
            "build_signature"
        ] = input_signature(
            input_files
        )

        st.session_state[
            "index_ready"
        ] = index_data is not None

        st.session_state[
            "search_result"
        ] = None

        st.session_state[
            "view_mode"
        ] = "search"

        st.session_state[
            "selected_document_id"
        ] = None


# ============================================================
# NOT READY
# ============================================================

if not st.session_state["index_ready"]:
    st.info(
        "Choose TXT or XML files, then click "
        "'Analyze & Build Index'."
    )
    st.stop()


# ============================================================
# INDEX DATA
# ============================================================

processed_documents = (
    st.session_state[
        "processed_documents"
    ]
)

positioned_documents = (
    st.session_state[
        "positioned_documents"
    ]
)

index_data = (
    st.session_state[
        "index_data"
    ]
)

current_signature = input_signature(
    input_files
)

if (
    input_files
    and st.session_state["build_signature"]
    and current_signature
    != st.session_state["build_signature"]
):
    st.warning(
        "The selected input files have changed. "
        "Click 'Analyze & Build Index' again before searching."
    )


loaded_count = len(
    processed_documents
)

skipped_count = len(
    st.session_state["build_errors"]
)

render_build_status(
    loaded_count,
    skipped_count,
)

if skipped_count:
    with st.expander(
        f"Processing Details · {skipped_count} skipped",
        expanded=False,
    ):
        st.caption(
            "Skipped files do not prevent valid documents from being indexed."
        )

        for error in st.session_state[
            "build_errors"
        ]:
            st.write(
                f"**{error['filename']}** — "
                f"{error['error']}"
            )


metric1, metric2, metric3 = st.columns(3)

with metric1:
    render_index_kpi(
        "Documents",
        f"{index_data['total_documents']:,}",
        "Successfully indexed",
        "primary",
    )

with metric2:
    render_index_kpi(
        "Indexed Words",
        f"{index_data['total_terms']:,}",
        "Searchable word positions",
    )

with metric3:
    render_index_kpi(
        "Unique Terms",
        f"{index_data['unique_terms']:,}",
        "Index vocabulary",
    )


# ============================================================
# ARTICLE VIEW MODE (legacy)
# ============================================================
# Search Results now render article text inline.  Reset any old session
# that was left in the previous separate Article View.
if st.session_state["view_mode"] == "article":
    st.session_state["view_mode"] = "search"
    st.session_state["selected_document_id"] = None

if False and st.session_state["view_mode"] == "article":

    result = st.session_state[
        "search_result"
    ]

    selected_document_id = (
        st.session_state[
            "selected_document_id"
        ]
    )

    document_lookup = (
        build_positioned_document_lookup(
            positioned_documents
        )
    )

    grouped = (
        group_results_by_document(result)
        if result
        else {}
    )

    if (
        selected_document_id
        not in document_lookup
        or selected_document_id
        not in grouped
    ):
        st.session_state[
            "view_mode"
        ] = "search"

        st.session_state[
            "selected_document_id"
        ] = None

        st.rerun()

    selected_document = (
        document_lookup[
            selected_document_id
        ]
    )

    selected_items = (
        grouped[
            selected_document_id
        ]
    )

    # --------------------------------------------------------
    # Result navigation:
    # Use the same order as Search Results.
    # First result shows only Next Result.
    # Last result shows only Previous Result.
    # --------------------------------------------------------

    ordered_document_ids = [
        document_id
        for document_id, _items
        in sort_document_results(
            grouped
        )
    ]

    current_result_index = (
        ordered_document_ids.index(
            selected_document_id
        )
    )

    previous_document_id = (
        ordered_document_ids[
            current_result_index - 1
        ]
        if current_result_index > 0
        else None
    )

    next_document_id = (
        ordered_document_ids[
            current_result_index + 1
        ]
        if current_result_index
        < len(ordered_document_ids) - 1
        else None
    )

    # --------------------------------------------------------
    # Fixed side navigation:
    # - Previous Result stays on the left.
    # - Next Result stays on the right.
    # - Search Results sits directly below Next Result.
    #
    # Because these controls are fixed, the user does not need
    # to scroll back to the top of a long article.
    # --------------------------------------------------------

    if previous_document_id is not None:
        if st.button(
            "← Prev Result",
            key="prev_result_side",
        ):
            st.session_state[
                "selected_document_id"
            ] = previous_document_id

            st.rerun()

        st.markdown(
            (
                '<div class="kfm-side-result-count-left">'
                f'Result {current_result_index + 1} '
                f'of {len(ordered_document_ids)}'
                '</div>'
            ),
            unsafe_allow_html=True,
        )

    if next_document_id is not None:
        if st.button(
            "Next Result →",
            key="next_result_side",
        ):
            st.session_state[
                "selected_document_id"
            ] = next_document_id

            st.rerun()

        st.markdown(
            (
                '<div class="kfm-side-result-count-right">'
                f'Result {current_result_index + 1} '
                f'of {len(ordered_document_ids)}'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
    else:
        # Last result: keep the result counter on the right
        # even though there is no Next Result button.
        st.markdown(
            (
                '<div class="kfm-side-result-count-right">'
                f'Result {current_result_index + 1} '
                f'of {len(ordered_document_ids)}'
                '</div>'
            ),
            unsafe_allow_html=True,
        )

    if st.button(
        "← Search Results",
        key="back_to_results_side",
        type="primary",
    ):
        st.session_state[
            "view_mode"
        ] = "search"

        st.session_state[
            "selected_document_id"
        ] = None

        st.rerun()

    st.caption(
        selected_document_id
    )

    st.subheader(
        selected_document["title"]
    )

    exact_count, related_count = (
        count_match_types(
            selected_items
        )
    )

    st.markdown(
        f"**All:** {len(selected_items)}  ·  "
        f"**Exact:** {exact_count}  ·  "
        f"**Related:** {related_count}"
    )

    # --------------------------------------------------------
    # Quick Search:
    # Run the next query directly from Article View.
    # This intentionally uses Auto mode so the live demo needs
    # only one input box and one Search button.
    # --------------------------------------------------------

    with st.form(
        "article_quick_search",
        clear_on_submit=True,
    ):
        quick_query_col, quick_button_col = st.columns(
            [6.6, 1.4]
        )

        with quick_query_col:
            quick_query = st.text_input(
                "Quick Search",
                placeholder="Search another word, phrase, or sentence...",
                label_visibility="collapsed",
            )

        with quick_button_col:
            quick_search_button = st.form_submit_button(
                "Search",
                type="primary",
                use_container_width=True,
            )

    if quick_search_button:
        if not quick_query.strip():
            st.warning(
                "Please enter a query."
            )

        else:
            with st.spinner(
                "Searching index..."
            ):
                quick_result = search_query(
                    index_data=index_data,
                    positioned_documents=positioned_documents,
                    query=quick_query,
                    query_type="auto",
                )

            st.session_state[
                "search_result"
            ] = quick_result

            st.session_state[
                "view_mode"
            ] = "search"

            st.session_state[
                "selected_document_id"
            ] = None

            st.rerun()


    viewer_html = build_article_viewer_html(
        document=selected_document,
        items=selected_items,
        query=result["query"],
    )

    components.html(
        viewer_html,
        height=900,
        scrolling=False,
    )

    st.stop()


# ============================================================
# SEARCH VIEW
# ============================================================

with st.expander(
    "Document Statistics",
    expanded=False,
):
    # --------------------------------------------------------
    # Pure HTML table instead of st.dataframe():
    #
    # 1. Avoids PyArrow DLL loading on managed Windows PCs.
    # 2. Avoids Markdown rendering <tr>/<td> as code by building
    #    the HTML without leading indentation.
    # --------------------------------------------------------

    stats_rows = document_stats_rows(
        processed_documents
    )

    table_rows = []

    for row_number, row in enumerate(stats_rows, start=1):
        table_rows.append(
            "<tr>"
            f'<td>{row_number}</td>'
            f'<td>{html.escape(str(row["PMID"] or "—"))}</td>'
            f'<td>{html.escape(str(row["File"]))}</td>'
            f'<td>{html.escape(str(row["Format"]))}</td>'
            f'<td>{html.escape(str(row["Characters With Spaces"]))}</td>'
            f'<td>{html.escape(str(row["Characters Without Spaces"]))}</td>'
            f'<td>{html.escape(str(row["Words"]))}</td>'
            f'<td>{html.escape(str(row["Sentences"]))}</td>'
            "</tr>"
        )

    stats_table_html = (
        '<div class="kfm-stats-table-wrap">'
        '<table class="kfm-stats-table">'
        '<thead><tr>'
        '<th>No.</th>'
        '<th>PMID</th>'
        '<th>XML File</th>'
        '<th>XML Format</th>'
        '<th>Characters<br>(with spaces)</th>'
        '<th>Characters<br>(without spaces)</th>'
        '<th>Words</th>'
        '<th>Sentences</th>'
        '</tr></thead>'
        '<tbody>'
        + "".join(table_rows)
        + '</tbody></table></div>'
    )

    st.markdown(
        stats_table_html,
        unsafe_allow_html=True,
    )

    st.caption(
        "Document Statistics are computed by this system. "
        "PubMed records use the Abstract as the statistics corpus; "
        "JATS uses Front (excluding permissions) + Body + Back; "
        "BioC uses all visible passage text; Generic XML uses all visible text. "
        "Words use whitespace segmentation for Document Statistics; Search indexing keeps its Regex tokenizer. Sentences use pySBD."
    )


# ============================================================
# 2. SEARCH
# ============================================================

render_section_header(
    "02",
    "Search",
    "Enter a word, phrase, or sentence. Auto mode selects the retrieval strategy.",
)

with st.form(
    "search_form",
    clear_on_submit=False,
):
    search_col, type_col, button_col = st.columns(
        [7.6, 1.7, 1.45]
    )

    with search_col:
        query = st.text_input(
            "Search query",
            placeholder="Enter a word, phrase, or sentence",
            label_visibility="collapsed",
        )

    with type_col:
        query_type_label = st.selectbox(
            "Query Type",
            [
                "Auto",
                "Word",
                "Phrase",
                "Sentence",
                "Literal Text",
            ],
            help=(
                "Auto first uses Word / Phrase / Sentence retrieval. "
                "If no positional match is found, it falls back to "
                "Literal Substring search."
            ),
            label_visibility="collapsed",
        )

    with button_col:
        search_button = st.form_submit_button(
            "Search",
            type="primary",
            use_container_width=True,
        )



query_type_map = {
    "Auto": "auto",
    "Word": "word",
    "Phrase": "phrase",
    "Sentence": "sentence",
    "Literal Text": "literal",
}


if search_button:
    if not query.strip():
        st.warning(
            "Please enter a query."
        )

    else:
        with st.spinner(
            "Searching index..."
        ):
            result = search_query(
                index_data=index_data,
                positioned_documents=positioned_documents,
                query=query,
                query_type=query_type_map[
                    query_type_label
                ],
            )

        st.session_state[
            "search_result"
        ] = result


# ============================================================
# SEARCH RESULT
# ============================================================

result = st.session_state[
    "search_result"
]

if result is None:
    st.info(
        "Enter a query to search the loaded documents."
    )
    st.stop()


render_subheading("Search Summary")

st.markdown(
    (
        '<div class="kfm-query-line">'
        '<strong>Query:</strong> '
        f'<span class="kfm-query-value">{html.escape(result["query"])}</span>'
        '</div>'
    ),
    unsafe_allow_html=True,
)

with st.expander(
    "Search Details",
    expanded=False,
):
    st.write(
        f"Query Type: "
        f"{result['query_type'].replace('_', ' ').title()}"
    )

    st.write(
        f"Retrieval Mode: "
        f"{result.get('retrieval_mode', 'positional').replace('_', ' ').title()}"
    )


summary1, summary2, summary3, summary4 = (
    st.columns(4)
)

with summary1:
    render_kpi_card(
        "Retrieved Documents",
        (
            f"{result['documents_found']} "
            f"/ {index_data['total_documents']}"
        ),
        "primary",
    )

with summary2:
    render_kpi_card(
        "Exact Matches",
        result["exact_matches"],
        "exact",
    )

with summary3:
    render_kpi_card(
        "Related Matches",
        result["related_matches"],
    )

with summary4:
    render_kpi_card(
        "Total Matches",
        result["total_matches"],
    )


# ============================================================
# AUTO LITERAL FALLBACK NOTICE
# ============================================================

if result.get("fallback_used", False):
    st.info(
        "No positional Word / Phrase / Sentence match was found. "
        "Auto Search used Literal Substring fallback, similar to "
        "browser Ctrl+F, and searched the cleaned article content."
    )

elif result.get("retrieval_mode") == "literal":
    st.info(
        "Literal Text mode is active. "
        "The query is matched as a continuous character substring "
        "inside the cleaned searchable article content."
    )


if result["total_matches"] == 0:
    st.info(
        "No matching results found."
    )
    st.stop()


# ============================================================
# DOCUMENT RESULT CARDS
# ============================================================

render_subheading("Search Results")

st.caption(
    "One card per matching document. "
    "The article text is shown directly below the match counts."
)

grouped = group_results_by_document(
    result
)

document_lookup = (
    build_positioned_document_lookup(
        positioned_documents
    )
)

processed_document_lookup = (
    build_processed_document_lookup(
        processed_documents
    )
)


for result_number, (document_id, items) in enumerate(
    sort_document_results(
        grouped
    ),
    start=1,
):
    document = document_lookup[
        document_id
    ]

    exact_count, related_count = (
        count_match_types(
            items
        )
    )

    with st.container(
        border=True
    ):
        number_col, content_col = st.columns(
            [0.42, 9.58]
        )

        with number_col:
            st.markdown(
                (
                    '<div class="kfm-result-number">'
                    f'{result_number}'
                    '</div>'
                ),
                unsafe_allow_html=True,
            )

        with content_col:
            st.subheader(
                document["title"]
            )

            source_format = document.get(
                "source_format",
                "Unknown",
            )

            display_identifier = (
                document.get("pmid")
                or document_id
            )

            identifier_label = (
                f"PMID {display_identifier}"
                if document.get("pmid")
                else str(display_identifier)
            )

            st.markdown(
                (
                    '<div class="kfm-meta-row">'
                    f'<span class="kfm-chip">{html.escape(identifier_label)}</span>'
                    f'<span class="kfm-chip format">{html.escape(str(source_format))}</span>'
                    '</div>'
                ),
                unsafe_allow_html=True,
            )

            stats_document = processed_document_lookup.get(
                document_id
            )

            render_result_metrics_grid(
                exact_count=exact_count,
                related_count=related_count,
                total_count=len(items),
                stats_document=stats_document,
            )

            inline_article_html = build_inline_result_article_html(
                document=document,
                items=items,
            )

            components.html(
                inline_article_html,
                height=estimate_inline_article_height(document),
                scrolling=True,
            )
