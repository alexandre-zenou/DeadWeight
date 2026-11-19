"""#43 / levier 05 : une mémoire de conversation qui ne se vide jamais (R20 endless_memory), bornée aux N
derniers échanges et prouvée par rejeu (bench.memory.prove : mêmes appels, même modèle, mémoire bornée,
comparés aux réponses d'origine avec un rejeu témoin à mémoire complète). Sans clé, non testé, comme
optimize.leviers.reasoning : jamais de score inventé. Toutes les mesures sont « mesuré » ou « non testé » :
l'estimation de la règle (evidence.est_saving_month_usd) n'est jamais reprise ici, donc jamais additionnée.
La clé de session par utilisateur est un conseil de correction (confidentialité), porté par le diff n8n et
le texte Slack, jamais un gain chiffré."""
from optimize.propose import MESURE, NON_TESTE, _m, _pct_change

VERDICTS = {"pass": "pass", "reject": "reject", "inconclusive": "inconclusive", "not_tested": "non_teste"}


def memory_proposal(finding, events, keys_available, prove_memory=None):
    if prove_memory is None:
        from bench.memory import prove as prove_memory
    from bench.memory import DEFAULT_WINDOW
    head = {"type": "memoire", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
            "model": finding["model"],
            # #45 : prévision de plantage de la règle, affichée telle quelle, jamais une mesure ni un gain
            "prevision": (finding.get("evidence") or {}).get("forecast")}
    if not keys_available:
        return {**head, "fenetre": DEFAULT_WINDOW,
                "changement": f"Borner la mémoire de conversation aux {DEFAULT_WINDOW} derniers échanges.",
                "verdict": "non_teste", "raisons": ["aucune clé pour le banc : rien de mesuré"],
                "mesures": {"precision": _m(None, NON_TESTE, "%")}}
    r = prove_memory(events, finding)
    window = r["window"]
    measured = r["agreement"] is not None
    gain = r["tokens_before"] is not None and r["tokens_after"] is not None
    cost = r["cost_before_usd"] is not None and r["cost_after_usd"] is not None
    return {
        **head, "fenetre": window,
        "changement": f"Borner la mémoire de conversation aux {window} derniers échanges.",
        "verdict": VERDICTS.get(r["verdict"], "reject"), "raisons": list(r["reasons"]), "preuve": r,
        "mesures": {
            "precision": _m(round(r["agreement"] * 100, 1), MESURE, "%") if measured else _m(None, NON_TESTE, "%"),
            "appels_rejoues": _m(r["n_replayed"], MESURE) if measured else _m(None, NON_TESTE),
            "jetons_envoyes": (_m(_pct_change(r["tokens_before"], r["tokens_after"]), MESURE, "%") if gain
                               else _m(None, NON_TESTE, "%")),
            "cout": (_m(_pct_change(r["cost_before_usd"], r["cost_after_usd"]), MESURE, "%") if cost
                     else _m(None, NON_TESTE, "%")),
        },
        # coût réel des appels mesurés, avant et après : base du total Slack (dollars, jamais des pourcentages)
        "cout_usd": ({"avant": r["cost_before_usd"], "apres": r["cost_after_usd"], "statut": MESURE}
                     if cost else None),
    }
