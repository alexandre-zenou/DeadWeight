"""D3.2 : rejeu et seuil, aucun appel réseau réel."""
import json
from pathlib import Path

import jsonschema
import pytest

from proof.extract import extract_rules
from proof.replay import HARD_MAX_CALLS, MIN_REPLAY, Throttle, main, replay
from rules.low_entropy import detect

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'fixtures/dataset/v1/events.jsonl'
PROOF_SCHEMA = json.loads((ROOT / 'schemas/proof.schema.json').read_text())


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


@pytest.fixture(scope='module')
def dataset():
    events = [json.loads(line) for line in DATASET.read_text().splitlines()]
    return events, {f['app_id']: f for f in detect(events)}


class FakeFallback:
    def __init__(self, answer='spam', error=None):
        self.answer, self.error, self.calls = answer, error, 0

    def classify(self, text, keys):
        self.calls += 1
        if self.error:
            raise self.error
        return self.answer, 50, 1


def _mot(i):
    """Un mot propre à chaque appel : les chiffres ne distinguent pas deux textes (jumeaux, ADR 0002)."""
    return 'x' + ''.join(chr(97 + i // 26 ** k % 26) for k in (2, 1, 0))


def _events(n, label='spam', text='gagnez un iphone'):
    return [{'event_id': f'e{i}', 'model': 'gpt-4o', 'provider': 'openai', 'latency_ms': 600,
             'ts_start': f'2026-09-20T09:{i // 60:02d}:{i % 60:02d}Z',
             'ts_end': f'2026-09-20T09:{i // 60:02d}:{i % 60:02d}.5Z', 'error': None,
             'request': {'messages': [{'role': 'user', 'content': f'{text} {_mot(i)}'}]},
             'response': {'content': label}, 'usage': {'input_tokens': 60, 'output_tokens': 2}}
            for i in range(n)]


def _finding(events, samples=()):
    return {'finding_id': 'f', 'event_ids': [e['event_id'] for e in events],
            'evidence': {'samples': [{'event_id': s, 'output': 'spam'} for s in samples]}}


RULES = {'categories': [{'key': 'spam', 'regex': 'gagnez'}]}


def test_dataset_mail_triage_non_conclu_une_fois_les_jumeaux_ecartes(dataset):
    # ADR 0002 : la v1 ne connaît que 28 phrases ; sans leurs jumeaux, il reste trop peu de textes
    # distincts remplacés. « Prouvé » avant, « non conclu » maintenant : changement accepté (#7).
    events, findings = dataset
    finding = findings['mail-triage']
    proof = replay(finding, events, extract_rules(finding, events))
    assert proof['verdict'] == 'inconclusive'
    assert proof['n_replayed'] == 170 and proof['n_excluded_twins'] == 194
    assert proof['n_distinct'] == 50 and proof['n_distinct_replaced'] < MIN_REPLAY
    assert proof['agreement_rate'] == 1  # rien à reprocher aux règles : il manque des textes
    assert any('Il manque' in r and 'texte(s) distinct(s)' in r for r in proof['reasons'])
    assert proof['cost_after_month_usd'] < proof['cost_before_month_usd']
    for field in ('patch_id', 'finding_id', 'n_replayed', 'agreement_rate', 'threshold',
                  'p95_before_ms', 'p95_after_ms', 'cost_before_month_usd', 'cost_after_month_usd'):
        assert proof[field] is not None


def test_dataset_reviews_non_conclu_faute_de_textes_distincts(dataset):
    events, findings = dataset
    finding = findings['reviews']
    proof = replay(finding, events, extract_rules(finding, events))
    assert proof['verdict'] == 'inconclusive' and proof['reasons']
    assert proof['n_distinct'] == 3
    assert proof['cost_before_month_usd'] > 0  # claude-opus-4-1 est au catalogue


def test_unmeasured_cost_is_null_never_a_default(dataset):
    events, findings = dataset
    finding = findings['reviews']
    unknown = [{**e, 'model': 'modele-maison-inconnu'} if e['app_id'] == 'reviews' else e for e in events]
    finding = {**finding, 'model': 'modele-maison-inconnu'}
    proof = replay(finding, unknown, extract_rules(finding, unknown))
    assert proof['cost_before_month_usd'] is None and proof['cost_factor'] is None
    assert any('catalogue' in m for m in proof['cost_missing'])
    jsonschema.validate(proof, PROOF_SCHEMA)


def test_extraction_samples_are_excluded():
    events = _events(40)
    proof = replay(_finding(events, samples=['e0', 'e1']), events, RULES)
    assert proof['n_replayed'] == 38 and proof['n_excluded_extraction_samples'] == 2


def test_below_threshold_rejects_with_reason():
    events = _events(40)
    for e in events[:5]:
        e['response']['content'] = 'Facture.'
    proof = replay(_finding(events), events, RULES)
    assert proof['agreement_rate'] == pytest.approx(35 / 40)
    assert proof['verdict'] == 'reject'
    assert any('sous le seuil' in r for r in proof['reasons'])
    assert proof['disagreements'][0] == {'event_id': 'e0', 'input': 'gagnez un iphone xaaa',
                                        'expected': 'facture', 'got': 'spam', 'via': 'regles'}


def test_unmatched_stays_on_original_and_is_not_compared():
    events = _events(30) + _events(10, text='bonjour')
    for i, e in enumerate(events[30:]):
        e['event_id'] = f'u{i}'
    proof = replay(_finding(events), events, RULES)
    assert proof['n_replaced'] == 30 and proof['agreement_rate'] == 1
    assert proof['verdict'] == 'pass'
    assert proof['cost_after_month_usd'] == pytest.approx(proof['cost_before_month_usd'] / 4, rel=1e-3)


def test_trop_peu_de_textes_distincts_a_plein_accord_est_non_conclu():
    events = _events(MIN_REPLAY - 1)
    proof = replay(_finding(events), events, RULES)
    assert proof['agreement_rate'] == 1 and proof['verdict'] == 'inconclusive'
    assert any('Il manque 1 texte(s) distinct(s)' in r for r in proof['reasons'])


def test_trop_peu_de_textes_distincts_et_accord_bas_est_refuse():
    events = _events(MIN_REPLAY - 10)
    for e in events[:5]:
        e['response']['content'] = 'facture'
    proof = replay(_finding(events), events, RULES)
    assert proof['verdict'] == 'reject'
    assert any('sous le seuil' in r for r in proof['reasons'])


def test_des_regles_par_coeur_sur_des_jumeaux_finissent_non_conclu():
    # 5 phrases habillées de politesse, de chiffres et de mois : 100 appels, 5 textes distincts.
    # Les règles recopient les phrases entières ; elles passaient quand on comptait par appel.
    phrases = [('ma facture est fausse', 'facture'), ('le site ne charge plus', 'support'),
               ('gagnez un iphone gratuit', 'spam'), ('je change mon adresse', 'compte'),
               ('remboursement de ma commande', 'facture')]
    habits = ['Bonjour, {} ({} {})', '{} {} {}. Merci d\'avance', 'Hello, {} - {} {} !',
              '{}, {} {}. Cordialement']
    mois = ['janvier', 'mars', 'mai', 'juin', 'octobre']
    events = _events(100)
    for i, e in enumerate(events):
        phrase, label = phrases[i % 5]
        e['request']['messages'][0]['content'] = habits[i % 4].format(phrase, mois[i // 20], 100 + i)
        e['response']['content'] = label
    samples = ['e0', 'e1', 'e2']
    rules = {'categories': [{'key': k, 'regex': '|'.join(p for p, lab in phrases if lab == k)}
                            for k in ('facture', 'support', 'spam', 'compte')]}
    proof = replay({**_finding(events), 'evidence': {'samples': [
        {'event_id': s, 'output': events[int(s[1:])]['response']['content']} for s in samples]}},
        events, rules)
    assert proof['n_distinct'] == 2 and proof['agreement_rate'] == 1
    assert proof['verdict'] == 'inconclusive'
    assert any('Il manque 28 texte(s) distinct(s)' in r for r in proof['reasons'])


def test_fallback_is_capped_and_spaced():
    events = _events(40, text='bonjour')
    clock, sleeps = [0.0], []
    throttle = Throttle(max_calls=3, min_interval_s=2, clock=lambda: clock[0], sleep=sleeps.append)
    fallback = FakeFallback()
    proof = replay(_finding(events), events, RULES, fallback, 'gpt-4o-mini', throttle)
    assert fallback.calls == 3 and proof['sent_to_fallback'] == 3 and proof['capped'] == 37
    assert sleeps == [2, 2]
    assert Throttle(max_calls=10 ** 6).max_calls == HARD_MAX_CALLS


def test_fallback_error_counts_as_disagreement_without_leaking():
    events = _events(35, text='bonjour')
    fallback = FakeFallback(error=RuntimeError('secret-api-key'))
    proof = replay(_finding(events), events, RULES, fallback, 'gpt-4o-mini',
                   Throttle(max_calls=50, min_interval_s=0))
    assert proof['agreement_rate'] == 0 and proof['verdict'] == 'reject'
    assert proof['cost_after_month_usd'] is None
    assert 'secret-api-key' not in json.dumps(proof)


def test_cli_writes_proofs_and_exits_zero_when_not_proven(tmp_path, capsys):
    assert main([str(DATASET), '--out', str(tmp_path)]) == 0
    written = {p.name for p in tmp_path.glob('proof-*.json')}
    assert len(written) == 2
    out = capsys.readouterr().out
    assert out.count('VERDICT   NON CONCLU') == 2 and 'textes distincts' in out


def test_toute_preuve_produite_respecte_le_contrat(dataset):
    events, findings = dataset
    produced = [replay(f, events, extract_rules(f, events)) for f in findings.values()]  # non conclu
    events = _events(40)
    produced.append(replay(_finding(events), events, RULES))  # prouvé
    for e in events[:5]:
        e['response']['content'] = 'facture'
    produced.append(replay(_finding(events), events, RULES))  # refusé
    assert {p['verdict'] for p in produced} == {'pass', 'reject', 'inconclusive'}
    for proof in produced:
        jsonschema.validate(proof, PROOF_SCHEMA)
        assert isinstance(proof['n_distinct'], int)


def test_les_economies_restent_comptees_par_appel():
    # 30 textes couverts une fois chacun, et une phrase non couverte répétée 90 fois (jumeaux) :
    # 90 appels sur 120 restent facturés, quel que soit le nombre de textes distincts
    couverts = _events(30)
    restants = _avec_textes([{**e, 'event_id': f'u{i}'} for i, e in enumerate(_events(90))],
                            [f'Bonjour, une question {i}' for i in range(90)])
    events = couverts + restants
    proof = replay(_finding(events), events, RULES)
    assert proof['n_distinct'] == 31 and proof['n_replaced'] == 30
    assert proof['rules_coverage'] == pytest.approx(30 / 120, abs=1e-4)
    assert proof['cost_after_month_usd'] == pytest.approx(proof['cost_before_month_usd'] * 90 / 120, rel=1e-3)


def test_inconclusive_proof_matches_the_contract(dataset):
    """ADR 0002 : trop peu de textes distincts → « non conclu », avec n_distinct et memorized_rules (facultatifs)."""
    events, findings = dataset
    finding = findings['reviews']
    proof = replay(finding, events, extract_rules(finding, events))
    jsonschema.validate({**proof, 'verdict': 'inconclusive', 'n_distinct': 3,
                         'memorized_rules': [
                             {'category': 'positif', 'alternative': 'merci pour votre commande',
                              'example': 'Merci pour votre commande, tout est parfait !'},
                             {'category': 'negatif', 'alternative': 'colis jamais arrivé'}]}, PROOF_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**proof, 'verdict': 'peut-etre'}, PROOF_SCHEMA)
    for bad in (['merci pour votre commande'], [{'category': 'positif'}]):  # objet, et alternative obligatoire
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**proof, 'memorized_rules': bad}, PROOF_SCHEMA)


def test_jeu_de_test_a_une_seule_reponse_rien_n_est_prouve():
    # vu chez un testeur : tous les « true » servent à apprendre, il ne reste que des « false » à
    # vérifier ; une règle qui répond toujours « false » ferait 100 % sans rien prouver
    events = _events(40, label='false', text='idée de campagne')
    rules = {'categories': [{'key': 'false', 'regex': 'idée'}, {'key': 'true', 'regex': 'excellente'}]}
    proof = replay(_finding(events), events, rules)
    assert proof['verdict'] == 'reject'
    assert any('une seule réponse' in r for r in proof['reasons'])


def test_une_regle_qui_ne_trouve_jamais_la_reponse_minoritaire_est_refusee():
    # 38 « false » et 2 « true » : répondre toujours « false » donne 95 %, sans rien prouver
    events = _events(38, label='false', text='idée de campagne') + [
        {**e, 'event_id': f't{i}'} for i, e in enumerate(_events(2, label='true', text='idée géniale'))]
    rules = {'categories': [{'key': 'false', 'regex': 'idée'}, {'key': 'true', 'regex': 'jamaisvu'}]}
    proof = replay(_finding(events), events, rules)
    assert proof['verdict'] == 'reject'
    assert any('true' in r and 'jamais' in r for r in proof['reasons'])


def test_regles_justes_sur_chaque_reponse_passent_toujours():
    events = _events(20, label='spam', text='gagnez un iphone') + [
        {**e, 'event_id': f'h{i}'} for i, e in enumerate(_events(20, label='ham', text='réunion demain'))]
    rules = {'categories': [{'key': 'spam', 'regex': 'gagnez'}, {'key': 'ham', 'regex': 'réunion'}]}
    assert replay(_finding(events), events, rules)['verdict'] == 'pass'


def test_echantillon_trop_petit_dit_non_conclu_et_combien_d_appels_manquent():
    events = _events(MIN_REPLAY - 10)
    proof = replay(_finding(events), events, RULES)
    raison = next(r for r in proof['reasons'] if 'il en faut au moins' in r)
    assert 'NON CONCLU' in raison and 'pas un échec des règles' in raison
    assert 'Il manque 10 texte(s) distinct(s)' in raison and 'environ' in raison
    assert proof['verdict'] == 'inconclusive'


def _avec_textes(events, textes):
    for e, t in zip(events, textes):
        e['request']['messages'][0]['content'] = t
    return events


def test_un_jumeau_d_un_exemple_d_extraction_n_est_pas_rejoue():
    # même phrase, autre politesse, autre mois, autres chiffres : c'est le même texte pour la preuve
    events = _events(43)
    _avec_textes(events, ['Bonjour, gagnez un iphone en mars !',
                          'Gagnez un iPhone en janvier. Merci d\'avance',
                          'Hello, gagnez un iphone en MAI 2026 ... Cordialement'])
    proof = replay(_finding(events, samples=['e0']), events, RULES)
    assert proof['n_replayed'] == 40 and proof['n_distinct'] == 40
    assert proof['n_excluded_extraction_samples'] == 1
    assert {'e1', 'e2'}.isdisjoint(d['event_id'] for d in proof['disagreements'])


def test_une_phrase_facile_repetee_ne_cache_pas_les_echecs_sur_les_phrases_rares():
    # 60 jumeaux faciles (une voix) + 35 phrases rares dont 4 ratées : 32/36 par texte, 91/95 par appel
    faciles = _avec_textes(_events(60), [f'Gagnez un iphone ! {i}' for i in range(60)])
    rares = [{**e, 'event_id': f'r{i}'} for i, e in enumerate(_events(35))]
    for e in rares[:4]:
        e['response']['content'] = 'facture'
    events = faciles + rares
    rules = {'categories': [{'key': 'spam', 'regex': 'gagnez'}, {'key': 'facture', 'regex': 'jamaisvu'}]}
    proof = replay(_finding(events), events, rules)
    assert proof['n_distinct'] == 36
    assert proof['agreement_rate'] == pytest.approx(32 / 36, abs=1e-4)
    assert proof['verdict'] == 'reject'


def test_une_seule_reponse_sur_trop_peu_de_textes_est_non_conclu():
    # une seule réponse dans 20 textes : il manque des données, rien n'est reproché aux règles (ADR 0002)
    events = _events(MIN_REPLAY - 10, label='false', text='idée de campagne')
    rules = {'categories': [{'key': 'false', 'regex': 'idée'}, {'key': 'true', 'regex': 'excellente'}]}
    proof = replay(_finding(events), events, rules)
    assert proof['verdict'] == 'inconclusive'
    assert any('une seule réponse' in r for r in proof['reasons'])
