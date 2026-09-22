"""Native parsers for common RBC Business and TD Business statement exports.

These layouts are text based, but their PDF text streams are positioned rather
than tabular.  The parsers use the visible column coordinates and reconcile the
rows to the printed totals before the ledger reaches underwriting.
"""
from datetime import date, datetime
from decimal import Decimal
import hashlib
import re

import pdfplumber
from statement_validation import parse_money, MONEY_TOKEN, MONEY_PATTERN


MONTHS = {m: i for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1
)}
MONEY_RE = MONEY_TOKEN


def _money(value):
    return parse_money(value)


def _base(data, filename, adapter):
    return {
        "source_file": filename,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "status": "review_required",
        "adapter": adapter,
        "transactions": [],
        "issues": [],
        "warnings": [],
    }


def _word_lines(page):
    words = page.dedupe_chars().extract_words(x_tolerance=2, y_tolerance=3)
    groups = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if not groups or abs(groups[-1][0] - word["top"]) > 3:
            groups.append([word["top"], [word]])
        else:
            groups[-1][1].append(word)
    return [(y, sorted(ws, key=lambda w: w["x0"])) for y, ws in groups]


def _date_label(text):
    # Preserve ordinary 11/22 dates. Only decode paired glyphs when the
    # entire label, including the month, proves the text was duplicated.
    raw = str(text).strip()
    pattern = r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    match = re.fullmatch(pattern, raw, re.I)
    if match: return match
    parts = raw.split()
    if len(parts) == 2 and all(len(p) % 2 == 0 and all(p[i] == p[i+1] for i in range(0, len(p), 2)) for p in parts):
        return re.fullmatch(pattern, ' '.join(p[::2] for p in parts), re.I)
    return None


def _add_row(result, filename, page, top, day, description, debit, credit, balance):
    if debit is None and credit is None:
        return
    if debit is not None and credit is not None:
        result["issues"].append(f"Page {page}, y={top:.2f}: debit and credit both populated")
        return
    amount = credit if credit is not None else debit
    result["transactions"].append({
        "id": f"{result['source_sha256'][:16]}:{page}:{top:.2f}",
        "page": page,
        "top": round(top, 2),
        "date": day.isoformat() if day else None,
        "month": day.strftime("%Y-%m") if day else None,
        "description": description.strip(),
        "amount": str(amount),
        "tx_type": "credit" if credit is not None else "debit",
        "balance": str(balance) if balance is not None else None,
        "source_file": filename,
    })


def _finish(result, opening=None, closing=None, expected=None, counts=None):
    debits = sum((Decimal(t["amount"]) for t in result["transactions"] if t["tx_type"] == "debit"), Decimal("0"))
    credits = sum((Decimal(t["amount"]) for t in result["transactions"] if t["tx_type"] == "credit"), Decimal("0"))
    result["debits"] = str(debits)
    result["credits"] = str(credits)
    result["opening_balance"] = str(opening) if opening is not None else None
    result["closing_balance"] = str(closing) if closing is not None else None
    result["last_transaction_balance"] = next((t["balance"] for t in reversed(result["transactions"]) if t.get("balance") is not None), None)
    result["running_balance_checks"] = sum(t.get("balance") is not None for t in result["transactions"])
    result["statement_totals"] = {
        "debits": str(expected["debits"]) if expected and expected.get("debits") is not None else str(debits),
        "credits": str(expected["credits"]) if expected and expected.get("credits") is not None else str(credits),
    }
    if counts:
        result["statement_counts"] = counts
    if expected:
        if expected.get("debits") is not None and expected["debits"] != debits:
            result["issues"].append(f"Printed debit total {expected['debits']} does not match extracted rows {debits}")
        if expected.get("credits") is not None and expected["credits"] != credits:
            result["issues"].append(f"Printed credit total {expected['credits']} does not match extracted rows {credits}")
    if counts:
        if counts.get("debits") is not None and counts["debits"] != sum(t["tx_type"] == "debit" for t in result["transactions"]):
            result["issues"].append("Printed debit count does not match extracted rows")
        if counts.get("credits") is not None and counts["credits"] != sum(t["tx_type"] == "credit" for t in result["transactions"]):
            result["issues"].append("Printed credit count does not match extracted rows")
    if opening is not None and closing is not None and opening + credits - debits != closing:
        result["issues"].append("Opening/closing balance equation does not reconcile")
    result["status"] = "review_required" if result["issues"] else "reconciled_candidate_review_required"
    return result


def _period_date(text, start, end, day=1):
    month = MONTHS[text[:3].upper()]
    year = start.year
    if start.month > end.month and month < start.month:
        year += 1
    return date(year, month, int(day))


def _rbc_header(page):
    for y, words in _word_lines(page):
        labels = {w["text"].lower(): w for w in words}
        if {"date", "description"}.issubset(labels) and any("cheques" in w["text"].lower() for w in words):
            debit = next(w["x0"] for w in words if "cheques" in w["text"].lower())
            credit = next(w["x0"] for w in words if "deposits" in w["text"].lower())
            balance = next(w["x0"] for w in words if w["text"].lower().startswith("balance"))
            desc = labels["description"]["x0"]
            return y, desc, debit, credit, balance
    return None


def parse_rbc(data, filename, doc):
    first = doc.pages[0].extract_text(x_tolerance=2) or ""
    result = _base(data, filename, "rbc_business")
    period_match = re.search(
        r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s+to\s+([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
        first,
    )
    account_match = re.search(r"Account\s*number:\s*([\d -]+)", first, re.I)
    if not period_match or not account_match:
        result["issues"].append("RBC account or statement period not found")
        return result
    sm, sd, sy, em, ed, ey = period_match.groups()
    start = date(int(sy), MONTHS[sm[:3].upper()], int(sd))
    end = date(int(ey), MONTHS[em[:3].upper()], int(ed))
    result.update(
        account_id="rbc:" + re.sub(r"\D", "", account_match.group(1)),
        currency="CAD",
        period_start=start.isoformat(),
        period_end=end.isoformat(),
    )
    opening_match = re.search(r"Opening balance on [^\n]*? (" + MONEY_PATTERN + r")\s*$", first, re.I | re.M)
    closing_match = re.search(r"Closing balance on .*?=\s*(" + MONEY_PATTERN + r")", first, re.I)
    totals_match = re.search(
        r"Total deposits\s*&\s*credits\s*\((\d+)\)\s*\+\s*([\d,]+\.\d{2}).*?"
        r"Total cheques\s*&\s*debits\s*\((\d+)\)\s*-\s*([\d,]+\.\d{2})",
        first,
        re.S | re.I,
    )
    opening = _money(opening_match.group(1)) if opening_match else None
    closing = _money(closing_match.group(1)) if closing_match else None
    expected = None
    counts = None
    if totals_match:
        nc, vc, nd, vd = totals_match.groups()
        expected = {"credits": _money(vc), "debits": _money(vd)}
        counts = {"credits": int(nc), "debits": int(nd)}
    pending = None
    last_date = None
    for pn, page in enumerate(doc.pages, 1):
        header = _rbc_header(page)
        if not header:
            continue
        header_y, desc_x, debit_x, credit_x, balance_x = header
        for y, words in _word_lines(page):
            if y <= header_y + 5 or y > page.height - 45:
                continue
            line_text = re.sub(r'\s+', '', ' '.join(w['text'] for w in words)).lower()
            if line_text.startswith('closingbalance'):
                pending = None
                break
            desc_words = [w for w in words if desc_x - 4 <= w["x0"] < debit_x - 8]
            description = " ".join(w["text"] for w in desc_words).strip()
            before_desc = " ".join(w["text"] for w in words if w["x0"] < desc_x - 4)
            date_match = _date_label(before_desc)
            row_date = None
            if date_match:
                try: row_date = _period_date(date_match.group(2), start, end, int(date_match.group(1)))
                except ValueError: result['issues'].append(f'Page {pn}: invalid date {before_desc!r}')
                last_date = row_date
            elif before_desc.strip():
                result['issues'].append(f'Page {pn}: unreadable date {before_desc!r}')
                last_date = None
            amounts = {"debit": None, "credit": None, "balance": None}
            for word in words:
                text = word["text"].replace("$", "")
                if not MONEY_RE.fullmatch(text):
                    continue
                x = word["x1"]
                try:
                    value = _money(text)
                except ValueError:
                    continue
                if debit_x - 12 <= x < credit_x - 10:
                    amounts["debit"] = value
                elif credit_x - 12 <= x < balance_x - 10:
                    amounts["credit"] = value
                elif x >= balance_x - 12:
                    amounts["balance"] = value
            if description.lower().startswith("opening balance") and amounts["balance"] is not None:
                if opening is None:
                    opening = amounts["balance"]
                continue
            if not description and not any(amounts.values()):
                continue
            if not any(amounts[k] is not None for k in ("debit", "credit")):
                if description:
                    if pending and not row_date:
                        pending["description"] += " " + description
                    else:
                        pending = {"date": row_date or last_date, "description": description}
                continue
            if pending and not row_date:
                pending["description"] += (" " + description) if description else ""
                _add_row(result, filename, pn, y, pending["date"], pending["description"], amounts["debit"], amounts["credit"], amounts["balance"])
                pending = None
            else:
                _add_row(result, filename, pn, y, row_date or last_date, description, amounts["debit"], amounts["credit"], amounts["balance"])
    return _finish(result, opening, closing, expected, counts)


def _td_header(page):
    for y, words in _word_lines(page):
        text = " ".join(w["text"].upper() for w in words)
        if "DESCRIPTION" in text and "CHEQUE/DEBIT" in text and "DEPOSIT/CREDIT" in text and "DATE" in text and "BALANCE" in text:
            find = lambda needle: next(w["x0"] for w in words if w["text"].upper() == needle)
            return y, find("DESCRIPTION"), find("CHEQUE/DEBIT"), find("DEPOSIT/CREDIT"), find("DATE"), find("BALANCE")
    return None


def _td_date(text, start, end):
    match = re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{1,2})", text.upper())
    if not match:
        return None
    month, day = MONTHS[match.group(1)], int(match.group(2))
    year = start.year
    if start.month > end.month and month < start.month:
        year += 1
    return date(year, month, day)


def _td_summary(text, label, stop_label):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().lower().startswith(label.lower()):
            continue
        for candidate in lines[index + 1:index + 6]:
            candidate_text = candidate.strip().lower()
            if stop_label and candidate_text.startswith(stop_label.lower()):
                break
            match = re.match(r"\s*(\d+)\s+([\d,]+\.\d{2})\b", candidate)
            if match:
                return int(match.group(1)), _money(match.group(2))
    return None


def _parse_td_amounts(words, debit_x, credit_x, date_x, balance_x):
    amounts = {"debit": None, "credit": None, "balance": None}
    for word in words:
        x, text = word["x0"], word["text"].replace("$", "")
        if debit_x - 10 <= x < credit_x - 10:
            if MONEY_RE.fullmatch(text):
                amounts["debit"] = _money(text)
        elif credit_x - 10 <= x < date_x - 10:
            if MONEY_RE.fullmatch(text):
                amounts["credit"] = _money(text)
            else:
                glued = re.match(r"^(\$?[\d,]+\.\d{2})([A-Z]{3}\d{2})$", text, re.I)
                if glued:
                    amounts["credit"] = _money(glued.group(1))
        elif x >= balance_x - 10 and MONEY_RE.fullmatch(text):
            amounts["balance"] = _money(text)
    return amounts


def _td_balance_cell(page, y, balance_x):
    # Separate overlapping footer labels from the actual balance glyphs.
    # Never repair a balance by stripping arbitrary letters from a mixed word.
    groups = {}
    for char in page.chars:
        if char['x0'] >= balance_x - 10 and abs(char['top'] - y) <= 3:
            key = (round(char['top'], 2), round(char['size'], 2))
            groups.setdefault(key, []).append(char)
    values = set()
    for chars in groups.values():
        text = ''.join(c['text'] for c in sorted(chars, key=lambda c: c['x0'])).strip()
        if MONEY_RE.fullmatch(text):
            values.add(_money(text))
    return next(iter(values)) if len(values) == 1 else None


def parse_td_formal(data, filename, doc):
    first = doc.pages[0].extract_text(x_tolerance=2) or ""
    result = _base(data, filename, "td_business")
    period_match = re.search(r"Statement From - To.*?([A-Z]{3})\s*(\d{2})/(\d{2})\s*-\s*([A-Z]{3})\s*(\d{2})/(\d{2})", first, re.S | re.I)
    account_match = re.search(r"\b\d{4}\s+(\d{4}-\d{7})\b", first)
    if not period_match or not account_match:
        result["issues"].append("TD account or statement period not found")
        return result
    sm, sd, sy, em, ed, ey = period_match.groups()
    start = date(2000 + int(sy), MONTHS[sm.upper()], int(sd))
    end = date(2000 + int(ey), MONTHS[em.upper()], int(ed))
    currency_match = re.search(r"ACCOUNT\s*-\s*([A-Z]{3})\b", first)
    currency = currency_match.group(1) if currency_match else None
    if currency is None: result["issues"].append("TD currency not found; verify the original account")
    result.update(account_id="td:" + re.sub(r"\D", "", account_match.group(1))[-7:], currency=currency,
                  period_start=start.isoformat(), period_end=end.isoformat())
    expected = {"debits": Decimal("0"), "credits": Decimal("0")}
    counts = {"debits": 0, "credits": 0}
    opening = None
    closing = None
    for page_index, page in enumerate(doc.pages, 1):
        text = page.extract_text(x_tolerance=2) or ""
        credit_summary = _td_summary(text, "Credits", "Debits")
        debit_summary = _td_summary(text, "Debits", "")
        if credit_summary:
            counts["credits"] += credit_summary[0]; expected["credits"] += credit_summary[1]
        if debit_summary:
            counts["debits"] += debit_summary[0]; expected["debits"] += debit_summary[1]
        header = _td_header(page)
        if not header:
            continue
        header_y, desc_x, debit_x, credit_x, date_x, balance_x = header
        for y, words in _word_lines(page):
            if y <= header_y + 5 or y > 615:
                continue
            description = " ".join(w["text"] for w in words if 55 <= w["x0"] < debit_x - 8).strip()
            # TD's PDF sometimes glues the date to the deposit amount (for
            # example ``4,403.29AUG04``), so search both date and credit cells.
            date_text = " ".join(w["text"] for w in words if credit_x - 10 <= w["x0"] < balance_x - 10)
            day = _td_date(date_text, start, end)
            amounts = _parse_td_amounts(words, debit_x, credit_x, date_x, balance_x)
            cell_balance = _td_balance_cell(page, y, balance_x)
            if cell_balance is not None: amounts["balance"] = cell_balance
            if description.upper().startswith("BALANCE FORWARD"):
                if amounts["balance"] is not None and opening is None:
                    opening = amounts["balance"]
                continue
            if amounts["debit"] is None and amounts["credit"] is None:
                continue
            _add_row(result, filename, page_index, y, day, description, amounts["debit"], amounts["credit"], amounts["balance"])
            if result["transactions"]:
                result["transactions"][-1]["source_date_evidence"] = {
                    "printed_date": date_text,
                    "normalized_date": day.isoformat() if day else None,
                    "page": page_index,
                    "top": round(y, 2),
                    "method": "native_td_date_column",
                }
    # The final transaction balance is the statement closing balance.
    if result["transactions"]:
        last_balance = next((t["balance"] for t in reversed(result["transactions"]) if t.get("balance") is not None), None)
        closing = _money(last_balance) if last_balance is not None else None
    return _finish(result, opening, closing, expected, counts)


def parse_td_activity(data, filename, doc):
    first = doc.pages[0].extract_text(x_tolerance=2) or ""
    result = _base(data, filename, "td_activity")
    account_match = re.search(r"TD\s+BUSINESS\s+(?:DIGITAL|UNLIMITED)\s+ACCOUNT\s*-\s*(\d+)", first, re.I)
    balance_match = re.search(r"Current Balance.*?\n(" + MONEY_PATTERN + r")", first, re.S | re.I)
    if not account_match:
        result["issues"].append("TD online activity account not found")
        return result
    result.update(account_id="td:" + account_match.group(1), currency="CAD")
    expected = {"debits": Decimal("0"), "credits": Decimal("0")}
    total_match = re.search(r"Total\s*:\s*\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})", "\n".join(p.extract_text(x_tolerance=2) or "" for p in doc.pages), re.I)
    if total_match:
        expected = {"debits": _money(total_match.group(1)), "credits": _money(total_match.group(2))}
    search=re.search(r'Your transactions for ([A-Za-z]{3} \d{1,2}, \d{4}) to ([A-Za-z]{3} \d{1,2}, \d{4})',first)
    if search:
        result['search_start']=datetime.strptime(search[1],'%b %d, %Y').date().isoformat()
        result['search_end']=datetime.strptime(search[2],'%b %d, %Y').date().isoformat()
    dates = []
    header = None
    for page_index, page in enumerate(doc.pages, 1):
        page_header = None
        for y, words in _word_lines(page):
            text = " ".join(w["text"].upper() for w in words)
            if "TRANSACTION" in text and "WITHDRAWALS" in text and "DEPOSITS" in text and "BALANCE" in text:
                find = lambda needle: next(w["x0"] for w in words if w["text"].upper() == needle)
                page_header = (y, find("TRANSACTION"), find("WITHDRAWALS"), find("DEPOSITS"), find("BALANCE"))
                break
        if page_header:
            header = page_header
        if not header:
            continue
        header_y, desc_x, debit_x, credit_x, balance_x = page_header or (0, *header[1:])
        # A continuation page has no repeated heading. Its rows start near the
        # top of the page, so the inherited heading must not filter them out.
        if not page_header:
            header_y = -1
        for y, words in _word_lines(page):
            if y <= header_y + 5 or y > page.height - 25:
                continue
            prefix = " ".join(w["text"] for w in words if w["x0"] < desc_x - 5)
            m = re.search(r"([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})", prefix)
            if not m:
                continue
            try:
                day = date(int(m.group(3)), MONTHS[m.group(1)[:3].upper()], int(m.group(2)))
            except (KeyError, ValueError):
                continue
            description = " ".join(w["text"] for w in words if desc_x - 5 <= w["x0"] < debit_x - 8).strip()
            debit = credit = balance = None
            for word in words:
                text = word["text"].replace("$", "")
                if not MONEY_RE.fullmatch(text):
                    continue
                value = _money(text); x = word["x1"]
                if debit_x - 10 <= x < credit_x - 10: debit = value
                elif credit_x - 10 <= x < balance_x - 10: credit = value
                elif x >= balance_x - 10: balance = value
            if debit is None and credit is None:
                continue
            dates.append(day)
            _add_row(result, filename, page_index, y, day, description, debit, credit, balance)
    if len(dates)>1 and dates[0]>dates[-1]:
        result['transactions'].reverse()
    if dates:
        result["period_start"] = min(dates).isoformat()
        result["period_end"] = max(dates).isoformat()
    rows=result['transactions']
    opening=closing=None
    if rows and rows[0].get('balance') is not None:
        head=rows[0]
        opening=_money(head['balance'])-(_money(head['amount']) if head['tx_type']=='credit' else -_money(head['amount']))
        closing=_money(rows[-1]['balance']) if rows[-1].get('balance') is not None else None
    result['opening_balance_source']='derived from earliest displayed transaction'
    result['warnings'].append('Online activity: opening balance is derived, not independently printed. Confirm the exported window is complete.')
    if not total_match:
        result['issues'].append('TD activity printed totals missing; completeness requires review.')
    return _finish(result, opening, closing, expected if total_match else None, None)



def parse_td(data, filename, doc):
    first = doc.pages[0].extract_text(x_tolerance=2) or ""
    if "Statement of Account" in first and "CHEQUE/DEBIT" in first:
        return parse_td_formal(data, filename, doc)
    if "Account Activity" in first and "Withdrawals" in first and "Deposits" in first:
        return parse_td_activity(data, filename, doc)
    result = _base(data, filename, "td")
    result["issues"].append("Unsupported TD layout")
    return result
