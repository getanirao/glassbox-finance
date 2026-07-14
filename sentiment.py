"""FinBERT ONNX sentiment scorer with LM lexicon fallback."""
import os
import re
import json
import numpy as np
from config import BUSINESS_RISK_SENTIMENT_FLOOR, FINBERT_TEMPERATURE, MODEL_DIR

_NEGATION_WORDS = {"not", "no", "never", "neither", "nor", "t"}
_BUSINESS_RISK_PATTERNS = [
    re.compile(r"\blos(?:e|es|ing|t)\s+(viewers|subscribers|users|customers|market\s+share|traffic|revenue|sales)\b"),
    re.compile(r"\b(viewer|subscriber|user|customer|revenue|sales)\s+loss(?:es)?\b"),
    re.compile(r"\b(viewership|subscribers?|users?|customers?|traffic|revenue|sales)\s+(decline|declines|declined|fall|falls|fell|drop|drops|dropped)\b"),
    re.compile(r"\b(churn|cancellations?|downgrades?)\s+(rise|rises|rose|increase|increases|increased)\b"),
]


class FinBERTScorer:
    def __init__(self, model_dir=None):
        self.model_dir = model_dir
        self._session = None
        self._tokenizer = None
        self._pos_idx = 2
        self._neg_idx = 0

    def _ensure_loaded(self):
        if self._session is not None:
            return
        if not self.model_dir or not os.path.isdir(self.model_dir):
            self._session = False
            return
        qp = os.path.join(self.model_dir, "finbert_quantized.onnx")
        if not os.path.isfile(qp):
            self._session = False
            return
        try:
            import onnxruntime
            from transformers import AutoTokenizer
            self._session = onnxruntime.InferenceSession(
                qp, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
            cfgp = os.path.join(self.model_dir, "config.json")
            if os.path.isfile(cfgp):
                with open(cfgp) as f:
                    cfg = json.load(f)
                id2label = cfg.get("id2label", {})
                for k, v in id2label.items():
                    if v.lower() == "positive":
                        self._pos_idx = int(k)
                    elif v.lower() == "negative":
                        self._neg_idx = int(k)
        except Exception as exc:
            print(f"[sentiment] ONNX load failed: {exc}")
            self._session = False

    def score(self, headline):
        """Return (net_score, pos_prob, neg_prob).

        net_score in [-1, 1]; pos_prob/neg_prob in [0, 1].
        Falls back to LM lexicon if ONNX unavailable.
        """
        self._ensure_loaded()
        if self._session:
            return _apply_business_risk_floor(headline, *self._score_onnx(headline))
        return _apply_business_risk_floor(headline, *self._score_lm(headline))

    def _score_onnx(self, headline):
        inputs = self._tokenizer(
            headline,
            return_tensors="np",
            truncation=True,
            max_length=128,
        )
        logits = self._session.run(None, {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
        })[0]
        logits = logits / FINBERT_TEMPERATURE
        exp = np.exp(logits - logits.max(axis=-1, keepdims=True))
        probs = exp / exp.sum(axis=-1, keepdims=True)
        pos = float(probs[0, self._pos_idx])
        neg = float(probs[0, self._neg_idx])
        return (pos - neg, pos, neg)

    def _score_lm(self, headline):
        from config import POSITIVE_LEXICON, NEGATIVE_LEXICON, CRITICAL_NEGATIVE_LEXICON
        words = re.findall(r"[a-z]+", headline.lower())
        tokens = [w for w in words if len(w) > 1]
        pos = 0.0
        neg = 0.0
        for i, t in enumerate(tokens):
            if t in CRITICAL_NEGATIVE_LEXICON:
                neg += 1.5
            elif t in POSITIVE_LEXICON:
                if any(tokens[j] in _NEGATION_WORDS for j in range(max(0, i - 3), i)):
                    neg += 1
                else:
                    pos += 1
            elif t in NEGATIVE_LEXICON:
                if any(tokens[j] in _NEGATION_WORDS for j in range(max(0, i - 3), i)):
                    pos += 1
                else:
                    neg += 1
        total = pos + neg
        if total == 0:
            return (0.0, 0.0, 0.0)
        return ((pos - neg) / total, pos / total, neg / total)


_SCORER = None


def get_scorer(model_dir=None):
    global _SCORER
    if model_dir is None:
        model_dir = MODEL_DIR
    if _SCORER is None:
        _SCORER = FinBERTScorer(model_dir=model_dir)
    return _SCORER


def score_headline(headline, model_dir=None):
    return get_scorer(model_dir=model_dir).score(headline)


def _apply_business_risk_floor(headline, net, pos, neg):
    text = " ".join(re.findall(r"[a-z]+", headline.lower()))
    if any(pattern.search(text) for pattern in _BUSINESS_RISK_PATTERNS):
        net = min(net, BUSINESS_RISK_SENTIMENT_FLOOR)
        neg = max(neg, abs(BUSINESS_RISK_SENTIMENT_FLOOR))
        pos = max(0.0, neg + net)
    return net, pos, neg
