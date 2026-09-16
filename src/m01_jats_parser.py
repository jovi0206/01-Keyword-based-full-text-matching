from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


# ============================================================
# MODULE 1 — XML PARSER / FORMAT ADAPTER
# ============================================================
#
# Input:
#     JATS XML / BioC XML / Generic XML
#
# Process:
#     解析 XML 結構
#
# Output:
#     Structured Document
#
# 這個模組只負責：
#     「XML 裡面有什麼？」
#
# 不負責：
#     Word Count
#     Sentence Count
#     Position
#     Index
#     Search
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"


# ============================================================
# 1. XML 基本工具
# ============================================================

def local_name(element):

    return element.tag.split("}")[-1]


# ------------------------------------------------------------
# 整理文字中的多餘空白與標點
# ------------------------------------------------------------

def normalize_inline_text(text):

    if not text:
        return ""

    text = " ".join(
        text.split()
    )

    # 移除標點符號前面多餘空白
    text = re.sub(
        r"\s+([,.;:!?%)\]])",
        r"\1",
        text
    )

    # 移除括號後面多餘空白
    text = re.sub(
        r"([(\[])\s+",
        r"\1",
        text
    )

    # Citation 被移除後可能留下 [ , ] 或 ()
    text = re.sub(
        r"\[\s*[,;–—\-]*\s*\]",
        "",
        text
    )

    text = re.sub(
        r"\(\s*[,;–—\-]*\s*\)",
        "",
        text
    )

    return " ".join(
        text.split()
    )



# ============================================================
# Statistics Text Helpers
# ============================================================
#
# 這一組函式只給「文件統計」使用。
#
# 與一般 normalize_inline_text() 不同：
#     只整理連續空白
#     不移除標點前空白
#
# 原因：
#     JATS 的文字分散在許多 inline XML nodes 中。
#     統計 Word 時，我們希望保留 XML text node 之間的
#     whitespace boundary，避免把原本分開的 token 合併。
# ============================================================

def normalize_statistics_text(text):

    if not text:
        return ""

    return " ".join(
        text.split()
    )


def get_statistics_text(
    element,
    excluded_tags=None
):

    if element is None:
        return ""

    excluded_tags = set(
        excluded_tags
        or []
    )

    parts = []

    def walk(node):

        if node.text:
            parts.append(
                node.text
            )

        for child in node:

            if local_name(child) in excluded_tags:

                # 排除整個 subtree，
                # 但仍保留 subtree 後面的 tail。
                if child.tail:
                    parts.append(
                        child.tail
                    )

                continue

            walk(
                child
            )

            if child.tail:
                parts.append(
                    child.tail
                )

    walk(
        element
    )

    return normalize_statistics_text(
        " ".join(parts)
    )


def build_jats_statistics_text(
    front,
    body,
    back
):

    # --------------------------------------------------------
    # JATS 統計範圍
    #
    # Front:
    #     保留 metadata / title / author / identifiers...
    #     排除 permissions / license 文字
    #
    # Body:
    #     保留完整可見文字
    #     包含 citation number、table、figure 等
    #
    # Back:
    #     保留完整可見文字
    #     包含 references
    # --------------------------------------------------------

    front_text = get_statistics_text(
        front,
        excluded_tags={
            "permissions"
        }
    )

    body_text = get_statistics_text(
        body
    )

    back_text = get_statistics_text(
        back
    )

    combined = "\n".join(
        text
        for text in (
            front_text,
            body_text,
            back_text
        )
        if text
    )

    return {
        "front":
            front_text,

        "body":
            body_text,

        "back":
            back_text,

        "combined":
            combined
    }


# ------------------------------------------------------------
# 取得 Element 文字
#
# exclude_bibr=False
#     保留 citation
#
# exclude_bibr=True
#     跳過：
#         <xref ref-type="bibr">
#
# 因此我們可以同時保留：
#
# RAW TEXT
# CLEAN TEXT
# ------------------------------------------------------------

def get_text(
    element,
    exclude_bibr=False
):

    if element is None:
        return ""

    parts = []

    def walk(node):

        if node.text:
            parts.append(
                node.text
            )

        for child in node:

            is_bibliographic_xref = (
                local_name(child) == "xref"
                and child.get("ref-type") == "bibr"
            )

            if not (
                exclude_bibr
                and is_bibliographic_xref
            ):
                walk(
                    child
                )

            # 即使跳過 xref，
            # xref 後面的文字仍然必須留下
            if child.tail:
                parts.append(
                    child.tail
                )

    walk(
        element
    )

    return normalize_inline_text(
        " ".join(parts)
    )


# ============================================================
# 2. 找真正的 <article>
# ============================================================
#
# 支援：
#
# <article>
#
# 或：
#
# <OAI-PMH>
#   ...
#   <article>
#
# ============================================================

def find_article_root(root):

    if local_name(root) == "article":
        return root

    article = root.find(
        ".//{*}article"
    )

    if article is None:

        raise ValueError(
            "No JATS <article> element found."
        )

    return article


# ============================================================
# 3. 選擇主要 Abstract
# ============================================================
#
# 有些文章會同時存在：
#
# normal abstract
# short abstract
# graphical abstract
#
# 我們優先使用主要 Abstract，
# 避免把 short abstract 又算一次。
# ============================================================

def choose_primary_abstract(
    article_meta
):

    abstracts = article_meta.findall(
        "./{*}abstract"
    )

    if not abstracts:
        return None

    ignored_types = {
        "short",
        "toc",
        "graphical"
    }

    for abstract in abstracts:

        abstract_type = (
            abstract.get(
                "abstract-type",
                ""
            )
            .lower()
        )

        if abstract_type not in ignored_types:
            return abstract

    return abstracts[0]


# ============================================================
# 4. Abstract
# ============================================================
#
# 重要修正：
#
# 不再使用：
#
#     .findall(".//p")
#
# 因為 nested <p> 可能重複計算。
#
# 現在遇到一個 <p> 後：
#
#     抓整個 paragraph
#     然後停止往裡面找其他 <p>
#
# ============================================================

def extract_abstract(
    article_meta
):

    section_titles = []

    raw_paragraphs = []

    clean_paragraphs = []

    abstract = choose_primary_abstract(
        article_meta
    )

    if abstract is None:

        return (
            section_titles,
            raw_paragraphs,
            clean_paragraphs
        )

    # --------------------------------------------------------
    # Section Titles
    # --------------------------------------------------------

    for sec in abstract.findall(
        ".//{*}sec"
    ):

        title = sec.find(
            "./{*}title"
        )

        text = get_text(
            title
        )

        if text:

            section_titles.append(
                text
            )

    # --------------------------------------------------------
    # Paragraphs
    # --------------------------------------------------------

    def walk(element):

        for child in element:

            tag = local_name(
                child
            )

            if tag == "p":

                raw_text = get_text(
                    child,
                    exclude_bibr=False
                )

                clean_text = get_text(
                    child,
                    exclude_bibr=True
                )

                if raw_text:

                    raw_paragraphs.append(
                        raw_text
                    )

                    clean_paragraphs.append(
                        clean_text
                    )

                # 不繼續進入 nested p
                # 避免重複
                continue

            walk(
                child
            )

    walk(
        abstract
    )

    return (
        section_titles,
        raw_paragraphs,
        clean_paragraphs
    )


# ============================================================
# 5. Body
# ============================================================
#
# Body Paragraph：
#
# 保留 RAW
# 也建立 CLEAN
#
# Figure / Table / Definition List
# 不混入 Narrative Body。
# ============================================================

def extract_body(
    body_element
):

    section_titles = []

    raw_paragraphs = []

    clean_paragraphs = []

    if body_element is None:

        return (
            section_titles,
            raw_paragraphs,
            clean_paragraphs
        )

    skip_tags = {
        "fig",
        "table-wrap",
        "supplementary-material",
        "def-list"
    }

    def walk(
        element,
        parent_tag=None
    ):

        tag = local_name(
            element
        )

        # ----------------------------------------------------
        # 這些內容另外保存
        # ----------------------------------------------------

        if tag in skip_tags:
            return

        # ----------------------------------------------------
        # Section Title
        # ----------------------------------------------------

        if (
            tag == "title"
            and parent_tag == "sec"
        ):

            text = get_text(
                element
            )

            if text:

                section_titles.append(
                    text
                )

            return

        # ----------------------------------------------------
        # Paragraph
        # ----------------------------------------------------

        if tag == "p":

            raw_text = get_text(
                element,
                exclude_bibr=False
            )

            clean_text = get_text(
                element,
                exclude_bibr=True
            )

            if raw_text:

                raw_paragraphs.append(
                    raw_text
                )

                clean_paragraphs.append(
                    clean_text
                )

            return

        # ----------------------------------------------------
        # Recursive walk
        # ----------------------------------------------------

        for child in element:

            walk(
                child,
                tag
            )

    walk(
        body_element
    )

    return (
        section_titles,
        raw_paragraphs,
        clean_paragraphs
    )


# ============================================================
# 6. Definition / Abbreviation List
# ============================================================
#
# 例如：
#
# AD  → Alzheimer's disease
# MCI → Mild cognitive impairment
#
# 之前 PMC12382734 的 Abbreviation List
# 被誤當成 Body 第一段。
#
# 現在獨立保存。
# ============================================================

def extract_definitions(
    body_element
):

    definitions = []

    if body_element is None:
        return definitions

    for item in body_element.findall(
        ".//{*}def-list/{*}def-item"
    ):

        term = get_text(
            item.find(
                "./{*}term"
            )
        )

        definition = get_text(
            item.find(
                "./{*}def"
            ),
            exclude_bibr=True
        )

        if term or definition:

            definitions.append(
                {
                    "term": term,
                    "definition": definition
                }
            )

    return definitions


# ============================================================
# 7. Figures
# ============================================================

def extract_figures(
    article
):

    figures = []

    for fig in article.findall(
        ".//{*}fig"
    ):

        figures.append(
            {
                "label":
                    get_text(
                        fig.find(
                            "./{*}label"
                        )
                    ),

                "caption":
                    get_text(
                        fig.find(
                            "./{*}caption"
                        ),
                        exclude_bibr=True
                    )
            }
        )

    return figures


# ============================================================
# 8. Tables
# ============================================================

def extract_tables(
    article
):

    tables = []

    for table_wrap in article.findall(
        ".//{*}table-wrap"
    ):

        label = get_text(
            table_wrap.find(
                "./{*}label"
            )
        )

        caption = get_text(
            table_wrap.find(
                "./{*}caption"
            ),
            exclude_bibr=True
        )

        cells = []

        for cell_tag in (
            "th",
            "td"
        ):

            for cell in table_wrap.findall(
                f".//{{*}}{cell_tag}"
            ):

                text = get_text(
                    cell,
                    exclude_bibr=True
                )

                if text:

                    cells.append(
                        text
                    )

        tables.append(
            {
                "label":
                    label,

                "caption":
                    caption,

                "text":
                    " ".join(
                        cells
                    )
            }
        )

    return tables


# ============================================================
# 9. Acknowledgments
# ============================================================

def extract_acknowledgments(
    article
):

    results = []

    for ack in article.findall(
        ".//{*}back/{*}ack"
    ):

        text = get_text(
            ack,
            exclude_bibr=True
        )

        if text:

            results.append(
                text
            )

    return results


# ============================================================
# 10. References
# ============================================================

def extract_references(
    article
):

    references = []

    for ref in article.findall(
        ".//{*}ref-list/{*}ref"
    ):

        text = get_text(
            ref
        )

        if text:

            references.append(
                text
            )

    return references


# ============================================================
# 11. Authors
# ============================================================

def extract_authors(
    article_meta
):

    authors = []

    for contrib in article_meta.findall(
        ".//{*}contrib[@contrib-type='author']"
    ):

        surname = get_text(
            contrib.find(
                ".//{*}surname"
            )
        )

        given_names = get_text(
            contrib.find(
                ".//{*}given-names"
            )
        )

        full_name = (
            f"{given_names} {surname}"
        ).strip()

        if full_name:

            authors.append(
                full_name
            )

    return authors


# ============================================================
# 12. Affiliations
# ============================================================

def extract_affiliations(
    article_meta
):

    affiliations = []

    for aff in article_meta.findall(
        ".//{*}aff"
    ):

        text = get_text(
            aff
        )

        if (
            text
            and text not in affiliations
        ):

            affiliations.append(
                text
            )

    return affiliations


# ============================================================
# 13. Keywords
# ============================================================

def extract_keywords(
    article_meta
):

    keywords = []

    for keyword in article_meta.findall(
        ".//{*}kwd-group/{*}kwd"
    ):

        text = get_text(
            keyword
        )

        if text:

            keywords.append(
                text
            )

    return keywords


# ============================================================
# 14. Source Counts
# ============================================================
#
# 注意：
#
# 這些是 JATS 裡原本寫好的數字。
#
# 不是我們自己的統計結果。
# ============================================================

def get_reported_count(
    article_meta,
    tag_name
):

    element = article_meta.find(
        f".//{{*}}{tag_name}"
    )

    if element is None:
        return None

    value = element.get(
        "count"
    )

    if value is None:
        return None

    try:
        return int(
            value
        )

    except ValueError:
        return value


# ============================================================
# 15. 核心 Parser
# ============================================================

def _parse_jats_only(
    xml_file
):

    tree = ET.parse(
        xml_file
    )

    root = tree.getroot()

    article = find_article_root(
        root
    )

    front = article.find(
        "./{*}front"
    )

    if front is None:

        raise ValueError(
            "JATS article has no <front>."
        )

    article_meta = front.find(
        "./{*}article-meta"
    )

    if article_meta is None:

        raise ValueError(
            "JATS article has no <article-meta>."
        )

    # --------------------------------------------------------
    # Metadata Elements
    # --------------------------------------------------------

    pmcid_element = article_meta.find(
        "./{*}article-id[@pub-id-type='pmcid']"
    )

    pmid_element = article_meta.find(
        "./{*}article-id[@pub-id-type='pmid']"
    )

    doi_element = article_meta.find(
        "./{*}article-id[@pub-id-type='doi']"
    )

    journal_element = front.find(
        "./{*}journal-meta/"
        "{*}journal-title-group/"
        "{*}journal-title"
    )

    title_element = article_meta.find(
        "./{*}title-group/"
        "{*}article-title"
    )

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    authors = extract_authors(
        article_meta
    )

    affiliations = extract_affiliations(
        article_meta
    )

    keywords = extract_keywords(
        article_meta
    )

    # --------------------------------------------------------
    # Abstract
    # --------------------------------------------------------

    (
        abstract_section_titles,
        abstract_paragraphs,
        abstract_paragraphs_clean
    ) = extract_abstract(
        article_meta
    )

    # --------------------------------------------------------
    # Body
    # --------------------------------------------------------

    body_element = article.find(
        "./{*}body"
    )

    (
        section_titles,
        body_paragraphs,
        body_paragraphs_clean
    ) = extract_body(
        body_element
    )

    definitions = extract_definitions(
        body_element
    )

    # --------------------------------------------------------
    # Other Sections
    # --------------------------------------------------------

    figures = extract_figures(
        article
    )

    tables = extract_tables(
        article
    )

    acknowledgments = extract_acknowledgments(
        article
    )

    references = extract_references(
        article
    )

    # --------------------------------------------------------
    # Statistics Corpus
    # --------------------------------------------------------
    #
    # 這裡另外保留「統計專用全文」。
    #
    # Search Corpus 仍維持原本的 structured fields；
    # M03 ~ M05 的搜尋、位置與索引邏輯不受影響。
    # --------------------------------------------------------

    back_element = article.find(
        "./{*}back"
    )

    jats_statistics = build_jats_statistics_text(
        front=front,
        body=body_element,
        back=back_element
    )

    # --------------------------------------------------------
    # Structured Document
    # --------------------------------------------------------

    document = {

        "filename":
            Path(xml_file).name,

        # 原始 XML 格式
        "source_format":
            "JATS",

        "article_type":
            article.get(
                "article-type",
                ""
            ),

        "pmcid":
            get_text(
                pmcid_element
            ),

        "pmid":
            get_text(
                pmid_element
            ),

        "doi":
            get_text(
                doi_element
            ),

        "journal":
            get_text(
                journal_element
            ),

        "title":
            get_text(
                title_element
            ),

        "authors":
            authors,

        "affiliations":
            affiliations,

        "keywords":
            keywords,

        # Abstract RAW / CLEAN
        "abstract_section_titles":
            abstract_section_titles,

        "abstract_paragraphs":
            abstract_paragraphs,

        "abstract_paragraphs_clean":
            abstract_paragraphs_clean,

        "abstract":
            " ".join(
                abstract_paragraphs
            ),

        "abstract_clean":
            " ".join(
                abstract_paragraphs_clean
            ),

        # Body RAW / CLEAN
        "section_titles":
            section_titles,

        "body_paragraphs":
            body_paragraphs,

        "body_paragraphs_clean":
            body_paragraphs_clean,

        "body":
            " ".join(
                body_paragraphs
            ),

        "body_clean":
            " ".join(
                body_paragraphs_clean
            ),

        # Separate structured content
        "definitions":
            definitions,

        "figures":
            figures,

        "tables":
            tables,

        "acknowledgments":
            acknowledgments,

        "references":
            references,

        # ---------------------------------------------
        # Statistics Corpus
        # ---------------------------------------------
        #
        # JATS:
        #     Front (excluding permissions)
        #     + Body
        #     + Back
        #
        # 這組文字只用來做：
        #     Character / Word / Sentence Statistics
        #
        # 搜尋仍使用上面的 structured fields。
        # ---------------------------------------------

        "statistics_front_text":
            jats_statistics["front"],

        "statistics_body_text":
            jats_statistics["body"],

        "statistics_back_text":
            jats_statistics["back"],

        "statistics_text":
            jats_statistics["combined"],

        "statistics_scope":
            (
                "JATS front (excluding permissions) "
                "+ body + back"
            ),

        # JATS Source Counts
        "reported_word_count":
            get_reported_count(
                article_meta,
                "word-count"
            ),

        "reported_figure_count":
            get_reported_count(
                article_meta,
                "fig-count"
            ),

        "reported_table_count":
            get_reported_count(
                article_meta,
                "table-count"
            ),

        "reported_ref_count":
            get_reported_count(
                article_meta,
                "ref-count"
            ),

        "reported_page_count":
            get_reported_count(
                article_meta,
                "page-count"
            )
    }

    return document



# ============================================================
# 16. BioC XML 工具
# ============================================================
#
# BioC 官方核心結構：
#
# <collection>
#   <document>
#     <id>...</id>
#     <passage>
#       <infon key="type">title / abstract / paragraph ...</infon>
#       <offset>...</offset>
#       <text>...</text>
#     </passage>
#   </document>
# </collection>
#
# 本專案的策略：
#
# BioC XML
#     ↓
# M01 轉成與 JATS 相同的 Structured Document
#     ↓
# M02 ~ M06 不需要知道原始格式
#
# 注意：
# BioC 的 infon 是可延伸的 key-value，
# 不同 corpus 的 passage type 可能不同。
# 因此這裡優先支援 NCBI BioC / BioC-PMC 常見型態，
# 並對未知 passage 做保守 fallback。
# ============================================================


def get_bioc_infons(
    element
):

    infons = {}

    if element is None:
        return infons

    for infon in element.findall(
        "./{*}infon"
    ):

        key = (
            infon.get(
                "key",
                ""
            )
            .strip()
            .lower()
        )

        value = normalize_inline_text(
            infon.text
            or ""
        )

        if key:

            infons[key] = value

    return infons


def get_bioc_passage_text(
    passage
):

    text_element = passage.find(
        "./{*}text"
    )

    if (
        text_element is not None
        and text_element.text
    ):

        return normalize_inline_text(
            text_element.text
        )

    # 有些 BioC 可能只有 sentence/text
    sentence_texts = []

    for sentence in passage.findall(
        "./{*}sentence"
    ):

        sentence_text = sentence.find(
            "./{*}text"
        )

        text = normalize_inline_text(
            (
                sentence_text.text
                if sentence_text is not None
                else ""
            )
            or ""
        )

        if text:

            sentence_texts.append(
                text
            )

    return " ".join(
        sentence_texts
    )


def clean_embedded_bioc_markup(
    text
):

    if not text:
        return ""

    # BioC-PMC 的 table passage 有時可能把 PMC XML
    # 以文字形式放在 <text> 中。
    #
    # 只有看起來真的含有 XML/HTML tag 時才處理，
    # 避免一般數學符號 < > 被誤刪。
    if not re.search(
        r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^>]*)?>",
        text
    ):

        return normalize_inline_text(
            text
        )

    try:

        wrapped = ET.fromstring(
            f"<root>{text}</root>"
        )

        cleaned = " ".join(
            part.strip()
            for part in wrapped.itertext()
            if part.strip()
        )

        return normalize_inline_text(
            cleaned
        )

    except ET.ParseError:

        # 保守 fallback：
        # 只移除看起來像 tag 的片段。
        cleaned = re.sub(
            r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^>]*)?>",
            " ",
            text
        )

        return normalize_inline_text(
            cleaned
        )


def extract_bioc_author_infons(
    bioc_document
):

    authors = []

    for passage in bioc_document.findall(
        "./{*}passage"
    ):

        infons = get_bioc_infons(
            passage
        )

        section_type = (
            infons.get(
                "section_type",
                ""
            )
            or infons.get(
                "section-type",
                ""
            )
        ).strip().upper()

        passage_type = infons.get(
            "type",
            ""
        ).strip().lower()

        # NCBI BioC-PMC 的文章作者通常放在
        # TITLE / front passage 的 name_0, name_1...
        #
        # Reference passages 也會有 name_0, name_1，
        # 那些是「參考文獻作者」，不能混進文章作者。
        if not (
            section_type == "TITLE"
            or passage_type == "front"
        ):

            continue

        name_items = sorted(
            (
                key,
                value
            )
            for key, value in infons.items()
            if re.fullmatch(
                r"name_\d+",
                key
            )
        )

        for _, value in name_items:

            surname_match = re.search(
                r"(?:^|;)surname:([^;]+)",
                value
            )

            given_match = re.search(
                r"(?:^|;)given-names:([^;]+)",
                value
            )

            surname = (
                surname_match.group(1).strip()
                if surname_match
                else ""
            )

            given_names = (
                given_match.group(1).strip()
                if given_match
                else ""
            )

            full_name = (
                f"{given_names} {surname}"
            ).strip()

            if (
                full_name
                and full_name not in authors
            ):

                authors.append(
                    full_name
                )

    return authors


def find_bioc_document(
    root
):

    # BioC 單一 document 也可直接作為 root
    if (
        local_name(root) == "document"
        and root.find(
            "./{*}passage"
        ) is not None
    ):

        return root

    documents = root.findall(
        "./{*}document"
    )

    if not documents:

        documents = root.findall(
            ".//{*}document"
        )

    # 避免把一般 XML 的 <document> 誤認為 BioC
    documents = [
        document
        for document in documents
        if document.find(
            "./{*}passage"
        ) is not None
    ]

    if not documents:

        raise ValueError(
            "No BioC <document>/<passage> structure found."
        )

    # 目前整個 Pipeline 的一個上傳檔案 = 一篇文章。
    # 若一個 BioC collection 塞多篇，明確報錯，
    # 避免默默只讀第一篇造成錯誤統計。
    if len(documents) > 1:

        raise ValueError(
            "BioC XML contains multiple <document> elements. "
            "Please upload one BioC document per XML file."
        )

    return documents[0]


def detect_xml_format(
    xml_file
):

    tree = ET.parse(
        xml_file
    )

    root = tree.getroot()

    # --------------------------------------------------------
    # PubMed XML
    # --------------------------------------------------------
    # EFetch(db=pubmed, retmode=xml) returns PubmedArticleSet.
    # A saved single record may also use PubmedArticle as root.
    # --------------------------------------------------------

    root_name = local_name(root)

    if root_name == "PubmedArticleSet":
        return "PubMed"

    if (
        root_name == "PubmedArticle"
        and root.find("./{*}MedlineCitation") is not None
    ):
        return "PubMed"

    # --------------------------------------------------------
    # JATS
    # --------------------------------------------------------
    #
    # 不再只看到 <article> 就直接判定為 JATS。
    #
    # 因為一般 XML 也可能使用 <article> 這個 tag。
    # 只有同時具有 JATS 典型的：
    #
    #     <front>
    #       <article-meta>
    #
    # 才判定為 JATS。
    # --------------------------------------------------------

    article_candidates = []

    if local_name(root) == "article":

        article_candidates.append(
            root
        )

    article_candidates.extend(
        root.findall(
            ".//{*}article"
        )
    )

    for article in article_candidates:

        front = article.find(
            "./{*}front"
        )

        if (
            front is not None
            and front.find(
                "./{*}article-meta"
            ) is not None
        ):

            return "JATS"

    # --------------------------------------------------------
    # BioC
    # --------------------------------------------------------

    if (
        local_name(root) == "collection"
        and root.find(
            "./{*}document/{*}passage"
        ) is not None
    ):

        return "BioC"

    if (
        local_name(root) == "document"
        and root.find(
            "./{*}passage"
        ) is not None
    ):

        return "BioC"

    # --------------------------------------------------------
    # Generic XML fallback
    # --------------------------------------------------------
    #
    # 只要 XML 本身是合法 XML，
    # 但不是 JATS / BioC，
    # 就交給 Generic XML Parser。
    #
    # 目的：
    #     教授若臨時放入其他 XML schema，
    #     系統仍可擷取可見文字並進行全文搜尋。
    # --------------------------------------------------------

    return "GenericXML"


# ============================================================
# 17. BioC Passage 分類
# ============================================================

BIOC_BODY_SECTION_TYPES = {
    "intro",
    "introduction",
    "methods",
    "method",
    "materials",
    "materials_methods",
    "materials and methods",
    "results",
    "discussion",
    "discuss",
    "conclusion",
    "conclusions",
    "concl",
    "background",
    "case",
    "supplement",
}


def classify_bioc_passage(
    passage_type,
    section_type,
    title_already_found
):

    passage_type = (
        passage_type
        or ""
    ).strip().lower()

    section_type = (
        section_type
        or ""
    ).strip().lower()

    combined = (
        f"{passage_type} {section_type}"
    )

    # --------------------------------------------------------
    # Article Title
    # --------------------------------------------------------

    if (
        passage_type
        in {
            "title",
            "article-title",
            "article_title"
        }
        or section_type == "title"
    ):

        if not title_already_found:

            return "title"

        # 第二個以上 title 通常較可能是 section title
        return "section_title"

    # --------------------------------------------------------
    # Abstract
    # --------------------------------------------------------

    if (
        "abstract" in combined
    ):

        if (
            "title" in passage_type
            or "title" in section_type
        ):

            return "abstract_section_title"

        return "abstract"

    # --------------------------------------------------------
    # Author / Affiliation / Keyword
    # --------------------------------------------------------

    if (
        "author" in combined
        and "reference" not in combined
    ):

        return "author"

    if (
        "affiliation" in combined
        or passage_type == "aff"
    ):

        return "affiliation"

    if (
        "keyword" in combined
        or passage_type == "kwd"
    ):

        return "keyword"

    # --------------------------------------------------------
    # References
    # --------------------------------------------------------

    if (
        passage_type
        in {
            "ref",
            "reference",
            "references"
        }
        or section_type
        in {
            "ref",
            "reference",
            "references"
        }
    ):

        return "reference"

    # --------------------------------------------------------
    # Acknowledgments
    # --------------------------------------------------------

    if (
        passage_type
        in {
            "ack",
            "acknowledgment",
            "acknowledgement",
            "acknowledgments",
            "acknowledgements"
        }
        or section_type
        in {
            "ack",
            "acknowledgment",
            "acknowledgement"
        }
    ):

        return "acknowledgment"

    # --------------------------------------------------------
    # Figure
    # --------------------------------------------------------

    if (
        "fig" in passage_type
        or section_type == "fig"
        or "figure" in section_type
    ):

        if (
            "label" in passage_type
        ):

            return "figure_label"

        return "figure_caption"

    # --------------------------------------------------------
    # Table
    # --------------------------------------------------------

    if (
        "table" in passage_type
        or section_type == "table"
    ):

        if (
            "label" in passage_type
        ):

            return "table_label"

        if (
            "caption" in passage_type
            or "title" in passage_type
        ):

            return "table_caption"

        return "table_text"

    # --------------------------------------------------------
    # Section Title
    # --------------------------------------------------------

    if (
        passage_type
        in {
            "section_title",
            "section-title",
            "sectitle",
            "subtitle"
        }
        or (
            "title" in passage_type
            and title_already_found
        )
    ):

        return "section_title"

    # --------------------------------------------------------
    # Definition
    # --------------------------------------------------------

    if (
        "definition" in combined
        or passage_type
        in {
            "def",
            "definition"
        }
    ):

        return "definition"

    # --------------------------------------------------------
    # Front / metadata passage
    #
    # 不把整段 front 直接塞入 body，
    # 避免 metadata 重複進搜尋。
    # --------------------------------------------------------

    if (
        passage_type == "front"
        or section_type == "front"
    ):

        return "front"

    # --------------------------------------------------------
    # Body
    #
    # NCBI BioC-PMC 常見 type=paragraph，
    # section_type 再指出 INTRO / METHODS / RESULTS...
    # --------------------------------------------------------

    if (
        passage_type
        in {
            "paragraph",
            "body",
            "text",
            "p"
        }
        or section_type in BIOC_BODY_SECTION_TYPES
    ):

        return "body"

    # --------------------------------------------------------
    # 未知 Passage：
    #
    # 有文字時保守視為 body，避免老師給的 BioC
    # 使用其他自訂 type 而整段漏掉。
    # --------------------------------------------------------

    return "body"


# ============================================================
# 18. BioC Parser
# ============================================================

def parse_bioc(
    xml_file
):

    tree = ET.parse(
        xml_file
    )

    root = tree.getroot()

    bioc_document = find_bioc_document(
        root
    )

    document_infons = get_bioc_infons(
        bioc_document
    )

    document_id_element = bioc_document.find(
        "./{*}id"
    )

    document_id = normalize_inline_text(
        (
            document_id_element.text
            if document_id_element is not None
            else ""
        )
        or ""
    )

    # --------------------------------------------------------
    # BioC Metadata
    # --------------------------------------------------------
    #
    # NCBI BioC-PMC 的 article metadata 常放在「第一個 passage」
    # 的 <infon>，例如：
    #
    #   article-id_pmc  = 10665088
    #   article-id_pmid = 38053812
    #   article-id_doi  = ...
    #
    # 不一定放在 <document> 本身。
    # 因此先整合 document infon + 所有 passage infon。
    # --------------------------------------------------------

    all_bioc_infons = dict(
        document_infons
    )

    for passage in bioc_document.findall(
        "./{*}passage"
    ):

        passage_infons_for_metadata = get_bioc_infons(
            passage
        )

        for key, value in passage_infons_for_metadata.items():

            if (
                value
                and key not in all_bioc_infons
            ):

                all_bioc_infons[key] = value

    pmcid = (
        all_bioc_infons.get(
            "pmcid",
            ""
        )
        or all_bioc_infons.get(
            "pmc",
            ""
        )
        or all_bioc_infons.get(
            "article-id_pmc",
            ""
        )
        or all_bioc_infons.get(
            "article_id_pmc",
            ""
        )
    )

    # NCBI BioC-PMC 常只存數字 10665088，
    # UI / JATS 端則使用 PMC10665088。
    if pmcid:

        pmcid = pmcid.strip()

        if (
            pmcid.isdigit()
        ):

            pmcid = (
                "PMC"
                + pmcid
            )

        elif not pmcid.upper().startswith(
            "PMC"
        ):

            pmc_match = re.search(
                r"PMC\d+",
                pmcid,
                flags=re.IGNORECASE
            )

            if pmc_match:

                pmcid = pmc_match.group(
                    0
                ).upper()

    pmid = (
        all_bioc_infons.get(
            "pmid",
            ""
        )
        or all_bioc_infons.get(
            "article-id_pmid",
            ""
        )
        or all_bioc_infons.get(
            "article_id_pmid",
            ""
        )
    )

    doi = (
        all_bioc_infons.get(
            "doi",
            ""
        )
        or all_bioc_infons.get(
            "article_doi",
            ""
        )
        or all_bioc_infons.get(
            "article-id_doi",
            ""
        )
        or all_bioc_infons.get(
            "article_id_doi",
            ""
        )
    )

    journal = (
        all_bioc_infons.get(
            "journal",
            ""
        )
        or all_bioc_infons.get(
            "journal-title",
            ""
        )
        or all_bioc_infons.get(
            "journal_title",
            ""
        )
    )

    article_type = (
        all_bioc_infons.get(
            "article-type",
            ""
        )
        or all_bioc_infons.get(
            "article_type",
            ""
        )
        or "bioc"
    )

    # --------------------------------------------------------
    # document <id> 只做 fallback。
    #
    # NCBI BioC-PMC 的 <document><id> 有時是「PMC 數字部分」
    # （例如 10665088），不能直接假設它是 PMID。
    # --------------------------------------------------------

    if (
        not pmcid
        and document_id.upper().startswith(
            "PMC"
        )
    ):

        pmcid = document_id.upper()

    if (
        not pmcid
        and not pmid
        and document_id.isdigit()
    ):

        # 無其他 metadata 時才保留舊 fallback。
        pmid = document_id

    # --------------------------------------------------------
    # 統一輸出欄位
    # --------------------------------------------------------

    title = ""

    authors = extract_bioc_author_infons(
        bioc_document
    )

    affiliations = []

    keywords = []

    abstract_section_titles = []

    abstract_paragraphs = []

    abstract_paragraphs_clean = []

    section_titles = []

    body_paragraphs = []

    body_paragraphs_clean = []

    definitions = []

    figures = []

    tables = []

    acknowledgments = []

    references = []

    # 統計專用：每個 BioC passage 的可見文字只收一次，
    # 避免用 structured fields 重新拼接時重複計算。
    statistics_passage_texts = []

    # --------------------------------------------------------
    # 每個 passage
    # --------------------------------------------------------

    for passage in bioc_document.findall(
        "./{*}passage"
    ):

        passage_infons = get_bioc_infons(
            passage
        )

        passage_type = passage_infons.get(
            "type",
            ""
        )

        section_type = (
            passage_infons.get(
                "section_type",
                ""
            )
            or passage_infons.get(
                "section-type",
                ""
            )
        )

        text = get_bioc_passage_text(
            passage
        )

        if not text:
            continue

        category = classify_bioc_passage(
            passage_type,
            section_type,
            bool(title)
        )

        # Table text may contain embedded PMC XML markup.
        if category == "table_text":

            text = clean_embedded_bioc_markup(
                text
            )

        statistics_passage_texts.append(
            text
        )

        # ----------------------------------------------------
        # Article title
        # ----------------------------------------------------

        if category == "title":

            if not title:
                title = text

            else:
                section_titles.append(
                    text
                )

        # ----------------------------------------------------
        # Abstract
        # ----------------------------------------------------

        elif category == "abstract":

            abstract_paragraphs.append(
                text
            )

            # BioC passage text 已沒有 JATS inline bibr tag，
            # RAW / CLEAN 先保持相同。
            abstract_paragraphs_clean.append(
                text
            )

        elif category == "abstract_section_title":

            abstract_section_titles.append(
                text
            )

        # ----------------------------------------------------
        # Metadata-like passages
        # ----------------------------------------------------

        elif category == "author":

            if text not in authors:
                authors.append(
                    text
                )

        elif category == "affiliation":

            if text not in affiliations:
                affiliations.append(
                    text
                )

        elif category == "keyword":

            if text not in keywords:
                keywords.append(
                    text
                )

        # ----------------------------------------------------
        # Body
        # ----------------------------------------------------

        elif category == "section_title":

            section_titles.append(
                text
            )

        elif category == "body":

            body_paragraphs.append(
                text
            )

            body_paragraphs_clean.append(
                text
            )

        # ----------------------------------------------------
        # Definitions
        # ----------------------------------------------------

        elif category == "definition":

            definitions.append(
                {
                    "term":
                        "",

                    "definition":
                        text
                }
            )

        # ----------------------------------------------------
        # Figures
        # ----------------------------------------------------

        elif category == "figure_label":

            figures.append(
                {
                    "label":
                        text,

                    "caption":
                        ""
                }
            )

        elif category == "figure_caption":

            figures.append(
                {
                    "label":
                        "",

                    "caption":
                        text
                }
            )

        # ----------------------------------------------------
        # Tables
        # ----------------------------------------------------

        elif category == "table_label":

            tables.append(
                {
                    "label":
                        text,

                    "caption":
                        "",

                    "text":
                        ""
                }
            )

        elif category == "table_caption":

            tables.append(
                {
                    "label":
                        "",

                    "caption":
                        text,

                    "text":
                        ""
                }
            )

        elif category == "table_text":

            tables.append(
                {
                    "label":
                        "",

                    "caption":
                        "",

                    "text":
                        text
                }
            )

        # ----------------------------------------------------
        # Acknowledgments / References
        # ----------------------------------------------------

        elif category == "acknowledgment":

            acknowledgments.append(
                text
            )

        elif category == "reference":

            references.append(
                text
            )

        # front 不重複塞入正文
        elif category == "front":

            pass

    # --------------------------------------------------------
    # 若 BioC passage 沒提供明確 title，
    # 仍保留一個可辨識名稱。
    # --------------------------------------------------------

    if not title:

        title = (
            document_infons.get(
                "title",
                ""
            )
            or document_id
            or Path(xml_file).stem
        )

    # --------------------------------------------------------
    # 某些 BioC corpus 會把 metadata 放在 document infon。
    # --------------------------------------------------------

    author_infon = (
        document_infons.get(
            "author",
            ""
        )
        or document_infons.get(
            "authors",
            ""
        )
    )

    if (
        author_infon
        and author_infon not in authors
    ):

        authors.append(
            author_infon
        )

    keyword_infon = (
        document_infons.get(
            "keyword",
            ""
        )
        or document_infons.get(
            "keywords",
            ""
        )
    )

    if (
        keyword_infon
        and keyword_infon not in keywords
    ):

        keywords.append(
            keyword_infon
        )

    # --------------------------------------------------------
    # Statistics Corpus
    # --------------------------------------------------------

    bioc_statistics_text = normalize_statistics_text(
        " ".join(
            statistics_passage_texts
        )
    )

    # --------------------------------------------------------
    # Structured Document
    #
    # 欄位名稱與 JATS Parser 完全對齊，
    # 讓 M02 ~ M06 不需要改核心介面。
    # --------------------------------------------------------

    document = {

        "filename":
            Path(xml_file).name,

        "source_format":
            "BioC",

        "article_type":
            article_type,

        "pmcid":
            pmcid,

        "pmid":
            pmid,

        "doi":
            doi,

        "journal":
            journal,

        "title":
            title,

        "authors":
            authors,

        "affiliations":
            affiliations,

        "keywords":
            keywords,

        # Abstract RAW / CLEAN
        "abstract_section_titles":
            abstract_section_titles,

        "abstract_paragraphs":
            abstract_paragraphs,

        "abstract_paragraphs_clean":
            abstract_paragraphs_clean,

        "abstract":
            " ".join(
                abstract_paragraphs
            ),

        "abstract_clean":
            " ".join(
                abstract_paragraphs_clean
            ),

        # Body RAW / CLEAN
        "section_titles":
            section_titles,

        "body_paragraphs":
            body_paragraphs,

        "body_paragraphs_clean":
            body_paragraphs_clean,

        "body":
            " ".join(
                body_paragraphs
            ),

        "body_clean":
            " ".join(
                body_paragraphs_clean
            ),

        # Separate structured content
        "definitions":
            definitions,

        "figures":
            figures,

        "tables":
            tables,

        "acknowledgments":
            acknowledgments,

        "references":
            references,

        # ---------------------------------------------
        # Statistics Corpus
        # ---------------------------------------------

        "statistics_front_text":
            "",

        "statistics_body_text":
            bioc_statistics_text,

        "statistics_back_text":
            "",

        "statistics_text":
            bioc_statistics_text,

        "statistics_scope":
            "All visible BioC passage text",

        # BioC 標準本身沒有 JATS counts 這組欄位。
        # 後續 M02 會自動使用 Computed Word Count。
        "reported_word_count":
            None,

        "reported_figure_count":
            None,

        "reported_table_count":
            None,

        "reported_ref_count":
            None,

        "reported_page_count":
            None
    }

    return document



# ============================================================
# 19. Generic XML Fallback
# ============================================================
#
# 用途：
#
#     合法 XML
#     但不是 JATS / BioC
#
# 策略：
#
#     Generic XML
#         ↓
#     擷取所有可見文字
#         ↓
#     轉成與 JATS / BioC 相同的 Structured Document
#         ↓
#     M02 ~ M06 照常運作
#
# 注意：
#
# Generic XML 沒有標準的 PMCID / DOI / Abstract / Reference
# 語意，因此不假裝理解未知 schema。
#
# 我們只保證：
#
#     「文字可以被擷取、建立索引、搜尋與定位」
#
# ============================================================


def find_first_generic_title(
    root
):

    title_names = {
        "title",
        "article-title",
        "article_title",
        "document-title",
        "document_title",
        "name",
    }

    for element in root.iter():

        if (
            local_name(element).lower()
            in title_names
        ):

            text = normalize_inline_text(
                " ".join(
                    part
                    for part in element.itertext()
                    if part
                )
            )

            if text:

                return (
                    element,
                    text
                )

    return (
        None,
        ""
    )


def collect_generic_xml_text(
    root,
    excluded_element=None
):

    parts = []

    def walk(
        node
    ):

        # 若這個節點被當成 title，
        # 不再把它重複塞進 body。
        if node is excluded_element:

            if node.tail:

                parts.append(
                    node.tail
                )

            return

        if node.text:

            parts.append(
                node.text
            )

        for child in node:

            walk(
                child
            )

            if (
                child is not excluded_element
                and child.tail
            ):

                parts.append(
                    child.tail
                )

    # root 本身沒有 parent，
    # 所以另外處理，避免 tail 重複。
    if root is excluded_element:

        return ""

    if root.text:

        parts.append(
            root.text
        )

    for child in root:

        if child is excluded_element:

            if child.tail:

                parts.append(
                    child.tail
                )

            continue

        # 子樹內的 tail 由 walk() 處理；
        # 這裡只走子節點本身。
        if child.text:

            parts.append(
                child.text
            )

        for descendant in child:

            # 這裡不用直接迭代 descendant，
            # 交給下方 helper 會比較安全。
            pass

        # 改用一個小型遞迴，從 child 的 children 開始
        def walk_children(
            node
        ):

            for sub in node:

                if sub is excluded_element:

                    if sub.tail:

                        parts.append(
                            sub.tail
                        )

                    continue

                if sub.text:

                    parts.append(
                        sub.text
                    )

                walk_children(
                    sub
                )

                if sub.tail:

                    parts.append(
                        sub.tail
                    )

        walk_children(
            child
        )

        if child.tail:

            parts.append(
                child.tail
            )

    return normalize_inline_text(
        " ".join(parts)
    )


def parse_generic_xml(
    xml_file
):

    tree = ET.parse(
        xml_file
    )

    root = tree.getroot()

    (
        title_element,
        title
    ) = find_first_generic_title(
        root
    )

    full_text = collect_generic_xml_text(
        root,
        excluded_element=title_element
    )

    # 如果沒有明確 <title> 類型欄位，
    # 用檔名當 UI 顯示名稱。
    if not title:

        title = Path(
            xml_file
        ).stem

    body_paragraphs = (
        [full_text]
        if full_text
        else []
    )

    generic_statistics_text = normalize_statistics_text(
        " ".join(
            text
            for text in (
                title,
                full_text
            )
            if text
        )
    )

    document = {

        "filename":
            Path(xml_file).name,

        "source_format":
            "GenericXML",

        "article_type":
            "generic_xml",

        "pmcid":
            "",

        "pmid":
            "",

        "doi":
            "",

        "journal":
            "",

        "title":
            title,

        "authors":
            [],

        "affiliations":
            [],

        "keywords":
            [],

        "abstract_section_titles":
            [],

        "abstract_paragraphs":
            [],

        "abstract_paragraphs_clean":
            [],

        "abstract":
            "",

        "abstract_clean":
            "",

        "section_titles":
            [],

        "body_paragraphs":
            body_paragraphs,

        "body_paragraphs_clean":
            body_paragraphs.copy(),

        "body":
            full_text,

        "body_clean":
            full_text,

        "definitions":
            [],

        "figures":
            [],

        "tables":
            [],

        "acknowledgments":
            [],

        "references":
            [],

        # ---------------------------------------------
        # Statistics Corpus
        # ---------------------------------------------

        "statistics_front_text":
            "",

        "statistics_body_text":
            generic_statistics_text,

        "statistics_back_text":
            "",

        "statistics_text":
            generic_statistics_text,

        "statistics_scope":
            "All visible Generic XML text",

        "reported_word_count":
            None,

        "reported_figure_count":
            None,

        "reported_table_count":
            None,

        "reported_ref_count":
            None,

        "reported_page_count":
            None
    }

    return document



# ============================================================
# 19. PubMed / PMID INPUT
# ============================================================
#
# Professor demo path:
#
# README.txt
#     ↓
# PMID
#     ↓
# NCBI EFetch (db=pubmed, retmode=xml)
#     ↓
# PubMed XML
#     ↓
# Structured Document
#
# PubMed mode in this project intentionally uses Abstract as the
# Statistics Corpus and Search Corpus.  Title / Authors / Journal /
# DOI are retained as metadata for display, but are not mixed into
# the Abstract text statistics/search scope.
# ============================================================

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)


def extract_pmids_from_text(text):
    """Extract PMIDs from a README-style text file.

    Supported examples:
        PMID: 12345678
        PMID 12345678
        https://pubmed.ncbi.nlm.nih.gov/12345678/
        12345678          (standalone line)

    Duplicates are removed while preserving the original order.
    """

    if not text:
        return []

    candidates = []

    # Explicit PMID labels are the strongest signal.
    candidates.extend(
        re.findall(
            r"(?i)\bPMID\s*[:#=]?\s*(\d+)\b",
            text,
        )
    )

    # PubMed URLs inside README files.
    candidates.extend(
        re.findall(
            r"(?i)pubmed\.ncbi\.nlm\.nih\.gov/(\d+)",
            text,
        )
    )

    # Standalone numeric lines are common in classroom README files.
    for line in text.splitlines():
        stripped = line.strip().strip(",;")
        if re.fullmatch(r"\d+", stripped):
            candidates.append(stripped)

    # If the file is just a compact comma/space-separated PMID list,
    # accept numeric tokens of realistic PMID length as a fallback.
    if not candidates:
        candidates.extend(
            re.findall(r"\b\d{5,10}\b", text)
        )

    pmids = []
    seen = set()

    for value in candidates:
        pmid = value.strip()
        if not pmid or pmid in seen:
            continue
        seen.add(pmid)
        pmids.append(pmid)

    return pmids


def read_pmids_from_readme(readme_file):
    """Read a local README.txt and return PMIDs."""

    path = Path(readme_file)
    text = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    return extract_pmids_from_text(text)


def fetch_pubmed_xml(pmids, timeout=30):
    """Fetch PubMed records as XML using the official NCBI EFetch API."""

    cleaned_pmids = []

    for pmid in pmids:
        value = str(pmid).strip()
        if not re.fullmatch(r"\d+", value):
            raise ValueError(
                f"Invalid PMID: {pmid}"
            )
        cleaned_pmids.append(value)

    if not cleaned_pmids:
        raise ValueError(
            "No PMID found in README.txt."
        )

    params = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "id": ",".join(cleaned_pmids),
            "retmode": "xml",
            "tool": "keyword_full_text_matching",
        }
    )

    request = urllib.request.Request(
        f"{PUBMED_EFETCH_URL}?{params}",
        headers={
            "User-Agent": (
                "KeywordFullTextMatching/1.0 "
                "(educational project)"
            )
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            return response.read()

    except Exception as error:
        raise RuntimeError(
            "Unable to fetch PubMed records from NCBI EFetch: "
            f"{error}"
        ) from error


def _pubmed_text(element):
    """Visible text of a PubMed XML element, preserving inline markup text."""

    if element is None:
        return ""

    return normalize_inline_text(
        " ".join(
            part
            for part in element.itertext()
            if part
        )
    )


def _pubmed_article_ids(pubmed_article):
    ids = {}

    for element in pubmed_article.findall(
        "./{*}PubmedData/{*}ArticleIdList/{*}ArticleId"
    ):
        id_type = (
            element.get("IdType", "")
            .strip()
            .lower()
        )
        value = _pubmed_text(element)
        if id_type and value:
            ids[id_type] = value

    return ids


def _pubmed_authors(article):
    authors = []

    for author in article.findall(
        "./{*}AuthorList/{*}Author"
    ):
        collective = _pubmed_text(
            author.find("./{*}CollectiveName")
        )

        if collective:
            full_name = collective
        else:
            surname = _pubmed_text(
                author.find("./{*}LastName")
            )
            given = _pubmed_text(
                author.find("./{*}ForeName")
            )
            if not given:
                given = _pubmed_text(
                    author.find("./{*}Initials")
                )

            full_name = (
                f"{given} {surname}"
            ).strip()

        if full_name and full_name not in authors:
            authors.append(full_name)

    return authors


def _pubmed_affiliations(article):
    affiliations = []

    for element in article.findall(
        ".//{*}AffiliationInfo/{*}Affiliation"
    ):
        text = _pubmed_text(element)
        if text and text not in affiliations:
            affiliations.append(text)

    return affiliations


def _pubmed_keywords(medline_citation):
    keywords = []

    for element in medline_citation.findall(
        "./{*}KeywordList/{*}Keyword"
    ):
        text = _pubmed_text(element)
        if text and text not in keywords:
            keywords.append(text)

    return keywords


def _pubmed_display_label(label):
    """Convert PubMed structured-abstract labels to readable UI text."""

    label = normalize_inline_text(
        (label or "").replace("_", " ")
    )

    if not label:
        return ""

    # NLM may use technical placeholders when no meaningful heading exists.
    if label.upper() in {
        "UNASSIGNED",
        "UNLABELLED",
        "UNLABELED",
    }:
        return ""

    if label.isupper():
        return label.title()

    return label


def _pubmed_abstract(article):
    """Return labels, paragraphs, and paired structured-abstract sections.

    PubMed structured abstracts store headings in attributes such as:

        <AbstractText Label="BACKGROUND">...</AbstractText>

    The previous parser kept the text but lost the label-to-text pairing.
    This version preserves that structure for later UI rendering while the
    label itself is NOT mixed into the Abstract statistics/search corpus.
    """

    section_titles = []
    paragraphs = []
    sections = []

    abstract = article.find(
        "./{*}Abstract"
    )

    if abstract is None:
        return section_titles, paragraphs, sections

    for abstract_text in abstract.findall(
        "./{*}AbstractText"
    ):
        xml_label = (
            abstract_text.get("Label", "")
            or ""
        ).strip()

        nlm_category = (
            abstract_text.get("NlmCategory", "")
            or ""
        ).strip()

        raw_label = xml_label or nlm_category
        display_label = _pubmed_display_label(
            raw_label
        )

        text = _pubmed_text(
            abstract_text
        )

        if not text:
            continue

        if display_label:
            section_titles.append(
                display_label
            )

        paragraphs.append(
            text
        )

        sections.append(
            {
                "label": display_label,
                "raw_label": raw_label,
                "nlm_category": nlm_category,
                "text": text,
            }
        )

    return section_titles, paragraphs, sections


def parse_pubmed_article_element(
    pubmed_article,
    source_name="PubMed EFetch",
):
    """Convert one <PubmedArticle> into the project's Structured Document."""

    medline_citation = pubmed_article.find(
        "./{*}MedlineCitation"
    )

    if medline_citation is None:
        raise ValueError(
            "PubMed record has no <MedlineCitation>."
        )

    article = medline_citation.find(
        "./{*}Article"
    )

    if article is None:
        raise ValueError(
            "PubMed record has no <Article>."
        )

    pmid = _pubmed_text(
        medline_citation.find("./{*}PMID")
    )

    if not pmid:
        raise ValueError(
            "PubMed record has no PMID."
        )

    article_ids = _pubmed_article_ids(
        pubmed_article
    )

    pmcid = article_ids.get(
        "pmc",
        "",
    )

    doi = article_ids.get(
        "doi",
        "",
    )

    if not doi:
        for location_id in article.findall(
            "./{*}ELocationID"
        ):
            if (
                location_id.get("EIdType", "")
                .strip()
                .lower()
                == "doi"
            ):
                doi = _pubmed_text(location_id)
                break

    title = _pubmed_text(
        article.find("./{*}ArticleTitle")
    )

    journal = _pubmed_text(
        article.find("./{*}Journal/{*}Title")
    )

    authors = _pubmed_authors(article)
    affiliations = _pubmed_affiliations(article)
    keywords = _pubmed_keywords(medline_citation)

    publication_types = [
        _pubmed_text(element)
        for element in article.findall(
            "./{*}PublicationTypeList/{*}PublicationType"
        )
        if _pubmed_text(element)
    ]

    (
        abstract_section_titles,
        abstract_paragraphs,
        abstract_sections,
    ) = _pubmed_abstract(article)

    abstract_text = normalize_statistics_text(
        " ".join(abstract_paragraphs)
    )

    # Professor's PubMed demo scope:
    # only the visible Abstract text block enters Statistics/Search.
    document = {
        "filename": f"PMID_{pmid}.xml",
        "source_name": source_name,
        "source_format": "PubMed",
        "article_type": (
            "; ".join(publication_types)
            if publication_types
            else "pubmed"
        ),
        "pmcid": pmcid,
        "pmid": pmid,
        "doi": doi,
        "journal": journal,
        "title": title,
        "authors": authors,
        "affiliations": affiliations,
        "keywords": keywords,

        "abstract_section_titles": abstract_section_titles,
        "abstract_sections": abstract_sections,
        "abstract_paragraphs": abstract_paragraphs,
        "abstract_paragraphs_clean": abstract_paragraphs.copy(),
        "abstract": abstract_text,
        "abstract_clean": abstract_text,

        # PubMed citation records do not provide PMC full-text body here.
        "section_titles": [],
        "body_paragraphs": [],
        "body_paragraphs_clean": [],
        "body": "",
        "body_clean": "",
        "definitions": [],
        "figures": [],
        "tables": [],
        "acknowledgments": [],
        "references": [],

        # Statistics Corpus = Abstract only.
        "statistics_front_text": "",
        "statistics_body_text": abstract_text,
        "statistics_back_text": "",
        "statistics_text": abstract_text,
        "statistics_scope": "PubMed Abstract only",

        # PubMed citation XML does not provide JATS article counts.
        "reported_word_count": None,
        "reported_figure_count": None,
        "reported_table_count": None,
        "reported_ref_count": None,
        "reported_page_count": None,
    }

    return document


def parse_pubmed_xml_bytes(
    xml_bytes,
    source_name="PubMed EFetch",
):
    """Parse one or more PubMed records returned by EFetch."""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise ValueError(
            f"Invalid PubMed XML: {error}"
        ) from error

    if local_name(root) == "PubmedArticle":
        article_elements = [root]
    else:
        article_elements = root.findall(
            "./{*}PubmedArticle"
        )

        if not article_elements:
            article_elements = root.findall(
                ".//{*}PubmedArticle"
            )

    if not article_elements:
        raise ValueError(
            "No <PubmedArticle> record found in PubMed XML."
        )

    return [
        parse_pubmed_article_element(
            element,
            source_name=source_name,
        )
        for element in article_elements
    ]


def parse_pubmed_file(xml_file):
    """Parse a saved PubMed XML file containing exactly one article."""

    path = Path(xml_file)
    documents = parse_pubmed_xml_bytes(
        path.read_bytes(),
        source_name=path.name,
    )

    if len(documents) != 1:
        raise ValueError(
            "PubMed XML contains multiple articles. "
            "Use README/PMID batch loading for multiple records."
        )

    return documents[0]


def fetch_pubmed_documents(
    pmids,
    timeout=30,
    source_name="README.txt",
):
    """Fetch PMIDs and return (documents, missing_pmids)."""

    requested = []
    seen = set()

    for value in pmids:
        pmid = str(value).strip()
        if not re.fullmatch(r"\d+", pmid):
            raise ValueError(
                f"Invalid PMID: {value}"
            )
        if pmid not in seen:
            seen.add(pmid)
            requested.append(pmid)

    xml_bytes = fetch_pubmed_xml(
        requested,
        timeout=timeout,
    )

    documents = parse_pubmed_xml_bytes(
        xml_bytes,
        source_name=source_name,
    )

    by_pmid = {
        document["pmid"]: document
        for document in documents
    }

    ordered_documents = [
        by_pmid[pmid]
        for pmid in requested
        if pmid in by_pmid
    ]

    missing_pmids = [
        pmid
        for pmid in requested
        if pmid not in by_pmid
    ]

    return ordered_documents, missing_pmids


def load_pubmed_documents_from_readme_text(
    readme_text,
    timeout=30,
    source_name="README.txt",
):
    """README text → PMID list → PubMed records → Structured Documents."""

    pmids = extract_pmids_from_text(
        readme_text
    )

    if not pmids:
        raise ValueError(
            "README.txt does not contain a recognizable PMID."
        )

    return fetch_pubmed_documents(
        pmids,
        timeout=timeout,
        source_name=source_name,
    )


# ============================================================
# 19. 對外統一入口
# ============================================================
#
# 為了不修改 M02 ~ M06 原本：
#
#     from m01_jats_parser import parse_jats
#
# 這個函式名稱暫時保留。
#
# 但它現在實際上是：
#
#     XML Auto Detector / Dispatcher
#
# JATS → 原本 JATS Parser
# BioC → BioC Parser
# ============================================================

def parse_jats(
    xml_file
):

    xml_format = detect_xml_format(
        xml_file
    )

    if xml_format == "PubMed":

        return parse_pubmed_file(
            xml_file
        )

    if xml_format == "JATS":

        return _parse_jats_only(
            xml_file
        )

    if xml_format == "BioC":

        return parse_bioc(
            xml_file
        )

    if xml_format == "GenericXML":

        return parse_generic_xml(
            xml_file
        )

    raise ValueError(
        f"Unsupported XML format: {xml_format}"
    )



# ============================================================
# 16. Parser Test
# ============================================================

if __name__ == "__main__":

    xml_files = sorted(
        DATA_DIR.glob(
            "*.xml"
        )
    )

    print(
        "=" * 85
    )

    print(
        "MODULE 1 - JATS / BioC PARSER TEST"
    )

    print(
        f"Found {len(xml_files)} XML files"
    )

    print(
        "=" * 85
    )

    for xml_file in xml_files:

        try:

            document = parse_jats(
                xml_file
            )

            print()

            print(
                f"File              : "
                f"{document['filename']}"
            )

            print(
                f"Source Format     : "
                f"{document.get('source_format', 'JATS')}"
            )

            print(
                f"PMCID             : "
                f"{document['pmcid']}"
            )

            print(
                f"Article Type      : "
                f"{document['article_type']}"
            )

            print(
                f"Abstract Paragraph: "
                f"{len(document['abstract_paragraphs'])}"
            )

            print(
                f"Body Paragraph    : "
                f"{len(document['body_paragraphs'])}"
            )

            print(
                f"Definitions       : "
                f"{len(document['definitions'])}"
            )

            print(
                f"Figures           : "
                f"{len(document['figures'])}"
            )

            print(
                f"Tables            : "
                f"{len(document['tables'])}"
            )

            print(
                f"References        : "
                f"{len(document['references'])}"
            )

            print(
                f"Statistics Scope  : "
                f"{document.get('statistics_scope', '')}"
            )

            print(
                f"Statistics Words  : "
                f"{len(document.get('statistics_text', '').split())}"
            )

            print(
                f"JATS Word Count   : "
                f"{document['reported_word_count']}"
            )

            print(
                "-" * 85
            )

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

            print(
                "-" * 85
            )