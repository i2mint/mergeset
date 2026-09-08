import json
for l in open('evaluations.jsonl'):
    r = json.loads(l)
    extra = r.get('failed_at') or f"b={r.get('build')} t={r.get('test')} l={r.get('lint')}"
    print(f"{r['verdict']:>4}  {r['label']:<64} {r.get('secs',0):>3}s  {extra:<26} {r.get('why','')}")
