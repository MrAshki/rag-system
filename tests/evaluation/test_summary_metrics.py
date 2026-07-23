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
