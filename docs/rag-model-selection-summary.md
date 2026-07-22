# RAG Model Selection Summary

## Final decision

- Production embedding: `nvidia/nemotron-3-embed-1b:free`
- Production retrieval: R2 bounded cross-language retrieval
- Primary generator: `google/gemini-2.5-flash`
- Fallback generator: `z-ai/glm-5.2`

Final routing:

```text
Nemotron + R2
-> Gemini 2.5 Flash
-> GLM 5.2 only after a technical or structured-output failure
```

## Key measured conclusions

- Nemotron H2 retrieval recall was `1.0000`, with `0` zero-recall cases.
- Nemotron retrieval p95 was approximately `3.60s` in the dated benchmark.
- Gemini passed every Phase 2A finalist trust gate and was the fastest eligible generator in screening.
- GLM passed every Phase 2A trust gate and was the finalist least sensitive to embedding changes.
- OpenAI Large produced some aggregate gains with GLM, but also case-level regressions.
- Qwen retrieval latency was approximately `100s` p95 and was rejected for production.
- OpenAI Small failed cross-language and multi-document retrieval gates.
- A second production embedding was rejected.
- The full generator-by-embedding matrix was intentionally avoided because most frozen contexts were identical.
- No full 31-case confirmation run is currently required.

## Operational policy

Gemini is the only primary grounded generator. GLM is called at most once and only after a timeout, connection or retryable provider failure, missing response, invalid JSON, schema failure, missing required fields, or structurally invalid citation markers. A valid grounded answer, refusal, or no-answer response does not trigger fallback.

The request-scoped prompt, evidence order, answerability policy, citation policy, and output-token limit are immutable across fallback. Their hashes are verified before GLM runs. Generator fallback never repeats rewriting, embedding, lexical or dense retrieval, fusion, reranking, document loading, or chunking. Telemetry records model choice, fallback status and reason, latency, token counts, cost, rewrite use, context hash, and error category without storing secrets or full evidence.

Production uses one embedding model and one vector collection only.

## Evaluation scope

The benchmark dated 2026-07-21 covered eight Persian and English documents and 31 gold cases, including OCR, tables, multilingual questions, and multi-document retrieval. The corpus is deliberately varied but still small, so the conclusions should be revisited when representative production traffic is available.
