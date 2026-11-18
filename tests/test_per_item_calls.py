"""R11 : lots courts variables, coûts manquants et cache."""
import copy
import json
import math
from pathlib import Path

import pytest

from rules.per_item_calls import detect
from tests.test_parallelizable_steps import series

ROOT = Path(__file__).resolve().parents[1]


def batch():
    es = series(10)
    for e in es:
        e['request']['system'] = 'Instructions communes pour analyser chaque élément. ' * 6
        e['trace'] = dict(id=None, step=None, source=None)
        e['usage']['input_tokens'] = 200
    return es


def test_savings():
    es = batch()
    before = copy.deepcopy(es)
    [f] = detect(es)
    assert f['evidence']['estimated_repeated_system_tokens'] > 500
    assert f['evidence']['est_saving_month_usd'] > 0
    assert f['evidence']['estimated_latency_saving_seconds'] == 18
    assert es == before
    assert detect(es[::-1]) == [f]


@pytest.mark.parametrize('case', ['few', 'identical', 'long', 'history', 'error', 'tools'])
def test_negatives(case):
    es = batch()[:7] if case == 'few' else batch()
    for e in es:
        if case == 'identical':
            e['request']['messages'][0]['content'] = 'Même élément'
        if case == 'long':
            e['usage']['output_tokens'] = 500
        if case == 'history':
            e['request']['messages'].append(dict(role='assistant', content='Historique'))
        if case == 'error':
            e['error'] = dict(message='Erreur')
        if case == 'tools':
            e['request']['tools'] = [dict(name='outil')]
    assert detect(es) == []


def test_unknown_price_and_cache():
    for cached in (0, None, 100):
        es = batch()
        for e in es:
            e['model'] = 'inconnu'
            e['usage']['cached_input_tokens'] = cached
        [f] = detect(es)
        assert f['evidence']['est_saving_month_usd'] is None
        assert f['evidence']['saving_missing']


def test_dataset():
    es = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(es)} == {'item-loop'}


# Motif « par élément dans une même exécution » (#34) : relectures par langue, sortie structurée.
LANGS = ['anglais', 'espagnol', 'allemand', 'italien']
REVIEW = 'Tu relis une traduction et tu rends une note sur 10 et un commentaire bref. ' * 4


def reviews(traces=5, per=4, shape='tool'):
    es = []
    for t in range(traces):
        for i, e in enumerate(series(per)):
            e.update(event_id=f'r{t}-{i}', app_id='audio-translate', model='gpt-4o',
                     ts_start=f'2026-11-1{t}T09:00:{i * 3:02d}Z', ts_end=f'2026-11-1{t}T09:00:{i * 3 + 2:02d}Z')
            e['trace'] = dict(id=f'n8n-{t}', source='header', step=i)
            e['request'].update(system=REVIEW, messages=[
                dict(role='user', content=f'Texte {t} traduit en {LANGS[i % len(LANGS)]} : contenu {t}-{i}.')])
            args = json.dumps({'note': 7 + i % 3, 'commentaire': f'Fidèle, ton correct ({t}-{i}).'})
            if shape == 'tool':
                e['request']['tools'] = [dict(name='format_final_json_response', description=None, parameters=None)]
                e['response'].update(content='', finish_reason='tool_calls', tool_calls=[
                    dict(id=f'c{t}{i}', name='format_final_json_response', arguments=args)])
            elif shape == 'json':
                e['response'].update(content=args)
            elif shape == 'lost':  # sortie structurée perdue à l'import (#33) : seul finish_reason la signale
                e['response'].update(content='', finish_reason='tool_calls', tool_calls=[])
            e['usage'].update(input_tokens=180, output_tokens=60)
            es.append(e)
    return es


@pytest.mark.parametrize('shape', ['tool', 'json', 'lost'])
def test_same_instructions_per_trace(shape):
    es = reviews(shape=shape)
    before = copy.deepcopy(es)
    [f] = detect(es)
    ev = f['evidence']
    assert f['rule'] == 'per_item_calls' and f['app_id'] == 'audio-translate'
    assert ev['traces'] == 5 and ev['calls'] == 20 and ev['calls_per_trace'] == 4
    assert ev['estimated_repeated_system_tokens'] == math.ceil(len(REVIEW) / 4) * 3 * 5
    assert ev['est_saving_month_usd'] > 0 and not ev['saving_missing']
    assert 'hypothèse' in ev['estimate_method']
    assert len(f['event_ids']) == 20
    assert es == before
    assert detect(es[::-1]) == [f]


@pytest.mark.parametrize('case', ['two_per_trace', 'few_traces', 'agent_loop', 'identical', 'slow',
                                  'heuristic', 'long_output', 'short_system', 'images', 'mixed_system',
                                  'error', 'free_text'])
def test_same_instructions_per_trace_negatives(case):
    es = reviews(per=2 if case == 'two_per_trace' else 4, traces=2 if case == 'few_traces' else 5)
    for e in es:
        t, i = e['trace']['id'], e['trace']['step']
        if case == 'agent_loop' and i == 3:  # la consigne sert une boucle d'agent : historique d'outil
            e['request']['messages'] += [
                dict(role='assistant', content=None, tool_calls=[dict(id='x', name='chercher', arguments='{}')]),
                dict(role='tool', content='résultat', tool_call_id='x')]
        if case == 'identical':
            e['request']['messages'][0]['content'] = f'Même texte pour {t}'
        if case == 'slow':  # appels d'une même « trace » espacés : session d'utilisateur, pas une boucle
            e['ts_start'] = e['ts_start'].replace('09:00', f'09:{10 * i:02d}')
            e['ts_end'] = e['ts_end'].replace('09:00', f'09:{10 * i:02d}')
        if case == 'heuristic':
            e['trace']['source'] = 'heuristic'
        if case == 'long_output':
            e['usage']['output_tokens'] = 900
        if case == 'short_system':
            e['request']['system'] = 'Relis.'
        if case == 'images':
            e['request']['messages'][0]['n_images'] = 1
        if case == 'mixed_system':
            e['request']['system'] = REVIEW + f' Langue cible numéro {i}.'
        if case == 'error':
            e['error'] = dict(message='Erreur')
        if case == 'free_text':  # texte libre long : rédaction, pas une sortie structurée courte
            e['request']['tools'] = []
            e['response'].update(content='Une relecture rédigée. ' * 20, finish_reason='stop', tool_calls=[])
            e['usage']['output_tokens'] = 120
    assert detect(es) == []


def test_long_trace_keeps_previous_behaviour():
    """Une trace de >= 8 éléments courts sans outil reste un constat par trace, comme avant."""
    es = batch()
    for e in es:
        e['trace'] = dict(id='lot', source='header', step=None)
    [f] = detect(es)
    assert f['evidence']['calls'] == 10 and 'traces' not in f['evidence']
