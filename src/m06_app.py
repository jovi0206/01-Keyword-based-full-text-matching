import html
import tempfile
from collections import defaultdict
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from m01_jats_parser import parse_jats
from m02_text_processor import process_document
from m03_position_mapper import map_document_positions
from m04_index_builder import build_index
from m05_query_engine import search_query


# ============================================================
# MODULE 06 — STREAMLIT WEB APP V2
# ============================================================
# UX:
# Upload XML → Build Index → Search Summary → Document Cards
# → Open Article → All / Exact / Related
# → Previous / Next Match → Position Details
#
# M01 ~ M05 are unchanged.
# ============================================================

st.set_page_config(
    page_title="Keyword-based Full-Text Matching",
    page_icon="🔎",
    layout="wide",
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

def uploaded_signature(uploaded_files):
    if not uploaded_files:
        return tuple()

    return tuple(
        (uploaded_file.name, uploaded_file.size)
        for uploaded_file in uploaded_files
    )


def get_document_id(document):
    return document["pmcid"] or document["filename"]


def build_positioned_document_lookup(positioned_documents):
    return {
        get_document_id(document): document
        for document in positioned_documents
    }


# ============================================================
# M01 → M04 BUILD PIPELINE
# ============================================================

def build_uploaded_documents(uploaded_files):
    processed_documents = []
    positioned_documents = []
    errors = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)

        for file_number, uploaded_file in enumerate(uploaded_files, start=1):
            try:
                safe_name = Path(uploaded_file.name).name

                file_folder = temp_root / f"{file_number:03d}"
                file_folder.mkdir(parents=True, exist_ok=True)

                xml_path = file_folder / safe_name
                xml_path.write_bytes(uploaded_file.getvalue())

                # M01
                document = parse_jats(xml_path)

                # M02
                processed = process_document(document)

                # M03
                positioned = map_document_positions(processed)

                processed_documents.append(processed)
                positioned_documents.append(positioned)

            except Exception as error:
                errors.append(
                    {
                        "filename": uploaded_file.name,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

    # M04
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
                "PMCID": document["pmcid"],
                "File": document["filename"],
                "Characters": document["character_count"],
                "Words": document["word_count"],
                "Word Source": document["word_count_source"],
                "Sentences": document["sentence_count"],
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
            '<span style="color:#d32f2f;font-weight:700;">'
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

        pieces.append(
            (
                '<span '
                f'id="match-{item["viewer_index"]}" '
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
    background: #f5f7fa;
    color: #202124;
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
    background: #17365d;
    color: white;
    padding: 14px 20px;
    border-bottom: 1px solid #102a49;
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
    color: #17365d;
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
    color: #17365d;
    font-size: 30px;
}}

.group-heading {{
    margin-top: 34px;
    margin-bottom: 15px;
    padding-bottom: 7px;
    color: #17365d;
    border-bottom: 2px solid #e5e9ef;
    font-size: 23px;
}}

.section-title {{
    color: #244d7a;
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
    background: #eef3f8;
    border-radius: 12px;
    padding: 4px 9px;
    margin: 3px 5px 3px 0;
    font-size: 13px;
}}

.figure-table-label {{
    margin-top: 16px;
    font-weight: 700;
    color: #244d7a;
}}

.table-text {{
    background: #f8f9fa;
    border: 1px solid #e3e6ea;
    border-radius: 6px;
    padding: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    margin: 10px 0;
}}

.reference {{
    padding-left: 12px;
    border-left: 3px solid #e0e4e8;
    color: #3c4043;
    font-size: 14px;
}}

.match.exact {{
    color: #c62828;
    font-weight: 800;
}}

.match.related {{
    font-weight: 800;
    text-decoration: underline dotted #555;
    text-underline-offset: 3px;
}}

.match.active-match {{
    background: #fff59d;
    color: #b71c1c;
    outline: 3px solid #ffca28;
    border-radius: 2px;
    padding: 1px 2px;
}}

.match.related.active-match {{
    color: #202124;
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
                ◀ Previous
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
                Next ▶
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
        "Educational prototype for PMC JATS XML"
    )

    st.divider()

    st.markdown(
        """
**Result display**

Exact → red  
Related → bold  
Current match → yellow
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


# ============================================================
# HEADER
# ============================================================

st.title(
    "Keyword-based Full-Text Matching"
)

st.caption(
    "Upload JATS XML → Build Index → Search → Open Article → Locate Match"
)


# ============================================================
# 1. UPLOAD
# ============================================================

st.header("1. Load Documents")

uploaded_files = st.file_uploader(
    "Upload one or more PMC JATS XML files",
    type=["xml"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.write(
        f"**Selected files:** {len(uploaded_files)}"
    )

    with st.expander(
        "View selected files",
        expanded=False,
    ):
        for uploaded_file in uploaded_files:
            st.write(
                f"- {uploaded_file.name}"
            )


build_button = st.button(
    "Analyze / Build Index",
    type="primary",
    disabled=not uploaded_files,
)


if build_button:
    with st.spinner(
        "Parsing XML and building positional index..."
    ):
        (
            processed_documents,
            positioned_documents,
            index_data,
            errors,
        ) = build_uploaded_documents(
            uploaded_files
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
        ] = uploaded_signature(
            uploaded_files
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
# BUILD ERRORS
# ============================================================

if st.session_state["build_errors"]:
    st.warning(
        "Some XML files could not be processed."
    )

    for error in st.session_state[
        "build_errors"
    ]:
        st.error(
            f"{error['filename']} — "
            f"{error['error']}"
        )


# ============================================================
# NOT READY
# ============================================================

if not st.session_state["index_ready"]:
    st.info(
        "Upload JATS XML files and click "
        "'Analyze / Build Index' to begin."
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

current_signature = uploaded_signature(
    uploaded_files
)

if (
    uploaded_files
    and st.session_state["build_signature"]
    and current_signature
    != st.session_state["build_signature"]
):
    st.warning(
        "The uploaded file selection has changed. "
        "Click 'Analyze / Build Index' again before searching."
    )


st.success(
    f"Index Ready — "
    f"{len(processed_documents)} documents loaded"
)


metric1, metric2, metric3 = st.columns(3)

metric1.metric(
    "Documents",
    index_data["total_documents"],
)

metric2.metric(
    "Indexed Words",
    index_data["total_terms"],
)

metric3.metric(
    "Unique Terms",
    index_data["unique_terms"],
)


# ============================================================
# ARTICLE VIEW MODE
# ============================================================

if st.session_state["view_mode"] == "article":

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

    if st.button(
        "← Back to Search Results"
    ):
        st.session_state[
            "view_mode"
        ] = "search"

        st.session_state[
            "selected_document_id"
        ] = None

        st.rerun()

    # Floating return button:
    # always available even when the user is deep inside the article.
    st.markdown(
        """
        <style>
        .st-key-floating_back_to_search {
            position: fixed;
            right: 28px;
            bottom: 28px;
            z-index: 9999;
        }

        .st-key-floating_back_to_search button {
            border-radius: 999px;
            padding: 0.65rem 1.1rem;
            font-weight: 700;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "← Search Results",
        key="floating_back_to_search",
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

    st.caption(
        "Use Previous / Next to move through matches. "
        "Current match = yellow."
    )

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
    st.dataframe(
        document_stats_rows(
            processed_documents
        ),
        width="stretch",
        hide_index=True,
    )

    st.caption(
        "Word Count Strategy: use the JATS-reported "
        "word-count when available; otherwise use the "
        "tokenizer-based computed count. "
        "References remain searchable but are excluded "
        "from article statistics."
    )


# ============================================================
# 3. SEARCH
# ============================================================

st.header("2. Search")

with st.form(
    "search_form",
    clear_on_submit=False,
):
    query = st.text_area(
        "Enter a word, phrase, or sentence",
        placeholder=(
            "Examples:\n"
            "cancer\n"
            "physical activity\n"
            "This study reviews the evidence "
            "to clarify association.\n"
            "eurol Sc  (Literal / Ctrl+F style)"
        ),
        height=90,
    )

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
            "Auto 會先使用一般 Word / Phrase / Sentence 檢索；"
            "若完全找不到，再自動使用 Literal Substring。 "
            "Literal Text 則直接使用類似瀏覽器 Ctrl+F 的連續字元搜尋。"
        ),
    )

    search_button = (
        st.form_submit_button(
            "Search",
            type="primary",
        )
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


st.subheader("Search Summary")

st.markdown(
    f"**Query:** {html.escape(result['query'])}"
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

summary1.metric(
    "Documents with Matches",
    (
        f"{result['documents_found']} "
        f"/ {index_data['total_documents']}"
    ),
)

summary2.metric(
    "Exact Occurrences",
    result["exact_matches"],
)

summary3.metric(
    "Related Occurrences",
    result["related_matches"],
)

summary4.metric(
    "Total Occurrences",
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

st.subheader("Search Results")

st.caption(
    "One card per matching document. "
    "Open an article to jump through every match."
)

grouped = group_results_by_document(
    result
)

document_lookup = (
    build_positioned_document_lookup(
        positioned_documents
    )
)


for document_id, items in sort_document_results(
    grouped
):
    document = document_lookup[
        document_id
    ]

    exact_count, related_count = (
        count_match_types(
            items
        )
    )

    snippet_item = choose_document_snippet(
        items
    )

    with st.container(
        border=True
    ):
        st.subheader(
            document["title"]
        )

        st.caption(
            document_id
        )

        st.markdown(
            f"**Exact:** {exact_count}  ·  "
            f"**Related:** {related_count}  ·  "
            f"**Total:** {len(items)}"
        )

        if snippet_item:
            snippet_html = highlight_snippet(
                context=snippet_item["context"],
                matched_text=snippet_item[
                    "matched_text"
                ],
                match_type=snippet_item[
                    "match_type"
                ],
            )

            st.markdown(
                (
                    '<div style="'
                    'line-height:1.65;'
                    'font-size:1rem;'
                    'margin:4px 0 10px 0;'
                    '">'
                    f"{snippet_html}"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

        if st.button(
            "Open Article",
            key=(
                "open_article_"
                + document_id
            ),
            type="primary",
        ):
            st.session_state[
                "selected_document_id"
            ] = document_id

            st.session_state[
                "view_mode"
            ] = "article"

            st.rerun()
