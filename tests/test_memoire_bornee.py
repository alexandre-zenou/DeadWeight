"""#43 : rejeu d'une mémoire sans fin (endless_memory) avec une mémoire bornée, sur des conversations
fabriquées, sans réseau (client simulé, comme tests/test_bench_reasoning.py)."""
import copy
import json
import re
from pathlib import Path

import pytest

from bench import memory
from bench.client import CallResult
from rules.endless_memory import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
PREFIX = "Relis la conversation avant de répondre.\nVoici la conversation précédente :\n"
FIRST = "Bonjour, je prépare un voyage à Lyon"
RECALL = "Rappelle-moi ma toute première question"


def question(i, recall_every=None):
    if i and recall_every and i % recall_every == 0:
        return RECALL
    return FIRST if i == 0 else f"Question numéro {i} sur le voyage"


def answer(q, history):
    """Le « modèle » : une réponse fixe par question, sauf le rappel qui dépend du tout premier échange."""
    if q == RECALL:
        return f"Votre première question était : {FIRST}" if f"Human: {FIRST}" in history \
            else "Je ne retrouve pas le début de notre conversation"
    return f"Voici ma réponse détaillée à « {q} » avec des conseils précis"


def flat(exchanges):
    return PREFIX + "".join(f"\nHuman: {q}\nAI Assistant: {a}\n" for q, a in exchanges)


def conversation(n=40, recall_every=None, app='voice-bot', model='gpt-4o-mini', render=flat):
    """Historique aplati dans un message assistant (comme n8n), entrée qui grandit à chaque appel."""
    events, exchanges = [], []
    for i in range(n):
        q = question(i, recall_every)
        history = render(exchanges)
        a = answer(q, history)
        e = copy.deepcopy(BASE)
        e.update(event_id=f'{app}-{i:03d}', app_id=app, model=model, provider='openai',
                 ts_start=f'2026-11-18T10:{i:02d}:00Z', ts_end=f'2026-11-18T10:{i:02d}:02Z',
                 latency_ms=2000, error=None)
        e['trace'] = dict(id=None, source=None, step=None)
        e['request'].update(system=None, tools=[], messages=[dict(role='assistant', content=history),
                                                              dict(role='user', content=q)])
        e['response'].update(content=a, tool_calls=[])
        e['usage'].update(input_tokens=70 + 230 * i, output_tokens=120, cached_input_tokens=0)
        events.append(e)
        exchanges.append((q, a))
    return events


def turns(n=40):
    """Même conversation, mais en tours de parole (user/assistant) au lieu d'un historique aplati."""
    events = conversation(n)
    for e in events:
        history = e['request']['messages'][0]['content']
        pairs = re.findall(r'\nHuman: (.*)\nAI Assistant: (.*)\n', history)
        msgs = [m for q, a in pairs for m in (dict(role='user', content=q), dict(role='assistant', content=a))]
        e['request']['messages'] = msgs + [e['request']['messages'][1]]
    return events


def fake_client():
    """Client simulé : rejoue « le modèle » sur ce qu'on lui envoie ; jetons d'entrée ~ caractères / 4."""
    seen = []

    class Client:
        def __init__(self, base_url, api_key, model, **kw):
            self.model = model

        def complete(self, messages, tools=None):
            seen.append(messages)
            history = "".join(m['content'] for m in messages[:-1])
            text = answer(messages[-1]['content'], history)
            return CallResult(text, 10.0, sum(len(m['content']) for m in messages) // 4, 30, None)

    return Client, seen


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')

    def forbidden(*a, **kw):
        raise AssertionError('appel réseau inattendu')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


def finding_of(events):
    [f] = detect(events)
    assert f['rule'] == 'endless_memory'
    return f


# ---------- bornage de l'historique ----------

def test_flat_history_keeps_the_instructions_and_the_last_n_exchanges():
    events = conversation(15)
    msgs = events[14]['request']['messages']
    bounded, n, fmt = memory.bound(msgs, 10)
    assert (n, fmt) == (14, 'aplati')
    kept = bounded[0]['content']
    assert kept.startswith(PREFIX) and kept.count('\nHuman: ') == 10
    assert 'Question numéro 4 ' in kept and 'Question numéro 3 ' not in kept and FIRST not in kept
    assert bounded[-1] == msgs[-1]
    assert msgs[0]['content'].count('\nHuman: ') == 14  # l'événement n'est jamais modifié


def test_turn_history_keeps_the_last_n_exchanges():
    msgs = turns(15)[14]['request']['messages']
    bounded, n, fmt = memory.bound(msgs, 10)
    assert (n, fmt) == (14, 'tours')
    assert [m['role'] for m in bounded].count('user') == 11 and bounded[-1] == msgs[-1]
    assert bounded[0]['content'] == 'Question numéro 4 sur le voyage'


def test_history_within_the_window_is_unchanged():
    msgs = conversation(8)[7]['request']['messages']
    bounded, n, fmt = memory.bound(msgs, 10)
    assert n == 7 and bounded == msgs


def test_unknown_history_format_is_not_readable():
    assert memory.bound([dict(role='user', content='Contexte : blabla. Question : et alors ?')], 10)[2] is None


# ---------- rejeu ----------

def test_recent_only_questions_pass_with_a_measured_gain(key):
    events = conversation()
    client, seen = fake_client()
    r = memory.prove(events, finding_of(events), client_cls=client)
    assert r['verdict'] == 'pass', r['reasons']
    assert r['window'] == 10 and r['n_identical'] == 11 and r['n_replayed'] == 29
    assert r['agreement'] == 1.0
    assert len(seen) == 2 * 29  # mémoire bornée + témoin à mémoire complète, jamais les appels identiques
    assert max(m[0]['content'].count('\nHuman: ') for m in seen[::2]) == 10
    assert r['tokens_after'] < r['tokens_before'] and r['cost_after_usd'] < r['cost_before_usd']


def test_turn_format_is_replayed_too(key):
    events = turns()
    r = memory.prove(events, finding_of(events), client_cls=fake_client()[0])
    assert r['verdict'] == 'pass' and r['format'] == 'tours' and r['n_replayed'] == 29


def test_a_question_about_an_old_exchange_lowers_the_agreement(key):
    events = conversation(recall_every=13)  # rappels aux appels 13, 26, 39 : le début est loin
    r = memory.prove(events, finding_of(events), client_cls=fake_client()[0])
    assert r['agreement'] < 1.0
    assert [g['question'] for g in r['gaps']] == [RECALL] * 3


def test_many_questions_about_old_exchanges_are_rejected(key):
    events = conversation(recall_every=4)
    r = memory.prove(events, finding_of(events), client_cls=fake_client()[0])
    assert r['verdict'] == 'reject' and r['agreement'] < .95
    assert any('fenêtre plus grande' in reason for reason in r['reasons'])


def test_unreadable_history_is_not_tested_and_nothing_is_called(key):
    events = conversation()
    for e in events:
        e['request']['messages'] = [dict(role='user', content='x' * (10 + e['usage']['input_tokens']))]
    client, seen = fake_client()
    r = memory.prove(events, finding_of(events), client_cls=client)
    assert r['verdict'] == 'not_tested' and 'historique illisible' in r['reasons'][0] and not seen


def test_without_key_nothing_is_called(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    events = conversation()
    client, seen = fake_client()
    r = memory.prove(events, finding_of(events), client_cls=client)
    assert r['verdict'] == 'not_tested' and 'OPENAI_API_KEY' in r['reasons'][0] and not seen


def test_too_few_calls_is_inconclusive(key):
    """Comme proof.replay : sous MIN_REPLAY appels mesurés (identiques + rejoués), on ne tranche pas."""
    events = conversation(25)
    r = memory.prove(events, finding_of(events), client_cls=fake_client()[0])
    assert r['n_identical'] + r['n_replayed'] == 25 and r['verdict'] == 'inconclusive'
    assert r['agreement'] == 1.0


def test_replay_errors_are_never_a_pass(key):
    events = conversation()
    client, _ = fake_client()

    class Broken(client):
        def complete(self, messages, tools=None):
            return CallResult(None, 5.0, None, None, 'http_500')
    r = memory.prove(events, finding_of(events), client_cls=Broken)
    assert r['verdict'] == 'not_tested'
