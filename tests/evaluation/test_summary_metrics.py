from evaluation.metrics.summaries import score_summary


def test_comprehensive_summary_requires_all_conditions():
    task = {
        "required_sections": ["هدف", "روش", "یافته"],
        "required_key_claims": ["دیالیز ۰٫۸۷", "معیار اقتصادی ۰٫۳۵"],
        "conclusion_required": True,
        "contamination_blacklist": ["ایمیل نویسنده"],
        "minimum_page_diversity": 3,
    }
    answer = "هدف مطالعه روشن است. روش TOPSIS بود. یافته شامل دیالیز ۰٫۸۷ و معیار اقتصادی ۰٫۳۵ است. نتیجه نیز پایلوت را پیشنهاد می‌کند."
    score = score_summary(task, answer, [1, 8, 9])
    assert score["substantive_section_coverage"] == 1
    assert score["key_claim_recall"] == 1
    assert score["contamination_rate"] == 0
    assert score["comprehensive_summary_pass"] is True


def test_summary_contamination_is_a_hard_failure():
    task = {
        "required_sections": [],
        "required_key_claims": [],
        "conclusion_required": False,
        "contamination_blacklist": ["ایمیل نویسنده"],
        "minimum_page_diversity": 1,
    }
    score = score_summary(task, "ایمیل نویسنده در متن آمده است", [1])
    assert score["contamination_rate"] == 1
    assert score["comprehensive_summary_pass"] is False


def test_summary_sections_and_atomic_claims_accept_safe_paraphrases():
    task = {
        "required_sections": ["مسئله و هدف", "روش مقایسه‌ای", "وضع ایران", "توصیه‌ها", "نتیجه‌گیری"],
        "required_key_claims": [
            "کشورهای منتخب سازوکار هماهنگ دارند",
            "راهبرد ملی یکپارچه لازم است",
        ],
        "conclusion_required": True,
        "contamination_blacklist": [],
        "minimum_page_diversity": 2,
    }
    answer = (
        "هدف و مسئله: شکاف سیاستی بررسی شد.\n\n"
        "مرور تطبیقی: کشورهای منتخب نهادهای متولی مشخص و ابزارهای استاندارد دارند.\n\n"
        "ارزیابی عملکرد فعلی ایران: اقدامات پراکنده است.\n\n"
        "توصیه‌ها: تدوین سند ملی و چارچوب یکپارچه ضروری است.\n\n"
        "نتیجه‌گیری: هماهنگی بین‌بخشی لازم است."
    )
    score = score_summary(task, answer, [1, 4])
    assert score["substantive_section_coverage"] == 1.0
    assert score["key_claim_recall"] == 1.0


def test_summary_wrong_number_and_missing_entity_do_not_pass_claim_recall():
    task = {
        "required_sections": [],
        "required_key_claims": [
            "پروژه آلفا با امتیاز ۰٫۸۷ رتبه اول است",
            "۳۷ خبره و ۱۵ عامل",
        ],
        "conclusion_required": False,
        "contamination_blacklist": [],
        "minimum_page_diversity": 1,
    }
    answer = "پروژه بتا با امتیاز ۰٫۷۸ رتبه اول است. ۳۷ خبره مصاحبه شدند."
    score = score_summary(task, answer, [1])
    assert score["key_claim_recall"] == 0.0
    assert score["comprehensive_summary_pass"] is False


def test_concluding_synthesis_without_literal_heading_counts_as_conclusion():
    task = {
        "required_sections": ["مسئله و هدف", "نتیجه‌گیری"],
        "required_key_claims": [],
        "contamination_blacklist": [],
        "conclusion_required": True,
        "minimum_page_diversity": 1,
    }
    answer = (
        "این موضوع برای عدالت سلامت اهمیت دارد و نقش نهادها را روشن می‌کند.\n\n"
        "در مجموع، تدوین چارچوب ملی ضروری است و اجرای آن نیازمند مشارکت بین‌بخشی است."
    )
    scored = score_summary(task, answer, [1])
    assert scored["conclusion_coverage"]
    assert scored["substantive_section_coverage"] == 1.0


def test_arbitrary_last_paragraph_is_not_mistaken_for_conclusion():
    task = {
        "required_sections": ["نتیجه‌گیری"],
        "required_key_claims": [],
        "contamination_blacklist": [],
        "conclusion_required": True,
        "minimum_page_diversity": 1,
    }
    scored = score_summary(task, "یک پاراگراف صرفاً توصیفی درباره داده‌های خام.", [1])
    assert not scored["conclusion_coverage"]
    assert scored["substantive_section_coverage"] == 0.0
