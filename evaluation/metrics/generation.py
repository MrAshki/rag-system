from __future__ import annotations

import re
import unicodedata

from .proportions import proportion_result


GENERIC_FAILURE_RE = re.compile(r"خطا در تولید پاسخ|اعتبارسنجی پاسخ ناموفق|unable to (?:answer|generate)", re.I)
REFUSAL_RE = re.compile(
    r"اطلاعات کافی|در سند.*نیست|اطلاعاتی ندارد|حکمی ندارد|ذکر نشده|"
    r"نمی‌توانم پاسخ|insufficient information|cannot answer|"
    r"does not (?:state|specify|regulate|contain)",
    re.I,
)
TRUNCATION_RE = re.compile(r"(?:\.\.\.|…|\[truncated\])\s*$", re.I)
CITATION_RE = re.compile(r"\[(?:S|E)\d+(?:\s*[-,]\s*(?:S|E)?\d+)*\]", re.I)
TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?|[a-z]+(?:-[a-z]+)*|[\u0600-\u06ff]+", re.I)
DIACRITIC_RE = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")

STOPWORDS = {
    "از", "با", "به", "در", "را", "و", "یا", "اما", "است", "بود", "شد",
    "شده", "می", "که", "برای", "این", "آن", "یک", "ترین", "the", "a", "an", "and",
    "or", "of", "to", "in", "is", "are", "was", "were", "with", "for",
}
QUESTION_STOPWORDS = STOPWORDS | {
    "چه", "چقدر", "چند", "کدام", "آیا", "چی", "چیست", "دارد", "درباره",
    "what", "which", "how", "does", "did", "document", "سند", "دستورالعمل",
}
SAFE_EQUIVALENTS = (
    {"مقایسه", "تطبیق"},
    {"سازوکار", "نهاد", "ابزار", "چارچوب"},
    {"هماهنگ", "مشخص", "منسجم", "یکپارچه", "مشارکت"},
    {"راهبرد", "سند", "چارچوب", "سیاست"},
    {"لازم", "ضرور", "نیاز"},
    {"راهنما", "راهنم", "دستورالعمل"},
    {"توصیه", "پیشنهاد", "ضرور"},
    {"مهم", "کلید", "بالاتر", "وزن", "اصلی", "عمدتا"},
    {"رتبه", "اولویت"},
    {"اول", "نخست"},
    {"آب", "آبی", "کم‌آبی"},
    {"بحران", "کمبود", "کاهش"},
    {"خبره", "خبرگان", "خبرگ"},
    {"حضور", "حاضر"},
    {"مکمل", "تکمیلی"},
)
SAFE_PHRASE_EQUIVALENTS = (
    {"error rate", "نرخ خطا"},
    {"previous stable version", "نسخه پایدار قبلی"},
    {"outside the document", "خارج از سند", "خارج از دامنه سند", "حکمی ندارد"},
    {"پروتکل های گروهی", "پروتکل های گروه", "پروتکلی"},
    {"arksey و o malley", "arksey and o malley", "آرکس و اومالی"},
    {
        "نه حل نهایی",
        "نه حل کامل",
        "با زمان حل کامل تفاوت دارد",
        "زمان حل کامل مشکل تفاوت دارد",
    },
    {
        "اطلاعات موجود نیست",
        "اطلاعات کافی ارائه نمی کند",
        "اطلاعاتی ارائه نمی کند",
        "ذکر نشده",
    },
    {
        "مهلت حل کامل تعیین نشده",
        "مهلت قطعی حل کامل مشخص نشده",
        "درباره مهلت حل کامل اطلاعات کافی ارائه نمی کند",
    },
)
PERSIAN_NUMBER_WORDS = {
    "صفر": "0", "یک": "1", "دو": "2", "سه": "3", "چهار": "4",
    "پنج": "5", "شش": "6", "هفت": "7", "هشت": "8", "نه": "9",
    "ده": "10", "یازده": "11", "دوازده": "12", "سیزده": "13",
    "چهارده": "14", "پانزده": "15", "شانزده": "16", "هفده": "17",
    "هجده": "18", "نوزده": "19", "بیست": "20",
}


def normalize_text(value: str) -> str:
    text = CITATION_RE.sub(" ", unicodedata.normalize("NFKC", value or "")).casefold()
    text = DIACRITIC_RE.sub("", text)
    # In Persian prose a slash between Persian/Arabic digits is commonly the
    # decimal mark (``۳/۶ درصد`` means 3.6%). Keep Latin fractions such as 3/6
    # untouched so this equivalence cannot turn a mathematical fraction into a
    # decimal accidentally.
    text = re.sub(r"([۰-۹٠-٩])\s*/\s*([۰-۹٠-٩])", r"\1.\2", text)
    text = text.translate(str.maketrans({
        **dict(zip("۰۱۲۳۴۵۶۷۸۹", "0123456789")),
        **dict(zip("٠١٢٣٤٥٦٧٨٩", "0123456789")),
        "ك": "ک", "ي": "ی", "ى": "ی", "ة": "ه", "ۀ": "ه",
        "\u200c": " ", "\u200f": " ", "\u200e": " ", "\xa0": " ",
        "٫": ".", "٬": "", "٪": "%",
        "،": " ", "؛": " ", "؟": " ", "ـ": "",
    }))
    # PDF text layers commonly serialize RTL decimals as 87/0 while ordinary
    # left-to-right prose uses 0/87. Normalize both without reversing integers.
    text = re.sub(r"(?<!\d)(\d{1,4})\s*/\s*0(?!\d)", r"0.\1", text)
    text = re.sub(r"(?<!\d)0\s*/\s*(\d{1,4})(?!\d)", r"0.\1", text)
    text = text.replace("≥", ">=").replace("≤", "<=")
    for word, number in PERSIAN_NUMBER_WORDS.items():
        text = re.sub(rf"(?<![\u0600-\u06ff]){word}(?![\u0600-\u06ff])", number, text)
    return " ".join(
        re.sub(r"[^a-z0-9\u0600-\u06ff.%<>=]+", " ", text).split()
    )


def _stem(token: str) -> str:
    token = token.casefold()
    if re.fullmatch(r"[a-z]+", token) and len(token) > 6 and token.endswith("ly"):
        return token[:-2]
    if re.fullmatch(r"[a-z]+", token) and len(token) > 4 and token.endswith("s"):
        return token[:-1]
    if not re.fullmatch(r"[\u0600-\u06ff]+", token):
        return token
    for suffix in ("هایی", "های", "ترین", "تر", "اند", "ای", "ها", "ی"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[:-len(suffix)]
    return token


def text_tokens(value: str, *, drop_stopwords: bool = False) -> list[str]:
    tokens = [_stem(token) for token in TOKEN_RE.findall(normalize_text(value))]
    return [token for token in tokens if not drop_stopwords or token not in STOPWORDS]


def _equivalent(required: str, observed: set[str]) -> bool:
    if required in observed:
        return True
    for group in SAFE_EQUIVALENTS:
        stems = {_stem(item) for item in group}
        if required in stems and stems & observed:
            return True
    return False


def _negated_anchor(answer: str, anchor: str) -> bool:
    escaped = re.escape(anchor)
    return bool(re.search(
        rf"(?:\bnot\b|\bno\b|نیست|نبود|نشد|نمی\s+\w+).{{0,24}}{escaped}"
        rf"|{escaped}.{{0,24}}(?:نیست|نبود|نشد|\bnot\b)",
        normalize_text(answer),
        re.I,
    ))


def concept_match(answer: str, concept: str) -> bool:
    """Strictly match one required concept with safe surface normalization."""
    normalized_answer = normalize_text(answer)
    normalized_concept = normalize_text(concept)
    if not normalized_concept:
        return True
    if normalized_concept in normalized_answer and not _negated_anchor(answer, normalized_concept):
        return True
    if normalized_concept == "مرخصی" and re.search(
        r"(?:استراحت|غیبت).{0,28}(?:کار|محل)|(?:کار|محل).{0,28}(?:استراحت|غیبت)",
        normalized_answer,
    ):
        return True
    if normalized_concept == normalize_text("نه حل نهایی") and re.search(
        r"(?:به معنای|یعنی).{0,48}(?:حل کامل|حل نهایی).{0,64}نیست|"
        r"(?:حل کامل|حل نهایی).{0,48}(?:متفاوت|یکسان نیست)",
        normalized_answer,
    ):
        return True
    for equivalents in SAFE_PHRASE_EQUIVALENTS:
        normalized_equivalents = {normalize_text(item) for item in equivalents}
        if normalized_concept in normalized_equivalents and normalized_equivalents & {
            item for item in normalized_equivalents if item in normalized_answer
        }:
            return True
    required = text_tokens(concept, drop_stopwords=True)
    observed = set(text_tokens(answer, drop_stopwords=True))
    if not required:
        return False
    numeric = {token for token in required if re.fullmatch(r"\d+(?:\.\d+)?%?", token)}
    if not numeric.issubset(observed) or any(_negated_anchor(answer, item) for item in numeric):
        return False
    return all(_equivalent(token, observed) for token in required)


def atomic_claim_match(answer: str, claim: str, *, threshold: float = 0.75) -> bool:
    """Match a paraphrased atomic claim while keeping numeric anchors strict."""
    normalized_claim = normalize_text(claim)
    if not normalized_claim:
        return True
    if normalized_claim in normalize_text(answer) and not _negated_anchor(answer, normalized_claim):
        return True
    normalized_answer = normalize_text(answer)
    for equivalents in SAFE_PHRASE_EQUIVALENTS:
        normalized_equivalents = {normalize_text(item) for item in equivalents}
        if (
            normalized_claim in normalized_equivalents
            and any(item in normalized_answer for item in normalized_equivalents)
        ):
            return True
    required = text_tokens(claim, drop_stopwords=True)
    if not required:
        return False
    numeric = {token for token in required if re.fullmatch(r"\d+(?:\.\d+)?%?", token)}
    paragraphs = [part for part in re.split(r"\n\s*\n+", answer or "") if part.strip()]
    for paragraph in paragraphs or [answer]:
        observed = set(text_tokens(paragraph, drop_stopwords=True))
        if not numeric.issubset(observed):
            continue
        if any(_negated_anchor(paragraph, item) for item in numeric):
            continue
        matched = sum(_equivalent(token, observed) for token in required)
        minimum = len(required) if len(required) <= 3 else max(3, int(len(required) * threshold + 0.999))
        if matched >= minimum:
            return True
    return False


def _topic_mentioned(task: dict, answer: str) -> bool:
    query_tokens = {
        token for token in text_tokens(task.get("query", ""), drop_stopwords=True)
        if token not in QUESTION_STOPWORDS and not token.isdigit()
    }
    observed = set(text_tokens(answer, drop_stopwords=True))
    return bool(query_tokens & observed)


def score_generation(task: dict, answer: str) -> dict:
    normalized = normalize_text(answer)
    acceptable = [normalize_text(item) for item in task.get("acceptable_answers", [])]
    concepts = list(task.get("required_concepts", []))
    forbidden = list(task.get("forbidden_claims", []))
    concept_hits = [item for item in concepts if concept_match(answer, item)]
    forbidden_hits = [item for item in forbidden if atomic_claim_match(answer, item)]
    exact = bool(acceptable and normalized in acceptable)
    exclusion_question = bool(re.search(
        r"which.+(?:not|outside).+(?:regulate|cover)|"
        r"(?:کدام|چه).+(?:حکمی ندارد|خارج از دامنه)",
        task.get("query", ""),
        re.IGNORECASE,
    ))
    refusal = bool(REFUSAL_RE.search(answer or "")) and not exclusion_question
    coverage = len(concept_hits) / len(concepts) if concepts else 1.0
    answerability = task.get("answerability")
    refusal_correct = (
        answerability == "unanswerable"
        and refusal
        and _topic_mentioned(task, answer)
        and not forbidden_hits
    )
    structured_correct = (
        (answerability == "unanswerable" and refusal_correct)
        or (
            coverage == 1.0
            and not forbidden_hits
            and (
                (answerability == "ambiguous" and not refusal)
                or (answerability not in {"unanswerable"} and not refusal)
            )
        )
    )
    acceptable_claim = any(
        atomic_claim_match(answer, item, threshold=0.75)
        for item in task.get("acceptable_answers", [])
    )
    acceptable_match = bool(
        normalized
        and (
            exact
            or structured_correct
            or (not concepts and acceptable_claim)
        )
    )
    return {
        "normalized_answer_match": exact,
        "acceptable_answer_match": acceptable_match,
        "required_concept_coverage": coverage,
        "required_concept_hits": concept_hits,
        "forbidden_claim": bool(forbidden_hits),
        "forbidden_claim_hits": forbidden_hits,
        "generic_failure": bool(GENERIC_FAILURE_RE.search(answer or "")),
        "false_refusal": task.get("answerability") == "answerable" and refusal,
        "answerable_for_false_refusal": task.get("answerability") == "answerable",
        "refusal_detected": refusal,
        "refusal_correct": refusal_correct,
        "truncation": bool(TRUNCATION_RE.search(answer or "")),
    }


def aggregate_generation(scored: list[dict]) -> dict:
    count = len(scored)
    answerable = [row for row in scored if row.get("answerable_for_false_refusal")]
    return {
        "normalized_answer_match": proportion_result(sum(row["normalized_answer_match"] for row in scored), count),
        "acceptable_answer_match": proportion_result(sum(row["acceptable_answer_match"] for row in scored), count),
        "required_concept_coverage_mean": sum(row["required_concept_coverage"] for row in scored) / count if count else 0.0,
        "forbidden_claim_rate": proportion_result(sum(row["forbidden_claim"] for row in scored), count),
        "generic_failure_rate": proportion_result(sum(row["generic_failure"] for row in scored), count),
        "false_refusal_rate": proportion_result(sum(row["false_refusal"] for row in answerable), len(answerable)),
        "truncation_rate": proportion_result(sum(row["truncation"] for row in scored), count),
    }
