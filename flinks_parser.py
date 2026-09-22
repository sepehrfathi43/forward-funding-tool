"""Deterministic reader for Flinks Insights Dashboard PDF exports.

The export is a transaction table rendered in a PDF, rather than a bank
statement with printed debit/credit totals. The table still contains explicit
withdrawal, deposit and balance columns, so it can be parsed locally without
asking a vision model to recreate the ledger.
"""
import hashlib
import io
import re
from datetime import date
from decimal import Decimal

import pdfplumber

from servus_parser import CURRENCY_ISSUE
from statement_validation import parse_money, MONEY_TOKEN


MONEY = MONEY_TOKEN
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _money(value):
    return parse_money(value)


def _lines(page):
    words = sorted(
        page.dedupe_chars().extract_words(x_tolerance=1, y_tolerance=2),
        key=lambda word: (word["top"], word["x0"]),
    )
    grouped = []
    for word in words:
        if not grouped or abs(grouped[-1][0] - word["top"]) > 3:
            grouped.append((word["top"], [word]))
        else:
            grouped[-1][1].append(word)
    return [(top, sorted(words, key=lambda word: word["x0"])) for top, words in grouped]


def _header(page_lines):
    for top, words in page_lines:
        by_name = {_norm(word["text"]): word for word in words}
        if all(name in by_name for name in ("date", "description", "withdrawals", "deposits", "balance")):
            return top, by_name
    return None, None


def _amount(words, left, right):
    cell = ' '.join(word['text'] for word in words if left - 3 <= word['x0'] < right - 3).strip()
    if not cell or cell in ('-', '—'): return None
    # Signs and currency markers may be separate PDF words within the cell.
    return _money(cell)


def _metadata(first_text):
    account_name = None
    account_type = None
    account_number = None
    match = re.search(r"Account Name.*?\n(.+?)\nDate Description", first_text, re.S)
    if match:
        account_line = " ".join(match.group(1).split())
        number = re.search(r"\b\d{3}-\d{5}-\d{7}\b", account_line)
        if number:
            account_number = number.group(0)
            before, after = account_line.split(account_number, 1)
            account_name = before.strip()
            account_type = after.strip().split("$")[0].strip() or None
    employer = re.search(r"Employer Name\s+([^\n]+)", first_text)
    days = re.search(r"Days Detected\s+(\d+)", first_text)
    return {
        "account_name": account_name,
        "account_type": account_type,
        "account_number": account_number,
        "employer_name": employer.group(1).strip() if employer else None,
        "days_detected": int(days.group(1)) if days else None,
    }


def parse_flinks(pdf_bytes, filename, doc=None):
    """Parse one Flinks dashboard export and reconcile every table balance."""
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    close_doc = doc is None
    if doc is None:
        doc = pdfplumber.open(io.BytesIO(pdf_bytes))
    try:
        pages = [_lines(page) for page in doc.pages]
        first_text = doc.pages[0].extract_text(x_tolerance=2) or ""
        metadata = _metadata(first_text)
        issues = []
        warnings = []
        rows = []
        first_header_top = None
        first_header = None
        for page_number, page_lines in enumerate(pages, 1):
            header_top, header = _header(page_lines)
            if header is not None and first_header is None:
                first_header_top, first_header = header_top, header
            if header is None and first_header is not None:
                # Flinks prints the column headings only on the first page;
                # the remaining pages use the same x coordinates.
                header = first_header
                header_top = -1
            if header is None:
                continue
            date_word = header["date"]
            description_word = header["description"]
            withdrawals_word = header["withdrawals"]
            deposits_word = header["deposits"]
            balance_word = header["balance"]
            for top, words in page_lines:
                if top <= header_top:
                    continue
                date_token = next((word for word in words if DATE.fullmatch(word["text"])), None)
                if date_token is None:
                    continue
                date_text = date_token["text"]
                description = " ".join(
                    word["text"]
                    for word in words
                    if word["x0"] >= description_word["x0"] - 3
                    and word["x0"] < withdrawals_word["x0"] - 4
                ).strip()
                withdrawal = _amount(words, withdrawals_word["x0"], deposits_word["x0"])
                deposit = _amount(words, deposits_word["x0"], balance_word["x0"])
                balance = _amount(words, balance_word["x0"], 10000)
                if balance is None or (withdrawal is None and deposit is None) or (withdrawal is not None and deposit is not None):
                    issues.append(f"Page {page_number}: unreadable transaction row on {date_text}.")
                    continue
                amount = withdrawal if withdrawal is not None else deposit
                rows.append({
                    "id": f"{sha[:16]}:flinks:{len(rows) + 1}",
                    "sequence": len(rows) + 1,
                    "page": page_number,
                    "top": round(top, 2),
                    "date": date_text,
                    "month": date_text[:7],
                    "description": description,
                    "amount": str(amount),
                    "tx_type": "debit" if withdrawal is not None else "credit",
                    "balance": str(balance),
                    "source_file": filename,
                })
        if not rows:
            issues.append("No Flinks transaction rows were found.")
        # Rows are printed newest-first. Each current balance should equal the
        # next older balance plus the signed movement on the current row.
        for current, older in zip(rows, rows[1:]):
            current_balance = Decimal(current["balance"])
            older_balance = Decimal(older["balance"])
            signed = Decimal(current["amount"]) if current["tx_type"] == "credit" else -Decimal(current["amount"])
            if current_balance - older_balance != signed:
                issues.append(
                    f"Page {current['page']}, transaction {current['sequence']}: "
                    "running balance does not match the table amount."
                )
        credits = sum((Decimal(row["amount"]) for row in rows if row["tx_type"] == "credit"), Decimal(0))
        debits = sum((Decimal(row["amount"]) for row in rows if row["tx_type"] == "debit"), Decimal(0))
        if rows:
            closing = Decimal(rows[0]["balance"])
            oldest = rows[-1]
            oldest_signed = Decimal(oldest["amount"]) if oldest["tx_type"] == "credit" else -Decimal(oldest["amount"])
            opening = Decimal(oldest["balance"]) - oldest_signed
            period_start = min(row["date"] for row in rows)
            period_end = max(row["date"] for row in rows)
        else:
            opening = closing = None
            period_start = period_end = None
        account_number = metadata["account_number"]
        result = {
            "source_file": filename,
            "source_sha256": sha,
            "adapter": "flinks_dashboard",
            "extraction_method": "native_text",
            "status": "review_required",
            # The source is newest-first; reverse the sequence within a date
            # so the shared ledger is oldest-first like the other adapters.
            "transactions": sorted(rows, key=lambda row: (row["date"], -row["sequence"])),
            "issues": issues + [CURRENCY_ISSUE],
            "warnings": [
                "Flinks exports do not print independent debit/credit totals; totals are calculated from the explicit table columns.",
                "Flinks exports do not print independent transaction counts; the extracted row count is retained for review.",
            ],
            "statement_counts": {"debits": sum(row["tx_type"] == "debit" for row in rows), "credits": sum(row["tx_type"] == "credit" for row in rows)},
            "extracted_counts": {"debits": sum(row["tx_type"] == "debit" for row in rows), "credits": sum(row["tx_type"] == "credit" for row in rows)},
            "account_id": f"flinks:{account_number}" if account_number else None,
            "currency": None,
            "currency_review_required": True,
            "period_start": period_start,
            "period_end": period_end,
            "opening_balance": str(opening) if opening is not None else None,
            "closing_balance": str(closing) if closing is not None else None,
            "last_transaction_balance": str(rows[-1]["balance"]) if rows else None,
            "debits": str(debits),
            "credits": str(credits),
            "statement_totals": {"debits": str(debits), "credits": str(credits)},
            "running_balance_checks": max(0, len(rows) - 1),
            **metadata,
        }
        if not issues:
            result["status"] = "reconciled_candidate_review_required"
        return result
    finally:
        if close_doc:
            doc.close()
