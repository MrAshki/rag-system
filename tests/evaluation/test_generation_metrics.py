from evaluation.metrics.generation import aggregate_generation, normalize_text, score_generation


def test_generation_normalizes_persian_digits_and_characters():
    assert normalize_text("کی ۰٫۸۷") == normalize_text("كي 0٫87")


def test_generation_detects_concepts_forbidden_claims_and_false_refusal():
    task = {
        "acceptable_answers": ["بازیافت پساب دیالیز، ۰٫۸۷"],
        "required_concepts": ["بازیافت پساب دیالیز", "۰٫۸۷"],
        "forbidden_claims": ["رتبه دوم"],
        "answerability": "answerable",
    }
    good = score_generation(task, "بازیافت پساب دیالیز، ۰٫۸۷")
    bad = score_generation(task, "در سند اطلاعات کافی نیست.")
    assert good["required_concept_coverage"] == 1
    assert good["acceptable_answer_match"] is True
    assert bad["false_refusal"] is True
    assert aggregate_generation([good, bad])["false_refusal_rate"]["numerator"] == 1
