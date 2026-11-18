"""#33 : l'import n8n garde la réponse quand elle arrive par sortie structurée.

Agent n8n + « Structured Output Parser » : le modèle répond en appelant l'outil
format_final_json_response. n8n n'enregistre pas cet appel sur le nœud modèle (texte vide,
finish_reason = tool_calls) ; ses arguments sont l'entrée du nœud parser. Exécutions fabriquées.
"""
import json
from pathlib import Path

import jsonschema

from importers.n8n.convert import convert
from rules.structured_output import unwrap

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
LC = "@n8n/n8n-nodes-langchain."
FORMAT = "format_final_json_response"

WF = {
    "id": "wf-so", "name": "Resumes",
    "nodes": [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {"name": "Resumeur", "type": LC + "agent", "typeVersion": 2, "parameters": {"hasOutputParser": True}},
        {"name": "Modele", "type": LC + "lmChatOpenAi", "parameters": {"model": {"value": "gpt-4o"}}},
        {"name": "Parser", "type": LC + "outputParserStructured", "parameters": {}},
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Resumeur", "type": "main", "index": 0}]]},
        "Modele": {"ai_languageModel": [[{"node": "Resumeur", "type": "ai_languageModel", "index": 0}]]},
        "Parser": {"ai_outputParser": [[{"node": "Resumeur", "type": "ai_outputParser", "index": 0}]]},
    },
}


def _model_run(start, text, finish, took=1000):
    return {
        "startTime": start, "executionTime": took, "source": [{"previousNode": "Resumeur"}],
        "inputOverride": {"ai_languageModel": [[{"json": {
            "messages": ["System: Resume le texte en JSON\nHuman: un texte"], "options": {"model": "gpt-4o"}}}]]},
        "data": {"ai_languageModel": [[{"json": {
            "response": {"generations": [[{"text": text, "generationInfo": {"finish_reason": finish}}]]},
            "tokenUsage": {"promptTokens": 50, "completionTokens": 20, "totalTokens": 70}}}]]},
    }


def _parser_run(start, text, parsed=None):
    run = {"startTime": start, "executionTime": 0, "source": [{"previousNode": "Resumeur"}],
           "inputOverride": {"ai_outputParser": [[{"json": {"action": "parse", "text": text}}]]}}
    if parsed is None:
        run["error"] = {"message": "Model output doesn't fit required format"}
    else:
        run["data"] = {"ai_outputParser": [[{"json": {"action": "parse", "response": parsed}}]]}
    return run


def _execution(ex_id, runs):
    return {"id": ex_id, "status": "success", "data": {"resultData": {"runData": runs}}}


def _structured(ex_id, summary, start=1_800_000_000_000):
    args = json.dumps({"output": {"resume": summary}}, ensure_ascii=False)
    return _execution(ex_id, {
        "Modele": [_model_run(start, "", "tool_calls")],
        "Parser": [_parser_run(start + 1000, args, {"output": {"resume": summary}})],
    })


def test_la_sortie_structuree_devient_un_appel_d_outil():
    events, _ = convert(WF, [_structured("1", "premier resume")])
    [e] = events
    jsonschema.validate(e, SCHEMA)
    assert e["response"]["tool_calls"] == [{
        "id": None, "name": FORMAT, "arguments": json.dumps({"output": {"resume": "premier resume"}})}]
    assert e["response"]["finish_reason"] == "tool_calls"
    assert [t["name"] for t in e["request"]["tools"]] == [FORMAT]


def test_les_sorties_restent_distinctes_et_se_deplient():
    events, _ = convert(WF, [_structured(str(k), f"resume numero {k}", 1_800_000_000_000 + k * 60_000)
                             for k in range(5)])
    contents = [unwrap(e)["response"]["content"] for e in events]
    assert len(set(contents)) == 5
    assert json.loads(contents[2]) == {"resume": "resume numero 2"}


def test_reponse_texte_ordinaire_inchangee():
    """Le modèle répond en texte (stop) : le parser échoue dessus, rien n'est inventé."""
    start = 1_800_000_000_000
    ex = _execution("t", {"Modele": [_model_run(start, "pas du JSON", "stop")],
                          "Parser": [_parser_run(start + 1000, "pas du JSON")]})
    [e] = convert(WF, [ex])[0]
    jsonschema.validate(e, SCHEMA)
    assert e["response"]["content"] == "pas du JSON"
    assert e["response"]["tool_calls"] == [] and e["response"]["finish_reason"] == "stop"


def test_chaque_appel_recoit_sa_propre_sortie():
    """Deux tours dans la même exécution (boucle de reprise) : chaque parser va au dernier appel avant lui."""
    start = 1_800_000_000_000
    a = json.dumps({"output": {"resume": "a"}})
    b = json.dumps({"output": {"resume": "b"}})
    ex = _execution("2", {
        "Modele": [_model_run(start, "", "tool_calls"), _model_run(start + 5000, "", "tool_calls")],
        "Parser": [_parser_run(start + 1000, a, {"output": {"resume": "a"}}),
                   _parser_run(start + 6000, b, {"output": {"resume": "b"}})],
    })
    events = convert(WF, [ex])[0]
    assert [e["response"]["tool_calls"][0]["arguments"] for e in events] == [a, b]


def test_appel_d_outil_serialise_par_langchain():
    """Si n8n garde le message LangChain, ses tool_calls sont lus directement."""
    start = 1_800_000_000_000
    run = _model_run(start, "", "tool_calls")
    gen = run["data"]["ai_languageModel"][0][0]["json"]["response"]["generations"][0][0]
    gen["message"] = {"lc": 1, "type": "constructor", "id": ["langchain_core", "messages", "AIMessage"],
                      "kwargs": {"content": "", "tool_calls": [
                          {"id": "call_1", "name": "extract", "args": {"ville": "Paris"}, "type": "tool_call"}]}}
    wf = {**WF, "connections": {k: v for k, v in WF["connections"].items() if k != "Parser"}}
    [e] = convert(wf, [_execution("3", {"Modele": [run]})])[0]
    jsonschema.validate(e, SCHEMA)
    assert e["response"]["tool_calls"] == [{"id": "call_1", "name": "extract", "arguments": '{"ville": "Paris"}'}]
    assert e["request"]["tools"] == []
