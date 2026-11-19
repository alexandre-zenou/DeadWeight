"""R20 — endless_memory : une mémoire de conversation qui ne se vide jamais.

Cas réel qui a motivé la règle (#40) : un assistant n8n avec mémoire recolle tout l'historique dans un
seul message à chaque appel ; la clé de session est fixe, tous les utilisateurs partagent la même
conversation. L'entrée passe de 69 à 9 115 jetons en 40 appels, presque linéairement, sans jamais
retomber, et le contexte fait 75 % du coût. Ni context_reread ni raw_context ne le voient : les deux
regroupent les appels par trace, et ici il n'y en a pas (passerelle : trace nulle ; import n8n : une
exécution = une trace d'un seul appel, l'historique vit dans la mémoire, pas dans la trace).

Niveau 1 STRICT : jetons (entrée, cache, sortie), modèle, application et ordre dans le temps. Aucun
message n'est lu. Le schéma d'événement n'a pas de gabarit de requête : le regroupement se fait par
(application, modèle) seulement.

Partage avec context_reread : un appel dont la trace regroupe au moins deux appels appartient à une
session explicite, c'est le terrain de context_reread (et de raw_context) ; il est écarté ici. Restent
les appels sans trace et ceux dont la trace ne contient qu'eux (une exécution n8n).

Série : par (application, modèle), les appels rangés par heure ; contexte d'un appel = jetons d'entrée
réellement transmis (même calcul que context_reread). La série est coupée à chaque retombée : un appel
dont le contexte tombe sous (1 - DROP_TOLERANCE) fois celui de l'appel précédent (nouvelle session,
compaction, résumé). La dernière portion, celle qui court encore à la fin de l'observation, est la
mémoire telle qu'elle est aujourd'hui.

Seuils, avec le raisonnement :

- DROP_TOLERANCE = 0.1 : une mémoire qu'on remplit ne rapetisse pas ; un léger recul (une question plus
  courte que la précédente quand la mémoire est déjà bornée) n'est pas une remise à zéro.
- MIN_GROWING_CALLS = 15 : une conversation de dix échanges est un usage normal de chat ; il faut une
  croissance qui dure au-delà avant de parler d'une mémoire jamais vidée. Le cas réel en compte 40.
- LONGER_THAN_PREVIOUS = 2 : la dernière portion doit être au moins deux fois plus longue que la plus
  longue des portions précédentes. Des sessions qui redémarrent régulièrement ou une compaction
  périodique coupent la série en morceaux de longueur voisine : c'est une mémoire bornée, pas le
  problème visé (le jeu v1 en contient un : deux boucles d'agent de 25 appels, sans trace). Un
  redémarrage isolé (un déploiement) suivi d'une croissance bien plus longue reste signalé.
- MIN_RISING_STEP_SHARE = 0.8 : au moins quatre pas sur cinq doivent faire grossir le contexte. Une
  fenêtre glissante oscille autour d'un plateau (un pas sur deux monte) et un contexte stable ne monte
  jamais.
- MIN_GROWTH_FACTOR = 2 et MIN_ADDED_TOKENS = 2048 : le dernier appel doit envoyer au moins deux fois
  le contexte du premier, et au moins 2 048 jetons de plus. Sous ces planchers, la croissance existe
  mais ne pèse rien (gros prompt système fixe, quelques phrases ajoutées). Le cas réel est à ×130 et
  +9 000 jetons : les deux seuils sont des planchers bas, pas calés sur lui.
- MIN_CONTEXT_COST_SHARE = celui de context_reread (50 %) : le contexte doit faire la majorité du coût,
  mesuré par report.cost.chiffrer (sorties mises à zéro). Prix inconnu : la règle se tait.

Économie : estimation, jamais une garantie, sans rejeu. Si la mémoire était bornée aux WINDOW_CALLS
derniers échanges, le contexte de chaque appel ne dépasserait pas celui atteint au WINDOW_CALLS-ième
appel de la portion. La part du contexte au-dessus de ce plafond, appliquée au coût du contexte, est
l'économie estimée. Elle ne dit pas si la réponse reste aussi bonne avec moins d'historique.

Angles morts : plusieurs conversations qui avancent en même temps dans la même application (une
mémoire par utilisateur, jamais vidée non plus) s'entremêlent dans le temps et font une série en dents
de scie : la règle ne les voit pas sans identifiant de session ; un historique qui grossit par paliers
irréguliers peut passer sous MIN_RISING_STEP_SHARE.

Prévision de plantage (#45), dans evidence.forecast : à ce rythme, quand la conversation dépassera-t-elle
la fenêtre de contexte du modèle (l'assistant cessera alors de répondre, pour tous si la clé de session est
fixe) ? Une prévision, jamais une mesure, et jamais additionnée à un gain.

- Fenêtre : fixtures/capabilities.json (OpenRouter, python -m catalog.capabilities), la route de l'éditeur
  quand elle existe (celle que le client appelle en direct), sinon le modèle. Nom cherché comme les prix
  (report.cost.lookup). Modèle absent : pas de prévision, raison notée.
- Limite : la fenêtre moins la plus longue réponse observée de la portion (la réponse compte dans la
  fenêtre) : prudent.
- Pente : moindres carrés du contexte sur le rang d'appel, sur la portion qui monte ; point de départ :
  le dernier contexte observé. Appel où ça casse : le premier dont le contexte dépasserait la limite,
  compté depuis le début de la portion (la conversation telle qu'elle court).
- IMMINENT_SHARE = 0.9 : dernier contexte à 90 % de la limite ou plus, la prévision est dite imminente.
- Appels déjà refusés pour contexte trop long (erreur dont le type ou le message le dit, même application
  et même modèle) : dit tel quel, c'est un fait, pas une prévision.
"""
import hashlib
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache

from rules.context_reread import MIN_CONTEXT_COST_SHARE, _context_cost_share, _context_tokens

DROP_TOLERANCE = 0.1
MIN_GROWING_CALLS = 15
LONGER_THAN_PREVIOUS = 2
MIN_RISING_STEP_SHARE = 0.8
MIN_GROWTH_FACTOR = 2
MIN_ADDED_TOKENS = 2048
WINDOW_CALLS = 10
IMMINENT_SHARE = 0.9
_OVERFLOW = re.compile(r"context_length_exceeded|maximum context length|context window|context length|"
                       r"prompt is too long|input is too long", re.I)
# lu par tests/test_finding_schema.py : aucun scénario du jeu v1 n'a de mémoire jamais vidée (le seul
# candidat, sales-agent, redémarre ses sessions) ; la règle y vérifie l'absence de faux positif et se
# teste sur des séries fabriquées (tests/test_endless_memory.py).
SILENT_ON_DATASET = "aucune mémoire jamais vidée dans le jeu v1 ; testée sur séries fabriquées"


def _series(events):
    """(app, modèle) -> [(événement, contexte)] rangés par heure, hors sessions explicites."""
    per_trace = Counter(e['trace']['id'] for e in events if e['trace']['id'] is not None)
    groups = defaultdict(list)
    for e in events:
        if e.get('error') is not None or per_trace.get(e['trace']['id'], 0) >= 2:
            continue
        ctx = _context_tokens(e)
        if ctx is None:
            continue
        groups[(e['app_id'], e['model'])].append((e, ctx))
    for pairs in groups.values():
        pairs.sort(key=lambda pair: (pair[0]['ts_start'], pair[0]['event_id']))
    return groups


def _runs(pairs):
    """Portions de la série coupées à chaque retombée du contexte."""
    runs = [[pairs[0]]]
    for pair in pairs[1:]:
        if pair[1] < (1 - DROP_TOLERANCE) * runs[-1][-1][1]:
            runs.append([])
        runs[-1].append(pair)
    return runs


@lru_cache(maxsize=1)
def _windows():
    """Nom complet et nom court (sans préfixe fournisseur) -> fenêtre ; un nom court ambigu est écarté."""
    from catalog.capabilities import load
    table, short = {}, defaultdict(set)
    for name, caps in load().items():
        window = (caps.get('route_editeur') or {}).get('contexte') or caps.get('contexte')
        table[name] = window
        short[name.split('/', 1)[-1]].add(window)
    table.update({k: next(iter(v)) for k, v in short.items() if len(v) == 1 and k not in table})
    return table


def context_window(model):
    """Fenêtre de contexte du modèle en jetons, ou None si fixtures/capabilities.json ne la connaît pas."""
    from report.cost import lookup
    return lookup(_windows(), model)


def _overflow(e):
    err = e.get('error') or {}
    return bool(_OVERFLOW.search(f"{err.get('type') or ''} {err.get('message') or ''}"))


def forecast(model, ctx, outputs, refused):
    """Prévision de plantage d'une portion qui monte (voir la docstring du module)."""
    window = context_window(model)
    if refused:
        return dict(statut='depassee', appels_refuses=refused, fenetre_tokens=window)
    if not window:
        return dict(statut='inconnue', raison=f"fenêtre de contexte du modèle « {model} » inconnue "
                                              f"(absent de fixtures/capabilities.json)")
    n = len(ctx)
    mx, my = (n - 1) / 2, sum(ctx) / n
    slope = sum((i - mx) * (c - my) for i, c in enumerate(ctx)) / sum((i - mx) ** 2 for i in range(n))
    limit = window - max(outputs, default=0)
    remaining = max(0, int((limit - ctx[-1]) // slope))
    return dict(statut='imminente' if ctx[-1] >= IMMINENT_SHARE * limit else 'prevision',
                fenetre_tokens=window, limite_tokens=limit, pente_tokens_par_appel=slope,
                appels_observes=n, appels_restants=remaining, appel_limite=n + remaining + 1,
                methode="Prévision à ce rythme : pente (moindres carrés) de l'entrée sur la portion qui monte, "
                        "depuis le dernier contexte observé, jusqu'à la fenêtre du modèle moins la plus longue "
                        "réponse observée. Estimation, pas une mesure.")


def finding(app, model, ids, title, evidence):
    digest = hashlib.sha256(json.dumps(['endless_memory', app, model, sorted(ids)]).encode()).hexdigest()[:20]
    return dict(finding_id=f'f_{digest}_endless_memory', rule='endless_memory', app_id=app, model=model,
                template=None, severity='trim', title=title, proven=False, event_ids=sorted(ids), evidence=evidence)


def detect(events):
    """Un constat par (application, modèle) dont le contexte grossit sans jamais se vider."""
    found = []
    refused = Counter((e['app_id'], e['model']) for e in events if e.get('error') and _overflow(e))
    for (app, model), pairs in sorted(_series(events).items()):
        runs = _runs(pairs)
        last = runs[-1]
        previous = max((len(r) for r in runs[:-1]), default=0)
        if len(last) < MIN_GROWING_CALLS or len(last) < LONGER_THAN_PREVIOUS * previous:
            continue
        ctx = [c for _, c in last]
        rising = sum(b > a for a, b in zip(ctx, ctx[1:])) / (len(ctx) - 1)
        if rising < MIN_RISING_STEP_SHARE:
            continue
        if ctx[-1] < MIN_GROWTH_FACTOR * ctx[0] or ctx[-1] - ctx[0] < MIN_ADDED_TOKENS:
            continue
        run_events = [e for e, _ in last]
        share, context_cost = _context_cost_share(run_events)
        if share is None or share < MIN_CONTEXT_COST_SHARE:
            continue

        cap = ctx[min(WINDOW_CALLS, len(ctx)) - 1]
        excess = sum(max(0, c - cap) for c in ctx) / sum(ctx)
        n = lambda v: f"{v:,}".replace(',', ' ')  # noqa: E731
        titre = (f"La mémoire de conversation ne se vide jamais : l'entrée passe de {n(ctx[0])} à {n(ctx[-1])} "
                 f"jetons en {len(ctx)} appels, {share * 100:.0f} % du coût.")
        found.append(finding(app, model, [e['event_id'] for e in run_events], titre,
            dict(calls=len(pairs), growing_calls=len(ctx), resets=len(runs) - 1,
                 first_context_tokens=ctx[0], last_context_tokens=ctx[-1],
                 rising_step_share=rising, context_cost_share=share, context_cost_month_usd=context_cost,
                 window_calls=WINDOW_CALLS, window_cap_tokens=cap,
                 est_saving_month_usd=context_cost * excess,
                 estimate_method=f"Coût du contexte (entrée + cache, sortie mise à zéro) multiplié par la part "
                                 f"du contexte au-dessus de celui du {WINDOW_CALLS}e appel : estimation d'une "
                                 f"mémoire bornée aux {WINDOW_CALLS} derniers échanges, sans rejeu, pas une "
                                 f"garantie.",
                 forecast=forecast(model, ctx, [e['usage'].get('output_tokens') or 0 for e in run_events],
                                   refused[(app, model)]))))
    return found
