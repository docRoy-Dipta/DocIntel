# AI disclosure

## How AI was used to build this project
The code, tests, scripts, migrations and documentation in this repository were written by **Claude (Anthropic)** acting as pair-programmer, architect and QA engineer
at the request of the repository owner, who defined the requirements, made the decisions (stack, free-tier LLM, scope, "all modules first") and is responsible for the project.
Claude executed the test-suite, performance runs and the evaluation in its own sandbox; the measured outputs are stored in `docs/` and the reports are generated from them.
Anything that could not be run there is listed under "Known gaps" in `TESTING_REPORT.md` and `CURRENT_PROJECT_STATE.md`.
**All code should be reviewed by a human before production use.**

## How AI is used by the running system
| Feature | AI involved? | Details |
|---|---|---|
| OCR | Machine-learning model (Tesseract LSTM) | local; no data leaves the machine |
| Default extraction (`LLM_PROVIDER=heuristic`) | **No** | rule-based; nothing is sent anywhere |
| Optional extraction (`LLM_PROVIDER=gemini`) | Yes — Google Gemini via the Gemini API | page text of invoice/receipt pages is sent to Google. Free-tier data may be used by Google to improve its products. Not suitable for confidential documents |
| Semantic search | Default `hashing` embedder: **no** ML (hashed word/phrase features). Optional `sentence-transformers` (all-MiniLM-L6-v2): local ML model | |
| Financial validation, matching, comparisons, approvals | **No** | deterministic code only — by design, an LLM never decides whether numbers are right |

## Safeguards
Grounding (values must exist in the source), computed confidence, extracted-vs-inferred labelling, mandatory human review for uncertain results,
immutable audit trail of corrections, and prompt-injection defences (see `ARCHITECTURE.md`, `SECURITY.md`).

## Limits of the claims
Reported accuracy comes from a **synthetic** dataset and the **rule-based** extractor (see `EVALUATION_REPORT.md`). No accuracy claim is made for real documents or for the LLM extractor.
