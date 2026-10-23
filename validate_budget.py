"""Isolated, unpaid budget guard checks. Does not touch the real cost ledger."""
import json
import tempfile
from pathlib import Path
import budget

def main():
    original_root,original_ledger=budget.ROOT,budget.LEDGER
    checks=[]
    with tempfile.TemporaryDirectory(prefix='sc-budget-check-',dir=original_root) as folder:
        budget.ROOT=Path(folder);budget.LEDGER=budget.ROOT/'ledger.json'
        try:
            assert budget.summary()['counted_usd']=='0';checks.append('new ledger starts at zero')
            rid=budget.reserve('simulated','test-only','4.99',{})
            budget.finish(rid,actual='4.99')
            try:budget.reserve('simulated','test-only','0.02',{});raise AssertionError('cap bypassed')
            except RuntimeError:checks.append('cumulative cap refuses excess reservation')
            budget.LEDGER=budget.ROOT/'uncertain.json'
            rid=budget.reserve('simulated','test-only','0.10',{});budget.uncertain(rid)
            assert budget.summary()['counted_usd']=='0.100000'
            try:budget.reserve('simulated retry','test-only','0.01',{});raise AssertionError('uncertain retried')
            except RuntimeError:checks.append('uncertain cost retained; subsequent paid request blocked')
            budget.LEDGER=budget.ROOT/'unfinished.json';budget.reserve('simulated','test-only','0.05',{})
            try:budget.reserve('simulated','test-only','0.01',{});raise AssertionError('unfinished retried')
            except RuntimeError:checks.append('unfinished persisted reservation blocks requests after interruption')
            budget.LEDGER=budget.ROOT/'upper-bound.json';rid=budget.reserve('simulated','test-only','0.01',{});budget.finish(rid,estimate='0.0045')
            assert budget.summary()['counted_usd']=='0.010000';checks.append('transcription upper bound retained when exact usage unavailable')
            budget.LEDGER=budget.ROOT/'metered.json';rid=budget.reserve('simulated','test-only','0.10',{});budget.finish(rid,actual='0.0212341')
            assert budget.summary()['counted_usd']=='0.021235';checks.append('metered token cost rounds upward and releases only known remainder')
        finally:budget.ROOT,budget.LEDGER=original_root,original_ledger
    (original_root/'budget-validation.json').write_text(json.dumps({'paid_calls':0,'test_ledger_isolated':True,'checks':checks},indent=2),encoding='utf-8')
    print(json.dumps(checks))

if __name__=='__main__':main()
