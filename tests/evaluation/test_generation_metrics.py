from evaluation.metrics.generation import (
    aggregate_generation,
    concept_match,
    normalize_text,
    score_generation,
)


def test_generation_normalizes_persian_digits_and_characters():
    assert normalize_text("کی ۰٫۸۷") == normalize_text("كي 0٫87")
    assert normalize_text("امتیاز 87/0 [S1]") == normalize_text("امتیاز ۰٫۸۷")


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


def test_correct_paraphrase_and_citation_markers_pass():
    task = {
        "query": "مهم‌ترین گزینه و امتیازش چیست؟",
        "acceptable_answers": ["دیالیز با امتیاز ۰٫۸۷ رتبه نخست است"],
        "required_concepts": ["بازیافت پساب دیالیز", "۰٫۸۷", "رتبه اول"],
        "forbidden_claims": [],
        "answerability": "answerable",
    }
    score = score_generation(
        task,
        "اولویت نخست، بازیافتِ پساب دیالیز با امتیاز 0.87 است. [S9]",
    )
    assert score["acceptable_answer_match"] is True
    assert score["required_concept_coverage"] == 1.0


def test_missing_fact_and_partial_answer_do_not_receive_full_credit():
    task = {
        "query": "چند خبره و چند عامل؟",
        "acceptable_answers": ["۳۷ خبره و ۱۵ عامل"],
        "required_concepts": ["۳۷ خبره", "۱۵ عامل"],
        "forbidden_claims": [],
        "answerability": "answerable",
    }
    score = score_generation(task, "۳۷ خبره مصاحبه شدند.")
    assert score["required_concept_coverage"] == 0.5
    assert score["acceptable_answer_match"] is False


def test_wrong_number_and_wrong_named_entity_fail_despite_lexical_overlap():
    numeric = {
        "query": "امتیاز دیالیز چیست؟",
        "acceptable_answers": ["دیالیز ۰٫۸۷"],
        "required_concepts": ["دیالیز", "۰٫۸۷"],
        "forbidden_claims": [],
        "answerability": "answerable",
    }
    entity = {
        "query": "کدام پروژه ۱۵ مهر تحویل می‌شود؟",
        "acceptable_answers": ["پروژه آلفا در ۱۵ مهر"],
        "required_concepts": ["پروژه آلفا", "۱۵ مهر"],
        "forbidden_claims": [],
        "answerability": "answerable",
    }
    assert score_generation(numeric, "دیالیز با امتیاز ۰٫۷۸ است.")["acceptable_answer_match"] is False
    assert score_generation(entity, "پروژه بتا در ۱۵ مهر تحویل می‌شود.")["acceptable_answer_match"] is False


def test_contradiction_and_irrelevant_lexical_overlap_fail():
    task = {
        "query": "آیا آلفا ۱۵ مهر تحویل می‌شود؟",
        "acceptable_answers": ["آلفا ۱۵ مهر تحویل می‌شود"],
        "required_concepts": ["آلفا", "۱۵ مهر"],
        "forbidden_claims": ["آلفا ۱۵ مهر تحویل نمی‌شود"],
        "answerability": "answerable",
    }
    contradiction = score_generation(
        task,
        "آلفا در ۱۵ مهر تحویل نمی‌شود؛ موعد صحیح بتا است.",
    )
    irrelevant = score_generation(
        task,
        "این گزارش درباره تحویل، برنامه و مهر سازمانی توضیح می‌دهد.",
    )
    assert contradiction["acceptable_answer_match"] is False
    assert contradiction["forbidden_claim"] is True
    assert irrelevant["acceptable_answer_match"] is False


def test_false_refusal_fails_but_topic_specific_true_refusal_passes():
    answerable = {
        "query": "مرخصی چند روز است؟",
        "acceptable_answers": ["۲۶ روز"],
        "required_concepts": ["۲۶ روز"],
        "forbidden_claims": [],
        "answerability": "answerable",
    }
    unanswerable = {
        "query": "نرخ اضافه‌کاری چقدر است؟",
        "acceptable_answers": ["سند درباره اضافه‌کاری حکمی ندارد"],
        "required_concepts": ["اضافه‌کاری"],
        "forbidden_claims": [],
        "answerability": "unanswerable",
    }
    false_refusal = score_generation(answerable, "در سند اطلاعات کافی نیست.")
    generic_refusal = score_generation(unanswerable, "در سند اطلاعات کافی نیست.")
    supported_refusal = score_generation(
        unanswerable,
        "سند درباره اضافه‌کاری اطلاعاتی ندارد.",
    )
    assert false_refusal["false_refusal"] is True
    assert false_refusal["acceptable_answer_match"] is False
    assert generic_refusal["acceptable_answer_match"] is False
    assert supported_refusal["refusal_correct"] is True
    assert supported_refusal["acceptable_answer_match"] is True


def test_persian_and_latin_number_formats_are_equivalent_but_not_reversed_integers():
    assert concept_match("ضریب 0.82 است", "۰٫۸۲")
    assert concept_match("ضریب 82/0 است", "۰٫۸۲")
    assert concept_match("۳/۶ درصد ارجاع شدند", "۳٫۶ درصد")
    assert not concept_match("3/6 of the sample", "3.6")
    assert not concept_match("مهلت ۵۱ دقیقه است", "۱۵ دقیقه")


def test_cross_language_technical_phrase_equivalence_is_safe_and_exact():
    task = {
        "query": "چه زمانی rollback انجام می‌شود؟",
        "answerability": "answerable",
        "acceptable_answers": [],
        "required_concepts": ["error rate", "previous stable version", "۱۵ دقیقه", "۳٪"],
        "forbidden_claims": [],
    }
    scored = score_generation(
        task,
        "اگر نرخ خطا در ۱۵ دقیقه از ۳٪ بیشتر شود، سیستم به نسخه پایدار قبلی بازمی‌گردد.",
    )
    assert scored["acceptable_answer_match"]
    assert scored["required_concept_coverage"] == 1.0


def test_safe_surface_paraphrases_for_attendance_and_protocol_forms_pass():
    attendance = {
        "query": "حضورگرایی چیست؟",
        "answerability": "answerable",
        "acceptable_answers": [],
        "required_concepts": ["حضور در محل کار", "با وجود بیماری", "مرخصی"],
        "forbidden_claims": [],
    }
    forms = {
        "query": "سه شکل نسخه‌نویسی چیست؟",
        "answerability": "answerable",
        "acceptable_answers": [],
        "required_concepts": ["مستقل", "مکمل", "پروتکل‌های گروهی"],
        "forbidden_claims": [],
    }
    assert score_generation(
        attendance,
        "فرد با وجود بیماری در محل کار حاضر می‌شود، وقتی باید استراحت کند و از کار غایب باشد.",
    )["acceptable_answer_match"]
    assert score_generation(
        forms,
        "سه شکل مستقل، تکمیلی و پروتکلی گزارش شده است.",
    )["acceptable_answer_match"]


def test_review_method_transliteration_and_no_answer_paraphrases_are_bounded():
    assert concept_match("مرور بر پایه آرکس و اومالی انجام شد.", "Arksey و O'Malley")
    no_answer = {
        "query": "در مرحله سوم از کدام برند واکسن استفاده شد؟",
        "answerability": "unanswerable",
        "acceptable_answers": [],
        "required_concepts": ["اطلاعات موجود نیست"],
        "forbidden_claims": [],
    }
    scored = score_generation(
        no_answer,
        "سند انتخاب‌شده دربارهٔ «برند واکسن» اطلاعات کافی برای پاسخ قابل‌اعتماد ارائه نمی‌کند.",
    )
    assert scored["refusal_correct"]
    assert scored["acceptable_answer_match"]
    generic = score_generation(no_answer, "اطلاعات کافی ارائه نمی‌شود.")
    assert not generic["refusal_correct"]
    assert not generic["acceptable_answer_match"]


def test_bounded_surface_equivalences_for_final_resolution_and_english_adverb():
    assert concept_match(
        "این به معنای حل کامل مشکل در همان بازه زمانی نیست.",
        "نه حل نهایی",
    )
    assert not concept_match("پاسخ اولیه دو ساعت است.", "نه حل نهایی")
    assert concept_match(
        "The record accurately supports coding decisions.",
        "accurate coding",
    )


def test_requested_scope_exclusion_is_not_a_false_refusal():
    task = {
        "query": "Which topics does this guideline explicitly not regulate?",
        "answerability": "answerable",
        "acceptable_answers": [],
        "required_concepts": ["overtime", "insurance"],
        "forbidden_claims": [],
    }
    scored = score_generation(task, "It does not regulate overtime or insurance.")
    assert scored["acceptable_answer_match"]
    assert not scored["false_refusal"]


def test_persian_number_words_match_numeric_concepts_without_wrong_number_leakage():
    task = {
        "query": "روش چه بود؟",
        "answerability": "answerable",
        "acceptable_answers": [],
        "required_concepts": ["هشت بیمارستان", "۱۷ خبره"],
        "forbidden_claims": [],
    }
    correct = score_generation(task, "پژوهش در هشت بیمارستان با هفده خبره انجام شد.")
    wrong = score_generation(task, "پژوهش در هفت بیمارستان با شانزده خبره انجام شد.")
    assert correct["acceptable_answer_match"]
    assert not wrong["acceptable_answer_match"]
