import re
from collections import Counter
from pathlib import Path

from m01_jats_parser import parse_jats
from m02_text_processor import process_document, tokenize_words
from m03_position_mapper import map_document_positions
from m04_index_builder import build_index


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


# ============================================================
# MODULE 05 — QUERY ENGINE
# ============================================================
#
# Search layers:
#
# 1. Exact / Positional Retrieval
# 2. Lexical / Proximity Retrieval
# 3. Literal Substring Fallback (Auto mode only)
#
# Literal Search:
#     Similar to browser Ctrl+F, but searches only the clean
#     searchable article content produced by M01 ~ M03.
#
#     It DOES NOT search raw XML tags such as:
#         <string-name>
#         <surname>
#         name-style="western"
#
# M01 ~ M04 remain unchanged.
# ============================================================


# ============================================================
# SETTINGS
# ============================================================

# Related phrase:
# all query words must exist inside one sentence.
# Up to N extra words may appear inside the matched span.
PHRASE_PROXIMITY_N = 2

# Approximate sentence:
# query words must remain in order.
SENTENCE_EXTRA_WORD_RATIO = 0.30
SENTENCE_MIN_EXTRA_WORDS = 2

# Prefix relation:
# avoid treating very short strings such as "an" as roots.
RELATED_PREFIX_MIN_LENGTH = 4


# ============================================================
# 1. BASIC NORMALIZATION
# ============================================================

def normalize_surface(token):

    if not token:
        return ""

    return (
        token
        .casefold()
        .replace("’", "'")
        .strip()
    )


# ============================================================
# 2. SIMPLE LEXICAL BASE
# ============================================================
#
# This is intentionally lightweight.
#
# Examples:
#     Alzheimer's -> alzheimer
#     activities  -> activity
#     cancers     -> cancer
#
# It is NOT a complete stemmer / PMC ATM implementation.
# ============================================================

def lexical_base(token):

    token = normalize_surface(
        token
    )

    # Alzheimer's -> alzheimer
    if (
        token.endswith("'s")
        and len(token) > 2
    ):
        token = token[:-2]

    # activities -> activity
    if (
        len(token) > 4
        and token.endswith("ies")
    ):

        token = (
            token[:-3]
            + "y"
        )

    # boxes / matches / wishes
    elif (
        len(token) > 4
        and token.endswith(
            (
                "ches",
                "shes",
                "xes",
                "zes",
            )
        )
    ):

        token = token[:-2]

    # cancers -> cancer
    elif (
        len(token) > 3
        and token.endswith("s")
        and not token.endswith(
            (
                "ss",
                "us",
                "is",
            )
        )
    ):

        token = token[:-1]

    return token


# ============================================================
# 3. RELATED WORD RULE
# ============================================================

def related_word_relation(
    query_term,
    candidate_term,
):

    query_surface = normalize_surface(
        query_term
    )

    candidate_surface = normalize_surface(
        candidate_term
    )

    if (
        not query_surface
        or not candidate_surface
    ):
        return None

    # Exact result is handled by exact search.
    if query_surface == candidate_surface:
        return None

    query_base = lexical_base(
        query_term
    )

    candidate_base = lexical_base(
        candidate_term
    )

    # Singular / plural / possessive
    if query_base == candidate_base:

        return {
            "method":
                "lexical_variant",

            "similarity":
                1.0,
        }

    # Prefix-related form
    if (
        len(query_base)
        >= RELATED_PREFIX_MIN_LENGTH
        and candidate_base.startswith(
            query_base
        )
    ):

        similarity = (
            len(query_base)
            /
            len(candidate_base)
        )

        return {
            "method":
                "prefix_related",

            "similarity":
                round(
                    similarity,
                    4,
                ),
        }

    if (
        len(candidate_base)
        >= RELATED_PREFIX_MIN_LENGTH
        and query_base.startswith(
            candidate_base
        )
    ):

        similarity = (
            len(candidate_base)
            /
            len(query_base)
        )

        return {
            "method":
                "prefix_related",

            "similarity":
                round(
                    similarity,
                    4,
                ),
        }

    return None


# ============================================================
# 4. AUTO QUERY TYPE
# ============================================================

def detect_query_type(query):

    tokens = tokenize_words(
        query
    )

    if len(tokens) <= 1:
        return "word"

    if (
        query.strip().endswith(
            (
                ".",
                "!",
                "?",
            )
        )
        or len(tokens) >= 8
    ):

        return "sentence"

    return "phrase"


# ============================================================
# 5. DOCUMENT HELPERS
# ============================================================

def resolve_document_id(document):
    return (
        document.get("pmcid")
        or document.get("pmid")
        or document["filename"]
    )


def build_document_lookup(
    positioned_documents,
):

    return {
        resolve_document_id(
            document
        ):
            document

        for document
        in positioned_documents
    }


def find_segment(
    document,
    segment_id,
):

    for segment in document[
        "segments"
    ]:

        if (
            segment["segment_id"]
            == segment_id
        ):

            return segment

    return None


def find_sentence_for_char(
    segment,
    char_start,
):

    for sentence in segment[
        "sentences"
    ]:

        if (
            sentence[
                "global_char_start"
            ]
            <= char_start
            < sentence[
                "global_char_end"
            ]
        ):

            return sentence

    # Fallback:
    # useful for a literal match starting in punctuation/whitespace.
    for sentence in segment[
        "sentences"
    ]:

        if (
            sentence[
                "global_char_start"
            ]
            <= char_start
            <= sentence[
                "global_char_end"
            ]
        ):

            return sentence

    return None


def get_sentence_words(
    segment,
    sentence,
):

    start = sentence[
        "global_char_start"
    ]

    end = sentence[
        "global_char_end"
    ]

    return [
        word

        for word
        in segment["words"]

        if (
            start
            <= word[
                "global_char_start"
            ]
            < end
        )
    ]


def find_word_position_for_range(
    segment,
    char_start,
    char_end,
):

    # First preference:
    # the query starts inside this word.
    for word in segment[
        "words"
    ]:

        if (
            word[
                "global_char_start"
            ]
            <= char_start
            < word[
                "global_char_end"
            ]
        ):

            return word[
                "global_word_index"
            ]

    # Second preference:
    # the query starts in punctuation/space,
    # then use the first overlapping word.
    for word in segment[
        "words"
    ]:

        if (
            word[
                "global_char_start"
            ]
            < char_end

            and

            char_start
            < word[
                "global_char_end"
            ]
        ):

            return word[
                "global_word_index"
            ]

    return None


def get_context(
    document,
    segment,
    char_start,
    char_end,
    radius=120,
):

    sentence = find_sentence_for_char(
        segment,
        char_start,
    )

    if sentence:

        return sentence[
            "text"
        ]

    text = document[
        "search_text"
    ]

    left = max(
        0,
        char_start - radius,
    )

    right = min(
        len(text),
        char_end + radius,
    )

    return (
        text[
            left:right
        ]
        .replace(
            "\n",
            " ",
        )
    )


# ============================================================
# 6. STANDARD RESULT FORMAT
# ============================================================

def make_result(
    document,
    segment,
    match_type,
    match_method,
    char_start,
    char_end,
    word_position,
    sentence_position,
    similarity=1.0,
):

    return {
        "document_id":
            resolve_document_id(
                document
            ),

        "title":
            document["title"],

        "segment_id":
            segment[
                "segment_id"
            ],

        "field":
            segment["field"],

        "match_type":
            match_type,

        "match_method":
            match_method,

        "matched_text":
            document[
                "search_text"
            ][
                char_start:
                char_end
            ],

        "similarity":
            round(
                similarity,
                4,
            ),

        "word_position":
            word_position,

        "sentence_position":
            sentence_position,

        "char_start":
            char_start,

        "char_end":
            char_end,

        "context":
            get_context(
                document,
                segment,
                char_start,
                char_end,
            ),
    }


# ============================================================
# 7. EXACT WORD
# ============================================================

def search_exact_word(
    index_data,
    document_lookup,
    query,
):

    query_surface = normalize_surface(
        query
    )

    results = []

    for (
        indexed_term,
        entry,
    ) in index_data[
        "index"
    ].items():

        if (
            normalize_surface(
                indexed_term
            )
            != query_surface
        ):

            continue

        for (
            document_id,
            postings,
        ) in entry[
            "postings"
        ].items():

            document = document_lookup[
                document_id
            ]

            for posting in postings:

                segment = find_segment(
                    document,
                    posting[
                        "segment_id"
                    ],
                )

                results.append(
                    make_result(
                        document=
                            document,

                        segment=
                            segment,

                        match_type=
                            "exact",

                        match_method=
                            "exact_word",

                        char_start=
                            posting[
                                "global_char_start"
                            ],

                        char_end=
                            posting[
                                "global_char_end"
                            ],

                        word_position=
                            posting[
                                "global_word_index"
                            ],

                        sentence_position=
                            posting[
                                "sentence_index"
                            ],
                    )
                )

    return results


# ============================================================
# 8. RELATED WORD
# ============================================================

def search_related_word(
    index_data,
    document_lookup,
    query,
):

    results = []

    for (
        indexed_term,
        entry,
    ) in index_data[
        "index"
    ].items():

        relation = (
            related_word_relation(
                query,
                indexed_term,
            )
        )

        if relation is None:
            continue

        for (
            document_id,
            postings,
        ) in entry[
            "postings"
        ].items():

            document = document_lookup[
                document_id
            ]

            for posting in postings:

                segment = find_segment(
                    document,
                    posting[
                        "segment_id"
                    ],
                )

                results.append(
                    make_result(
                        document=
                            document,

                        segment=
                            segment,

                        match_type=
                            "related",

                        match_method=
                            relation[
                                "method"
                            ],

                        char_start=
                            posting[
                                "global_char_start"
                            ],

                        char_end=
                            posting[
                                "global_char_end"
                            ],

                        word_position=
                            posting[
                                "global_word_index"
                            ],

                        sentence_position=
                            posting[
                                "sentence_index"
                            ],

                        similarity=
                            relation[
                                "similarity"
                            ],
                    )
                )

    return results


# ============================================================
# 9. EXACT PHRASE
# ============================================================
#
# Query words must be:
#     same order
#     adjacent
#     inside the same sentence
# ============================================================

def search_exact_phrase(
    positioned_documents,
    query,
):

    query_terms = [
        normalize_surface(
            token
        )

        for token
        in tokenize_words(
            query
        )
    ]

    if len(query_terms) < 2:
        return []

    results = []

    query_length = len(
        query_terms
    )

    for document in positioned_documents:

        for segment in document[
            "segments"
        ]:

            for sentence in segment[
                "sentences"
            ]:

                words = get_sentence_words(
                    segment,
                    sentence,
                )

                if (
                    len(words)
                    < query_length
                ):
                    continue

                terms = [
                    normalize_surface(
                        word["text"]
                    )

                    for word
                    in words
                ]

                for start in range(
                    len(words)
                    - query_length
                    + 1
                ):

                    end = (
                        start
                        + query_length
                    )

                    if (
                        terms[
                            start:end
                        ]
                        != query_terms
                    ):

                        continue

                    first_word = words[
                        start
                    ]

                    last_word = words[
                        end - 1
                    ]

                    results.append(
                        make_result(
                            document=
                                document,

                            segment=
                                segment,

                            match_type=
                                "exact",

                            match_method=
                                "exact_phrase",

                            char_start=
                                first_word[
                                    "global_char_start"
                                ],

                            char_end=
                                last_word[
                                    "global_char_end"
                                ],

                            word_position=
                                first_word[
                                    "global_word_index"
                                ],

                            sentence_position=
                                sentence[
                                    "global_sentence_index"
                                ],
                        )
                    )

    return results


# ============================================================
# 10. PROXIMITY HELPERS
# ============================================================

def counter_contains(
    window_counter,
    query_counter,
):

    return all(
        window_counter[
            term
        ]
        >= required

        for (
            term,
            required,
        )
        in query_counter.items()
    )


def find_proximity_windows(
    words,
    query_terms,
    max_extra_words,
):

    if (
        not words
        or not query_terms
    ):
        return []

    terms = [
        lexical_base(
            word["text"]
        )

        for word
        in words
    ]

    query_counter = Counter(
        query_terms
    )

    query_length = len(
        query_terms
    )

    maximum_window = (
        query_length
        + max_extra_words
    )

    windows = []
    seen = set()

    for start in range(
        len(words)
    ):

        if (
            terms[start]
            not in query_counter
        ):
            continue

        max_end = min(
            len(words),
            start + maximum_window,
        )

        for end in range(
            start + query_length,
            max_end + 1,
        ):

            window_terms = (
                terms[
                    start:end
                ]
            )

            if (
                window_terms[-1]
                not in query_counter
            ):
                continue

            if not counter_contains(
                Counter(
                    window_terms
                ),
                query_counter,
            ):
                continue

            key = (
                start,
                end,
            )

            if key not in seen:

                seen.add(
                    key
                )

                windows.append(
                    {
                        "start":
                            start,

                        "end":
                            end,

                        "extra_words":
                            (
                                end
                                - start
                                - query_length
                            ),
                    }
                )

            # Keep the shortest valid window for this start.
            break

    return windows


# ============================================================
# 11. RELATED PHRASE
# ============================================================
#
# All query terms must appear inside one sentence.
# Small lexical variation is allowed.
# ============================================================

def search_related_phrase(
    positioned_documents,
    query,
    proximity_n=
        PHRASE_PROXIMITY_N,
):

    query_terms = [
        lexical_base(
            token
        )

        for token
        in tokenize_words(
            query
        )
    ]

    if len(query_terms) < 2:
        return []

    results = []

    for document in positioned_documents:

        for segment in document[
            "segments"
        ]:

            for sentence in segment[
                "sentences"
            ]:

                words = get_sentence_words(
                    segment,
                    sentence,
                )

                windows = (
                    find_proximity_windows(
                        words,
                        query_terms,
                        max_extra_words=
                            proximity_n,
                    )
                )

                for window in windows:

                    first_word = words[
                        window["start"]
                    ]

                    last_word = words[
                        window["end"] - 1
                    ]

                    span_length = (
                        window["end"]
                        - window["start"]
                    )

                    similarity = (
                        len(query_terms)
                        /
                        span_length
                    )

                    results.append(
                        make_result(
                            document=
                                document,

                            segment=
                                segment,

                            match_type=
                                "related",

                            match_method=
                                f"proximity_N{proximity_n}",

                            char_start=
                                first_word[
                                    "global_char_start"
                                ],

                            char_end=
                                last_word[
                                    "global_char_end"
                                ],

                            word_position=
                                first_word[
                                    "global_word_index"
                                ],

                            sentence_position=
                                sentence[
                                    "global_sentence_index"
                                ],

                            similarity=
                                similarity,
                        )
                    )

    return results


# ============================================================
# 12. EXACT SENTENCE
# ============================================================

def search_exact_sentence(
    positioned_documents,
    query,
):

    query_terms = [
        normalize_surface(
            token
        )

        for token
        in tokenize_words(
            query
        )
    ]

    if len(query_terms) < 2:
        return []

    results = []

    for document in positioned_documents:

        for segment in document[
            "segments"
        ]:

            for sentence in segment[
                "sentences"
            ]:

                words = get_sentence_words(
                    segment,
                    sentence,
                )

                candidate_terms = [
                    normalize_surface(
                        word["text"]
                    )

                    for word
                    in words
                ]

                if (
                    candidate_terms
                    != query_terms
                ):
                    continue

                results.append(
                    make_result(
                        document=
                            document,

                        segment=
                            segment,

                        match_type=
                            "exact",

                        match_method=
                            "exact_sentence",

                        char_start=
                            sentence[
                                "global_char_start"
                            ],

                        char_end=
                            sentence[
                                "global_char_end"
                            ],

                        word_position=
                            (
                                words[0][
                                    "global_word_index"
                                ]
                                if words
                                else None
                            ),

                        sentence_position=
                            sentence[
                                "global_sentence_index"
                            ],
                    )
                )

    return results


# ============================================================
# 13. ORDERED PROXIMITY FOR SENTENCE
# ============================================================

def find_ordered_windows(
    words,
    query_terms,
    max_extra_words,
):

    terms = [
        lexical_base(
            word["text"]
        )

        for word
        in words
    ]

    if (
        not terms
        or not query_terms
    ):
        return []

    windows = []
    seen = set()

    first_term = (
        query_terms[0]
    )

    for start in range(
        len(terms)
    ):

        if (
            terms[start]
            != first_term
        ):
            continue

        cursor = (
            start + 1
        )

        matched_positions = [
            start
        ]

        success = True

        for query_term in query_terms[
            1:
        ]:

            found = False

            while (
                cursor
                < len(terms)
            ):

                if (
                    terms[cursor]
                    == query_term
                ):

                    matched_positions.append(
                        cursor
                    )

                    cursor += 1
                    found = True
                    break

                cursor += 1

            if not found:
                success = False
                break

        if not success:
            continue

        end = (
            matched_positions[-1]
            + 1
        )

        span_length = (
            end
            - start
        )

        extra_words = (
            span_length
            - len(query_terms)
        )

        if (
            extra_words
            > max_extra_words
        ):
            continue

        key = (
            start,
            end,
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        windows.append(
            {
                "start":
                    start,

                "end":
                    end,

                "extra_words":
                    extra_words,
            }
        )

    return windows


# ============================================================
# 14. APPROXIMATE SENTENCE
# ============================================================

def search_approximate_sentence(
    positioned_documents,
    query,
    extra_word_ratio=
        SENTENCE_EXTRA_WORD_RATIO,
):

    query_terms = [
        lexical_base(
            token
        )

        for token
        in tokenize_words(
            query
        )
    ]

    if len(query_terms) < 2:
        return []

    max_extra_words = max(
        SENTENCE_MIN_EXTRA_WORDS,
        round(
            len(query_terms)
            * extra_word_ratio
        ),
    )

    results = []

    for document in positioned_documents:

        for segment in document[
            "segments"
        ]:

            for sentence in segment[
                "sentences"
            ]:

                words = get_sentence_words(
                    segment,
                    sentence,
                )

                windows = (
                    find_ordered_windows(
                        words,
                        query_terms,
                        max_extra_words=
                            max_extra_words,
                    )
                )

                for window in windows:

                    first_word = words[
                        window["start"]
                    ]

                    last_word = words[
                        window["end"] - 1
                    ]

                    span_length = (
                        window["end"]
                        - window["start"]
                    )

                    similarity = (
                        len(query_terms)
                        /
                        span_length
                    )

                    results.append(
                        make_result(
                            document=
                                document,

                            segment=
                                segment,

                            match_type=
                                "related",

                            match_method=
                                "ordered_proximity",

                            char_start=
                                first_word[
                                    "global_char_start"
                                ],

                            char_end=
                                last_word[
                                    "global_char_end"
                                ],

                            word_position=
                                first_word[
                                    "global_word_index"
                                ],

                            sentence_position=
                                sentence[
                                    "global_sentence_index"
                                ],

                            similarity=
                                similarity,
                        )
                    )

    return results


# ============================================================
# 15. LITERAL SUBSTRING SEARCH
# ============================================================
#
# Browser-like Ctrl+F behavior.
#
# Example:
#
# Document:
#     Neurol Sci
#
# Query:
#     eurol Sc
#
# Result:
#     FOUND
#
# Important:
# This searches Segment TEXT only, not raw XML markup.
# ============================================================

def build_literal_pattern(query):

    query = query.strip()

    if not query:
        return None

    # Make copied line breaks / multiple spaces tolerant.
    #
    # Query:
    #     Rationale, Study
    #     Design an
    #
    # can still match one-line searchable text.
    parts = [
        part

        for part
        in re.split(
            r"\s+",
            query,
        )

        if part
    ]

    if not parts:
        return None

    pattern_text = (
        r"\s+"
        .join(
            re.escape(
                part
            )
            for part
            in parts
        )
    )

    return re.compile(
        pattern_text,
        re.IGNORECASE,
    )


def search_literal_text(
    positioned_documents,
    query,
):

    pattern = build_literal_pattern(
        query
    )

    if pattern is None:
        return []

    results = []

    for document in positioned_documents:

        for segment in document[
            "segments"
        ]:

            segment_text = segment[
                "text"
            ]

            segment_start = segment[
                "global_char_start"
            ]

            for match in pattern.finditer(
                segment_text
            ):

                char_start = (
                    segment_start
                    + match.start()
                )

                char_end = (
                    segment_start
                    + match.end()
                )

                sentence = (
                    find_sentence_for_char(
                        segment,
                        char_start,
                    )
                )

                sentence_position = (
                    sentence[
                        "global_sentence_index"
                    ]
                    if sentence
                    else None
                )

                word_position = (
                    find_word_position_for_range(
                        segment,
                        char_start,
                        char_end,
                    )
                )

                results.append(
                    make_result(
                        document=
                            document,

                        segment=
                            segment,

                        # Literal substring is an exact
                        # character-sequence match.
                        match_type=
                            "exact",

                        match_method=
                            "literal_substring",

                        char_start=
                            char_start,

                        char_end=
                            char_end,

                        word_position=
                            word_position,

                        sentence_position=
                            sentence_position,

                        similarity=
                            1.0,
                    )
                )

    results.sort(
        key=lambda item: (
            item[
                "document_id"
            ],
            item[
                "char_start"
            ],
        )
    )

    return results


# ============================================================
# 16. DUPLICATE REMOVAL
# ============================================================

def ranges_overlap(
    first,
    second,
):

    return (
        first[
            "char_start"
        ]
        < second[
            "char_end"
        ]

        and

        second[
            "char_start"
        ]
        < first[
            "char_end"
        ]
    )


def remove_exact_duplicates(
    exact_results,
    related_results,
):

    filtered = []
    seen = set()

    for related in related_results:

        duplicate = any(
            related[
                "document_id"
            ]
            == exact[
                "document_id"
            ]

            and

            related[
                "segment_id"
            ]
            == exact[
                "segment_id"
            ]

            and

            ranges_overlap(
                related,
                exact,
            )

            for exact
            in exact_results
        )

        if duplicate:
            continue

        key = (
            related[
                "document_id"
            ],

            related[
                "segment_id"
            ],

            related[
                "char_start"
            ],

            related[
                "char_end"
            ],

            related[
                "match_method"
            ],
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        filtered.append(
            related
        )

    return filtered


# ============================================================
# 17. EMPTY RESULT
# ============================================================

def empty_search_result():

    return {
        "query":
            "",

        "query_type":
            "empty",

        "requested_query_type":
            "empty",

        "retrieval_mode":
            "empty",

        "fallback_used":
            False,

        "documents_found":
            0,

        "exact_matches":
            0,

        "related_matches":
            0,

        "total_matches":
            0,

        "exact_results":
            [],

        "related_results":
            [],
    }


# ============================================================
# 18. MAIN QUERY ENGINE
# ============================================================

def search_query(
    index_data,
    positioned_documents,
    query,
    query_type="auto",
    phrase_proximity_n=
        PHRASE_PROXIMITY_N,
):

    query = query.strip()

    if not query:
        return empty_search_result()

    requested_query_type = (
        query_type
    )

    auto_requested = (
        query_type
        == "auto"
    )

    if auto_requested:
        resolved_query_type = (
            detect_query_type(
                query
            )
        )
    else:
        resolved_query_type = (
            query_type
        )

    document_lookup = (
        build_document_lookup(
            positioned_documents
        )
    )

    retrieval_mode = (
        "positional"
    )

    fallback_used = False


    # --------------------------------------------------------
    # EXPLICIT LITERAL
    # --------------------------------------------------------

    if (
        resolved_query_type
        == "literal"
    ):

        exact_results = (
            search_literal_text(
                positioned_documents,
                query,
            )
        )

        related_results = []

        retrieval_mode = (
            "literal"
        )


    # --------------------------------------------------------
    # WORD
    # --------------------------------------------------------

    elif (
        resolved_query_type
        == "word"
    ):

        exact_results = (
            search_exact_word(
                index_data,
                document_lookup,
                query,
            )
        )

        related_results = (
            search_related_word(
                index_data,
                document_lookup,
                query,
            )
        )


    # --------------------------------------------------------
    # PHRASE
    # --------------------------------------------------------

    elif (
        resolved_query_type
        == "phrase"
    ):

        exact_results = (
            search_exact_phrase(
                positioned_documents,
                query,
            )
        )

        related_results = (
            search_related_phrase(
                positioned_documents,
                query,
                proximity_n=
                    phrase_proximity_n,
            )
        )


    # --------------------------------------------------------
    # SENTENCE
    # --------------------------------------------------------

    elif (
        resolved_query_type
        == "sentence"
    ):

        exact_results = (
            search_exact_sentence(
                positioned_documents,
                query,
            )
        )

        related_results = (
            search_approximate_sentence(
                positioned_documents,
                query,
            )
        )


    else:

        raise ValueError(
            "query_type must be "
            "auto, word, phrase, "
            "sentence, or literal"
        )


    # --------------------------------------------------------
    # Exact has priority over related.
    # --------------------------------------------------------

    related_results = (
        remove_exact_duplicates(
            exact_results,
            related_results,
        )
    )


    # --------------------------------------------------------
    # AUTO FALLBACK
    #
    # Only when normal retrieval finds NOTHING.
    #
    # This preserves normal keyword counts such as:
    #
    # cancer
    # Exact 343 / Related 69
    #
    # It does NOT add raw substring counts on top.
    # --------------------------------------------------------

    if (
        auto_requested
        and not exact_results
        and not related_results
    ):

        literal_results = (
            search_literal_text(
                positioned_documents,
                query,
            )
        )

        if literal_results:

            exact_results = (
                literal_results
            )

            related_results = []

            resolved_query_type = (
                "literal"
            )

            retrieval_mode = (
                "literal_fallback"
            )

            fallback_used = True


    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    exact_results.sort(
        key=lambda item: (
            item[
                "document_id"
            ],
            item[
                "char_start"
            ],
        )
    )

    related_results.sort(
        key=lambda item: (
            -item[
                "similarity"
            ],
            item[
                "document_id"
            ],
            item[
                "char_start"
            ],
        )
    )

    all_results = (
        exact_results
        + related_results
    )

    documents_found = len(
        {
            item[
                "document_id"
            ]

            for item
            in all_results
        }
    )

    return {
        "query":
            query,

        "query_type":
            resolved_query_type,

        "requested_query_type":
            requested_query_type,

        "retrieval_mode":
            retrieval_mode,

        "fallback_used":
            fallback_used,

        "documents_found":
            documents_found,

        "exact_matches":
            len(
                exact_results
            ),

        "related_matches":
            len(
                related_results
            ),

        "total_matches":
            len(
                all_results
            ),

        "exact_results":
            exact_results,

        "related_results":
            related_results,
    }


# ============================================================
# 19. TEST OUTPUT
# ============================================================

def print_search_result(
    result,
    limit=5,
):

    print()

    print(
        "=" * 90
    )

    print(
        f"QUERY            : "
        f"{result['query']}"
    )

    print(
        f"QUERY TYPE       : "
        f"{result['query_type']}"
    )

    print(
        f"RETRIEVAL MODE   : "
        f"{result['retrieval_mode']}"
    )

    print(
        f"FALLBACK USED    : "
        f"{result['fallback_used']}"
    )

    print(
        f"DOCUMENTS FOUND  : "
        f"{result['documents_found']}"
    )

    print(
        f"EXACT MATCHES    : "
        f"{result['exact_matches']}"
    )

    print(
        f"RELATED MATCHES  : "
        f"{result['related_matches']}"
    )

    print(
        f"TOTAL MATCHES    : "
        f"{result['total_matches']}"
    )


    if result[
        "exact_results"
    ]:

        print()
        print(
            "EXACT RESULTS"
        )

        for item in result[
            "exact_results"
        ][:limit]:

            print(
                f"[{item['document_id']}] "
                f"Method={item['match_method']} "
                f"Field={item['field']} "
                f"Word={item['word_position']} "
                f"Sentence={item['sentence_position']} "
                f"Char={item['char_start']}:"
                f"{item['char_end']}"
            )

            print(
                f"    "
                f"{item['context']}"
            )


    if result[
        "related_results"
    ]:

        print()
        print(
            "RELATED / APPROXIMATE RESULTS"
        )

        for item in result[
            "related_results"
        ][:limit]:

            print(
                f"[{item['document_id']}] "
                f"Method={item['match_method']} "
                f"Similarity="
                f"{item['similarity']:.0%} "
                f"Field={item['field']} "
                f"Sentence={item['sentence_position']} "
                f"Char={item['char_start']}:"
                f"{item['char_end']}"
            )

            print(
                f"    "
                f"{item['context']}"
            )


# ============================================================
# 20. TEST
# ============================================================

if __name__ == "__main__":

    xml_files = sorted(
        DATA_DIR.glob(
            "*.xml"
        )
    )

    print(
        "=" * 90
    )

    print(
        "MODULE 05 - QUERY ENGINE + "
        "LITERAL FALLBACK TEST"
    )

    print(
        f"Found "
        f"{len(xml_files)} "
        f"XML files"
    )

    print(
        "=" * 90
    )

    positioned_documents = []

    # M01 → M02 → M03
    for xml_file in xml_files:

        document = parse_jats(
            xml_file
        )

        processed = (
            process_document(
                document
            )
        )

        positioned = (
            map_document_positions(
                processed
            )
        )

        positioned_documents.append(
            positioned
        )

    # M04
    index_data = build_index(
        positioned_documents
    )


    # --------------------------------------------------------
    # M05 TEST QUERIES
    # --------------------------------------------------------

    test_queries = [

        # Normal word retrieval
        (
            "how",
            "word",
        ),

        # Lexical variants
        (
            "Alzheimer",
            "word",
        ),

        # Phrase retrieval
        (
            "physical activity",
            "phrase",
        ),

        # Approximate phrase
        (
            "light physical activities",
            "phrase",
        ),

        # Exact sentence
        (
            "This study systematically reviews "
            "the evidence to clarify this association.",
            "sentence",
        ),

        # Ordered proximity sentence
        (
            "This study reviews the evidence "
            "to clarify association.",
            "sentence",
        ),

        # Browser-like partial-word search.
        # In Auto mode this should first try Phrase retrieval.
        # If no positional result exists, it falls back to
        # literal substring matching.
        (
            "eurol Sc",
            "auto",
        ),

        # Explicit Literal mode
        (
            "eurol Sc",
            "literal",
        ),
    ]


    for (
        query,
        query_type,
    ) in test_queries:

        result = search_query(
            index_data=
                index_data,

            positioned_documents=
                positioned_documents,

            query=
                query,

            query_type=
                query_type,
        )

        print_search_result(
            result,
            limit=5,
        )

    print()
    print(
        "=" * 90
    )
