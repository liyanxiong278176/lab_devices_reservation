# Independent backend + AI evaluation harness

This tree is self-contained and does not import `backend/tests`, `frontend/e2e`,
or the older benchmark and evaluation folders. Runtime fixtures are tagged with
a unique `QAEVAL_<run>` prefix and are cleaned by their recorded primary keys.

## Environment

The test environment lives at `.venv`. Its direct evaluation dependencies are
pinned in `requirements.txt`. External services are opt-in and must use an
isolated database schema, Redis database, and Qdrant collection created by
`prepare_runtime.py`; the project `.env` files are read but never rewritten.

```powershell
python -m venv qa_system\.venv
qa_system\.venv\Scripts\python -m pip install -r qa_system\requirements.txt
qa_system\.venv\Scripts\python qa_system\prepare_runtime.py
qa_system\.venv\Scripts\python -m pytest qa_system\backend_tests qa_system\ai_tests qa_system\integration -q
```

Live provider calls are disabled by default. `AI_RUN_LIVE=1` is required before
any live call; ordinary evaluation uses the local deterministic mock provider
and cassettes. No live output is used to claim a quality threshold was met.

## Artifacts

`results/` stores generated capability inventories, test output, quality
measurements, load profiles, browser evidence, and the final report. Secret
runtime connection material is held only in the ignored `.runtime-secrets.json`
and removed by `cleanup_runtime.py` after the run.
