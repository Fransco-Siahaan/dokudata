#!/usr/bin/env bash
# Build the OCR cache used by training and evaluation (resumable: finished files are skipped).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/Scripts/python}
W=${WORKERS:-4}
$PY -m ml.evaluation.ocr_cache --splits train,val --variants primary --workers "$W"
$PY -m ml.evaluation.ocr_cache --splits test_seen,test_unseen,injection --variants clean,degraded --workers "$W"
$PY -m ml.evaluation.ocr_cache --splits test_seen,test_unseen --variants clean,degraded --no-preprocess --workers "$W"
echo ALL_DONE
