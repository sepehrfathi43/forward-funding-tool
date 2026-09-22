# Setup and operating notes

## Local workstation

Use Python 3.12 or a compatible version supported by the dependencies. Create a fresh virtual environment on each machine:

```powershell
py -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-local\Scripts\python.exe -m streamlit run app.py --server.address localhost
```

The `-m` flag must follow the Python executable. `Start Tool.cmd` uses this environment after setup. Ctrl+C stops the server. Restart the server after updating helper modules to avoid retaining old imports.

## Secrets and models

Set `OPENAI_API_KEY` in `.streamlit/secrets.toml`, an environment variable, or the app sidebar. Never commit real secrets. Model selectors must use model IDs available to the configured API project. An unavailable model, exhausted quota or API permissions failure leaves unresolved documents flagged.

## Shared hosting

The Streamlit entrypoint is `app.py`; dependencies are in `requirements.txt`. Configure secrets in the hosting provider's secret settings. Repository creation does not deploy or publish a running application.

Do not expose this financial-document application to unauthenticated users. The current code has no production login system or durable case database. Confirm access controls and provider data handling before allowing real customer uploads. A faster host can improve local parsing; it does not remove API latency or the need to review extraction errors.

Optional OCR dependencies are separate in `requirements-ocr.txt`; installing the Python wrapper alone does not install the system Tesseract executable or language data.

## Case lifecycle

- Confirm applicant/business identity and include all relevant statements and accounts.
- Currency defaults to CAD only when unspecified; flag suspected foreign currency in Document Analyzer.
- Confirm missing coverage from the source. Suggested transaction-date bounds are not automatically verified coverage.
- Resolve classifications, debt positions and Diagnostics before relying on estimates.
- Export the reviewed ledger and audit/decision documents before restarting or using Start new deal / Refresh.

## Troubleshooting

| Symptom | Check |
|---|---|
| `streamlit` is not recognized | Use the full virtual-environment Python command above |
| New module attribute is missing | Stop the server and restart after updating all project files |
| Extraction appears slow | Check stage/page progress; image or outlined tables require visual extraction |
| Months used is None | Confirm missing/invalid statement coverage; check account overlap |
| Revenue is zero or understated | Review pending deposits and business/payment context |
| Debt percentage awaits verification | Verify the active/closed status, frequency and payment amount of each candidate |
| Currency remains unconfirmed | Use the first-tab currency controls; configure the USD reporting rate if needed |

## Tests

```powershell
.\.venv-local\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-local\Scripts\python.exe -m unittest test_statement_settings test_flinks_review_fixes test_mca_funding test_industry_lookup test_payment_risk test_debt_review test_partial_ui
.\.venv-local\Scripts\python.exe test_chat_ui_run.py
```

Historical private-fixture tests may require source PDFs and a private regression manifest, which are intentionally excluded from the repository. Run the chat smoke script separately because it executes its AppTest during import.
