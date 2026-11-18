"""#43 — banc de la mémoire bornée : les appels d'un constat endless_memory rejoués sur le même modèle
en ne gardant que les ``window`` derniers échanges de l'historique, comparés aux réponses d'origine.

Deux formes d'historique sont lues, rien d'autre :
- « tours » : des messages user/assistant successifs ; un échange commence à chaque message user ;
- « aplati » : tout l'historique recollé dans un seul message (cas n8n : « Human: … / AI Assistant: … »).
Un historique dans une autre forme n'est pas deviné : le constat reste « non testé », avec la raison.

Les appels dont l'historique tient déjà dans la fenêtre envoient exactement la même requête : ils ne sont
pas rejoués et comptent comme d'accord. Les autres sont rejoués deux fois, à la même température (0) :
avec la mémoire bornée, et avec la mémoire complète (rejeu témoin). Les deux sont notés contre la réponse
d'origine par bench.scoring.score_case. Le témoin mesure ce que le modèle redonne de lui-même avec tout
l'historique : en texte libre, il ne répète jamais mot pour mot sa réponse d'origine (F1 bien sous 1), et
ce bruit n'est pas un effet de la mémoire bornée. L'accord rapporte donc la fidélité de la mémoire bornée
à celle du témoin, sur les mêmes appels :

    accord = (identiques + rejoués × min(1, Σ score borné / Σ score témoin)) / (identiques + rejoués)

Même seuil que tout le projet (proof.replay.THRESHOLD, 95 %), mêmes verdicts : « pass », « reject »,
« inconclusive » sous proof.replay.MIN_REPLAY appels mesurés (ADR 0002), « not_tested » quand rien n'a pu
être mesuré (clé absente, historique illisible, tous les appels en échec). Une question qui fait appel à un
échange sorti de la fenêtre (« rappelle-moi le début ») fait baisser l'accord : elle est listée dans
``gaps`` (appels où la mémoire bornée s'écarte le plus du témoin), jamais masquée.

Gain mesuré : jetons d'entrée et coût réellement facturés par l'API sur les rejeux bornés (sortie
comprise), contre ceux d'origine des mêmes appels ; les appels identiques gardent leur coût d'origine des
deux côtés. Rien n'est extrapolé aux appels non rejoués (plafond ``max_cases``).

Seul OpenAI est câblé (OPENAI_API_KEY, OPENAI_BASE_URL), comme bench.reasoning ; sans clé, aucun appel.
"""
import hashlib
import os
import re
from collections import Counter

from bench.client import CandidateLLM
from bench.models import BenchCase
from bench.pricing import load_prices
from bench.runner import Throttle, ask
from bench.scoring import answer_of, detect_task_type, score_case
from bench.testset import _reference, _usable_messages
from proof.replay import MIN_REPLAY, THRESHOLD
from report.cost import lookup
from rules.endless_memory import WINDOW_CALLS

DEFAULT_WINDOW = WINDOW_CALLS  # la fenêtre de l'estimation de endless_memory : on prouve ce qu'on a estimé
DEFAULT_MAX_CASES = 50         # appels rejoués au plus (deux requêtes chacun, sous bench.runner.HARD_MAX_CALLS)
DEFAULT_BASE_URL = "https://api.openai.com/v1"
MAX_GAPS = 10
TOURS, APLATI = "tours", "aplati"
# début d'un échange dans un historique aplati : préfixes de LangChain / n8n (« Human: », « User: »)
_EXCHANGE = re.compile(r"(?m)^(?:Human|User|Utilisateur)\s*:")


def _bound_flat(messages, window):
    """Historique aplati : le premier message (hors question finale) qui contient des échanges."""
    for i, m in enumerate(messages[:-1]):
        text = m.get("content") or ""
        starts = [x.start() for x in _EXCHANGE.finditer(text)]
        if not starts:
            continue
        # le saut de ligne qui précède un échange lui appartient : le préfixe garde sa forme exacte
        cuts = [s - 1 if s and text[s - 1] == "\n" else s for s in starts]
        keep = cuts[max(0, len(cuts) - window)]
        bounded = list(messages)
        bounded[i] = {**m, "content": text[:cuts[0]] + text[keep:]}
        return (bounded if len(cuts) > window else list(messages)), len(cuts), APLATI
    return None


def _bound_turns(messages, window):
    """Tours de parole : messages système en tête, puis un échange par message user, puis la question."""
    head = 0
    while head < len(messages) and messages[head]["role"] == "system":
        head += 1
    users = [i for i in range(head, len(messages)) if messages[i]["role"] == "user"]
    if len(users) < 2:
        return None
    current = users[-1]
    # message(s) assistant avant le premier user (un accueil) : rattachés au premier échange
    starts = [head] + users[1:-1] if users[0] > head else users[:-1]
    n = len(starts)
    if n <= window:
        return list(messages), n, TOURS
    return list(messages[:head]) + list(messages[starts[n - window]:current]) + list(messages[current:]), n, TOURS


def bound(messages, window):
    """(messages bornés aux ``window`` derniers échanges, nombre d'échanges, forme) ; forme None si aucun
    historique n'est reconnu (premier appel d'une conversation, ou forme inconnue : à l'appelant de trancher).
    La liste d'origine n'est jamais modifiée."""
    messages = list(messages)
    found = _bound_turns(messages, window) or _bound_flat(messages, window)
    return found if found else (messages, 0, None)


def _not_tested(window, reason, **extra):
    return {"window": window, "format": None, "task_type": None, "n_identical": 0, "n_replayed": 0,
            "n_errors": 0, "n_unreadable": 0, "agreement": None, "score_bounded": None, "score_full": None,
            "tokens_before": None, "tokens_after": None, "cost_before_usd": None, "cost_after_usd": None,
            "gaps": [], "verdict": "not_tested", "reasons": [reason], **extra}


def _cost(price, tin, tout):
    return None if price is None or tin is None or tout is None else (tin * price["in"] + tout * price["out"]) / 1e6


def _sample_key(event_id):
    return hashlib.sha1(event_id.encode("utf-8")).hexdigest()


def prove(events, finding, window=DEFAULT_WINDOW, max_cases=DEFAULT_MAX_CASES, min_interval=0.0, prices=None,
          client_cls=CandidateLLM):
    """N'échoue jamais par exception : une panne d'appel compte 0 sur son cas, un historique illisible
    rend « not_tested »."""
    ids = set(finding["event_ids"])
    group = [e for e in events if e["event_id"] in ids and e.get("error") is None and _reference(e) is not None]
    parsed = [(e, bound(_usable_messages(e), window)) for e in group]
    formats = Counter(fmt for _, (_, _, fmt) in parsed if fmt)
    if not formats:
        return _not_tested(window, "historique illisible : ni tours de conversation (user/assistant), ni "
                                   "historique aplati (« Human: … ») dans les requêtes ; rien n'est deviné")
    fmt = formats.most_common(1)[0][0]
    # sans historique reconnu : un début de conversation (0 échange) seulement s'il est plus court que tous
    # les appels lisibles ; sinon l'historique est là, sous une forme inconnue : appel exclu, jamais « identique »
    floor = min(e["usage"].get("input_tokens") or 0 for e, (_, _, f) in parsed if f == fmt)
    identical, replay, unreadable = [], [], 0
    for e, (msgs, n, f) in parsed:
        if f is None and (e["usage"].get("input_tokens") or 0) > floor:
            unreadable += 1
        elif f not in (None, fmt):
            unreadable += 1
        elif n <= window:
            identical.append(e)
        else:
            replay.append((e, msgs))
    if not replay:
        return _not_tested(window, f"aucun appel n'a plus de {window} échanges : borner la mémoire ne change "
                                   "aucune requête", format=fmt, n_identical=len(identical), n_unreadable=unreadable)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _not_tested(window, "clé OPENAI_API_KEY absente : rien de mesuré", format=fmt,
                           n_identical=len(identical), n_unreadable=unreadable)

    replay = sorted(sorted(replay, key=lambda pair: _sample_key(pair[0]["event_id"]))[:max_cases],
                    key=lambda pair: (pair[0]["ts_start"], pair[0]["event_id"]))
    cases = []
    for e, msgs in replay:
        usage = e.get("usage") or {}
        common = dict(event_id=e["event_id"], reference=_reference(e),
                      origin_input_tokens=usage.get("input_tokens"), origin_output_tokens=usage.get("output_tokens"))
        cases.append((BenchCase(messages=tuple(msgs), **common),
                      BenchCase(messages=tuple(_usable_messages(e)), **common), e))
    task_type = detect_task_type([full for _, full, _ in cases])
    client = client_cls(os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL, api_key, finding["model"])
    throttle = Throttle(2 * len(cases), min_interval)

    prices = prices if prices is not None else load_prices()
    price = lookup(prices, finding["model"])
    origin = lambda e: (e["usage"].get("input_tokens") or 0, e["usage"].get("output_tokens") or 0)  # noqa: E731
    tokens_before = tokens_after = sum(origin(e)[0] for e in identical)
    cost_before = cost_after = sum(_cost(price, *origin(e)) or 0 for e in identical) if price else None
    sum_b = sum_f = 0.0
    measured, errors, gaps, usage_missing = 0, 0, [], False
    for short, full, e in cases:
        if not throttle.acquire():
            break
        rb = ask(client, short)
        rf = ask(client, full) if throttle.acquire() else None
        if rb.error is not None or rf is None or rf.error is not None:
            errors += 1
            continue
        measured += 1
        sb = score_case(task_type, answer_of(short, rb), short.reference)
        sf = score_case(task_type, answer_of(full, rf), full.reference)
        sum_b, sum_f = sum_b + sb, sum_f + sf
        if sb < THRESHOLD * sf:
            gaps.append({"event_id": e["event_id"], "question": full.messages[-1]["content"][:200],
                         "exchanges": None, "score_bounded": round(sb, 4), "score_full": round(sf, 4)})
        tin, tout = origin(e)
        tokens_before += tin
        if rb.input_tokens is None or rb.output_tokens is None:
            usage_missing = True
            continue
        tokens_after += rb.input_tokens
        if price:
            cost_before += _cost(price, tin, tout)
            cost_after += _cost(price, rb.input_tokens, rb.output_tokens)

    base = {"format": fmt, "task_type": task_type, "n_identical": len(identical),
            "n_unreadable": unreadable, "n_errors": errors}
    if not measured:
        return _not_tested(window, f"les {errors} rejeux ont échoué : rien de mesuré" if errors
                           else "plafond d'appels atteint avant le premier rejeu", **base)
    if sum_f == 0:
        return {**_not_tested(window, "le rejeu témoin (mémoire complète) ne retrouve aucune réponse d'origine : "
                                      "rien à comparer", **base), "n_replayed": measured}
    ratio = min(1.0, sum_b / sum_f)
    total = len(identical) + measured
    agreement = round((len(identical) + ratio * measured) / total, 4)
    for g in gaps:
        g["exchanges"] = next(n for e, (_, n, _) in parsed if e["event_id"] == g["event_id"])
    gaps.sort(key=lambda g: g["score_bounded"] - g["score_full"])

    reasons = []
    if agreement < THRESHOLD:
        reasons.append(f"accord {agreement:.0%} sous le seuil {THRESHOLD:.0%}")
        if gaps:
            reasons.append(f"{len(gaps)} réponse(s) s'écartent quand la mémoire est bornée (rappel d'un échange "
                           f"ancien ?) : essayer une fenêtre plus grande que {window} échanges")
    if errors:
        reasons.append(f"{errors}/{errors + measured} rejeu(x) en erreur")
    if unreadable:
        reasons.append(f"{unreadable} appel(s) à l'historique illisible, exclus de la mesure")
    if total < MIN_REPLAY:
        verdict = "inconclusive"
        reasons.append(f"{total} appels mesurés, il en faut au moins {MIN_REPLAY} pour conclure")
    else:
        verdict = "pass" if agreement >= THRESHOLD and not errors else "reject"
    gain_ok = not usage_missing
    return {**base, "window": window, "n_replayed": measured, "agreement": agreement,
            "score_bounded": round(sum_b / measured, 4), "score_full": round(sum_f / measured, 4),
            "tokens_before": tokens_before if gain_ok else None, "tokens_after": tokens_after if gain_ok else None,
            "cost_before_usd": cost_before if gain_ok else None, "cost_after_usd": cost_after if gain_ok else None,
            "gaps": gaps[:MAX_GAPS], "verdict": verdict, "reasons": reasons}
