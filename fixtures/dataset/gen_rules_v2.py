"""T7 (#10) : règles d'aiguillage écrites une fois sur le jeu v2, et workflows d'exemple corrigés régénérés.

Deux étapes :

1. Extraction (une seule fois, quelques centimes, DW_LLM_API_KEY de .env.local) : pour chaque constat
   ``low_entropy_output`` du jeu v2, DeadWeight écrit ses règles avec le même LLM que l'optimiseur
   (``optimize.__main__.RULES_MODEL``) ; elles sont enregistrées dans ``v2/rules.json``. La preuve
   (``tests/test_preuves_v2.py``) les rejoue ensuite sans réseau.
2. Workflows (déterministe, sans clé) : les deux workflows d'exemple corrigés sont reconstruits à partir
   des règles enregistrées, avec ``optimize.patch_n8n.build_patched_workflow``. Un workflow n'est corrigé
   que si sa preuve passe ; sinon le fichier corrigé est retiré (DeadWeight ne propose rien).

    python3 fixtures/dataset/gen_rules_v2.py              # extraction puis workflows
    python3 fixtures/dataset/gen_rules_v2.py --workflows  # workflows seulement, depuis v2/rules.json

Jamais lancé par la CI.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from optimize.__main__ import RULES_MODEL  # noqa: E402
from optimize.patch_n8n import build_patched_workflow  # noqa: E402
from proof.extract import OpenAICompatibleLLM, extract_rules  # noqa: E402
from proof.replay import replay  # noqa: E402
from rules.low_entropy import detect  # noqa: E402

V2 = Path(__file__).resolve().parent / "v2"
EVENTS = V2 / "events.jsonl"
RULES = V2 / "rules.json"

# app_id du jeu v2 -> workflow d'exemple, nœud remplacé, workflow corrigé
WORKFLOWS = {
    "support-ticket-triage": ("workflows/support-ticket-triage.json", "Classify ticket",
                              "workflows/support-ticket-triage-patched-by-deadweight.json"),
    "spam-checker": ("workflows/my-workflow-sandboxed.json", "Spam checker",
                     "workflows/my-workflow-sandboxed-patched-by-deadweight.json"),
}


def load_events():
    return [json.loads(line) for line in EVENTS.read_text(encoding="utf-8").splitlines() if line.strip()]


def findings_by_app(events):
    return {f["app_id"]: f for f in detect(events)}


def extract(llm):
    events = load_events()
    recorded = {}
    for app_id, finding in sorted(findings_by_app(events).items()):
        rules = extract_rules(finding, events, llm)
        recorded[app_id] = rules
        proof = replay(finding, events, rules)
        print(f"{app_id}: {rules['method']}, {len(rules['categories'])} catégorie(s), "
              f"verdict {proof['verdict']}, accord {proof['agreement_rate']:.1%} sur "
              f"{proof['n_distinct_replaced']} textes distincts, "
              f"{len(proof['memorized_rules'])} règle(s) par-cœur")
    RULES.write_text(json.dumps(recorded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {RULES.relative_to(ROOT)}")


def regenerate_workflows():
    events = load_events()
    findings = findings_by_app(events)
    recorded = json.loads(RULES.read_text(encoding="utf-8"))
    for app_id, (source, node, target) in WORKFLOWS.items():
        finding, rules = findings[app_id], recorded[app_id]
        proof = replay(finding, events, rules)
        out = ROOT / target
        if proof["verdict"] != "pass":
            out.unlink(missing_ok=True)
            print(f"{app_id}: {proof['verdict']}, aucun workflow corrigé")
            continue
        original = json.loads((ROOT / source).read_text(encoding="utf-8"))
        patched = build_patched_workflow(original, node, rules, finding["model"])
        out.write_text(json.dumps(patched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{app_id}: prouvé, → {target}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workflows", action="store_true", help="workflows seulement, depuis v2/rules.json")
    args = ap.parse_args(argv)
    if not args.workflows:
        key = os.environ.get("DW_LLM_API_KEY")
        if not key:
            print("DW_LLM_API_KEY manquante (.env.local)", file=sys.stderr)
            return 2
        extract(OpenAICompatibleLLM(os.environ.get("DW_LLM_BASE_URL", "https://api.openai.com/v1"), key,
                                    os.environ.get("DW_RULES_MODEL", RULES_MODEL)))
    regenerate_workflows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
