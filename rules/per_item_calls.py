"""R11 — traitement unitaire répétitif, regroupement à essayer.

Même application/modèle/instructions exactes, >= 8 appels : écarter une poignée
normale d'interactions. Une trace explicite ou une rafale (écart <= 10 s entre
fins/débuts) suffit. Un seul message utilisateur, sans outils/images/historique,
<= 512 caractères, sortie <= 64 jetons, >= 80 % d'entrées distinctes.
Instructions >= 64 jetons estimés : gain de répétition suffisamment substantiel.
Estimation hypothétique : ceil(caractères système / 4), répétés N-1 fois.
Coût via chiffrer avant/après, mêmes dates, sorties inchangées, entrée plafonnée.
Cache positif/inconnu : attribution impossible, gain financier inconnu.
Latence : somme des durées - maximum uniquement en série ; hypothèse de lot
parallèle, pas prédiction de la durée d'un unique appel groupé.
Angles morts : contraintes de confidentialité, délai, limite de contexte et
qualité d'un lot inconnus. Similarité du système ne prouve pas un même métier.

Second motif (#34), « une fois par élément dans une même exécution » : une trace
explicite (en-tête client, ou identifiant d'exécution n8n) où la même consigne
est appelée >= 3 fois sur des entrées distinctes (ex. 4 relectures, une par
langue). La sortie peut être structurée (JSON, appel d'outil de mise en forme,
ou fin « tool_calls » dont l'import a perdu le contenu) jusqu'à 256 jetons.
Garde-fous contre les faux positifs :
- trace explicite seulement : une trace devinée (heuristique) est une
  conversation ou une boucle d'agent par construction ;
- chaque appel de la consigne dans la trace est un seul message utilisateur ;
  si un seul porte un historique (tour assistant, résultat d'outil), la
  consigne sert une boucle d'agent ou une conversation : toute la consigne de
  cette trace est écartée ;
- appels serrés (écart <= 10 s) : une « trace » qui serait une session
  d'utilisateur étalée dans le temps n'est pas une boucle sur des éléments ;
- >= 3 exécutions montrent le motif : un motif récurrent du workflow ;
- consigne >= 64 jetons estimés, pas d'erreur ni d'image.
Un constat par (application, modèle, consigne), qui additionne les exécutions.
Une trace déjà couverte par le premier motif (>= 8 éléments courts) le reste.
"""
import math
import statistics
from collections import defaultdict

from gateway.traces import assign_traces
from report.cost import chiffrer
from rules.low_entropy import output_kind
from rules.parallelizable_steps import finding, plain, serial_gain, text, time

MIN_CALLS = 8  # Assez de répétitions pour amortir un regroupement.
MAX_GAP_SECONDS = 10  # Rafale serrée, pas des utilisateurs séparés dans la journée.
MAX_INPUT_CHARS = 512  # Un élément court peut raisonnablement rejoindre un lot.
MAX_OUTPUT_TOKENS = 64  # Éviter les générations longues difficiles à regrouper.
MIN_DISTINCT_SHARE = .8  # Les doublons exacts relèvent plutôt du cache de réponse.
MIN_SYSTEM_TOKENS = 64  # La répétition doit représenter un volume utile à retirer.

# Second motif : même consigne, plusieurs appels dans une même exécution.
MIN_TRACE_CALLS = 3  # Deux appels peuvent être deux étapes ; trois de même consigne, une boucle.
MIN_TRACES = 3  # Le motif revient d'une exécution à l'autre, pas un accident isolé.
MAX_TRACE_INPUT_CHARS = 4000  # Quelques éléments de cette taille tiennent dans un seul appel.
MAX_STRUCTURED_OUTPUT_TOKENS = 256  # Une note et un commentaire, pas une rédaction longue.


def _system_tokens(e):
    return math.ceil(len(e['request']['system'] or '') / 4)


def _saving(es, firsts, fixed):
    """Coût mensuel avant/après retrait des instructions répétées (hors premier appel de chaque lot)."""
    before = chiffrer(es)
    missing = list(before['manquants'])
    if any(e['usage'].get('cached_input_tokens') != 0 for e in es):
        missing.append('Attribution du cache aux instructions inconnue.')
    if missing:
        return None, missing
    reduced = [e if e['event_id'] in firsts else
               {**e, 'usage': {**e['usage'], 'input_tokens': max(0, e['usage']['input_tokens'] - fixed)}}
               for e in es]
    after = chiffrer(reduced)
    missing.extend(after['manquants'])
    if after['cout_mensuel_usd'] is None:
        return None, missing
    return before['cout_mensuel_usd'] - after['cout_mensuel_usd'], missing


def _distinct_share(es):
    return len({text(e['request']['messages'][0]['content']) for e in es}) / len(es)


def _per_item_bursts(ordered):
    groups = defaultdict(list)
    for e in ordered:
        ms = e['request']['messages']
        out = e['usage']['output_tokens']
        if (not plain(e) or len(ms) != 1 or ms[0]['role'] != 'user'
                or not text(ms[0].get('content')) or len(ms[0]['content']) > MAX_INPUT_CHARS
                or out is None or out > MAX_OUTPUT_TOKENS):
            continue
        if _system_tokens(e) < MIN_SYSTEM_TOKENS:
            continue
        groups[(e['app_id'], e['model'], e['provider'], e['request']['system'], e['trace']['id'])].append(e)
    batches = []
    for key, es in sorted(groups.items(), key=lambda pair: str(pair[0])):
        if key[-1] is not None:
            batches.append(es)
            continue
        current = []
        for e in es:
            if current and (time(e['ts_start']) - time(current[-1]['ts_end'])).total_seconds() > MAX_GAP_SECONDS:
                batches.append(current)
                current = []
            current.append(e)
        batches.append(current)
    found = []
    for es in batches:
        if len(es) < MIN_CALLS:
            continue
        share = _distinct_share(es)
        if share < MIN_DISTINCT_SHARE:
            continue
        fixed = _system_tokens(es[0])
        saving, missing = _saving(es, {es[0]['event_id']}, fixed)
        found.append(finding('per_item_calls', es,
                             f'{len(es)} éléments courts sont traités séparément avec les mêmes instructions.',
                             dict(calls=len(es), distinct_input_share=share,
                                  estimated_repeated_system_tokens=fixed * (len(es) - 1),
                                  estimate_method='Caractères système / 4 arrondis au supérieur, multipliés par N−1 ; hypothèse de lot.',
                                  estimated_latency_saving_seconds=serial_gain(es),
                                  est_saving_month_usd=saving, saving_missing=missing)))
    return found


def _structured(e):
    r = e['response']
    return bool(r['tool_calls']) or r.get('finish_reason') == 'tool_calls' or output_kind(e) == 'json'


def _item_call(e):
    """Un élément traité seul : un message utilisateur, sortie courte, structurée ou non."""
    ms = e['request']['messages']
    out = e['usage']['output_tokens']
    if (e.get('error') is not None or len(ms) != 1 or ms[0]['role'] != 'user'
            or not text(ms[0].get('content')) or len(ms[0]['content']) > MAX_TRACE_INPUT_CHARS
            or ms[0].get('n_images') or out is None):
        return False
    if _structured(e):
        return out <= MAX_STRUCTURED_OUTPUT_TOKENS
    return bool(text(e['response']['content'])) and out <= MAX_OUTPUT_TOKENS


def _tight(es):
    return all((time(b['ts_start']) - time(a['ts_end'])).total_seconds() <= MAX_GAP_SECONDS
               for a, b in zip(es, es[1:]))


def _per_item_in_traces(ordered, covered):
    groups = defaultdict(list)
    for e in ordered:
        if e['trace']['id'] is not None and e['trace']['source'] == 'header':
            groups[(e['app_id'], e['model'], e['provider'], e['request']['system'] or '', e['trace']['id'])].append(e)
    families = defaultdict(list)
    for key, es in groups.items():
        if (len(es) < MIN_TRACE_CALLS or _system_tokens(es[0]) < MIN_SYSTEM_TOKENS
                or any(e['event_id'] in covered for e in es) or not all(_item_call(e) for e in es)
                or _distinct_share(es) < MIN_DISTINCT_SHARE or not _tight(es)):
            continue
        families[key[:-1]].append(es)
    found = []
    for key, runs in sorted(families.items(), key=lambda pair: str(pair[0])):
        if len(runs) < MIN_TRACES:
            continue
        runs = sorted(runs, key=lambda es: (es[0]['ts_start'], es[0]['event_id']))
        es = [e for run in runs for e in run]
        fixed = _system_tokens(es[0])
        saving, missing = _saving(es, {run[0]['event_id'] for run in runs}, fixed)
        gains = [serial_gain(run) for run in runs]
        sizes = [len(run) for run in runs]
        per_trace = statistics.median_low(sizes)
        found.append(finding('per_item_calls', es,
                             f'Dans {len(runs)} exécutions, la même consigne est appelée {per_trace} fois '
                             f'(une fois par élément) au lieu d\'un appel groupé.',
                             dict(calls=len(es), traces=len(runs), calls_per_trace=per_trace,
                                  distinct_input_share=min(_distinct_share(run) for run in runs),
                                  structured_output_share=sum(map(_structured, es)) / len(es),
                                  estimated_repeated_system_tokens=fixed * sum(n - 1 for n in sizes),
                                  estimate_method='Caractères système / 4 arrondis au supérieur, multipliés par '
                                                  '(appels − 1) dans chaque exécution ; hypothèse d\'un appel '
                                                  'groupé par exécution, sortie et outils inchangés.',
                                  estimated_latency_saving_seconds=None if None in gains else sum(gains),
                                  est_saving_month_usd=saving, saving_missing=missing)))
    return found


def detect(events):
    ordered = assign_traces(sorted(events, key=lambda e: (e['ts_start'], e['event_id'])))
    found = _per_item_bursts(ordered)
    covered = {i for f in found for i in f['event_ids']}
    return found + _per_item_in_traces(ordered, covered)
