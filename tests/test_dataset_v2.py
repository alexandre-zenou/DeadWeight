"""T6 (#5) : jeu de test v2, tickets variés passés une fois dans le modèle d'origine sous les deux consignes."""
import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("gen_v2", ROOT / "fixtures/dataset/gen_dataset_v2.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def ticket(i, text, subject="Question", sender="client@example.fr"):
    return {"id": f"t{i:03d}", "subject": subject, "from": sender, "text": text}


# --- contrôles de fin de génération --------------------------------------------------------------

def test_deux_jumeaux_sont_signales():
    tickets = [ticket(1, "Bonjour, ma facture de mars est fausse. Merci d'avance."),
               ticket(2, "ma facture de juin est fausse !"),
               ticket(3, "L'application plante quand j'exporte en PDF")]
    report = gen.checks(tickets, {"t001": "billing", "t002": "billing", "t003": "technical"})
    assert not report["jumeaux"]["ok"]
    assert report["jumeaux"]["groupes"] == [["t001", "t002"]]


def test_un_mot_qui_commence_comme_une_salutation_n_est_pas_retire():
    tickets = [ticket(1, "Chercher le PDF ne marche pas"), ticket(2, "le PDF ne marche pas"),
               ticket(3, "Je cherche le PDF, merci"), ticket(4, "Je cherche le PDF remerciements")]
    report = gen.checks(tickets, {t["id"]: "technical" for t in tickets})
    assert report["jumeaux"]["ok"], report["jumeaux"]


def words(n, seed):
    """n mots distincts, sans chiffre (les chiffres sont retirés à la normalisation)."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return " ".join(f"mot{letters[seed % 26]}{letters[seed // 26]}{letters[i % 26]}{letters[i // 26]}"
                    for i in range(n))


def test_des_longueurs_toutes_courtes_ne_passent_pas():
    tickets = [ticket(i, f"Sujet numéro {chr(97 + i)} ne marche pas") for i in range(10)]
    report = gen.checks(tickets, {t["id"]: "technical" for t in tickets})
    assert not report["longueurs"]["ok"]
    assert report["longueurs"]["repartition"] == {"court": 10, "moyen": 0, "long": 0}


def test_courts_moyens_et_longs_melanges_passent():
    tickets = ([ticket(i, words(8, i)) for i in range(4)] + [ticket(10 + i, words(40, 10 + i)) for i in range(3)]
               + [ticket(20 + i, words(120, 20 + i)) for i in range(3)])
    report = gen.checks(tickets, {t["id"]: "technical" for t in tickets})
    assert report["longueurs"]["ok"]
    assert report["longueurs"]["repartition"] == {"court": 4, "moyen": 3, "long": 3}


def test_une_categorie_absente_est_signalee():
    tickets = [ticket(i, words(10, i)) for i in range(3)]
    report = gen.checks(tickets, {"t000": "Billing.", "t001": "technical", "t002": "other"})
    assert not report["categories"]["ok"]
    assert report["categories"]["repartition"] == {"billing": 1, "technical": 1, "account": 0, "other": 1}


def test_les_quatre_categories_presentes_passent():
    tickets = [ticket(i, words(10, i)) for i in range(4)]
    report = gen.checks(tickets, {"t000": "billing", "t001": "technical", "t002": "account", "t003": "other"})
    assert report["categories"]["ok"]


def test_un_debut_de_phrase_repete_en_masse_est_signale():
    tickets = ([ticket(i, f"Bonjour, je vous écris {words(6, i)}") for i in range(5)]
               + [ticket(10 + i, words(9, 10 + i)) for i in range(5)])
    report = gen.checks(tickets, {t["id"]: "other" for t in tickets})
    assert not report["debuts"]["ok"]
    assert report["debuts"]["plus_frequent"] == ["bonjour je vous", 5]
    assert report["fins"]["ok"]


def test_une_fin_de_phrase_repetee_en_masse_est_signalee():
    tickets = ([ticket(i, f"{words(6, i)}. Merci d'avance !") for i in range(5)]
               + [ticket(10 + i, words(9, 10 + i)) for i in range(5)])
    report = gen.checks(tickets, {t["id"]: "other" for t in tickets})
    assert not report["fins"]["ok"]
    assert report["fins"]["plus_frequent"] == ["merci d avance", 5]
    assert report["debuts"]["ok"]


# --- passage dans le modèle d'origine ------------------------------------------------------------

SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
TRIAGE_PROMPT = "Classe ce ticket parmi billing, technical, account, other. Reponds uniquement par le mot.\n\nTicket: "
SPAM_PROMPT = json.loads((ROOT / "workflows/my-workflow-sandboxed.json").read_text())


def spam_system_prompt():
    node = next(n for n in SPAM_PROMPT["nodes"] if n["name"] == "Spam checker")
    return next(m["content"] for m in node["parameters"]["messages"]["values"] if m.get("role") == "system")


SPAM_INPUT = "Subject: FactureFrom: a@b.frMa facture est fausse"


class FakeModel:
    """Modèle d'origine simulé : répond « Billing. » au tri, « Spam » au détecteur, et garde ce qu'il reçoit."""

    def __init__(self):
        self.received = []

    def __call__(self, model, messages):
        self.received.append((model, messages))
        content = "Spam" if messages[0]["role"] == "system" else "Billing."
        return {"content": content, "finish_reason": "stop", "input_tokens": 50, "output_tokens": 2,
                "latency_ms": 321, "ts_start": "2026-11-17T10:00:00.000Z"}


def test_chaque_ticket_donne_un_evenement_de_tri_et_un_de_spam_au_contrat():
    tickets = [ticket(1, "Ma facture est fausse", subject="Facture", sender="a@b.fr"),
               ticket(2, "Je n'arrive plus à me connecter")]
    events = gen.build_events(tickets, FakeModel())
    assert len(events) == 4
    assert len({e["event_id"] for e in events}) == 4
    validator = jsonschema.Draft7Validator(SCHEMA)
    assert [err.message for e in events for err in validator.iter_errors(e)] == []
    assert {e["model"] for e in events} == {"gpt-4o-mini"}


def test_les_deux_consignes_sont_celles_des_workflows_de_test():
    model = FakeModel()
    events = gen.build_events([ticket(1, "Ma facture est fausse", subject="Facture", sender="a@b.fr")], model)
    triage = next(e for e in events if e["app_id"] == "support-ticket-triage")
    spam = next(e for e in events if e["app_id"] == "spam-checker")
    assert triage["request"]["system"] is None
    assert triage["request"]["messages"] == [{"role": "user", "content": TRIAGE_PROMPT + "Ma facture est fausse"}]
    assert spam["request"]["system"] == spam_system_prompt()
    # en production, le nœud Gmail (simple: false) rend les lignes d'en-tête brutes, que le nœud colle au corps
    assert spam["request"]["messages"] == [{"role": "user", "content": SPAM_INPUT}]
    assert [m for _, m in model.received] == [
        [{"role": "user", "content": TRIAGE_PROMPT + "Ma facture est fausse"}],
        [{"role": "system", "content": spam_system_prompt()},
         {"role": "user", "content": SPAM_INPUT}]]


def test_la_reponse_du_modele_d_origine_est_gardee_telle_quelle():
    events = gen.build_events([ticket(1, "Ma facture est fausse")], FakeModel())
    assert {e["app_id"]: e["response"]["content"] for e in events} == {
        "support-ticket-triage": "Billing.", "spam-checker": "Spam"}
    assert all(e["usage"]["input_tokens"] == 50 and e["latency_ms"] == 321 for e in events)


# --- le jeu enregistré ---------------------------------------------------------------------------

V2 = ROOT / "fixtures/dataset/v2"
recorded = pytest.mark.skipif(not (V2 / "events.jsonl").exists(),
                              reason="jeu v2 pas encore généré : make dataset-v2 (clé OpenAI requise, une seule fois)")


def load_v2():
    return gen.read_jsonl(V2 / "tickets.jsonl"), gen.read_jsonl(V2 / "events.jsonl")


@recorded
def test_le_jeu_enregistre_respecte_le_contrat_d_evenement():
    _, events = load_v2()
    validator = jsonschema.Draft7Validator(SCHEMA)
    assert [(e["event_id"], err.message) for e in events for err in validator.iter_errors(e)] == []
    assert len({e["event_id"] for e in events}) == len(events)


@recorded
def test_chaque_ticket_a_ses_deux_reponses_du_modele_d_origine():
    tickets, events = load_v2()
    assert 280 <= len(tickets) <= 320
    by_id = {e["event_id"]: e for e in events}
    for t in tickets:
        triage, spam = by_id[f"v2_{t['id']}_tri"], by_id[f"v2_{t['id']}_spam"]
        assert triage["request"]["messages"][-1]["content"] == TRIAGE_PROMPT + t["text"]
        assert spam["request"]["messages"][-1]["content"] == f"Subject: {t['subject']}From: {t['from']}{t['text']}"
        assert triage["model"] == spam["model"] == "gpt-4o-mini"
        assert triage["response"]["content"] and spam["response"]["content"]
    assert len(events) == 2 * len(tickets)


@recorded
def test_le_jeu_enregistre_passe_les_controles_de_fin_de_generation():
    tickets, events = load_v2()
    report = gen.checks(tickets, gen.triage_answers(events))
    assert {name: r for name, r in report.items() if not r["ok"]} == {}


@recorded
def test_aucune_cle_dans_le_jeu_enregistre():
    for path in V2.iterdir():
        assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", path.read_text()), path.name
