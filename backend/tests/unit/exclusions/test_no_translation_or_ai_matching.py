"""§49 EX-08, EX-11: nothing is translated, and nothing needs a model to be matched.

Language is a property of a Source Track, kept as the source gave it (INV-02). OneShelf never renders a
work in a language its source did not publish, and matching is local, explainable and evidence-based —
there is no model to call, no key to hold, and nothing that degrades when offline.
"""
import importlib.util
import re

from .conftest import code_lines, frontend_sources, python_sources

TRANSLATION_PACKAGES = ["googletrans", "deep_translator", "translate", "argostranslate", "libretranslate",
                        "translators", "mtranslate"]
AI_PACKAGES = ["openai", "anthropic", "transformers", "torch", "sentence_transformers", "sklearn",
               "tensorflow", "llama_cpp", "onnxruntime", "spacy", "gensim", "faiss"]
# `str.translate` normalises digits and is not language translation, so this names what translation and
# embedding code actually needs: a target language, a model, or a hosted endpoint.
CALLS = re.compile(r"\b(translate_text|detect_language|target_language|source_language|translate_to|"
                   r"embeddings?|cosine_similarity|chat\.completions|generate_text)\b|"
                   r"api\.openai\.com|api\.anthropic\.com|huggingface", re.IGNORECASE)


def test_no_translation_engine_is_installed():
    assert [n for n in TRANSLATION_PACKAGES if importlib.util.find_spec(n) is not None] == []


def test_no_model_runtime_or_hosted_model_client_is_installed():
    assert [n for n in AI_PACKAGES if importlib.util.find_spec(n) is not None] == []


def test_nothing_in_the_product_translates_or_embeds_anything():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources() + frontend_sources()) if CALLS.search(line)]
    assert offenders == []


def test_matching_decides_from_evidence_rather_than_a_score_from_a_model():
    """What binds a listing to a work is named evidence or a user decision, never an opaque score (§6)."""
    grouping = next(p for p in python_sources() if p.name == "grouping.py")
    text = grouping.read_text(encoding="utf-8")
    assert 'decided_by: str = "evidence"' in text
    assert not re.search(r"\b(model|inference|predict|embedding)\b", text, re.IGNORECASE)
