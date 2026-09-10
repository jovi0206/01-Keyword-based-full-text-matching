from pathlib import Path

from m01_jats_parser import parse_jats
from m02_text_processor import (
    process_document,
    WORD_PATTERN,
    SENTENCE_SEGMENTER,
    normalize_text
)


# ============================================================
# MODULE 3 — POSITION MAPPER
# ============================================================
#
# Input:
#     Module 2 的 processed_document
#
# Process:
#     替 Search Segment 中的：
#
#     1. Character
#     2. Word
#     3. Sentence
#
#     建立位置資訊
#
# Output:
#     positioned_document
#
# Module 4 之後會使用這些位置建立 Positional Index
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


# ============================================================
# 1. WORD POSITION
# ============================================================
#
# 例如：
#
# Alzheimer disease is common
#
# Word:
#
# Alzheimer
# local word index  = 0
# char start        = 0
# char end          = 9
#
# disease
# local word index  = 1
#
# char_end 使用 Python 慣例：
#
# [start:end]
#
# end 本身不包含在文字內。
# ============================================================

def map_word_positions(
    text,
    global_char_offset,
    global_word_offset
):

    positions = []

    for local_word_index, match in enumerate(
        WORD_PATTERN.finditer(text)
    ):

        word = match.group()

        local_char_start = match.start()
        local_char_end = match.end()

        positions.append(
            {
                "text":
                    word,

                "word_index":
                    local_word_index,

                "global_word_index":
                    global_word_offset
                    + local_word_index,

                "char_start":
                    local_char_start,

                "char_end":
                    local_char_end,

                "global_char_start":
                    global_char_offset
                    + local_char_start,

                "global_char_end":
                    global_char_offset
                    + local_char_end
            }
        )

    return positions


# ============================================================
# 2. SENTENCE POSITION
# ============================================================
#
# pySBD 負責切句。
#
# 我們這裡只負責：
#
# Sentence → 找到它在原本 Segment Text 的位置
#
# 不重新判斷句子。
# ============================================================

def map_sentence_positions(
    text,
    global_char_offset,
    global_sentence_offset
):

    positions = []

    if not text:
        return positions

    raw_sentences = SENTENCE_SEGMENTER.segment(
        text
    )

    search_cursor = 0

    for local_sentence_index, raw_sentence in enumerate(
        raw_sentences
    ):

        sentence = raw_sentence.strip()

        if not sentence:
            continue

        # ----------------------------------------------------
        # 從上一句結束的位置往後找
        #
        # 避免文章裡有完全相同的句子時找到錯的位置
        # ----------------------------------------------------

        local_char_start = text.find(
            sentence,
            search_cursor
        )

        if local_char_start == -1:

            # 極少數 pySBD 空白處理不同時的 fallback
            sentence = normalize_text(
                sentence
            )

            local_char_start = text.find(
                sentence,
                search_cursor
            )

        if local_char_start == -1:

            # 找不到位置就跳過
            # 不讓單一句子造成整篇文件失敗
            continue

        local_char_end = (
            local_char_start
            + len(sentence)
        )

        positions.append(
            {
                "text":
                    sentence,

                "sentence_index":
                    local_sentence_index,

                "global_sentence_index":
                    global_sentence_offset
                    + len(positions),

                "char_start":
                    local_char_start,

                "char_end":
                    local_char_end,

                "global_char_start":
                    global_char_offset
                    + local_char_start,

                "global_char_end":
                    global_char_offset
                    + local_char_end
            }
        )

        search_cursor = local_char_end

    return positions


# ============================================================
# 3. PROCESS ONE DOCUMENT
# ============================================================

def map_document_positions(
    processed_document
):

    positioned_segments = []

    global_char_offset = 0
    global_word_offset = 0
    global_sentence_offset = 0

    search_segments = processed_document[
        "search_segments"
    ]

    # --------------------------------------------------------
    # 每個 Search Segment 分別建立位置
    # --------------------------------------------------------

    for segment in search_segments:

        text = segment["text"]

        # ----------------------------------------------------
        # Word Positions
        # ----------------------------------------------------

        word_positions = map_word_positions(
            text,
            global_char_offset,
            global_word_offset
        )

        # ----------------------------------------------------
        # Sentence Positions
        # ----------------------------------------------------

        sentence_positions = map_sentence_positions(
            text,
            global_char_offset,
            global_sentence_offset
        )

        # ----------------------------------------------------
        # Segment Position
        # ----------------------------------------------------

        global_char_start = (
            global_char_offset
        )

        global_char_end = (
            global_char_offset
            + len(text)
        )

        positioned_segments.append(
            {
                "segment_id":
                    segment["segment_id"],

                "field":
                    segment["field"],

                "text":
                    text,

                "global_char_start":
                    global_char_start,

                "global_char_end":
                    global_char_end,

                "words":
                    word_positions,

                "sentences":
                    sentence_positions
            }
        )

        # ----------------------------------------------------
        # 更新全域位置
        # ----------------------------------------------------

        global_word_offset += len(
            word_positions
        )

        global_sentence_offset += len(
            sentence_positions
        )

        # ----------------------------------------------------
        # 每個 Segment 在 search_text 裡使用 "\n" 相隔
        #
        # 所以：
        #
        # 下一個 Segment 起點
        # = 現在文字長度 + 1
        # ----------------------------------------------------

        global_char_offset += (
            len(text)
            + 1
        )

    # ========================================================
    # 固定 Module 3 Output
    # ========================================================

    positioned_document = {

        "filename":
            processed_document["filename"],

        "pmcid":
            processed_document["pmcid"],

        "title":
            processed_document["title"],

        "search_text":
            processed_document["search_text"],

        "segments":
            positioned_segments,

        "total_search_characters":
            len(
                processed_document[
                    "search_text"
                ]
            ),

        "total_search_words":
            global_word_offset,

        "total_search_sentences":
            global_sentence_offset
    }

    return positioned_document


# ============================================================
# 4. POSITION VALIDATION
# ============================================================
#
# 用位置切回原始文字：
#
# text[start:end]
#
# 如果結果與原本 Word / Sentence 一樣，
# 代表 Character Position 正確。
# ============================================================

def validate_positions(
    positioned_document
):

    errors = []

    search_text = positioned_document[
        "search_text"
    ]

    for segment in positioned_document[
        "segments"
    ]:

        # ----------------------------------------------------
        # Validate Words
        # ----------------------------------------------------

        for word in segment["words"]:

            extracted = search_text[
                word["global_char_start"]:
                word["global_char_end"]
            ]

            if extracted != word["text"]:

                errors.append(
                    {
                        "type":
                            "word",

                        "expected":
                            word["text"],

                        "actual":
                            extracted
                    }
                )

        # ----------------------------------------------------
        # Validate Sentences
        # ----------------------------------------------------

        for sentence in segment[
            "sentences"
        ]:

            extracted = search_text[
                sentence[
                    "global_char_start"
                ]:
                sentence[
                    "global_char_end"
                ]
            ]

            if extracted != sentence["text"]:

                errors.append(
                    {
                        "type":
                            "sentence",

                        "expected":
                            sentence["text"],

                        "actual":
                            extracted
                    }
                )

    return errors


# ============================================================
# 5. TEST
# ============================================================

if __name__ == "__main__":

    xml_files = sorted(
        DATA_DIR.glob(
            "*.xml"
        )
    )

    print("=" * 90)

    print(
        "MODULE 3 - POSITION MAPPER TEST"
    )

    print(
        f"Found {len(xml_files)} XML files"
    )

    print("=" * 90)

    for xml_file in xml_files:

        try:

            # =================================================
            # Module 1
            # XML → Structured Document
            # =================================================

            document = parse_jats(
                xml_file
            )

            # =================================================
            # Module 2
            # Structured Document → Text Processing
            # =================================================

            processed = process_document(
                document
            )

            # =================================================
            # Module 3
            # Text → Positions
            # =================================================

            positioned = map_document_positions(
                processed
            )

            # =================================================
            # Validate
            # =================================================

            errors = validate_positions(
                positioned
            )

            print()

            print(
                f"File  : "
                f"{positioned['filename']}"
            )

            print(
                f"PMCID : "
                f"{positioned['pmcid']}"
            )

            print("-" * 90)

            print(
                f"Search Characters : "
                f"{positioned['total_search_characters']}"
            )

            print(
                f"Search Words      : "
                f"{positioned['total_search_words']}"
            )

            print(
                f"Search Sentences  : "
                f"{positioned['total_search_sentences']}"
            )

            print(
                f"Segments          : "
                f"{len(positioned['segments'])}"
            )

            print(
                f"Position Errors   : "
                f"{len(errors)}"
            )

            # =================================================
            # 顯示第一個有 Word 的 Segment
            # =================================================

            for segment in positioned[
                "segments"
            ]:

                if segment["words"]:

                    print()

                    print(
                        "SAMPLE WORD POSITIONS"
                    )

                    for word in segment[
                        "words"
                    ][:5]:

                        print(
                            f"{word['text']:<20} "
                            f"Word={word['global_word_index']:<6} "
                            f"Char="
                            f"{word['global_char_start']}:"
                            f"{word['global_char_end']}"
                        )

                    break

            # =================================================
            # 顯示第一個有 Sentence 的 Segment
            # =================================================

            for segment in positioned[
                "segments"
            ]:

                if segment["sentences"]:

                    sentence = segment[
                        "sentences"
                    ][0]

                    print()

                    print(
                        "SAMPLE SENTENCE POSITION"
                    )

                    print(
                        f"Sentence Index : "
                        f"{sentence['global_sentence_index']}"
                    )

                    print(
                        f"Character      : "
                        f"{sentence['global_char_start']}:"
                        f"{sentence['global_char_end']}"
                    )

                    print(
                        f"Text           : "
                        f"{sentence['text']}"
                    )

                    break

            print()

            if len(errors) == 0:

                print(
                    "POSITION VALIDATION: PASS"
                )

            else:

                print(
                    "POSITION VALIDATION: FAIL"
                )

                print(
                    errors[:3]
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