"""LLM-assisted structure relabeling (Step 2.5).

Takes the blocks already produced by ingest.py's deterministic tokenizer and
asks a configured chat provider to RELABEL them -- never to rewrite, translate,
summarize, or regenerate their text. The model only ever sees a numbered list
of block/unit previews and returns {"index": int, "label": str} pairs; our
code always splices the ORIGINAL, untouched text back in using whichever
label the model (or the deterministic fallback) assigned. The model's output
text is never used as document content -- only as a label.

Safe by construction: there is no code path where model-generated text can
end up in the final Markdown.
"""
import json
import re
from typing import Dict, List, Optional, Tuple

from model_gateway import get_chat_provider

LABELS = (
    "title", "heading_1", "heading_2", "heading_3", "paragraph",
    "list_intro", "bullet", "numbered_list", "quote", "table_like",
    "noise_front_matter", "page_marker",
)

CHARS_PER_TOKEN_ESTIMATE = 4
PROMPT_OVERHEAD_TOKENS = 900  # system prompt + few-shot + heading-stack context
MAX_UNITS_PER_BATCH = 18
PREVIEW_CHARS = 200

SYSTEM_PROMPT = """You are a document structure classifier for Persian and/or English text.
You will see a numbered list of short text blocks from one document. For EACH block,
assign exactly one structural label from this fixed list:
title, heading_1, heading_2, heading_3, paragraph, list_intro, bullet, numbered_list,
quote, table_like, noise_front_matter, page_marker

STRICT RULES:
- Classify ONLY. Never rewrite, translate, summarize, shorten, or add/remove text.
- Never return the block's text in your answer -- only its index and a label.
- "list_intro" = a sentence introducing a list but not itself a list item (often ends with ':').
- "bullet" / "numbered_list" = a short, self-contained list item fragment.
- A flow/diagram line such as "A -> B -> C" or similar arrow chains is "paragraph" or
  "table_like", NEVER a heading.
- "noise_front_matter" = copyright lines, cover text, publisher names, page headers/footers --
  not real content headings.
- If unsure, choose "paragraph" (the safest, least structurally destructive label).
- Output ONLY one JSON object, no markdown fences, no explanation, in exactly this shape:
{"labels": [{"index": 0, "label": "paragraph"}, {"index": 1, "label": "heading_2"}]}
- You MUST include exactly one entry for every index shown below, using only the labels
  listed above.
"""


def explode_blocks_to_units(blocks: List[Tuple]) -> List[Dict]:
    """Splits blocks into classifiable units. A 'list' block (which may bundle
    several "- item"/"N. item" lines joined by \\n) is exploded into one unit
    per item, so the LLM can independently re-judge each one (this is what
    lets it fix e.g. a wrongly-merged list-intro sentence). Headings and
    paragraphs are already singular and map 1:1 to a unit."""
    units = []
    for bi, b in enumerate(blocks):
        if b[0] == "heading":
            _, level, text, _strength = b
            orig_label = "title" if (bi == 0 and level == 1) else f"heading_{level}"
            units.append({
                "block_idx": bi, "text": text, "orig_label": orig_label,
                "orig_kind": "heading", "orig_level": level,
            })
        elif b[0] == "list":
            for si, item in enumerate(b[1].split("\n")):
                m = re.match(r"^-\s+(.*)$", item)
                if m:
                    units.append({
                        "block_idx": bi, "sub_idx": si, "text": m.group(1),
                        "orig_label": "bullet", "orig_marker": "-", "orig_kind": "list_item",
                    })
                    continue
                m = re.match(r"^(\d+)\.\s+(.*)$", item)
                if m:
                    units.append({
                        "block_idx": bi, "sub_idx": si, "text": m.group(2),
                        "orig_label": "numbered_list", "orig_marker": m.group(1), "orig_kind": "list_item",
                    })
                    continue
                units.append({
                    "block_idx": bi, "sub_idx": si, "text": item,
                    "orig_label": "bullet", "orig_marker": "-", "orig_kind": "list_item",
                })
        else:  # "para"
            units.append({"block_idx": bi, "text": b[1], "orig_label": "paragraph", "orig_kind": "para"})
    return units


def reassemble_blocks_from_units(units: List[Dict], final_labels: List[str]) -> List[Tuple]:
    """Rebuilds a blocks list from units + final labels. ALWAYS uses each
    unit's original text (`u["text"]`) -- the label is the only thing that
    can differ from the deterministic pass."""
    new_blocks = []
    for u, label in zip(units, final_labels):
        text = u["text"]
        if label in ("title", "heading_1"):
            new_blocks.append(("heading", 1, text, "strong"))
        elif label == "heading_2":
            new_blocks.append(("heading", 2, text, "strong"))
        elif label == "heading_3":
            new_blocks.append(("heading", 3, text, "strong"))
        elif label == "bullet":
            new_blocks.append(("list", f"- {text}"))
        elif label == "numbered_list":
            marker = u.get("orig_marker") if u.get("orig_label") == "numbered_list" else "1"
            new_blocks.append(("list", f"{marker}. {text}"))
        elif label == "quote":
            new_blocks.append(("para", f"> {text}"))
        else:  # paragraph, list_intro, table_like, noise_front_matter, page_marker
            new_blocks.append(("para", text))
    return new_blocks


def estimate_char_budget(num_ctx: int) -> int:
    available_tokens = max(num_ctx - PROMPT_OVERHEAD_TOKENS, 512)
    return available_tokens * CHARS_PER_TOKEN_ESTIMATE


def build_batches(units: List[Dict], char_budget: int, max_units_per_batch: int = MAX_UNITS_PER_BATCH) -> List[Tuple[int, int]]:
    """Greedily packs unit indices into (start, end) ranges so each batch's
    total preview size stays within char_budget (a rough token-budget proxy,
    ~4 chars/token), capped at max_units_per_batch regardless."""
    batches = []
    n = len(units)
    start = 0
    while start < n:
        end = start
        total_chars = 0
        while end < n and (end - start) < max_units_per_batch:
            preview_len = min(len(units[end]["text"]), PREVIEW_CHARS)
            projected = total_chars + preview_len
            if end > start and projected > char_budget:
                break
            total_chars = projected
            end += 1
        if end == start:
            end = start + 1  # always make progress, even if one unit alone exceeds budget
        batches.append((start, end))
        start = end
    return batches


def build_prompt(units: List[Dict], start_index: int, end_index: int, heading_stack: Dict[str, Optional[str]]) -> str:
    lines = []
    if any(heading_stack.values()):
        lines.append("Current document position (context only, do not repeat in your answer):")
        for key in ("heading_1", "heading_2", "heading_3"):
            if heading_stack.get(key):
                lines.append(f"  {key}: {heading_stack[key]}")
        lines.append("")
    lines.append("Blocks to classify:")
    for i in range(start_index, end_index):
        text = units[i]["text"]
        preview = text[:PREVIEW_CHARS] + ("..." if len(text) > PREVIEW_CHARS else "")
        lines.append(f"[{i}] {preview}")
    return SYSTEM_PROMPT + "\n\n" + "\n".join(lines)


def call_llm(prompt: str, provider: str, model: str, num_ctx: int) -> str:
    chat_provider = get_chat_provider(provider=provider, model=model, feature="document_normalization")
    return chat_provider.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0, "num_ctx": num_ctx},
        response_format="json",
    )


def call_ollama(prompt: str, model: str, num_ctx: int) -> str:
    return call_llm(prompt, "ollama", model, num_ctx)


def call_model(prompt: str, provider: str, model: str, num_ctx: int) -> str:
    if provider == "ollama":
        return call_ollama(prompt, model, num_ctx)
    return call_llm(prompt, provider, model, num_ctx)


def _classification_prompt(units: List[Dict], start_index: int, end_index: int, heading_stack: Dict[str, Optional[str]]) -> str:
    return build_prompt(units, start_index, end_index, heading_stack).removeprefix(SYSTEM_PROMPT).strip()


def parse_and_validate_response(raw: str, start_index: int, end_index: int) -> Tuple[Optional[Dict[int, str]], Optional[str]]:
    """Strict validation: clean JSON, exactly one label per requested index,
    no duplicates/out-of-range indices, labels from the allowed enum only.
    Returns (index->label dict, None) on success or (None, error_message)."""
    text = (raw or "").strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e < s:
        return None, "no JSON object found in response"
    try:
        parsed = json.loads(text[s:e + 1])
    except Exception as ex:
        return None, f"JSON parse error: {ex}"

    labels = parsed.get("labels") if isinstance(parsed, dict) else None
    if not isinstance(labels, list):
        return None, "missing or non-list 'labels' field"

    expected = set(range(start_index, end_index))
    result: Dict[int, str] = {}
    for entry in labels:
        if not isinstance(entry, dict) or "index" not in entry or "label" not in entry:
            return None, "malformed label entry (missing index/label)"
        idx = entry["index"]
        lbl = entry["label"]
        if not isinstance(idx, int) or idx not in expected:
            return None, f"index {idx!r} out of range or not requested"
        if idx in result:
            return None, f"duplicate index {idx}"
        if lbl not in LABELS:
            return None, f"label {lbl!r} not in allowed enum"
        result[idx] = lbl

    missing = expected - set(result.keys())
    if missing:
        return None, f"missing indices: {sorted(missing)}"
    return result, None


def classify_document(
    blocks: List[Tuple],
    model: str,
    num_ctx: int,
    max_batches: int = 20,
    force: bool = False,
    provider: str = "ollama",
) -> Tuple[List[Tuple], Dict]:
    """Orchestrates: explode -> batch -> call the configured LLM per batch (sequentially,
    carrying heading context forward) -> validate -> per-batch fallback ->
    reassemble. Returns (new_blocks, info). info["used"] is False (blocks
    returned unchanged) if there's nothing to classify or the estimated batch
    count exceeds max_batches and force=False."""
    units = explode_blocks_to_units(blocks)
    n = len(units)
    if n == 0:
        return blocks, {"used": False, "batches_total": 0, "batches_fallback": 0, "status": "not_attempted", "warnings": []}

    char_budget = estimate_char_budget(num_ctx)
    batches = build_batches(units, char_budget)
    if len(batches) > max_batches and not force:
        return blocks, {
            "used": False, "batches_total": len(batches), "batches_fallback": 0,
            "status": "skipped_too_many_batches",
            "warnings": [f"estimated {len(batches)} batches exceeds cap {max_batches}; skipped (use force=True to override)"],
        }

    final_labels: List[Optional[str]] = [None] * n
    warnings: List[str] = []
    fallback_count = 0
    heading_stack: Dict[str, Optional[str]] = {"heading_1": None, "heading_2": None, "heading_3": None}

    for batch_idx, (start, end) in enumerate(batches):
        prompt = _classification_prompt(units, start, end, heading_stack)
        try:
            raw = call_model(prompt, provider, model, num_ctx)
        except Exception as ex:
            raw = ""
            warnings.append(f"batch {batch_idx} [{start}:{end}]: {provider} call failed ({ex}); fell back to deterministic labels")
            fallback_count += 1
            for i in range(start, end):
                final_labels[i] = units[i]["orig_label"]
            continue

        labels_map, error = parse_and_validate_response(raw, start, end)
        if error:
            warnings.append(f"batch {batch_idx} [{start}:{end}]: {error}; fell back to deterministic labels")
            fallback_count += 1
            for i in range(start, end):
                final_labels[i] = units[i]["orig_label"]
            continue

        for i in range(start, end):
            final_labels[i] = labels_map[i]
            lbl = labels_map[i]
            if lbl in ("title", "heading_1"):
                heading_stack["heading_1"] = units[i]["text"][:60]
                heading_stack["heading_2"] = None
                heading_stack["heading_3"] = None
            elif lbl == "heading_2":
                heading_stack["heading_2"] = units[i]["text"][:60]
                heading_stack["heading_3"] = None
            elif lbl == "heading_3":
                heading_stack["heading_3"] = units[i]["text"][:60]

    new_blocks = reassemble_blocks_from_units(units, final_labels)
    if fallback_count == 0:
        status = "passed"
    elif fallback_count == len(batches):
        status = "failed"
    else:
        status = "partial"
    return new_blocks, {
        "used": True,
        "batches_total": len(batches),
        "batches_fallback": fallback_count,
        "status": status,
        "warnings": warnings,
    }
