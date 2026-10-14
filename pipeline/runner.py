"""End-to-end pipeline: load -> preprocess -> OCR -> classify -> extract -> validate -> confidence -> decision."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pipeline.classify import load_classifier
from pipeline.confidence import CONF_FIELDS, ConfidenceModel, HeuristicConfidence, decide, field_features
from pipeline.config import MODELS_DIR, decision_config
from pipeline.extract.llm import OCRLLMExtractor, VisionLLMExtractor
from pipeline.extract.rules import RulesExtractor
from pipeline.interfaces import ClassificationResult, ExtractionInput, ExtractionResult, OCRDocument
from pipeline.llm import LLMClient, LLMError
from pipeline.ocr import get_ocr_engine, pdf_text_layer, run_ocr
from pipeline.preprocess import PreprocessInfo, PreprocessOptions, load_images, preprocess
from pipeline.preprocess.image import PDF_DPI
from pipeline.safety import find_injection
from pipeline.schema import DocumentResult, Extraction, FieldValue, ValidationFinding
from pipeline.validate import validate

EXTRACTORS = ["rules", "llm_ocr", "llm_vision"]


def get_extractor(name: str, llm_client: LLMClient | None = None) -> Any:
    if name == "rules":
        return RulesExtractor()
    if name == "llm_ocr":
        return OCRLLMExtractor(llm_client)
    if name == "llm_vision":
        return VisionLLMExtractor(llm_client)
    raise ValueError(f"unknown extractor {name!r}")


@dataclass
class PipelineConfig:
    ocr_engine: str = "rapidocr"
    extractor: str = "rules"
    # A cheap second opinion; agreement between methods is a strong confidence signal.
    cross_check: bool = True
    classifier: str = "tfidf"
    preprocess: bool = True
    use_pdf_text: bool = True
    max_pages: int = 10


@dataclass
class PipelineOutput:
    result: DocumentResult
    pages: list[np.ndarray]
    ocr: OCRDocument | None
    classification: ClassificationResult
    primary: ExtractionResult
    preprocess_info: list[PreprocessInfo] = field(default_factory=list)
    features: dict[str, list[float]] = field(default_factory=dict)


StageCallback = Callable[[str], None]


class Pipeline:
    def __init__(self, config: PipelineConfig | None = None, llm_client: LLMClient | None = None) -> None:
        self.config = config or PipelineConfig()
        self.llm_client = llm_client
        self._ocr: Any = None
        self.classifier = load_classifier(self.config.classifier)
        path = MODELS_DIR / "confidence.joblib"
        self.confidence: Any = ConfidenceModel.load(path) if path.exists() else HeuristicConfidence()
        self.thresholds = decision_config()

    @property
    def ocr_engine(self) -> Any:
        if self._ocr is None:
            self._ocr = get_ocr_engine(self.config.ocr_engine)
        return self._ocr

    def run(self, data: bytes, mime: str, on_stage: StageCallback | None = None) -> PipelineOutput:
        stage = on_stage or (lambda _s: None)
        timings: dict[str, float] = {}

        def timed(name: str, t0: float) -> None:
            timings[name] = round((time.perf_counter() - t0) * 1000, 1)

        stage("preprocessing")
        t0 = time.perf_counter()
        raw_pages = load_images(data, mime, max_pages=self.config.max_pages, dpi=PDF_DPI)
        ocr: OCRDocument | None = None
        infos: list[PreprocessInfo] = []
        if mime == "application/pdf" and self.config.use_pdf_text:
            ocr = pdf_text_layer(data, dpi=PDF_DPI)
        if ocr is not None:
            pages = raw_pages  # digital PDF: keep geometry so text-layer boxes line up with the page images
            infos = [PreprocessInfo(steps=["pdf_text_layer"]) for _ in pages]
        else:
            opts = (
                PreprocessOptions()
                if self.config.preprocess
                else PreprocessOptions(False, False, False, False)
            )
            processed = [preprocess(p, opts) for p in raw_pages]
            pages = [p for p, _ in processed]
            infos = [i for _, i in processed]
        timed("preprocess", t0)

        stage("ocr")
        t0 = time.perf_counter()
        if ocr is None:
            ocr = run_ocr(self.ocr_engine, pages)
        timed("ocr", t0)

        return self.run_from_ocr(pages, ocr, stage, timings, infos)

    def run_from_ocr(
        self,
        pages: list[np.ndarray],
        ocr: OCRDocument | None,
        stage: StageCallback | None = None,
        timings: dict[str, float] | None = None,
        infos: list[PreprocessInfo] | None = None,
    ) -> PipelineOutput:
        stage = stage or (lambda _s: None)
        timings = timings if timings is not None else {}
        text = ocr.text if ocr else ""

        stage("classifying")
        t0 = time.perf_counter()
        cls = self.classifier.predict(text)
        timings["classify"] = round((time.perf_counter() - t0) * 1000, 1)

        stage("extracting")
        t0 = time.perf_counter()
        inp = ExtractionInput(pages, ocr, cls.label)
        flags: list[str] = []
        secondary: Extraction | None = None
        cost = 0.0
        engines = {"ocr": ocr.engine if ocr else "none", "classifier": cls.engine}
        try:
            primary = get_extractor(self.config.extractor, self.llm_client).extract(inp)
            cost += primary.cost_usd
        except LLMError as exc:
            # The LLM is optional: fall back to rules and send the document to review.
            flags.append(f"Mesin {self.config.extractor} gagal ({exc}); memakai aturan")
            primary = RulesExtractor().extract(inp)
        engines["extractor"] = primary.engine
        if primary.meta.get("model"):
            engines["llm_model"] = str(primary.meta["model"])
        if self.config.cross_check and primary.engine != "rules" and ocr is not None:
            secondary = RulesExtractor().extract(inp).extraction
            engines["cross_check"] = "rules"
        timings["extract"] = round((time.perf_counter() - t0) * 1000, 1)

        stage("validating")
        t0 = time.perf_counter()
        ex = primary.extraction
        findings = validate(ex)
        injection_hits = find_injection(text)
        if injection_hits or primary.meta.get("suspicious_instructions"):
            flags.append(
                "Dokumen berisi teks yang mencoba memberi instruksi ke sistem (kemungkinan prompt injection)"
            )
        grounded = primary.meta.get("grounded") or {}
        ungrounded = [f for f, ok in grounded.items() if not ok]
        if ungrounded and ocr is not None:
            findings.append(
                ValidationFinding(
                    rule="values_present_in_document",
                    status="warning",
                    fields=ungrounded,
                    detail="Nilai tidak ditemukan pada teks dokumen: " + ", ".join(ungrounded),
                )
            )
        timings["validate"] = round((time.perf_counter() - t0) * 1000, 1)

        t0 = time.perf_counter()
        feats = field_features(ex, findings, ocr, cls.confidence, secondary, bool(injection_hits))
        x = np.array([feats[f] for f in CONF_FIELDS])
        probs = self.confidence.predict(x)
        field_conf = {f: round(float(p), 4) for f, p in zip(CONF_FIELDS, probs, strict=True)}
        for f, p in field_conf.items():
            if f == "line_items":
                for li in ex.line_items:
                    li.confidence = round(min(p, li.confidence or p), 4) if li.confidence else p
            else:
                ex.field(f).confidence = p
        decision = decide(
            cls.label,
            cls.confidence,
            ex,
            findings,
            field_conf,
            float(self.thresholds["field_threshold"]),
            float(self.thresholds["classifier_threshold"]),
            flags,
        )
        timings["confidence"] = round((time.perf_counter() - t0) * 1000, 1)
        result = DocumentResult(
            document_type=FieldValue(value=cls.label, confidence=round(cls.confidence, 4), source=cls.engine),
            extraction=ex,
            validation=findings,
            decision=decision.decision,  # type: ignore[arg-type]
            decision_reasons=decision.reasons,
            document_confidence=decision.document_confidence,
            engines=engines,
            timings_ms=timings,
            cost_usd=round(cost, 6),
            flags=flags,
            thresholds={
                "field": float(self.thresholds["field_threshold"]),
                "classifier": float(self.thresholds["classifier_threshold"]),
            },
        )
        return PipelineOutput(result, pages, ocr, cls, primary, infos or [], feats)
