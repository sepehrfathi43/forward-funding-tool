"""Shared monetary parsing and evidence checks for every statement import path."""
from datetime import date
from decimal import Decimal, InvalidOperation
import re

VALIDATION_VERSION = 2
_NUMBER = r'(?:\d{1,3}(?:[ \u00a0]\d{3})+[.,]\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d{1,3}(?:\.\d{3})+,\d{2}|\d+[.,]\d{2})'
MONEY_PATTERN = rf'(?:[-+\u2212]?[ \u00a0]*\$?[ \u00a0]*[-+\u2212]?{_NUMBER}-?|\([ \u00a0]*\$?[ \u00a0]*{_NUMBER}[ \u00a0]*\))(?:[ \u00a0]*(?:DR|CR|OD))?'
MONEY_TOKEN = re.compile(MONEY_PATTERN, re.I)


def parse_money(value):
    """Read a complete cell; preserve signs and reject malformed/grouped values."""
    text = str(value).strip().replace('\u2212', '-').replace('\u2013', '-')
    suffix = re.search(r'\s*(DR|CR|OD)$', text, re.I)
    direction = suffix.group(1).upper() if suffix else None
    if suffix: text = text[:suffix.start()].strip()
    negative = False
    if text.startswith('(') and text.endswith(')'):
        negative = True; text = text[1:-1].strip()
    elif '(' in text or ')' in text:
        raise ValueError(f'Invalid money cell: {value!r}')
    text = re.sub(r'\s', '', text).replace('$', '')
    if text.startswith(('-', '+')):
        if negative: raise ValueError(f'Conflicting money signs: {value!r}')
        negative = text.startswith('-'); text = text[1:]
    if text.endswith('-'):
        if negative: raise ValueError(f'Conflicting money signs: {value!r}')
        negative = True; text = text[:-1]
    if direction == 'CR' and negative:
        raise ValueError(f'Conflicting money signs: {value!r}')
    negative = negative or direction in ('DR', 'OD')
    # The last punctuation is the decimal separator. Thousands groups must
    # contain three digits; this never accepts NaN, infinity or partial cells.
    if ',' in text and ('.' not in text or text.rfind(',') > text.rfind('.')) and len(text.rsplit(',',1)[1])<=2:
        if not re.fullmatch(r'(?:\d+|\d{1,3}(?:\.\d{3})+),\d{1,2}', text):
            raise ValueError(f'Invalid money cell: {value!r}')
        text = text.replace('.', '').replace(',', '.')
    else:
        if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', text):
            raise ValueError(f'Invalid money cell: {value!r}')
        text = text.replace(',', '')
    return Decimal(text).quantize(Decimal('.01')) * (-1 if negative else 1)


def decimal_value(value):
    if isinstance(value, bool): raise ValueError('Boolean is not an amount')
    try: number = Decimal(str(value))
    except (InvalidOperation, ValueError): raise ValueError('Invalid numeric amount')
    try: valid = number.is_finite() and number == number.quantize(Decimal('.01'))
    except InvalidOperation: valid = False
    if not valid:
        raise ValueError('Amount must be finite with at most two decimal places')
    return number


def iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Date must use YYYY-MM-DD')
    return date.fromisoformat(value)


def validate_statement(result):
    """Check source order, dates and every printed checkpoint without repairs.

    Totals alone can hide an incorrect date, a reversed debit or offsetting
    omissions. Keep every parser's existing issues and add independent checks.
    """
    if 'account_statements' in result:
        for child in result['account_statements']: validate_statement(child)
        if any(c.get('status') == 'review_required' for c in result['account_statements']):
            result['status'] = 'review_required'
        return result
    rows = result.get('transactions', [])
    if not rows: return result
    issues = [i for i in result.get('issues', []) if not i.startswith('Shared validation:')]
    errors = []
    def fail(text): errors.append('Shared validation: ' + text)
    def number(value, label):
        if value is None: return None
        try: return decimal_value(value)
        except ValueError: fail(label + ' is not a finite amount in cents'); return None
    try:
        start, end = iso_day(result.get('period_start')), iso_day(result.get('period_end'))
        if start > end: raise ValueError()
    except ValueError:
        fail('invalid or missing statement period'); start = end = None
    opening = number(result.get('opening_balance'), 'opening balance')
    closing = number(result.get('closing_balance'), 'closing balance')
    running = opening
    previous_date = None
    sums = {'debits': Decimal(0), 'credits': Decimal(0)}
    counts = {'debits': 0, 'credits': 0}
    balance_checks = 0; seen = set()
    for index, row in enumerate(rows, 1):
        label = f'row {index} (page {row.get("page", "?")})'
        try:
            day = iso_day(row.get('date'))
            if start and not start <= day <= end: fail(label + ' date is outside the statement period')
            if previous_date and day < previous_date: fail(label + ' date is earlier than the preceding source row')
            if row.get('month') != day.strftime('%Y-%m'): fail(label + ' month does not match its date')
            previous_date = day
        except ValueError: fail(label + ' date is invalid or missing')
        row_id = row.get('id')
        if not row_id or row_id in seen: fail(label + ' source ID is missing or duplicated')
        seen.add(row_id)
        if not str(row.get('description') or '').strip(): fail(label + ' description is missing')
        amount = number(row.get('amount'), label + ' amount')
        side = row.get('tx_type')
        if amount is None or amount <= 0 or side not in ('debit', 'credit'):
            fail(label + ' requires one positive debit or credit'); running = None; continue
        sums[side + 's'] += amount; counts[side + 's'] += 1
        if running is not None: running += amount if side == 'credit' else -amount
        printed = number(row.get('balance'), label + ' balance')
        if printed is not None:
            if running is not None:
                balance_checks += 1
                if running != printed: fail(label + f' balance mismatch: calculated {running}, printed {printed}')
            # Restart at source evidence, so one error does not mask the rest.
            running = printed
    for side in sums:
        total = number(result.get('statement_totals', {}).get(side), 'statement ' + side)
        if total is not None and total != sums[side]: fail(side + ' total does not match the statement')
        count = result.get('statement_counts', {}).get(side)
        if count is not None and (type(count) is not int or count != counts[side]):
            fail(side + ' count does not match the statement')
    if opening is not None and closing is not None and opening + sums['credits'] - sums['debits'] != closing:
        fail('opening + credits - debits does not equal closing')
    if running is not None and closing is not None and running != closing:
        fail('final balance checkpoint does not reach the closing balance')
    result['issues'] = list(dict.fromkeys(issues + errors))
    result['validation'] = dict(version=VALIDATION_VERSION, date_checks=len(rows),
                                balance_checks=balance_checks, errors=len(errors))
    if errors: result['status'] = 'review_required'
    return result
