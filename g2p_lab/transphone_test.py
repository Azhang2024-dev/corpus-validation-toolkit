# -*- coding: utf-8 -*-
"""transphone live-fire test — portable edition.
Uses local venv + local nltk_data. Run: python transphone_test.py
"""
import os, sys, io
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.environ.setdefault("NLTK_DATA", str(BASE / "nltk_data"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from transphone import read_tokenizer

results = []
t = read_tokenizer('swa')
r = t.tokenize('watoto wanaondoka sasa hivi')
results.append(('SWA', r))
print('SWA ->', r, flush=True)

t2 = read_tokenizer('eng')
r2 = t2.tokenize('hello world')
results.append(('ENG', r2))
print('ENG ->', r2, flush=True)

t3 = read_tokenizer('hau')
r3 = t3.tokenize('yara suna makaranta')
results.append(('HAU', r3))
print('HAU ->', r3, flush=True)

if __name__ == "__main__":
    out = BASE / "output" / "transphone_test_result.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(f"{k} -> {v}" for k, v in results), encoding="utf-8")
    print(f"\n[saved] {out}", file=sys.stderr)
