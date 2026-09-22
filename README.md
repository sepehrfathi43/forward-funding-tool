# Forward Funding Tool

Streamlit application for reviewing bank statements and applicant/co-applicant credit reports, classifying deposits, reviewing debt and producing conditional funding estimates. No SQL server is needed to run the application.

See [Architecture and data flow](ARCHITECTURE.md) and [Setup, deployment and troubleshooting](README_DEPLOYMENT.md).

## Run in VS Code on Windows

Open this folder in VS Code, then use its PowerShell terminal:

```powershell
py -m venv .venv-local
.\.venv-local\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-local\Scripts\python.exe -m streamlit run app.py --server.address localhost
```

After the first setup, double-click `Start Tool.cmd` or rerun the final command. Stop the server with Ctrl+C. Restart after updating the application modules. Virtual environments are machine-specific and are not included in the repository.

## Optional AI configuration

Enter your own API key in the app sidebar, or create `.streamlit/secrets.toml` locally:

```toml
OPENAI_API_KEY = "your-own-api-key"
```

The secrets file is ignored by Git. Use model identifiers available to your API project in the app's model selectors. PDF fallback, deposit classification, industry lookup and the case assistant require suitable API access and may incur usage charges. Native extraction remains available without an API key. Enabling fallback permits sending uploaded document content to the configured API; industry web lookup sends the business name.

## Workflow

1. Upload bank statements for one deal; upload credit reports separately for applicant and co-applicant.
2. Process statements and review dates, reconciliation, currencies and deposit classifications.
3. Confirm lender positions and review the MCA funding/repayment table in Bank Summary.
4. Verify industry, credit and other underwriting inputs; calculate the conditional estimated range.
5. Export the reviewed ledger, audit records and decision memo as needed. Use Start new deal / Refresh to clear the case inputs.

The scorecard is a configurable heuristic, not a validated probability-of-default model. Funding ranges use average true revenue and grade-based percentages. Partial coverage produces warnings and estimates. Integrity flags indicate items to investigate, not proof of fraud. MCA repayment at factor 1.46 is an estimate; missing advances, returns and overlapping contracts require review. The tool does not automatically confirm payoff.

Data and review state are primarily session-local. Export work before restarting or clearing a case. Source PDFs, customer reports, API keys and local audit scratch files are deliberately excluded from this repository.

## Tests

```powershell
.\.venv-local\Scripts\python.exe -m unittest test_mca_funding test_industry_lookup test_payment_risk test_debt_review test_partial_ui
.\.venv-local\Scripts\python.exe test_chat_ui_run.py
```

Some historical regression tests require private statement fixtures and may skip or need local fixture paths. Customer fixtures are not distributed. Run the chat smoke script separately because it executes AppTest at import time.

## Project structure

- `app.py`: Streamlit interface and review workflow.
- Bank-specific parser modules and validation modules: extraction and reconciliation.
- `revenue_tools.py`, `debt_review.py`, `mca_funding.py`: revenue, debt and funding evidence.
- `industry_lookup.py`, `industry_catalog.py`: public-name research and selectable industry descriptions.
- `funding_engine.py`, `cashflow.py`: funding arithmetic and statement coverage.
- `case_assistant.py`: conversational review and explicitly accepted changes.
- `statement_settings.py`, `balance_review.py`: currency policy, verified coverage and audited source corrections.
- `production/schema.sql`: optional future database design; not required or connected to the current app.
