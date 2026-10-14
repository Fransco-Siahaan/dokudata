# Model Card: DokuData Extraction v0.1

> Generated from evaluation run `20261011-061006`. Numbers are measured on the frozen synthetic test set; see [evaluation-report.md](evaluation-report.md).

## Intended use

- Turning Indonesian receipts (nota/struk) and invoices (faktur) into structured data for bookkeeping exports, with a human reviewing every document the system is not sure about.
- **Out of scope:** medical or highly sensitive documents, handwriting-heavy notes, legal decisions, unattended export of money data without the validation and review gates.

## Components

| Component | Model | Trained on |
|---|---|---|
| OCR | PP-OCR detection + recognition (RapidOCR, ONNX Runtime) | pre-trained, not fine-tuned |
| Document type | TF-IDF + regresi logistik on OCR text | train split (1,200 docs) |
| Field extraction A | rules and layout heuristics | tuned on train documents only |
| Field extraction B / C | Claude (`claude-opus-5` by default) with a strict JSON schema | not trained (prompted) |
| Field confidence | logistic regression on 13 signals + field one-hot, isotonic calibration | train split; calibration chosen on val |

## Data

Synthetic documents only (no real person's or company's documents): 8 receipt, 6 invoice and 7 other templates, Indonesian vocabulary, fake NPWP numbers, clean and degraded (photo, scan, faded thermal) variants. `test_unseen` holds out one template per type and a separate vendor-name pool.

## Results (metode A, test set)

| Metric | Value |
|---|--:|
| Document type macro-F1 | 1.000 |
| F1 total | 0.975 |
| F1 vendor, date, total | 0.962 |
| F1 tax and document number | 0.977 |
| F1 line items | 0.966 |
| Documents fully correct | 81.9% |
| Auto-approved / accuracy of auto-approved | 29.7% / 97.0% |
| ECE of calibrated field confidence | 0.0076 |

Performance by condition (F1 total / vendor):

| Subset | Total | Vendor | Doc fully correct |
|---|--:|--:|--:|
| Dikenal · bersih | 0.993 | 0.993 | 93.8% |
| Dikenal · terdegradasi | 0.979 | 0.983 | 81.9% |
| Baru · bersih | 1.000 | 0.863 | 82.5% |
| Baru · terdegradasi | 0.912 | 0.713 | 60.0% |

## Limitations and risks

- Measured on synthetic data only; performance on real documents is unknown and expected to be lower.
- New layouts and degraded photos are the weakest conditions (see the subset table). With the validation-chosen threshold, new layouts are never auto-approved (safe, no automation), while some wrong documents from degraded photos of known layouts still pass; see the per-subset decision table in the evaluation report.
- Small or faint text (including injected instructions) can be missed by OCR.
- Methods B/C send document content to an external LLM provider and cost money per document.

## Mitigations

- Arithmetic and format validation, OCR grounding of every value, calibrated confidence and a human review queue; nothing is exported as validated without passing those gates or a review.
- Prompt-injection scanner plus the LLM's own flag force review; the LLM has no tools.
- Uploads deleted after 24 hours, never used for training.

## Re-running

`make data && make ocr && make train && make evaluate` (see the README).
