"""Calendar coverage and cash balances shared by all account formats."""
import calendar
from datetime import date, timedelta
from decimal import Decimal
from statement_validation import decimal_value, iso_day


def latest_consecutive_months(months):
    ordered=sorted(set(months))
    if not ordered:return []
    keep=[ordered[-1]]
    for month in reversed(ordered[:-1]):
        y,m=map(int,keep[0].split('-'))
        previous=(date(y,m,1)-timedelta(days=1)).strftime('%Y-%m')
        if month!=previous:break
        keep.insert(0,month)
    return keep


def available_offer_months(months):
    """Prefer recent continuous history; gaps alone do not prevent an offer.

    If the latest run has fewer than three months, use supplied months across
    gaps. Callers separately report partial-day coverage for each month.
    """
    supplied=sorted(set(months))
    recent=latest_consecutive_months(supplied)
    return recent if len(recent)>=3 else supplied


def coverage_gaps(results):
    accounts={}
    for r in results:
        if r.get('exclude_from_ledger'):continue
        try:start,end=iso_day(r.get('period_start')),iso_day(r.get('period_end'))
        except ValueError:continue
        if start>end or not r.get('account_id'):continue
        accounts.setdefault(r['account_id'],[]).append((start,end))
    gaps=[]
    for account,intervals in accounts.items():
        intervals.sort(); previous=intervals[0][1]
        for start,end in intervals[1:]:
            if start>previous+timedelta(days=1):
                gaps.append({'Account':account,'Missing from':(previous+timedelta(days=1)).isoformat(),
                             'Missing through':(start-timedelta(days=1)).isoformat()})
            previous=max(previous,end)
    return gaps


def covered_dates(results):
    """Intersect supplied account coverage; never infer coverage from activity."""
    accounts = {}
    for result in results:
        if result.get('exclude_from_ledger'):
            continue
        account = result.get('account_id')
        if not account:
            return set()
        days = accounts.setdefault(account, set())
        try:
            start, end = iso_day(result.get('period_start')), iso_day(result.get('period_end'))
        except ValueError:
            return set()
        if end < start or (end - start).days > 3660:
            return set()
        days.update(start + timedelta(days=n) for n in range((end - start).days + 1))
    return set.intersection(*accounts.values()) if accounts else set()


def coverage_summary(results, months=None):
    days = covered_dates(results)
    selected = set(months) if months is not None else {d.strftime('%Y-%m') for d in days}
    rows = []
    for month in sorted(selected):
        year, number = map(int, month.split('-'))
        total = calendar.monthrange(year, number)[1]
        count = sum(d.strftime('%Y-%m') == month for d in days)
        rows.append({'month': month, 'covered_days': count, 'calendar_days': total,
                     'coverage_fraction': count / total, 'complete': count == total})
    return rows


def covered_frame(frame, results, months):
    days = {d.isoformat() for d in covered_dates(results) if d.strftime('%Y-%m') in months}
    return frame[frame.date.isin(days)].copy()


def daily_balances(frame, results, months):
    """Reconstruct only covered days, restarting at each statement opening.

    Missing days never inherit a stale balance. Conflicting overlapping
    reconstructions are unavailable rather than arbitrarily selecting one.
    """
    if not months or not results or 'account_id' not in frame:
        return None
    wanted = {d for d in covered_dates(results) if d.strftime('%Y-%m') in months}
    if not wanted:
        return None
    accounts = {}
    try:
        for statement in results:
            if statement.get('exclude_from_ledger'):
                continue
            account = statement['account_id']
            start, end = iso_day(statement['period_start']), iso_day(statement['period_end'])
            if not any(start <= d <= end for d in wanted):
                continue
            balance = decimal_value(statement.get('original_opening_balance', statement.get('opening_balance')))
            rate = Decimal(str(statement.get('reporting_rate', 1)))
            if not rate.is_finite() or rate <= 0:
                return None
            records = frame[frame.account_id.eq(account)].to_dict('records')
            by_day = {}
            for row in records:
                day = iso_day(row['date'])
                if start <= day <= end:
                    # A shared handoff date belongs to the statement whose
                    # ledger supplied the transaction, not both openings.
                    origin = row.get('statement_period_start')
                    if origin and origin < statement['period_start']:
                        continue
                    by_day.setdefault(day, []).append(row)
            balances = accounts.setdefault(account, {})
            cursor = start
            while cursor <= min(end, max(wanted)):
                below = balance < 0
                for row in by_day.get(cursor, []):
                    amount = decimal_value(row.get('original_amount', row.get('amount')))
                    if amount <= 0 or row.get('tx_type') not in ('credit', 'debit'):
                        return None
                    balance += amount if row['tx_type'] == 'credit' else -amount
                    below = below or balance < 0
                if cursor in wanted:
                    value = (balance * rate, below)
                    if cursor in balances and balances[cursor][0] != value[0]:
                        return None
                    if cursor in balances:
                        value = (value[0], below or balances[cursor][1])
                    balances[cursor] = value
                cursor += timedelta(days=1)
        if not accounts or any(not wanted.issubset(values) for values in accounts.values()):
            return None
        totals = [sum(values[d][0] for values in accounts.values()) for d in wanted]
        return dict(average_daily_balance=float(sum(totals) / len(totals)),
                    negative_days=sum(any(v[d][0] < 0 for v in accounts.values()) for d in wanted),
                    intraday_negative_days=sum(any(v[d][1] for v in accounts.values()) for d in wanted),
                    covered_days=len(wanted))
    except (ValueError, TypeError, KeyError):
        return None
