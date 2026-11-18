"""endless_memory : une mémoire de conversation qui ne se vide jamais, vue au seul usage (niveau 1)."""
import copy
import json
from pathlib import Path

import pytest

from rules.context_reread import detect as detect_context_reread
from rules.endless_memory import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])


def call(i, input_tokens, output_tokens=200, app='voice-bot', model='gpt-4o-mini', trace_id=None, minute=None):
    e = copy.deepcopy(BASE)
    m = i if minute is None else minute
    e.update(event_id=f'{app}-{i:03d}', app_id=app, model=model, provider='openai',
             ts_start=f'2026-11-18T{10 + m // 60:02d}:{m % 60:02d}:00Z',
             ts_end=f'2026-11-18T{10 + m // 60:02d}:{m % 60:02d}:02Z', latency_ms=2000, error=None)
    e['trace'] = dict(id=trace_id, source='header' if trace_id else None, step=None)
    e['request'].update(system=None, tools=[], messages=[dict(role='user', content=f'Question {i}'),
                                                          dict(role='assistant', content='historique')])
    e['response'].update(content=f'Réponse {i}', tool_calls=[])
    e['usage'].update(input_tokens=input_tokens, output_tokens=output_tokens, cached_input_tokens=0)
    return e


def growing(n=40, start=70, step=230, **kw):
    """Le cas du ticket : l'entrée monte de ~70 à ~9 000 jetons en 40 appels, sans jamais retomber."""
    return [call(i, start + step * i + (i * 37) % 50, **kw) for i in range(n)]


def test_positive_memory_never_emptied():
    events = growing()
    before = copy.deepcopy(events)
    [f] = detect(events)
    ev = f['evidence']
    assert f['rule'] == 'endless_memory' and f['app_id'] == 'voice-bot' and f['model'] == 'gpt-4o-mini'
    assert f['proven'] is False and f['severity'] == 'trim'
    assert ev['calls'] == 40 and ev['growing_calls'] == 40 and ev['resets'] == 0
    assert ev['first_context_tokens'] == 70 and ev['last_context_tokens'] > 9000
    assert ev['context_cost_share'] >= .5
    assert 0 < ev['est_saving_month_usd'] < ev['context_cost_month_usd']
    assert 'estimation' in ev['estimate_method']
    assert 'ne se vide jamais' in f['title'] and ' jetons en 40 appels, ' in f['title']
    assert len(f['event_ids']) == 40
    assert events == before
    assert detect(events[::-1]) == [f]


def test_singleton_traces_are_not_sessions():
    """Import n8n : une exécution = une trace d'un seul appel ; l'historique est dans la mémoire."""
    events = growing()
    for e in events:
        e['trace'] = dict(id=f'exec-{e["event_id"]}', source='n8n', step=0)
    assert len(detect(events)) == 1


def test_one_restart_then_endless_growth_still_flags():
    """Un seul redémarrage (déploiement) puis une croissance qui dure : la mémoire ne se vide toujours pas."""
    first = [call(i, 70 + 230 * i) for i in range(10)]
    then = [call(10 + i, 70 + 230 * i) for i in range(30)]
    [f] = detect(first + then)
    assert f['evidence']['resets'] == 1 and f['evidence']['growing_calls'] == 30


def test_apps_and_models_are_separated():
    a = growing()
    b = [call(i, 3000, app='other-bot', minute=i) for i in range(40)]
    assert [f['app_id'] for f in detect(a + b)] == ['voice-bot']


def restarting(every, total=60):
    return [call(i, 70 + 230 * (i % every)) for i in range(total)]


@pytest.mark.parametrize('case', ['stable', 'sessions_restart', 'equal_sessions', 'compaction', 'too_short', 'small_growth',
                                  'output_dominates', 'plateau_noise', 'unknown_price', 'errors'])
def test_negatives(case):
    if case == 'stable':
        events = [call(i, 5000) for i in range(40)]
    elif case == 'sessions_restart':  # sessions de 10 échanges qui redémarrent
        events = restarting(10)
    elif case == 'equal_sessions':  # deux sessions de 25 appels : la dernière ne domine pas
        events = restarting(25, total=50)
    elif case == 'compaction':  # la mémoire grossit puis est résumée tous les 20 appels
        events = [call(i, 600 + 400 * (i % 20)) for i in range(80)]
    elif case == 'too_short':
        events = growing(n=12)
    elif case == 'small_growth':  # +20 jetons par appel : rien qui pèse
        events = growing(step=20)
    elif case == 'output_dominates':
        events = growing(output_tokens=60000)
    elif case == 'plateau_noise':  # fenêtre glissante : le contexte oscille autour d'un plateau
        events = [call(i, 4000 + (300 if i % 2 else -300)) for i in range(40)]
    else:
        events = growing()
    if case == 'unknown_price':
        for e in events:
            e['model'] = 'modele-inconnu'
    if case == 'errors':
        for e in events:
            e['error'] = dict(message='échec')
    assert detect(events) == []


def test_explicit_trace_left_to_context_reread():
    """Une trace posée par le client regroupe la conversation : c'est le terrain de context_reread."""
    events = []
    for s in range(3):
        for e in growing(n=40):
            e = copy.deepcopy(e)
            e['event_id'] = f's{s}-{e["event_id"]}'
            e['ts_start'] = e['ts_start'].replace('T10', f'T{10 + 2 * s}').replace('T11', f'T{11 + 2 * s}')
            e['ts_end'] = e['ts_end'].replace('T10', f'T{10 + 2 * s}').replace('T11', f'T{11 + 2 * s}')
            e['trace'] = dict(id=f'session-{s}', source='header', step=None)
            e['usage']['input_tokens'] += 9000  # assez gros pour context_reread
            events.append(e)
    assert detect_context_reread(events)
    assert detect(events) == []


@pytest.mark.parametrize('path', ['fixtures/dataset/v1/events.jsonl', 'fixtures/dataset/v2/events.jsonl',
                                  'fixtures/events.jsonl'])
def test_no_false_positive_on_fixtures(path):
    events = [json.loads(line) for line in (ROOT / path).read_text().splitlines() if line.strip()]
    assert detect(events) == []
