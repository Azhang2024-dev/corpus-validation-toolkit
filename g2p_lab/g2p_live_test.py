# -*- coding: utf-8 -*-
"""G2P tools live-fire test — portable edition.
One script, fixed test sentences, JSON result dump.
Self-contained: uses local espeak-ng (../espeak-ng), local nltk_data,
local venv. Run from anywhere: python g2p_live_test.py
"""
import json, os, subprocess, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent          # g2p_lab/
ESPEAK_DIR = BASE / "espeak-ng"
ESPEAK = ESPEAK_DIR / "espeak-ng.exe"

# ---- make local resources visible BEFORE importing the libraries ----
os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = str(ESPEAK_DIR / "libespeak-ng.dll")
os.environ["ESPEAK_DATA_PATH"] = str(ESPEAK_DIR / "espeak-ng-data")
os.environ.setdefault("NLTK_DATA", str(BASE / "nltk_data"))
os.environ.setdefault("NLTK_ALLOW_PROXIED_URLOPEN", "1")

OUT = {}

def run(fn):
    name = fn.__name__
    try:
        OUT[name] = {"status": "ok", "data": fn()}
    except Exception as ex:
        OUT[name] = {"status": "error", "error": f"{type(ex).__name__}: {ex}"}

# ---------- 1. espeak-ng (direct CLI: IPA) ----------
def espeak_ipa():
    r = {}
    for lang, text in [("en", "hello world"), ("sw", "Watoto wanaondoka sasa hivi?"),
                       ("sw", "Niko na KSh 500 saa tatu."), ("hau", "Yara suna makaranta"),
                       ("fil", "Salamat sa tulong"), ("gu", "કેમ છો"), ("te", "నకు ధన్యవాదాలు")]:
        p = subprocess.run([str(ESPEAK), "-q", "--ipa", "-v", lang, text],
                           capture_output=True, text=True, timeout=30)
        r[f"{lang}:{text}"] = p.stdout.strip()
    return r
run(espeak_ipa)

# ---------- 2. phonemizer (ESpeak backend) ----------
def phonemizer_test():
    from phonemizer import phonemize
    from phonemizer.backend import EspeakBackend
    r = {}
    r["en_ipa"] = phonemize("hello world", language="en-us", backend="espeak")
    r["sw_ipa"] = EspeakBackend(language="sw").phonemize(["Watoto wanaondoka sasa hivi?"])
    r["sw_default"] = phonemize("hello world", language="sw", backend="espeak",
                                with_stress=True)  # default output check
    return r
run(phonemizer_test)

# ---------- 3. epitran ----------
def epitran_test():
    import epitran
    r = {}
    tests = {"swa-Latn": "Watoto wanaondoka sasa hivi? Niko na KSh 500.",
             "hau-Latn": "Yara suna makaranta",
             "tgl-Latn": "Salamat sa tulong",
             "ind-Latn": "Terima kasih banyak",
             "spa-Latn": "Hola mundo",
             "tur-Latn": "Merhaba dünya",
             "rus-Cyrl": "Привет мир",
             "hin-Deva": "नमस्ते दुनिया",
             "ben-Beng": "নমস্কার",
             "tam-Taml": "வணக்கம்",
             "tel-Telu": "నమస్కారం",
             "mar-Deva": "नमस्कार",
             "ara-Arab": "مرحبا بالعالم",
             "eng-Latn": "hello world",
             "fra-Latn": "Bonjour le monde",
             "por-Latn": "Olá mundo",
             "cmn-Hans": "你好世界",
             "guj-Gujr": "કેમ છો",
             "urd-Arab": "ہیلو"}
    for code, text in tests.items():
        try:
            r[code] = epitran.Epitran(code).transliterate(text)
        except Exception as ex:
            r[code] = f"UNSUPPORTED/ERROR: {type(ex).__name__}"
    try:
        import glob
        d = os.path.join(os.path.dirname(epitran.__file__), "data", "map")
        r["_total_map_files"] = len(glob.glob(os.path.join(d, "*.csv")))
    except Exception:
        pass
    return r
run(epitran_test)

# ---------- 4. g2p_en (ARPABET, English) ----------
def g2p_en_test():
    from g2p_en import G2p
    g2p = G2p()
    return {"hello world": g2p("hello world"),
            "with number": g2p("I have 5 dollars")}
run(g2p_en_test)

# ---------- 5. gruut ----------
def gruut_test():
    from gruut import sentences
    r = {}
    for lang, text in [("en-us", "hello world"), ("sw", "Watoto wanaondoka sasa hivi?")]:
        try:
            out = []
            for sent in sentences(text, lang=lang):
                for word in sent:
                    out.append(word.phonemes)
            r[lang] = out
        except Exception as ex:
            r[lang] = f"ERR {type(ex).__name__}: {ex}"
    return r
run(gruut_test)

if __name__ == "__main__":
    out_path = BASE / "output" / "g2p_live_test_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(OUT, ensure_ascii=False, indent=1)
    out_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[saved] {out_path}", file=sys.stderr)
