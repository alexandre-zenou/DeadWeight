"""#45 : pour une mémoire sans fin (endless_memory), prévoir quand la conversation dépassera la fenêtre de
contexte du modèle. Séries fabriquées, aucun réseau. La prévision est toujours dite comme telle et n'entre
jamais dans un gain."""
import copy

import pytest

from optimize.devpage import render
from optimize.propose import propose
from optimize.slack import message
from report.audit import build_report, render_html
from report.prevision import texte
from rules import endless_memory
from rules.endless_memory import context_window, detect
from tests.test_endless_memory import call


def exact(n=40, start=70, step=230, **kw):
    return [call(i, start + step * i, **kw) for i in range(n)]


def forecast(events):
    [f] = detect(events)
    return f['evidence']['forecast']


def test_window_comes_from_the_capabilities_table():
    assert context_window('gpt-4o-mini') == 128000  # route OpenAI de openai/gpt-4o-mini
    assert context_window('openai/gpt-4o-mini') == 128000
    assert context_window('modele-inconnu') is None


def test_ticket_case_breaks_near_the_560th_call():
    """+230 jetons par appel, 128 000 jetons de fenêtre : la limite tombe vers le 560e appel."""
    fc = forecast(exact())
    assert fc['statut'] == 'prevision'
    assert fc['fenetre_tokens'] == 128000 and fc['pente_tokens_par_appel'] == pytest.approx(230)
    # limite = fenêtre moins la plus longue réponse observée (200) ; dernier contexte 9 040
    assert fc['appels_restants'] == (128000 - 200 - 9040) // 230 == 516
    assert fc['appel_limite'] == 40 + 516 + 1
    assert 540 <= fc['appel_limite'] <= 580
    t = texte(fc)
    assert t.startswith('Prévision') and 'à ce rythme' in t
    assert '557e appel' in t and '128 000 jetons' in t and 'environ 516' in t


def test_noisy_series_uses_the_fitted_slope():
    events = [call(i, 70 + 230 * i + (i * 37) % 50) for i in range(40)]
    fc = forecast(events)
    assert 225 <= fc['pente_tokens_par_appel'] <= 235 and 530 <= fc['appel_limite'] <= 580


def test_unknown_window_gives_no_forecast_and_says_why(monkeypatch):
    monkeypatch.setattr(endless_memory, 'context_window', lambda model: None)
    fc = forecast(exact())
    assert fc['statut'] == 'inconnue' and 'appel_limite' not in fc
    assert 'gpt-4o-mini' in fc['raison'] and 'fenêtre' in fc['raison']
    assert texte(fc).startswith('Pas de prévision')


def test_close_to_the_limit_is_imminent(monkeypatch):
    monkeypatch.setattr(endless_memory, 'context_window', lambda model: 10000)
    fc = forecast(exact())
    assert fc['statut'] == 'imminente' and fc['appels_restants'] == (10000 - 200 - 9040) // 230 == 3
    t = texte(fc)
    assert 'presque atteinte' in t and 'à ce rythme' in t and '10 000 jetons' in t


def test_context_too_long_errors_are_reported_as_they_are():
    events = exact()
    for k in range(3):
        e = call(40 + k, 0)
        e['usage'].update(input_tokens=None, output_tokens=None)
        e['error'] = dict(type='invalid_request_error', message="This model's maximum context length is 128000 "
                          "tokens. However, your messages resulted in 128203 tokens. (context_length_exceeded)")
        events.append(e)
    fc = forecast(events)
    assert fc['statut'] == 'depassee' and fc['appels_refuses'] == 3
    t = texte(fc)
    assert 'déjà' in t and '3 appels refusés' in t and 'Prévision' not in t


def test_other_errors_do_not_count_as_overflow():
    events = exact()
    e = call(40, 0)
    e['error'] = dict(type='rate_limit_error', message='Rate limit reached')
    fc = forecast(events + [e])
    assert fc['statut'] == 'prevision'


def test_forecast_is_never_part_of_a_saving():
    [f] = detect(exact())
    ev = f['evidence']
    without = {k: v for k, v in ev.items() if k != 'forecast'}
    [g] = detect(exact())
    assert {k: v for k, v in g['evidence'].items() if k != 'forecast'} == without
    assert ev['est_saving_month_usd'] < ev['context_cost_month_usd']


def test_audit_page_shows_the_forecast():
    page = render_html(build_report(exact()))
    assert 'à ce rythme' in page and '557e appel' in page


def test_devpage_and_slack_show_the_forecast_when_the_proposal_is_there(monkeypatch):
    p = next(p for p in propose(exact()) if p['type'] == 'memoire')
    assert p['prevision']['statut'] == 'prevision'
    assert '557e appel' in render([p])
    assert '557e appel' in message([p], show_all=True)
    passed = copy.deepcopy(p)
    passed['verdict'] = 'pass'
    text = message([passed])
    assert '557e appel' in text and '~' not in text.split('\n\n')[1]
    assert '557e appel' not in message([p])  # Slack sans la proposition : rien
