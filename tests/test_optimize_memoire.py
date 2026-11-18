"""#43 : la proposition « memoire » (endless_memory) dans propose, la page développeur, Slack, et le
diff d'un workflow n8n (fenêtre de la mémoire, clé de session fixe). Aucun réseau."""
import copy
import json
import subprocess

import pytest

from optimize import __main__ as optimize_main
from optimize.devpage import render
from optimize.patch import make_patch
from optimize.patch_memoire_n8n import bound_memory
from optimize.propose import ESTIME, MESURE, NON_TESTE, propose
from optimize.slack import message
from tests.test_memoire_bornee import conversation, fake_client


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('réseau')))


def prove_with_fake(events, finding, **kw):
    from bench.memory import prove
    return prove(events, finding, client_cls=fake_client()[0], **kw)


def memory_proposal(events):
    return next(p for p in propose(events, keys_available=True, prove_memory=prove_with_fake)
                if p['type'] == 'memoire')


def test_proven_memory_proposal_is_measured_never_estimated(key):
    p = memory_proposal(conversation())
    assert p['verdict'] == 'pass' and p['fenetre'] == 10
    assert 'derniers échanges' in p['changement']
    m = p['mesures']
    assert m['precision'] == {'valeur': 100.0, 'statut': MESURE, 'unite': '%'}
    assert m['appels_rejoues']['valeur'] == 29
    assert m['jetons_envoyes']['valeur'] < 0 and m['cout']['valeur'] < 0
    assert all(v['statut'] != ESTIME for v in m.values())
    assert p['cout_usd']['statut'] == MESURE and p['cout_usd']['apres'] < p['cout_usd']['avant']


def test_slack_total_is_the_measured_replay_never_the_rule_estimate(key):
    events = conversation()
    p = memory_proposal(events)
    text = message([p], total_spent=1.0)
    c = p['cout_usd']
    assert f"{c['avant']:.4g} $ → {c['apres']:.4g} $" in text
    assert '~' not in text.split('\n\n')[1]  # aucune estimation dans les lignes de gain
    assert 'clé de session' in text  # conseil de correction, sans chiffre


def test_rejected_memory_proposal_stays_out_of_slack_but_shows_in_the_devpage(key):
    p = memory_proposal(conversation(recall_every=4))
    assert p['verdict'] == 'reject'
    assert 'voice-bot' not in message([p]).split('\n\n')[1]  # Slack : gains prouvés seulement
    page = render([p])
    assert 'Refusée' in page and 'Rappelle-moi ma toute première question' in page
    assert 'témoin' in page


def test_without_keys_the_proposal_is_not_tested():
    p = next(p for p in propose(conversation()) if p['type'] == 'memoire')
    assert p['verdict'] == 'non_teste' and p['mesures']['precision']['statut'] == NON_TESTE


def test_unreadable_history_is_a_non_tested_proposal_with_its_reason(key):
    events = conversation()
    for e in events:
        e['request']['messages'] = [dict(role='user', content='x' * (10 + e['usage']['input_tokens']))]
    p = memory_proposal(events)
    assert p['verdict'] == 'non_teste' and 'historique illisible' in p['raisons'][0]


# ---------- diff n8n ----------

def workflow(trigger='n8n-nodes-base.webhook', session_key='test-1234', manager=True):
    nodes = [
        {"name": "Webhook", "type": trigger, "typeVersion": 2, "position": [0, 0], "parameters": {}},
        {"name": "Basic LLM Chain", "type": "@n8n/n8n-nodes-langchain.chainLlm", "position": [600, 0],
         "parameters": {"text": "={{ $json.text }}"}},
        {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "position": [600, 200],
         "parameters": {"model": {"value": "gpt-4o-mini"}}},
        {"name": "Window Buffer Memory", "type": "@n8n/n8n-nodes-langchain.memoryBufferWindow",
         "typeVersion": 1.2, "position": [400, 200],
         "parameters": {"sessionKey": session_key, "sessionIdType": "customKey"}},
    ]
    conns = {"OpenAI Chat Model": {"ai_languageModel": [[{"node": "Basic LLM Chain", "type": "ai_languageModel",
                                                          "index": 0}]]}}
    if manager:
        nodes += [
            {"name": "Get Chat", "type": "@n8n/n8n-nodes-langchain.memoryManager", "position": [200, 0],
             "parameters": {"options": {}}},
            {"name": "Aggregate", "type": "n8n-nodes-base.aggregate", "position": [400, 0],
             "parameters": {"aggregate": "aggregateAllItemData", "destinationFieldName": "context"}},
        ]
        conns.update({"Webhook": {"main": [[{"node": "Get Chat", "type": "main", "index": 0}]]},
                      "Get Chat": {"main": [[{"node": "Aggregate", "type": "main", "index": 0}]]},
                      "Aggregate": {"main": [[{"node": "Basic LLM Chain", "type": "main", "index": 0}]]},
                      "Window Buffer Memory": {"ai_memory": [[{"node": "Get Chat", "type": "ai_memory",
                                                               "index": 0}]]}})
    else:
        conns.update({"Webhook": {"main": [[{"node": "Basic LLM Chain", "type": "main", "index": 0}]]},
                      "Window Buffer Memory": {"ai_memory": [[{"node": "Basic LLM Chain", "type": "ai_memory",
                                                               "index": 0}]]}})
    return {"name": "Assistant vocal (test)", "nodes": nodes, "connections": conns, "settings": {}}


def node(wf, name):
    return next(n for n in wf['nodes'] if n['name'] == name)


def test_window_is_set_and_full_history_reads_are_limited():
    original = workflow()
    wf, notes = bound_memory(original, 10)
    assert node(wf, 'Window Buffer Memory')['parameters']['contextWindowLength'] == 10
    [limit] = [n for n in wf['nodes'] if n['type'] == 'n8n-nodes-base.limit']
    assert limit['parameters'] == {'maxItems': 10, 'keep': 'lastItems'}
    assert wf['connections']['Get Chat']['main'] == [[{'node': limit['name'], 'type': 'main', 'index': 0}]]
    assert wf['connections'][limit['name']]['main'][0][0]['node'] == 'Aggregate'
    assert any('Get Chat' in n for n in notes)
    assert 'contextWindowLength' not in node(original, 'Window Buffer Memory')['parameters']  # jamais modifié


def test_fixed_session_key_is_replaced_by_a_per_user_key_and_flagged():
    wf, notes = bound_memory(workflow(), 10)
    params = node(wf, 'Window Buffer Memory')['parameters']
    assert params['sessionKey'].startswith('=') and "$('Webhook')" in params['sessionKey']
    assert any('clé de session fixe' in n and 'test-1234' in n for n in notes)


def test_chat_trigger_uses_its_own_session_id():
    wf, _ = bound_memory(workflow(trigger='@n8n/n8n-nodes-langchain.chatTrigger', manager=False), 10)
    params = node(wf, 'Window Buffer Memory')['parameters']
    assert params['sessionIdType'] == 'fromInput' and 'sessionKey' not in params
    assert not [n for n in wf['nodes'] if n['type'] == 'n8n-nodes-base.limit']


def test_per_user_key_is_left_alone():
    wf, notes = bound_memory(workflow(session_key="={{ $json.body.user_id }}"), 10)
    assert node(wf, 'Window Buffer Memory')['parameters']['sessionKey'] == "={{ $json.body.user_id }}"
    assert not any('clé de session' in n for n in notes)


def git_repo(tmp_path, files):
    repo = tmp_path / 'repo'
    repo.mkdir()
    for name, content in files.items():
        (repo / name).write_text(content, encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init'], cwd=repo, check=True)
    return repo


def test_make_patch_produces_a_diff_of_the_workflow(tmp_path):
    repo = git_repo(tmp_path, {'assistant.json': json.dumps(workflow(), ensure_ascii=False, indent=2) + '\n'})
    diff, notes = make_patch(repo, {'type': 'memoire', 'fenetre': 10, 'app_id': 'n8n-voice'})
    assert 'assistant.json' in diff and '"contextWindowLength": 10' in diff and '"keep": "lastItems"' in diff
    assert any('clé de session fixe' in n for n in notes)
    assert json.loads((repo / 'assistant.json').read_text())['nodes'] == workflow()['nodes']  # dépôt intact


def test_make_patch_without_n8n_workflow_says_so(tmp_path):
    repo = git_repo(tmp_path, {'app.py': 'print(1)\n'})
    diff, notes = make_patch(repo, {'type': 'memoire', 'fenetre': 10, 'app_id': 'voice-bot'})
    assert diff == '' and 'aucun workflow n8n' in notes[0]


def test_optimize_writes_the_memory_diff_when_proven(tmp_path, monkeypatch):
    proposal = {'type': 'memoire', 'verdict': 'pass', 'finding_id': 'f1', 'app_id': 'n8n-voice',
                'model': 'gpt-4o-mini', 'fenetre': 10, 'changement': 'Borner la mémoire.', 'raisons': [],
                'mesures': {'precision': {'valeur': 100.0, 'statut': MESURE, 'unite': '%'}}}
    monkeypatch.setattr(optimize_main, 'propose', lambda events, **kw: [copy.deepcopy(proposal)])
    events = tmp_path / 'events.jsonl'
    events.write_text(json.dumps(conversation()[0]) + '\n')
    repo = git_repo(tmp_path, {'assistant.json': json.dumps(workflow(), indent=2) + '\n'})
    out = tmp_path / 'out'
    assert optimize_main.main([str(events), '--out', str(out), '--repo', str(repo)]) == 0
    [diff] = list(out.glob('*-memoire-*.diff'))
    assert 'contextWindowLength' in diff.read_text()
