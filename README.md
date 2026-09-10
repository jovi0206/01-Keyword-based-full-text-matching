# Keyword-based Full-Text Matching

A web-based full-text retrieval prototype for biomedical XML documents.

## Features

- Supports JATS XML and BioC XML
- Automatic XML format detection
- Article statistics
  - Character count
  - Word count
  - Sentence count
- Rule-based sentence segmentation using pySBD
- Positional inverted index
- Exact word search
- Lexical variant search
- Exact phrase search
- Proximity phrase search
- Exact sentence search
- Ordered proximity sentence search
- Literal substring fallback
- Match position visualization
  - Field
  - Word Position
  - Sentence Position
  - Character Position
- Article Viewer with Previous / Next match navigation

## Architecture

XML Upload
→ Parser
→ Text Processing
→ Position Mapping
→ Positional Index
→ Query Engine
→ Search Results / Article Viewer

## Modules

src/
- m01_jats_parser.py
- m02_text_processor.py
- m03_position_mapper.py
- m04_index_builder.py
- m05_query_engine.py
- m06_app.py

## Supported XML Formats

### JATS XML
PMC JATS articles and OAI-PMH wrapped JATS XML.

### BioC XML
BioC / NCBI BioC-PMC documents are converted into the same internal document structure as JATS.

## Word Count

If JATS provides a source <word-count>, the reported value is displayed.

If no source word count exists, the system calculates a Computed Word Count from the main article content.

References are searchable but are not included in the article statistics word count.

## Run

`powershell
python -m streamlit run .\src\m06_app.py


Dependencies
Python 3.12
Streamlit
pySBD
Purpose

This project was developed for the Keyword-based Full-Text Matching assignment in an Information Retrieval course.

The retrieval design is inspired by PubMed / PMC search concepts, but this is a lightweight educational implementation and not a complete PMC ATM / MeSH / UMLS system.
