"""#35 : une exécution n8n qui plante après des appels LLM réussis a payé pour rien.

L'import reporte le statut de l'exécution sur ses événements (trace.status, facultatif) sans
toucher à `error`, qui reste l'erreur de l'appel LLM lui-même. La règle failed_executions chiffre
les appels payés dans des exécutions qui ont échoué ensuite. Exécutions fabriquées, sans réseau.
"""
import json
from pathlib import Path

import jsonschema

from importers.n8n.convert import convert
from report.audit import build_report, render_html
from rules import failed_executions, paid_errors

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
LC = "@n8n/n8n-nodes-langchain."

WF = {
    "id": "wf-fe", "name": "Fiches",
    "nodes": [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {"name": "Redacteur", "type": LC + "chainLlm", "parameters": {}},
        {"name": "Relecteur", "type": LC + "chainLlm", "parameters": {}},
        {"name": "Modele", "type": LC + "lmChatOpenAi", "parameters": {"model": {"value": "gpt-4o"}}},
        {"name": "Modele relecture", "type": LC + "lmChatOpenAi", "parameters": {"model": {"value": "gpt-4o"}}},
        {"name": "Envoi", "type": "n8n-nodes-base.httpRequest", "parameters": {}},
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Redacteur", "type": "main", "index": 0}]]},
        "Redacteur": {"main": [[{"node": "Relecteur", "type": "main", "index": 0}]]},
        "Relecteur": {"main": [[{"node": "Envoi", "type": "main", "index": 0}]]},
        "Modele": {"ai_languageModel": [[{"node": "Redacteur", "type": "ai_languageModel", "index": 0}]]},
        "Modele relecture": {"ai_languageModel": [[{"node": "Relecteur", "type": "ai_languageModel", "index": 0}]]},
    },
}


def _model_run(root, start, text):
    return {
        "startTime": start, "executionTime": 800, "source": [{"previousNode": root}],
        "inputOverride": {"ai_languageModel": [[{"json": {
            "messages": [f"System: consigne {root}\nHuman: texte {start}"], "options": {"model": "gpt-4o"}}}]]},
        "data": {"ai_languageModel": [[{"json": {
            "response": {"generations": [[{"text": text, "generationInfo": {"finish_reason": "stop"}}]]},
            "tokenUsage": {"promptTokens": 400, "completionTokens": 150, "totalTokens": 550}}}]]},
    }


def _execution(k, status, reviews=2):
    """Une rédaction puis `reviews` relectures ; en erreur, le nœud d'envoi plante ensuite."""
    start = 1_800_000_000_000 + k * 3_600_000
    runs = {"Modele": [_model_run("Redacteur", start, f"fiche {k}")],
            "Modele relecture": [_model_run("Relecteur", start + 1000 * (i + 1), f"note {k}-{i}")
                                 for i in range(reviews)]}
    ex = {"id": str(k), "status": status, "data": {"resultData": {"runData": runs}}}
    if status == "error":
        ex["data"]["resultData"]["error"] = {"name": "NodeOperationError", "message": "plantage aval"}
    return ex


def _workflow(n=30, failed=12, reviews=2, first_id=0):
    """Les identifiants d'exécution n8n sont uniques sur une instance, tous workflows confondus."""
    return [_execution(first_id + k, "error" if k < failed else "success", reviews) for k in range(n)]


# --- import : le statut de l'exécution arrive sur les événements -------------------------------

def test_le_statut_de_l_execution_est_reporte_sans_toucher_a_error():
    events, _ = convert(WF, [_execution(1, "error"), _execution(2, "success")])
    assert len(events) == 6
    for e in events:
        jsonschema.validate(e, SCHEMA)
        assert e["error"] is None and e["http_status"] == 200  # l'appel LLM, lui, a réussi
    assert {e["trace"]["status"] for e in events if e["trace"]["id"] == "n8n-1"} == {"error"}
    assert {e["trace"]["status"] for e in events if e["trace"]["id"] == "n8n-2"} == {"success"}


def test_crashed_compte_comme_une_erreur_et_un_statut_inconnu_est_omis():
    crashed, running, absent = _execution(1, "crashed"), _execution(2, "running"), _execution(3, "success")
    del absent["status"]
    events, _ = convert(WF, [crashed, running, absent])
    by_trace = {e["trace"]["id"]: e["trace"] for e in events}
    assert by_trace["n8n-1"]["status"] == "error"
    assert "status" not in by_trace["n8n-2"] and "status" not in by_trace["n8n-3"]
    for e in events:
        jsonschema.validate(e, SCHEMA)


def test_le_schema_accepte_un_evenement_sans_statut():
    gateway = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
    assert "status" not in gateway["trace"]
    jsonschema.validate(gateway, SCHEMA)


def test_le_bilan_compte_les_executions_en_erreur():
    _, stats = convert(WF, _workflow(n=5, failed=2))
    assert stats.as_dict()["executions_en_erreur"] == 2


# --- règle : appels payés dans des exécutions plantées ----------------------------------------

def test_douze_executions_sur_trente_plantees_apres_avoir_paye():
    events, _ = convert(WF, _workflow())
    [f] = failed_executions.detect(events)
    assert f["rule"] == "failed_executions" and f["proven"] is False
    assert f["app_id"] == "n8n:Fiches" and f["model"] == "gpt-4o"
    ev = f["evidence"]
    assert ev["executions"] == 30 and ev["failed_executions"] == 12
    assert ev["lost_calls"] == 36 and ev["calls"] == 90
    assert ev["est_lost_cost_month_usd"] > 0
    assert len(f["event_ids"]) == 36
    assert all(e["trace"]["status"] == "error" for e in events if e["event_id"] in set(f["event_ids"]))
    assert "12 exécutions sur 30 ont planté après avoir payé 36 appels" in f["title"]
    jsonschema.validate(f, json.loads((ROOT / "schemas/finding.schema.json").read_text()))


def test_un_plantage_isole_n_est_pas_un_motif():
    events, _ = convert(WF, _workflow(failed=1))
    assert failed_executions.detect(events) == []


def test_trop_peu_d_executions_pour_parler_de_taux():
    events, _ = convert(WF, _workflow(n=6, failed=3))
    assert failed_executions.detect(events) == []


def test_un_appel_sans_jetons_factures_n_est_pas_compte():
    executions = _workflow()
    for ex in executions[:12]:  # le modèle de relecture tombe en erreur, rien de facturé
        for run in ex["data"]["resultData"]["runData"]["Modele relecture"]:
            del run["data"]
            run["error"] = {"message": "overloaded", "httpCode": 529}
    events, _ = convert(WF, executions)
    [f] = failed_executions.detect(events)
    assert f["evidence"]["lost_calls"] == 12


def test_deux_workflows_donnent_deux_constats():
    other = {**WF, "id": "wf-2", "name": "Autre"}
    events = convert(WF, _workflow())[0] + convert(other, _workflow(first_id=100))[0]
    found = failed_executions.detect(events)
    assert sorted(f["app_id"] for f in found) == ["n8n:Autre", "n8n:Fiches"]
    assert len({f["finding_id"] for f in found}) == 2


def test_passerelle_sans_statut_rien_ne_change():
    gateway = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
    assert failed_executions.detect(gateway) == []
    assert all(not paid_errors._is_billed_failure(e) for e in convert(WF, _workflow())[0])


def test_le_rapport_l_affiche_sans_jargon():
    events, _ = convert(WF, _workflow())
    report = build_report(events)
    [c] = [c for c in report["constats"] if c["regle"] == "failed_executions"]
    assert c["chiffres"]["nb_appels"] == 36
    html = render_html(report)
    assert "failed_executions" not in html
    assert "planté après avoir payé" in html
