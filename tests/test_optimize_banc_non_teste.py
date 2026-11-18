"""#22 : un banc qui n'a testé aucun modèle rend une piste « non testée » avec sa raison, jamais « refusée ».
Faux banc injecté : aucun appel réseau."""
import html
import json
from pathlib import Path

from optimize.devpage import render
from optimize.propose import NON_TESTE, propose
from optimize.slack import message

ROOT = Path(__file__).resolve().parents[1]
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()
          if line.strip()]
RAISON = "moins d'une heure de trafic observée : projection sur un mois non fiable"


def _swaps(prove):
    swaps = [p for p in propose(EVENTS, keys_available=True, prove=prove) if p["type"] == "modele"]
    assert swaps
    return swaps


def _bench(options, raison=None):
    return lambda events, finding: {"finding_id": finding["finding_id"], "raison": raison, "options": options,
                                    "reference_cost_per_1000_calls_usd": 1.0}


def test_bench_without_any_option_is_not_tested_with_the_bench_reason():
    for p in _swaps(_bench({}, RAISON)):
        assert p["verdict"] == "non_teste"
        assert p["raisons"] == [RAISON]
        assert p["nouveau_modele"] is None
        assert all(m["valeur"] is None and m["statut"] == NON_TESTE for m in p["mesures"].values())


def test_bench_whose_options_all_failed_is_not_tested():
    failed = {"verdict": "not_tested", "score": None, "reasons": ["les 5 appels ont échoué : rien de mesuré"]}
    for p in _swaps(_bench({"petit": failed})):
        assert p["verdict"] == "non_teste" and p["raisons"] == ["les 5 appels ont échoué : rien de mesuré"]


def test_tested_options_below_the_threshold_are_still_rejected():
    low = {"verdict": "reject", "score": .7, "model": "petit", "n_calls": 5, "latency_p95_ms": 100,
           "cost_per_1000_calls_usd": .1, "reasons": ["score sous le seuil"]}
    for p in _swaps(_bench({"petit": low}, RAISON)):
        assert p["verdict"] == "reject" and p["raisons"] == ["aucun candidat au-dessus du seuil"]


def test_dev_page_and_slack_show_not_tested_and_the_reason():
    swaps = _swaps(_bench({}, RAISON))
    page = render(swaps)
    assert "Non testée" in page and "Refusée" not in page and html.escape(RAISON) in page
    slack = message(swaps, show_all=True)
    assert "◻️ *" in slack and RAISON in slack and "⛔ *" not in slack
    assert "aucun candidat au-dessus du seuil" not in slack
    hidden = message(swaps)
    assert f"{len(swaps)} non testée" in hidden and "0 rejetée" in hidden
