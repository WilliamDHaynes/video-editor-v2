"""Durable hard-cap reservations. Uncertain paid requests are never auto-retried."""
import contextlib
import json
import msvcrt
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

ROOT=Path(__file__).resolve().parent
LEDGER=ROOT/'api-cost-ledger.json'
CAP=Decimal('5.00')

def now():return datetime.now(timezone.utc).isoformat()

@contextlib.contextmanager
def locked():
    with (ROOT/'api-budget.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:yield
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def read():
    if not LEDGER.exists():return {'cap_usd':'5.00','currency':'USD','requests':[],'created_utc':now()}
    data=json.loads(LEDGER.read_text(encoding='utf-8'))
    if Decimal(data['cap_usd'])!=CAP:raise RuntimeError('Ledger cap mismatch')
    return data

def save(data):
    temp=LEDGER.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as handle:
        handle.write(json.dumps(data,indent=2));handle.flush();os.fsync(handle.fileno())
    os.replace(temp,LEDGER)

def used(data):return sum((Decimal(r['counted_usd']) for r in data['requests']),Decimal('0'))

def summary():
    with locked():
        data=read()
        if not LEDGER.exists():save(data)
    total=used(data)
    return {**data,'counted_usd':str(total),'remaining_usd':str(CAP-total),'paid_request_count':len(data['requests']),'uncertain_requests':sum(r['status'] in ('reserved','uncertain') for r in data['requests'])}

def reserve(kind,model,amount,units):
    amount=Decimal(str(amount)).quantize(Decimal('0.000001'),rounding=ROUND_CEILING)
    if not Decimal('0')<amount<=CAP:raise ValueError('Invalid reservation')
    with locked():
        data=read()
        if any(r['status'] in ('reserved','uncertain') for r in data['requests']):
            raise RuntimeError('An earlier paid request has uncertain outcome; manual review is required. No automatic retry.')
        if used(data)+amount>CAP:raise RuntimeError('Hard $5 total cap would be exceeded')
        rid=uuid.uuid4().hex
        data['requests'].append({'id':rid,'created_utc':now(),'kind':kind,'model':model,'status':'reserved','reserved_usd':str(amount),'counted_usd':str(amount),'actual_cost_usd':None,'units':units})
        save(data);return rid

def finish(rid,actual=None,usage=None,estimate=None):
    with locked():
        data=read();record=next(r for r in data['requests'] if r['id']==rid)
        if actual is None:
            record['status']='completed_upper_bound_retained'
        else:
            actual=Decimal(str(actual)).quantize(Decimal('0.000001'),rounding=ROUND_CEILING)
            if actual>Decimal(record['reserved_usd']):
                record['status']='uncertain';save(data);raise RuntimeError('Usage exceeded conservative reservation; paid pipeline stopped')
            record.update(status='completed_metered',actual_cost_usd=str(actual),counted_usd=str(actual))
        record['finished_utc']=now();record['usage']=usage
        if estimate is not None:record['estimated_cost_usd']=str(estimate)
        save(data)

def uncertain(rid):
    with locked():
        data=read();record=next(r for r in data['requests'] if r['id']==rid)
        record.update(status='uncertain',finished_utc=now(),note='Response/cost uncertain; full reservation retained. No automatic retry.')
        save(data)
