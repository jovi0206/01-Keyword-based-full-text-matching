from pathlib import Path
from functools import lru_cache
import re
import pysbd

from m01_jats_parser import parse_jats


# ============================================================
# MODULE 2 — TEXT PROCESSOR
# ============================================================
#
# Input:
#     Module 1 產生的 Structured Document
#
# Process:
#     1. Character Count
#     2. Word Tokenization / Word Count
#     3. Sentence Segmentation / Sentence Count
#
# Sentence Segmentation:
#     使用公開演算法 pySBD
#
# Output:
#     processed_document
#
# 下一個 Module 3 將使用：
#     words
#     sentences
#     search_segments
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


# ============================================================
# 1. pySBD Sentence Segmenter
# ============================================================

SENTENCE_SEGMENTER = pysbd.Segmenter(
    language="en",
    clean=False
)


# ============================================================
# 2. 基本文字整理
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = " ".join(
        text.split()
    )

    # 標點前不要有多餘空白
    text = re.sub(
        r"\s+([,.;:!?%)\]])",
        r"\1",
        text
    )

    # 左括號後不要有多餘空白
    text = re.sub(
        r"([(\[])\s+",
        r"\1",
        text
    )

    return text


# ============================================================
# 3. 統計文字清理
# ============================================================
#
# Parser 移除 citation <xref> 後，
# 有時會留下：
#
# ,,,,,
#
# 這裡整理成單一逗號。
# ============================================================

def normalize_stats_text(text):

    text = normalize_text(text)

    if not text:
        return ""

    # ,,,,, → ,
    text = re.sub(
        r"(?:\s*,\s*){2,}",
        ", ",
        text
    )

    # ;;;; → ;
    text = re.sub(
        r"(?:\s*;\s*){2,}",
        "; ",
        text
    )

    # 空括號
    text = re.sub(
        r"\(\s*[,;:\-–—]*\s*\)",
        "",
        text
    )

    text = re.sub(
        r"\[\s*[,;:\-–—]*\s*\]",
        "",
        text
    )

    return normalize_text(text)



# ============================================================
# 4. DOCUMENT STATISTICS CORPUS NORMALIZATION
# ============================================================
#
# Statistics Corpus 與 Search Corpus 的「範圍」與「分詞目的」不同。
#
# Statistics Corpus:
#     用於 Characters / Words / Sentences
#     Words 採 whitespace segmentation（text.split()）。
#     目的：提供簡單、可重現、接近一般文書軟體的 word count。
#
# Search Corpus:
#     用於 Position Mapping / Inverted Index / Search
#     仍使用 WORD_PATTERN Regex tokenizer。
#     目的：保留搜尋所需的 token 邊界與位置。
#
# 因此 Document Statistics 的 Words 與 Indexed Words
# 不要求完全相同；兩者用途不同。
# ============================================================

def normalize_statistics_corpus(text):

    if not text:
        return ""

    return " ".join(
        text.split()
    )


def tokenize_statistics_words(text):
    """Tokenize Document Statistics by whitespace boundaries.

    Important:
        This function is intentionally independent from the Search
        Regex tokenizer.  It preserves intra-token punctuation such as
        hyphens and slashes as long as there is no whitespace boundary.

    Examples:
        cancer-dementia -> 1 word
        all-cause       -> 1 word
        non-melanoma    -> 1 word
        16%/9%          -> 1 word
    """

    text = normalize_statistics_corpus(
        text
    )

    if not text:
        return []

    return text.split()


# ============================================================
# 4. WORD TOKENIZATION
# ============================================================
#
# 例如：
#
# Alzheimer's
# 24-hour
# cancer-related
# PI3K/Akt
# NF-κB
# 9.6
# 1,753
# 30%
#
# tokenize_words()
# = 定義我們系統認為「什麼是一個 Word」
# ============================================================

WORD_PATTERN = re.compile(

    # Numeric token, including scientific ranges such as:
    # 2‒3% / 3–5 / 1,000–2,000
    r"\d+(?:[.,]\d+)*(?:[‐‑‒–—-]\d+(?:[.,]\d+)*)?(?:%|[A-Za-z]+)?"

    r"|"

    r"[^\W_]+"
    r"(?:[.'’/‐‑‒–—-][^\W_]+)*"
    r"%?",

    re.UNICODE
)


def tokenize_words(text):

    text = normalize_text(text)

    if not text:
        return []

    return WORD_PATTERN.findall(
        text
    )


# ============================================================
# 5. SENTENCE SEGMENTATION
# ============================================================
#
# 不再自己用 Regex 判斷 EOS。
#
# 直接使用：
#
# pySBD
#
# 它會處理：
#
# e.g.
# i.e.
# Dr.
# et al.
# 9.6
# U.S.
# 等常見特殊情況。
# ============================================================

@lru_cache(maxsize=4096)
def _segment_sentences_cached(normalized_text):
    """
    Cache pySBD results for identical normalized text.

    The same paragraph/caption/reference can be used by both
    Document Statistics support structures and Search Segments.
    Caching prevents pySBD from parsing the same text twice.
    """

    raw_sentences = SENTENCE_SEGMENTER.segment(
        normalized_text
    )

    return tuple(
        normalize_text(sentence)
        for sentence in raw_sentences
        if normalize_text(sentence)
    )


def segment_sentences(text):

    text = normalize_text(text)

    if not text:
        return []

    # Return a new list so callers cannot mutate the cached tuple.
    return list(
        _segment_sentences_cached(text)
    )


# ============================================================
# 6. 分析單一 Segment
# ============================================================

def analyze_segment(
    field,
    text,
    count_sentence=True
):

    text = normalize_stats_text(
        text
    )

    words = tokenize_words(
        text
    )

    # Only run pySBD when this segment actually contributes
    # to sentence statistics. Section titles/table cells that are
    # not counted as sentences skip the expensive segmentation step.
    sentences = (
        segment_sentences(text)
        if count_sentence
        else []
    )

    return {

        "field":
            field,

        "text":
            text,

        "character_count":
            len(text),

        "character_count_without_spaces":
            len(
                re.sub(
                    r"\s+",
                    "",
                    text
                )
            ),

        "word_count":
            len(words),

        "sentence_count":
            (
                len(sentences)
                if count_sentence
                else 0
            ),

        "words":
            words,

        "sentences":
            sentences
    }


# ============================================================
# 7. 建立 STATS Segments
# ============================================================
#
# Character / Word：
#     計算主要文章內容
#
# Sentence：
#     只計算真正的敘述文字
#
# Section Title / Definition / Table Cell
# 不直接當成完整 Sentence。
# ============================================================

def build_stats_segments(document):

    segments = []

    def add(
        field,
        text,
        count_sentence=True
    ):

        text = normalize_stats_text(
            text
        )

        if text:

            segments.append(
                {
                    "field":
                        field,

                    "text":
                        text,

                    "count_sentence":
                        count_sentence
                }
            )

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    add(
        "title",
        document["title"],
        False
    )

    # --------------------------------------------------------
    # Abstract
    # --------------------------------------------------------

    for title in document[
        "abstract_section_titles"
    ]:

        add(
            "abstract_section_title",
            title,
            False
        )

    for paragraph in document[
        "abstract_paragraphs_clean"
    ]:

        add(
            "abstract",
            paragraph,
            True
        )

    # --------------------------------------------------------
    # Definitions / Abbreviations
    # --------------------------------------------------------

    for item in document[
        "definitions"
    ]:

        add(
            "definition",
            (
                f"{item['term']} "
                f"{item['definition']}"
            ),
            False
        )

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    for title in document[
        "section_titles"
    ]:

        add(
            "section_title",
            title,
            False
        )

    for paragraph in document[
        "body_paragraphs_clean"
    ]:

        add(
            "body",
            paragraph,
            True
        )

    # --------------------------------------------------------
    # Figures
    # --------------------------------------------------------

    for figure in document[
        "figures"
    ]:

        add(
            "figure_caption",
            figure["caption"],
            True
        )

    # --------------------------------------------------------
    # Tables
    # --------------------------------------------------------

    for table in document[
        "tables"
    ]:

        add(
            "table_caption",
            table["caption"],
            True
        )

        add(
            "table_text",
            table["text"],
            False
        )

    # --------------------------------------------------------
    # Acknowledgments
    # --------------------------------------------------------

    for acknowledgment in document[
        "acknowledgments"
    ]:

        add(
            "acknowledgment",
            acknowledgment,
            True
        )

    return segments


# ============================================================
# 8. PUBMED SENTENCE / EOS HELPERS
# ============================================================
#
# pySBD remains the primary Sentence Boundary Disambiguation engine.
# PubMed structured abstracts add one extra semantic layer:
# some AbstractText nodes are identifiers (for example a trial
# registration number) rather than prose sentences.  Those nodes stay
# searchable and remain in word/character statistics, but they do not
# contribute to the prose Sentence Count.
#
# We also segment each AbstractText section independently.  This keeps
# EOS decisions from leaking across structured-abstract section borders.
# ============================================================

PUBMED_NON_PROSE_LABEL_MARKERS = (
    "trial registration",
    "registration number",
    "clinical trial registration",
    "trial registration number",
    "registry number",
    "prospero",
)


def is_pubmed_sentence_section(section):
    label = (
        section.get("label", "")
        or section.get("raw_label", "")
        or section.get("nlm_category", "")
        or ""
    ).casefold()

    return not any(
        marker in label
        for marker in PUBMED_NON_PROSE_LABEL_MARKERS
    )


def get_pubmed_abstract_sections(document):
    sections = document.get(
        "abstract_sections",
        []
    )

    if sections:
        return sections

    # Compatibility fallback for PubMed documents created by an older M01.
    return [
        {
            "label": "",
            "raw_label": "",
            "nlm_category": "",
            "text": paragraph,
        }
        for paragraph in document.get(
            "abstract_paragraphs_clean",
            []
        )
        if paragraph
    ]


def segment_pubmed_abstract_sentences(document):
    sentences = []

    for section in get_pubmed_abstract_sections(
        document
    ):
        if not is_pubmed_sentence_section(
            section
        ):
            continue

        text = section.get(
            "text",
            ""
        )

        sentences.extend(
            segment_sentences(
                text
            )
        )

    return sentences


# ============================================================
# 8. 建立 SEARCH Segments
# ============================================================
#
# 未來老師輸入：
#
# Word
# Phrase
# Sentence
#
# 都從這些 Segment 搜尋。
#
# 每個 Segment 保留 field，
# Module 3 才知道命中位置屬於：
#
# title
# abstract
# body
# table
# reference
# ...
# ============================================================

def build_search_segments(document):

    segments = []

    segment_id = 0

    def add(
        field,
        text,
        label="",
        nlm_category="",
        count_sentence=True,
    ):

        nonlocal segment_id

        text = normalize_stats_text(
            text
        )

        if not text:
            return

        words = tokenize_words(
            text
        )

        sentences = (
            segment_sentences(
                text
            )
            if count_sentence
            else []
        )

        segments.append(
            {
                "segment_id":
                    segment_id,

                "field":
                    field,

                "label":
                    label,

                "nlm_category":
                    nlm_category,

                "sentence_countable":
                    count_sentence,

                "text":
                    text,

                "words":
                    words,

                "sentences":
                    sentences
            }
        )

        segment_id += 1

    # --------------------------------------------------------
    # PubMed professor-demo mode
    # --------------------------------------------------------
    # For PubMed citation records fetched by PMID, the requested
    # searchable text scope is the visible Abstract block only.
    # Metadata (Title / Authors / Journal / DOI / PMID) remains
    # available for display, but is not mixed into Search Corpus.
    # --------------------------------------------------------

    if document.get("source_format") == "PubMed":

        for section in get_pubmed_abstract_sections(
            document
        ):
            add(
                "abstract",
                section.get("text", ""),
                label=section.get("label", ""),
                nlm_category=section.get("nlm_category", ""),
                count_sentence=is_pubmed_sentence_section(
                    section
                ),
            )

        return segments

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    add(
        "title",
        document["title"]
    )

    for author in document[
        "authors"
    ]:

        add(
            "author",
            author
        )

    for affiliation in document[
        "affiliations"
    ]:

        add(
            "affiliation",
            affiliation
        )

    for keyword in document[
        "keywords"
    ]:

        add(
            "keyword",
            keyword
        )

    # --------------------------------------------------------
    # Abstract
    # --------------------------------------------------------

    for title in document[
        "abstract_section_titles"
    ]:

        add(
            "abstract_section_title",
            title
        )

    for paragraph in document[
        "abstract_paragraphs_clean"
    ]:

        add(
            "abstract",
            paragraph
        )

    # --------------------------------------------------------
    # Definitions
    # --------------------------------------------------------

    for item in document[
        "definitions"
    ]:

        add(
            "definition",
            (
                f"{item['term']} "
                f"{item['definition']}"
            )
        )

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    for title in document[
        "section_titles"
    ]:

        add(
            "section_title",
            title
        )

    for paragraph in document[
        "body_paragraphs_clean"
    ]:

        add(
            "body",
            paragraph
        )

    # --------------------------------------------------------
    # Figures
    # --------------------------------------------------------

    for figure in document[
        "figures"
    ]:

        add(
            "figure_label",
            figure["label"]
        )

        add(
            "figure_caption",
            figure["caption"]
        )

    # --------------------------------------------------------
    # Tables
    # --------------------------------------------------------

    for table in document[
        "tables"
    ]:

        add(
            "table_label",
            table["label"]
        )

        add(
            "table_caption",
            table["caption"]
        )

        add(
            "table_text",
            table["text"]
        )

    # --------------------------------------------------------
    # Acknowledgments
    # --------------------------------------------------------

    for acknowledgment in document[
        "acknowledgments"
    ]:

        add(
            "acknowledgment",
            acknowledgment
        )

    # --------------------------------------------------------
    # References
    # --------------------------------------------------------

    for reference in document[
        "references"
    ]:

        add(
            "reference",
            reference
        )

    return segments


# ============================================================
# 9. 核心：Process Entire Document
# ============================================================

def process_document(document):

    # --------------------------------------------------------
    # Legacy / Structured Stats Segments
    # --------------------------------------------------------
    #
    # 保留這組輸出，方便除錯與向下相容。
    #
    # 但最終 Document Statistics 不再用它當主要來源；
    # 會優先使用 M01 提供的 statistics_text。
    # --------------------------------------------------------

    raw_stats_segments = build_stats_segments(
        document
    )

    processed_stats_segments = []

    fallback_stats_text_parts = []

    for segment in raw_stats_segments:

        result = analyze_segment(
            segment["field"],
            segment["text"],
            segment["count_sentence"]
        )

        processed_stats_segments.append(
            result
        )

        fallback_stats_text_parts.append(
            result["text"]
        )

    fallback_stats_text = "\n".join(
        fallback_stats_text_parts
    )

    # --------------------------------------------------------
    # Document Statistics Corpus
    # --------------------------------------------------------
    #
    # M01 新版會提供 statistics_text：
    #
    # JATS:
    #     Front (excluding permissions)
    #     + Body
    #     + Back
    #
    # BioC:
    #     所有 passage 可見文字
    #
    # Generic XML:
    #     所有可見文字
    #
    # 若遇到舊版 M01，才 fallback 到舊 stats segments。
    # --------------------------------------------------------

    statistics_text = normalize_statistics_corpus(
        document.get(
            "statistics_text",
            ""
        )
    )

    if not statistics_text:

        statistics_text = (
            normalize_statistics_corpus(
                fallback_stats_text
            )
        )

    statistics_words = tokenize_statistics_words(
        statistics_text
    )

    if document.get("source_format") == "PubMed":
        statistics_sentences = segment_pubmed_abstract_sentences(
            document
        )
    else:
        statistics_sentences = segment_sentences(
            statistics_text
        )

    # --------------------------------------------------------
    # Search Segments
    # --------------------------------------------------------
    #
    # 搜尋仍沿用原本 structured fields + Regex tokenizer。
    # segment_sentences() 具有 LRU cache；若某段文字先前已由
    # Statistics support structures 切句，這裡直接重用結果，
    # 不會再次執行 pySBD。
    #
    # 因此本次統計優化不改變：
    #     M03 Position Mapping
    #     M04 Positional Index
    #     M05 Query Engine
    # --------------------------------------------------------

    search_segments = build_search_segments(
        document
    )

    search_text = "\n".join(
        segment["text"]
        for segment in search_segments
    )

    # --------------------------------------------------------
    # Word Count
    # --------------------------------------------------------
    #
    # Computed Words:
    #     本系統依 statistics_text
    #     使用 whitespace segmentation（text.split()）計算。
    #
    # Search Corpus 仍使用 Regex tokenizer；兩者用途分開。
    #
    # Reported Words:
    #     JATS XML <word-count> 提供的來源數字。
    #
    # 兩者分開保留，不再用 Reported 覆蓋 Computed。
    # --------------------------------------------------------

    computed_word_count = len(
        statistics_words
    )

    reported_word_count = document.get(
        "reported_word_count"
    )

    if isinstance(
        reported_word_count,
        int
    ):

        word_count_difference = (
            computed_word_count
            - reported_word_count
        )

    else:

        word_count_difference = None

    # ========================================================
    # 固定 Module 2 Output
    # ========================================================

    processed_document = {

        "filename":
            document["filename"],

        # 保留 M01 判定的 XML 格式，供後續模組與 UI 顯示。
        "source_format":
            document.get(
                "source_format",
                "Unknown"
            ),

        "pmcid":
            document.get("pmcid", ""),

        "pmid":
            document.get("pmid", ""),

        "doi":
            document.get("doi", ""),

        "journal":
            document.get("journal", ""),

        "authors":
            document.get("authors", []),

        "affiliations":
            document.get("affiliations", []),

        "keywords":
            document.get("keywords", []),

        "article_type":
            document.get("article_type", ""),

        "title":
            document["title"],

        "abstract":
            document.get("abstract", ""),

        "abstract_sections":
            document.get("abstract_sections", []),

        # ---------------------------------------------
        # Document Statistics
        # ---------------------------------------------

        "character_count":
            len(
                statistics_text
            ),

        "character_count_without_spaces":
            len(
                re.sub(
                    r"\s+",
                    "",
                    statistics_text
                )
            ),

        # word_count 現在就是「本系統實際計算值」。
        "word_count":
            computed_word_count,

        "word_count_source":
            "Computed",

        "computed_word_count":
            computed_word_count,

        "sentence_count":
            len(
                statistics_sentences
            ),

        "statistics_text":
            statistics_text,

        "statistics_scope":
            document.get(
                "statistics_scope",
                "Structured article content"
            ),

        "statistics_word_method":
            "Whitespace segmentation",

        "statistics_sentence_method":
            (
                "pySBD + PubMed section-aware EOS filtering"
                if document.get("source_format") == "PubMed"
                else "pySBD sentence segmentation"
            ),

        # ---------------------------------------------
        # Token / Sentence Lists
        # ---------------------------------------------
        #
        # 這裡代表 Document Statistics corpus。
        # Search / Position 仍使用 search_segments。
        # ---------------------------------------------

        "words":
            statistics_words,

        "sentences":
            statistics_sentences,

        # ---------------------------------------------
        # Structured Segments
        # ---------------------------------------------

        "stats_segments":
            processed_stats_segments,

        "search_segments":
            search_segments,

        # ---------------------------------------------
        # Search Corpus
        # ---------------------------------------------

        "search_text":
            search_text,

        # ---------------------------------------------
        # Validation / Comparison
        # ---------------------------------------------

        "jats_reported_word_count":
            reported_word_count,

        "word_count_difference":
            word_count_difference
    }

    return processed_document


# ============================================================
# 10. SENTENCE BOUNDARY DIAGNOSTICS
# ============================================================
#
# These examples are intentionally kept as diagnostics rather than
# hard-coded replacement rules.  pySBD remains the sentence boundary
# algorithm; this helper lets us demonstrate how ambiguous periods are
# segmented in class (abbreviation, initial, decimal, unit, etc.).
# ============================================================

SENTENCE_BOUNDARY_DIAGNOSTIC_CASES = [
    {
        "name": "title_abbreviation",
        "text": "Dr. Smith treated the patient. The patient recovered.",
        "expected_sentences": 2,
    },
    {
        "name": "name_initial",
        "text": "My name is Jonas E. Smith. He works here.",
        "expected_sentences": 2,
    },
    {
        "name": "decimal",
        "text": "The value was 9.6. Measurements were repeated.",
        "expected_sentences": 2,
    },
    {
        "name": "temperature_unit",
        "text": "The temperature was 37 °C. The patient was stable.",
        "expected_sentences": 2,
    },
    {
        "name": "country_abbreviation",
        "text": "The study was conducted in the U.S. Results were consistent.",
        "expected_sentences": 2,
    },
]


def sentence_boundary_diagnostics():
    results = []

    for case in SENTENCE_BOUNDARY_DIAGNOSTIC_CASES:
        sentences = segment_sentences(
            case["text"]
        )

        results.append(
            {
                **case,
                "actual_sentences": len(sentences),
                "pass": len(sentences) == case["expected_sentences"],
                "sentences": sentences,
            }
        )

    return results


# ============================================================
# 10. TEST
# ============================================================

if __name__ == "__main__":

    xml_files = sorted(
        DATA_DIR.glob(
            "*.xml"
        )
    )

    print("=" * 90)

    print(
        "MODULE 2 - TEXT PROCESSOR FINAL TEST"
    )

    print(
        f"Found {len(xml_files)} XML files"
    )

    print("=" * 90)

    for xml_file in xml_files:

        try:

            # Module 1
            document = parse_jats(
                xml_file
            )

            # Module 2
            processed = process_document(
                document
            )

            print()

            print(
                f"File  : "
                f"{processed['filename']}"
            )

            print(
                f"PMCID : "
                f"{processed['pmcid']}"
            )

            print("-" * 90)

            print(
                f"Character Count          : "
                f"{processed['character_count']}"
            )

            print(
                f"Character Count(no space): "
                f"{processed['character_count_without_spaces']}"
            )

            print(
                f"Word Count               : "
                f"{processed['word_count']}"
                f"({processed['word_count_source']})"
            )

            print(
                f"Our Computed Word Count  : "
                f"{processed['computed_word_count']}"
            )

            print(
                f"Sentence Count           : "
                f"{processed['sentence_count']}"
            )

            print(
                f"Statistics Scope         : "
                f"{processed['statistics_scope']}"
            )

            print(
                f"Word Method              : "
                f"{processed['statistics_word_method']}"
            )

            print(
                f"Sentence Method          : "
                f"{processed['statistics_sentence_method']}"
            )

            print()

            print(
                f"JATS Reported Word Count : "
                f"{processed['jats_reported_word_count']}"
            )

            print(
                f"Difference               : "
                f"{processed['word_count_difference']}"
            )

            print()

            print(
                f"Search Segments          : "
                f"{len(processed['search_segments'])}"
            )

            print(
                f"Search Corpus Characters : "
                f"{len(processed['search_text'])}"
            )

            print()

            print(
                "FIRST 3 SENTENCES"
            )

            for number, sentence in enumerate(

                processed[
                    "sentences"
                ][:3],

                start=1
            ):

                print(
                    f"{number}. {sentence}"
                )

            print()

            print("=" * 90)

        except Exception as error:

            print()

            print(
                f"ERROR: "
                f"{xml_file.name}"
            )

            print(
                f"{type(error).__name__}: "
                f"{error}"
            )

            print("=" * 90)