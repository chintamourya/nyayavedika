# Credits

Reused design and code ideas, re-implemented on permissive libraries:

| Source | Reused as |
|---|---|
| `backend-case-pdf-main/server/ocr_pipeline/casepdf_ocr_pipeline.py` | Per-page OCR-needed heuristic and Tesseract word-confidence filter (`nyayavedika/ocr.py`), re-implemented on permissive libraries |
| `backend-case-search-prod/summarizer/*` | Issue → ISSUE / KEY POINTS / DECISION design (Document Analyst synthesis) |
| `backend-case-search-prod/workflow_agents/*validator*`, `court_classifer.py` | Verify step; structured classification with fallback |
| `casechat-backend/source/readPDFv2.py`, `llm_v2.py` | Chunking, legal-document check, file ids, JSON parsing, map-reduce and timeline schema |
| `Case-Draft-Backend/source/prompts.py`, `GenAI.py` | Drafting prompts and the case-detail extraction schema |

Azure services, Google Document AI, AWS Textract and PyMuPDF (AGPL) were deliberately not used.
