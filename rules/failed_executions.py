"""R9 bis — failed_executions : des appels payés dont le résultat est perdu parce que l'exécution
du workflow plante ensuite.

Variante de paid_errors (#35). paid_errors voit les appels LLM qui échouent eux-mêmes ; ici chaque
appel a réussi (error = null), c'est l'exécution entière qui plante plus loin (un nœud aval, une
boucle qui casse) : tout ce qu'elle a payé avant est perdu. Seule une source qui connaît l'issue de
l'exécution remplit trace.status (import n8n) ; sans lui (passerelle), la règle ne dit rien.

Regroupement : par workflow. Les appels d'une exécution sont rangés sous plusieurs app_id (un par
nœud racine : « n8n:<workflow>/<nœud> ») ; deux exécutions qui partagent un app_id sont du même
workflow. Le constat porte le préfixe commun de ces app_id (« n8n:<workflow> »).

Seuils :
- MIN_EXECUTIONS = 10 : en dessous, un taux d'exécutions plantées ne veut rien dire.
- MIN_FAILED = 2 : un plantage isolé est un incident, pas un motif à corriger.
- MIN_FAILED_RATE = paid_errors.MIN_BILLED_FAILURE_RATE (5 %) : même raisonnement que paid_errors,
  au-delà d'une exécution sur vingt ce n'est plus ponctuel.

Chiffrage : report.cost.chiffrer sur les seuls appels facturés (output_tokens présent) des
exécutions plantées, jamais un forfait. Un appel qui a lui-même échoué sans être facturé ne coûte
rien et n'est pas compté.

Angle mort : une exécution peut planter à cause d'une mauvaise réponse du modèle (sortie mal
formée), auquel cas c'est l'appel, pas l'aval, qu'il faut corriger ; la règle ne tranche pas,
elle chiffre ce qui a été payé pour rien. proven=False.
"""
import hashlib
import json
import os
from collections import defaultdict

from report.cost import chiffrer
from rules import paid_errors

MIN_EXECUTIONS = 10
MIN_FAILED = 2
# lu par tests/test_finding_schema.py : le jeu passerelle n'a pas de trace.status, la règle s'y tait
SILENT_ON_GATEWAY = "trace.status vient de l'import n8n, absent des captures passerelle"


def _workflows(events):
    """Exécutions (trace.id) regroupées par workflow : deux exécutions qui partagent un app_id."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in events:
        a, b = find(("trace", e["trace"]["id"])), find(("app", e["app_id"]))
        parent[a] = b
    groups = defaultdict(list)
    for e in events:
        groups[find(("app", e["app_id"]))].append(e)
    return list(groups.values())


def _label(app_ids):
    """« n8n:<workflow> » : le préfixe commun des app_id, coupé au dernier « / »."""
    if len(app_ids) == 1:
        return app_ids[0]
    prefix = os.path.commonprefix(app_ids)
    head = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
    return head or max(app_ids, key=len)


def detect(events, pricing=None):
    known = [e for e in events if (e.get("trace") or {}).get("status") and (e["trace"].get("id"))]
    findings = []
    for evts in _workflows(known):
        status = {}
        for e in evts:
            status[e["trace"]["id"]] = e["trace"]["status"]
        lost = [e for e in evts if e["trace"]["status"] == "error" and e["usage"].get("output_tokens") is not None]
        failed = {e["trace"]["id"] for e in lost}
        rate = len(failed) / len(status)
        if len(status) < MIN_EXECUTIONS or len(failed) < MIN_FAILED or rate < paid_errors.MIN_BILLED_FAILURE_RATE:
            continue
        app = _label(sorted({e["app_id"] for e in evts}))
        model = ", ".join(sorted({e["model"] for e in lost}))
        cost = chiffrer(lost, pricing)
        digest = hashlib.sha256(json.dumps([app, "failed_executions"], ensure_ascii=False).encode()).hexdigest()[:20]
        findings.append({
            "finding_id": f"f_{digest}_failed_executions",
            "rule": "failed_executions",
            "app_id": app,
            "model": model,
            "template": None,
            "severity": "trim",
            "title": (f"{len(failed)} exécutions sur {len(status)} ont planté après avoir payé {len(lost)} appels : "
                      "leur résultat est perdu."),
            "proven": False,
            "event_ids": sorted(e["event_id"] for e in lost),
            "evidence": {
                "executions": len(status),
                "failed_executions": len(failed),
                "failed_execution_rate": round(rate, 3),
                "calls": len(evts),
                "lost_calls": len(lost),
                "est_lost_cost_month_usd": cost["cout_mensuel_usd"],
                "lost_cost_missing": cost["manquants"],
            },
        })
    return findings
