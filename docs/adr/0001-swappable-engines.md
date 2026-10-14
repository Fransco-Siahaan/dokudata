# ADR 0001: Every engine behind one interface

- Status: accepted
- Date: 2026-10-11

## Context

The portfolio's main claim is a measured comparison of approaches (rules, OCR + LLM, vision LLM) and of OCR engines and classifiers. If each approach had its own code path through the API and the evaluation, the comparison would compare plumbing as much as methods.

## Decision

`pipeline/interfaces.py` defines three protocols, `OCREngine.recognize(image) -> OCRPage`, `Classifier.predict(text) -> ClassificationResult` and `Extractor.extract(ExtractionInput) -> ExtractionResult`, and every implementation returns the same `Extraction` schema (`pipeline/schema.py`). The API worker and the evaluation harness both build engines from names (`PipelineConfig`, `get_extractor`, `get_ocr_engine`, `load_classifier`).

## Consequences

- Switching method is a configuration change (`engine=llm_ocr` on upload, `--engines` in evaluation).
- Validation, confidence and the review screen work unchanged for every extractor.
- An LLM failure degrades to the rules extractor in one place (`Pipeline.run_from_ocr`).
