# -*- coding: utf-8 -*-
"""G2P 斯语对照：espeak / phonemizer / epitran / transphone vs ipa-dict"""
import os, sys, io, subprocess
from pathlib import Path
BASE = Path(__file__).resolve().parent
ESPEAK = BASE / 'espeak-ng' / 'espeak-ng.exe'
os.environ['PHONEMIZER_ESPEAK_LIBRARY'] = str(BASE / 'espeak-ng' / 'libespeak-ng.dll')
os.environ['ESPEAK_DATA_PATH'] = str(BASE / 'espeak-ng' / 'espeak-ng-data')
os.environ.setdefault('NLTK_DATA', str(BASE / 'nltk_data'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ipa-dict 查表
DICT = {}
with open(BASE.parent / 'data' / 'ipa' / 'sw.txt', encoding='utf-8') as f:
    for line in f:
        line = line.rstrip('\n')
        if not line.strip(): continue
        p = line.split('\t')
        if len(p) >= 2:
            DICT[p[0].strip().lower()] = p[1].strip().strip('/').lower()

WORDS = ["habari","watoto","anasoma","nzuri","asante","ng'ombe","ndizi","mzuri",
         "hifadhi","kitabu","safari","sasa","hivi","kidijitali","programu","mgeni"]

def espeak_sw(w):
    p = subprocess.run([str(ESPEAK), '-q', '--ipa', '-v', 'sw', '-w', w],
                       capture_output=True, text=True, timeout=30)
    s = p.stdout.strip()
    # 去重音符号
    return ''.join(c for c in s if not ('\u02c8' == c or '\u02cc' == c))

def phonemizer_sw(w):
    from phonemizer.backend import EspeakBackend
    be = EspeakBackend(language='sw')
    return be.phonemize([w])[0].strip()

def epitran_sw(w):
    import epitran
    epi = epitran.Epitran('swa-Latn')
    return epi.transliterate(w)

def transphone_sw(w):
    from transphone import read_tokenizer
    t = read_tokenizer('swa')
    return ''.join(t.tokenize(w))

def norm(s):
    # 去掉重音/变长标记，统一小写，去掉空格
    out = []
    for c in s:
        if c.isalnum():
            out.append(c)
    return ''.join(out).lower()

def dist(a, b):
    # 编辑距离
    a, b = norm(a), norm(b)
    dp = list(range(len(b)+1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]; dp[0] = i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j]+1, dp[j-1]+1, prev + (ca != cb))
            prev = cur
    return dp[-1]

rows = []
for w in WORDS:
    gold = DICT.get(w, '')
    row = {'word': w, 'gold': gold}
    for name, fn in [('espeak', espeak_sw), ('phonemizer', phonemizer_sw),
                     ('epitran', epitran_sw), ('transphone', transphone_sw)]:
        try:
            row[name] = fn(w)
        except Exception as e:
            row[name] = f'ERR:{type(e).__name__}'
    rows.append(row)

hdr = f"{'词':<12}{'ipa-dict':<22}{'espeak':<22}{'phonemizer':<22}{'epitran':<22}{'transphone':<22}"
print(hdr)
stats = {k: [] for k in ['espeak','phonemizer','epitran','transphone']}
for r in rows:
    line = f"{r['word']:<12}{r['gold'][:20]:<22}"
    for k in stats:
        v = r[k]
        if r['gold'] and not v.startswith('ERR'):
            d = dist(r['gold'], v)
            stats[k].append(d)
            line += f"{v[:20]:<22}"
        else:
            line += f"{v[:20]:<22}"
    print(line)
print()
print('=== 平均编辑距离(越小越接近 ipa-dict 人工发音) ===')
for k, ds in stats.items():
    if ds:
        print(f"  {k:<12} avg={sum(ds)/len(ds):.2f}  n={len(ds)}")
