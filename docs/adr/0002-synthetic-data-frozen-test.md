# ADR 0002: Synthetic Indonesian documents and a test set frozen before training

- Status: accepted
- Date: 2026-10-11

## Context

The PRD forbids using other people's real documents. Public receipt datasets (SROIE, CORD) are English or Korean/Indonesian with licences to check, and none covers Indonesian invoices with NPWP and PPN. Without labelled data there is no evaluation.

## Decision

- Generate documents from HTML/CSS templates rendered by PyMuPDF's Story engine (no browser), with labels written by the generator: 8 receipt, 6 invoice and 7 "other" templates, Indonesian vocabulary, eight date formats and seven amount formats.
- Degrade every document: phone photo (perspective, rotation, uneven light), flatbed scan, or faded thermal print, then blur, noise and JPEG.
- Hold out one template per type and a separate pool of vendor-name words for `test_unseen`, to measure generalisation instead of memorised layouts.
- Freeze the test splits immediately after generation: `ml/data/frozen.json` stores split digests, and `check_frozen()` re-hashes every test file before any evaluation.
- Tune heuristics only on `train`, choose thresholds only on `val`.

## Consequences

- Results describe the generator's distribution. Every report says so, and results on real documents must be measured and reported separately before any claim about them.
- Any change to the generator changes the data; regenerating with the frozen seed must reproduce the same digests, or evaluation refuses to run.
