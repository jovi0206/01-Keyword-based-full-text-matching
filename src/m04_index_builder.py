from pathlib import Path
from collections import defaultdict

from m01_jats_parser import parse_jats
from m02_text_processor import process_document
from m03_position_mapper import map_document_positions


# ============================================================
# MODULE 04 — POSITIONAL INVERTED INDEX BUILDER
# ============================================================
#
# Input:
#     Module 3 的 positioned_document
#
# Process:
#     把：
#
#         Document → Word → Position
#
#     反轉成：
#
#         Word → Document → Positions
#
# Output:
#     positional_index
#
# Module 5 Query Engine
# 會直接查這個 Index。
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


# ============================================================
# 1. TERM NORMALIZATION
# ============================================================
#
# 搜尋時大小寫不敏感：
#
# Dementia
# dementia
# DEMENTIA
#
# 都視為同一個 term。
# ============================================================

def normalize_term(term):

    if not term:
        return ""

    return term.casefold()


# ============================================================
# 2. DOCUMENT ID
# ============================================================
#
# JATS / BioC commonly have PMCID.
# PubMed README mode always has PMID, but may not have PMCID.
# Generic XML falls back to filename.
# ============================================================

def resolve_document_id(document):
    return (
        document.get("pmcid")
        or document.get("pmid")
        or document["filename"]
    )


# ============================================================
# 2. FIND SENTENCE INDEX
# ============================================================
#
# Module 3 已經有：
#
# Word Character Position
# Sentence Character Position
#
# 這裡把 Word 配對到它所在的 Sentence。
#
# 之後老師搜尋某個字，
# 我們就可以直接知道：
#
# Word
# ↓
# 哪一句
# ↓
# 顯示 Context / Highlight
# ============================================================

def find_sentence_index(
    word_position,
    sentence_positions
):

    word_start = word_position[
        "global_char_start"
    ]

    for sentence in sentence_positions:

        if (
            sentence["global_char_start"]
            <= word_start
            < sentence["global_char_end"]
        ):

            return sentence[
                "global_sentence_index"
            ]

    return None


# ============================================================
# 3. BUILD INDEX
# ============================================================

def build_index(
    positioned_documents
):

    # --------------------------------------------------------
    # 暫存 Index
    # --------------------------------------------------------

    raw_index = defaultdict(
        lambda: defaultdict(list)
    )

    documents = {}

    total_indexed_words = 0

    # --------------------------------------------------------
    # 每一篇 Document
    # --------------------------------------------------------

    for document in positioned_documents:

        document_id = resolve_document_id(
            document
        )

        # ----------------------------------------------------
        # Document Metadata
        # ----------------------------------------------------

        documents[document_id] = {

            "filename":
                document["filename"],

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

            "title":
                document["title"],

            "total_search_characters":
                document[
                    "total_search_characters"
                ],

            "total_search_words":
                document[
                    "total_search_words"
                ],

            "total_search_sentences":
                document[
                    "total_search_sentences"
                ]
        }

        # ----------------------------------------------------
        # 每一個 Segment
        # ----------------------------------------------------

        for segment in document[
            "segments"
        ]:

            sentence_positions = segment[
                "sentences"
            ]

            # ------------------------------------------------
            # 每一個 Word
            # ------------------------------------------------

            for word in segment["words"]:

                original_word = word["text"]

                term = normalize_term(
                    original_word
                )

                if not term:
                    continue

                sentence_index = (
                    find_sentence_index(
                        word,
                        sentence_positions
                    )
                )

                posting = {

                    "document_id":
                        document_id,

                    "segment_id":
                        segment["segment_id"],

                    "field":
                        segment["field"],

                    "text":
                        original_word,

                    # ----------------------------------------
                    # Word Position
                    # ----------------------------------------

                    "word_index":
                        word["word_index"],

                    "global_word_index":
                        word[
                            "global_word_index"
                        ],

                    # ----------------------------------------
                    # Character Position
                    # ----------------------------------------

                    "char_start":
                        word["char_start"],

                    "char_end":
                        word["char_end"],

                    "global_char_start":
                        word[
                            "global_char_start"
                        ],

                    "global_char_end":
                        word[
                            "global_char_end"
                        ],

                    # ----------------------------------------
                    # Sentence Position
                    # ----------------------------------------

                    "sentence_index":
                        sentence_index
                }

                raw_index[
                    term
                ][
                    document_id
                ].append(
                    posting
                )

                total_indexed_words += 1

    # ========================================================
    # 4. 轉成一般 dict
    # ========================================================

    positional_index = {}

    for term, document_postings in raw_index.items():

        postings = {}

        total_frequency = 0

        for (
            document_id,
            positions
        ) in document_postings.items():

            postings[
                document_id
            ] = positions

            total_frequency += len(
                positions
            )

        positional_index[
            term
        ] = {

            # 有幾篇文章包含這個字
            "document_frequency":
                len(postings),

            # 所有文章總共出現幾次
            "total_frequency":
                total_frequency,

            # 詳細位置
            "postings":
                postings
        }

    # ========================================================
    # Module 4 Output
    # ========================================================

    index_data = {

        "documents":
            documents,

        "index":
            positional_index,

        "total_documents":
            len(documents),

        "total_terms":
            total_indexed_words,

        "unique_terms":
            len(positional_index)
    }

    return index_data


# ============================================================
# 5. LOOKUP TERM
# ============================================================
#
# 這還不是正式的 Query Engine。
#
# 只是 Module 4 測試用。
#
# Module 5 之後會正式負責：
#
# Word Search
# Phrase Search
# Sentence Search
# ============================================================

def lookup_term(
    index_data,
    query
):

    term = normalize_term(
        query
    )

    return index_data[
        "index"
    ].get(
        term
    )


# ============================================================
# 6. VALIDATE INDEX
# ============================================================
#
# 驗證：
#
# Module 3 所有 Search Words
#
#     ==
#
# Module 4 所有 Indexed Terms
# ============================================================

def validate_index(
    positioned_documents,
    index_data
):

    expected_words = sum(

        document[
            "total_search_words"
        ]

        for document
        in positioned_documents
    )

    actual_words = index_data[
        "total_terms"
    ]

    return (
        expected_words
        == actual_words,
        expected_words,
        actual_words
    )


# ============================================================
# 7. TEST
# ============================================================

if __name__ == "__main__":

    xml_files = sorted(
        DATA_DIR.glob(
            "*.xml"
        )
    )

    print("=" * 90)

    print(
        "MODULE 04 - POSITIONAL INDEX BUILDER TEST"
    )

    print(
        f"Found {len(xml_files)} XML files"
    )

    print("=" * 90)

    positioned_documents = []

    # ========================================================
    # Module 1 → Module 2 → Module 3
    # ========================================================

    for xml_file in xml_files:

        try:

            # Module 01
            document = parse_jats(
                xml_file
            )

            # Module 02
            processed = process_document(
                document
            )

            # Module 03
            positioned = map_document_positions(
                processed
            )

            positioned_documents.append(
                positioned
            )

        except Exception as error:

            print(
                f"ERROR: {xml_file.name}"
            )

            print(
                f"{type(error).__name__}: "
                f"{error}"
            )

    # ========================================================
    # Module 04
    # ========================================================

    index_data = build_index(
        positioned_documents
    )

    print()

    print(
        f"Documents     : "
        f"{index_data['total_documents']}"
    )

    print(
        f"Indexed Words : "
        f"{index_data['total_terms']}"
    )

    print(
        f"Unique Terms  : "
        f"{index_data['unique_terms']}"
    )

    # ========================================================
    # Validation
    # ========================================================

    (
        valid,
        expected_words,
        actual_words
    ) = validate_index(
        positioned_documents,
        index_data
    )

    print()

    print(
        f"Module 3 Words: "
        f"{expected_words}"
    )

    print(
        f"Module 4 Terms: "
        f"{actual_words}"
    )

    print()

    if valid:

        print(
            "INDEX VALIDATION: PASS"
        )

    else:

        print(
            "INDEX VALIDATION: FAIL"
        )

    # ========================================================
    # SAMPLE LOOKUPS
    # ========================================================

    sample_queries = [
        "dementia",
        "Alzheimer",
        "how"
    ]

    for query in sample_queries:

        print()

        print("=" * 90)

        print(
            f"QUERY: {query}"
        )

        result = lookup_term(
            index_data,
            query
        )

        if result is None:

            print(
                "Not found"
            )

            continue

        print(
            f"Documents : "
            f"{result['document_frequency']}"
        )

        print(
            f"Occurrences: "
            f"{result['total_frequency']}"
        )

        print()

        # ----------------------------------------------------
        # 顯示每篇文章
        # ----------------------------------------------------

        for (
            document_id,
            postings
        ) in result[
            "postings"
        ].items():

            print(
                f"{document_id}: "
                f"{len(postings)} occurrences"
            )

            # 只顯示前 3 個位置
            for posting in postings[:3]:

                print(
                    "    "
                    f"Field={posting['field']:<18} "
                    f"Word={posting['global_word_index']:<6} "
                    f"Sentence={str(posting['sentence_index']):<6} "
                    f"Char="
                    f"{posting['global_char_start']}:"
                    f"{posting['global_char_end']}"
                )

    print()

    print("=" * 90)