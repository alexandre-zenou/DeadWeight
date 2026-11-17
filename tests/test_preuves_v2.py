"""T7 (#10) : preuves sur le jeu v2, avec les règles écrites une fois par DeadWeight (v2/rules.json).

Aucun appel réseau : les règles sont enregistrées par ``fixtures/dataset/gen_rules_v2.py``, la preuve
les rejoue sur les réponses enregistrées du modèle d'origine. Les verdicts sont figés tels quels :
sur des tickets variés, des règles de mots-clés écrites par gpt-4.1-mini restent sous 95 % d'accord.
"""
import json
from pathlib import Path

import jsonschema
import pytest

from optimize.patch_n8n import build_patched_workflow
from proof.replay import MIN_REPLAY, THRESHOLD, replay
from rules.low_entropy import detect

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / 'fixtures/dataset/v2'
PROOF_SCHEMA = json.loads((ROOT / 'schemas/proof.schema.json').read_text())

# app_id -> workflow d'exemple, nœud remplacé, workflow corrigé (comme gen_rules_v2.WORKFLOWS)
WORKFLOWS = {
    'support-ticket-triage': ('workflows/support-ticket-triage.json', 'Classify ticket',
                              'workflows/support-ticket-triage-patched-by-deadweight.json'),
    'spam-checker': ('workflows/my-workflow-sandboxed.json', 'Spam checker',
                     'workflows/my-workflow-sandboxed-patched-by-deadweight.json'),
}


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


@pytest.fixture(scope='module')
def v2():
    events = [json.loads(line) for line in (V2 / 'events.jsonl').read_text().splitlines() if line.strip()]
    findings = {f['app_id']: f for f in detect(events)}
    rules = json.loads((V2 / 'rules.json').read_text())
    return events, findings, rules


@pytest.fixture(scope='module')
def proofs(v2):
    events, findings, rules = v2
    return {app_id: replay(findings[app_id], events, rules[app_id]) for app_id in WORKFLOWS}


def test_les_regles_enregistrees_viennent_du_llm(v2):
    _, findings, rules = v2
    assert set(WORKFLOWS) <= set(findings)
    assert {app_id: rules[app_id]['method'] for app_id in WORKFLOWS} == {
        'support-ticket-triage': 'llm', 'spam-checker': 'llm'}


def test_tri_de_tickets_refuse_sur_la_v2(proofs):
    proof = proofs['support-ticket-triage']
    assert proof['verdict'] == 'reject'
    assert proof['reasons'] == ['accord 74.9% sous le seuil de 95%']
    assert proof['agreement_rate'] == 0.7488 < THRESHOLD
    assert proof['n_distinct_replaced'] == 215 >= MIN_REPLAY  # assez de textes : refusé, pas « non conclu »
    assert proof['n_excluded_twins'] == 0  # jeu v2 sans jumeaux


def test_detecteur_de_spam_refuse_sur_la_v2(proofs):
    proof = proofs['spam-checker']
    assert proof['verdict'] == 'reject'
    assert proof['reasons'] == ['accord 81.6% sous le seuil de 95%']
    assert proof['agreement_rate'] == 0.8161 < THRESHOLD
    assert proof['n_distinct_replaced'] == 174 >= MIN_REPLAY


def test_les_preuves_v2_respectent_le_contrat(proofs):
    validator = jsonschema.Draft7Validator(PROOF_SCHEMA)
    assert {app_id: [e.message for e in validator.iter_errors(p)] for app_id, p in proofs.items()} == {
        app_id: [] for app_id in proofs}


@pytest.mark.parametrize('app_id', WORKFLOWS)
def test_un_workflow_corrige_n_existe_que_si_sa_preuve_passe(app_id, v2, proofs):
    """Les workflows d'exemple corrigés sont ceux que gen_rules_v2 reconstruit : aucun sans preuve."""
    source, node, target = WORKFLOWS[app_id]
    path = ROOT / target
    if proofs[app_id]['verdict'] != 'pass':
        assert not path.exists(), f'{target} livré sans preuve'
        return
    _, findings, rules = v2
    expected = build_patched_workflow(json.loads((ROOT / source).read_text()), node, rules[app_id],
                                      findings[app_id]['model'])
    without_ids = lambda wf: [{k: v for k, v in n.items() if k != 'id'} for n in wf['nodes']]  # noqa: E731
    patched = json.loads(path.read_text())
    assert without_ids(patched) == without_ids(expected)
    assert patched['connections'] == expected['connections']
