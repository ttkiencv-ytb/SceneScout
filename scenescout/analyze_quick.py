"""Offline keyword extraction (no AI). Fast, free, decent for named subjects.

Improvements over v1: carries the last named person forward to resolve pronouns,
keeps place names, and builds a broader fallback keyword from the whole script.
"""
import re
from collections import Counter

_STOP = set("""
A An And As At But By For From He Her Hers Him His How I If In Into It Its Of On Or She So That The Their Them
Then There These They This Those To Was We Were What When Where Which While Who Why With Yet You Your Our Not No
Nor Now One Two Three Four Five Six Seven Eight Nine Ten Some Many Most Much More Every Each All Both Before After
Even Still Only Just Also Here Today Tonight Later Soon Once During Within Without Over Under Because Although Though
Since Until Unless Instead Meanwhile However Yes Mr Mrs Sir Do Did Does Had Has Have Is Are Be Been Being Can Could
Would Should Will May Might Must Let Look Listen Notice Think Remember Consider Start Read Take Go Stop Come Get Keep
Tell Hold Picture Imagine Now Another Other Same First Last Next Few
""".split())
_WEAK = set("""German Germans American Americans British Soviet Soviets Russian Russians Japanese Italian French Allied Allies
Army Navy Nazi Nazis January February March April May June July August September October November December
Monday Tuesday Wednesday Thursday Friday Saturday Sunday""".split())
_MONTHS = set("January February March April May June July August September October November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split())
_JOIN = {"of", "de", "von", "van", "der", "du", "la", "le", "al"}
# Nouns that usually make a findable picture. Kept short on purpose; extend as needed.
_VISUAL = set("""tank tanks truck trucks jeep jeeps convoy convoys gasoline fuel can cans jerrycan jerrycans ship ships
destroyer destroyers cruiser battleship carrier submarine u-boat bomber bombers fighter fighters plane planes aircraft
airfield runway glider gliders parachute paratroopers soldier soldiers troops infantry marines sailors pilots prisoners
prisoner camp camps barracks fence wire beach beaches bridge bridges river cliff hill ridge bunker bunkers pillbox
trench trenches artillery gun guns howitzer rifle rifles mortar mortars machine-gun ammunition shells map maps letter
letters telegram document documents newspaper radio train trains railway station factory factories city cities town
village ruins church cathedral harbor port headquarters general generals admiral officers medal flag ration rations
food bread mess kitchen hospital nurse doctor wounded graves cemetery coupon coupons money dollars gold mine""".split())
_POSSESSIVE = re.compile(r"\b([A-Z][\w\-]+(?:\s[A-Z][\w\-]+)*)['’]s\s+([a-z][a-z\-]+)")
_YEAR = re.compile(r"\b(18\d\d|19\d\d|20[0-2]\d)\b")
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*")
_PRONOUN = re.compile(r"\b(he|she|him|his|her)\b", re.I)


def proper_phrases(text, common=frozenset()):
    """Runs of capitalised words. A capitalised word whose lowercase form also appears
    in the script (e.g. 'Outside' at a sentence start) is treated as an ordinary word."""
    phrases, cur = [], []
    for tok in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*|\S", text):
        if not tok[0].isalpha():  # punctuation or digits end a name ("August 1944. Patton" is two phrases)
            while cur and cur[-1].lower() in _JOIN:
                cur.pop()
            if cur:
                phrases.append(" ".join(cur))
            cur = []
            continue
        clean = re.sub(r"['’]s$", "", tok.strip("'’-"))
        if "'" in clean or "’" in clean:
            clean = ""
        if clean[:1].isupper() and clean not in _STOP and len(clean) > 1 and clean.lower() not in common:
            cur.append(clean)
        elif cur and clean.lower() in _JOIN:
            cur.append(clean)
        else:
            while cur and cur[-1].lower() in _JOIN:
                cur.pop()
            if cur:
                phrases.append(" ".join(cur))
            cur = []
    while cur and cur[-1].lower() in _JOIN:
        cur.pop()
    if cur:
        phrases.append(" ".join(cur))
    return phrases


def analyze(rows, title=""):
    full = " ".join(r["text"] for r in rows) + " " + title
    common = frozenset(w for w in re.findall(r"\b[a-z][a-z'’\-]+\b", full))
    counts = Counter(p for p in proper_phrases(full, common) if p not in _WEAK)
    top = [n for n, _ in counts.most_common(4)]
    years = Counter(_YEAR.findall(full))
    top_year = years.most_common(1)[0][0] if years else ""
    people = [n for n in top if len(n.split()) <= 3]
    last_person = people[0] if people else ""
    for r in rows:
        names, weak = [], []
        for p in proper_phrases(r["text"], common):
            bucket = weak if p in _WEAK else names
            if p not in bucket:
                bucket.append(p)
        if names:
            last_person = names[0]
        elif _PRONOUN.search(r["text"]) and last_person:
            names = [last_person]
        yrs = _YEAR.findall(r["text"])
        year = yrs[0] if yrs else top_year
        # "Patton's tanks" -> subject phrase "Patton tanks": the thing the picture should show
        subject = ""
        m = _POSSESSIVE.search(r["text"])
        if m and m.group(2) in _VISUAL:
            subject = f"{m.group(1)} {m.group(2)}"
        nouns = []
        for w in re.findall(r"[a-z][a-z\-]+", r["text"]):
            if w in _VISUAL and w not in nouns and (not subject or w not in subject):
                nouns.append(w)
        if subject:
            core = [subject] + [n for n in names[1:2] if n not in subject]
        else:
            core = names[:2] or top[:1]
        parts = core + nouns[:2 if subject else 2] + ([year] if year else [])
        if not subject and not names and not nouns:
            parts = [w for w in weak[:1] if w not in _MONTHS] + parts
        kw = " ".join(parts)
        r["keyword"] = kw.strip() or "World War II"
        # fallback: the most frequent script-wide subject not already in this row's keyword (often a place)
        other = next((t for t in top if t not in kw), top[0] if top else "")
        r["keyword_phu"] = " ".join(([other] if other else []) + ([top_year] if top_year else [])).strip() or "World War II"
        r["mota"] = r.get("mota") or ""  # Quick mode cannot write a translated shot description
    return rows, {"characters": top, "year": top_year, "mode": "quick"}
