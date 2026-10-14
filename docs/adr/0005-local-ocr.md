# ADR 0005: PaddleOCR models through ONNX Runtime as the default OCR

- Status: accepted
- Date: 2026-10-11

## Context

The PRD lists Tesseract and PaddleOCR. The PaddlePaddle runtime is heavy and has no wheels for the local Python (3.14); the demo must run on a small CPU server.

## Decision

Use RapidOCR, which runs the PP-OCR detection and recognition models on ONNX Runtime, as the default engine (`rapidocr`), with word boxes. Tesseract (`ind+eng`) is implemented behind the same interface and installed in the Docker image for experiment E1. Digital PDFs skip OCR and use their text layer. ONNX Runtime threads are capped (`DOKUDATA_OCR_THREADS`, default 2) so several workers do not oversubscribe the CPU.

## Consequences

- One A4 page takes about 2-4 s on a laptop CPU; receipts are faster.
- Tesseract results appear in the report only when the binary is available where the evaluation runs.
