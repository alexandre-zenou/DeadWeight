"""Proposer, tester, chiffrer, préparer la micro-PR et le message Slack. Hors ligne (aucune clé)."""
import json
import subprocess
from pathlib import Path

import pytest

from optimize.patch import make_patch, pr_text
from optimize.propose import MESURE, propose
from optimize.slack import LEGEND, message

# preuve « prouvé » attendue sur le jeu v1 : minimum abaissé (cf. tests/conftest.py, #7)
pytestmark = pytest.mark.usefixtures("minimum_v1")

ROOT = Path(__file__).resolve().parents[1]
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()
          if line.strip()]


@pytest.fixture(scope="module")
def proposals(minimum_v1):
    return propose(EVENTS)


def test_proven_rules_are_measured_on_the_history(proposals):
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    assert triage["verdict"] == "pass"
    m = triage["mesures"]
    assert m["precision"] == {"valeur": 100.0, "statut": MESURE, "unite": "%"}
    assert m["latence_mediane"]["statut"] == MESURE and m["latence_mediane"]["valeur"] < -90
    assert m["cout"]["valeur"] < 0
    # jetons envoyés : mesurés au rejeu (0 jeton pour les entrées couvertes par une règle), plus
    # d'estimation par taux de couverture (D : plus de « ~ » sur cette figure).
    assert m["jetons_envoyes"]["statut"] == MESURE and "hypothese" not in m["jetons_envoyes"]
    assert m["jetons_envoyes"]["valeur"] < 0
    assert triage["cout_usd"]["apres"] < triage["cout_usd"]["avant"]
    # latence brute (ms) : pour l'affichage quand le pourcentage seul ressemble à un bug (-100 %)
    assert triage["latence_ms"]["avant"] > triage["latence_ms"]["apres"] >= 0
    assert triage["latence_ms"]["statut"] == MESURE


def test_without_a_key_a_model_swap_is_not_tested_never_guessed(proposals):
    swaps = [p for p in proposals if p["type"] == "modele"]
    assert swaps and all(p["verdict"] == "non_teste" and p["mesures"]["precision"]["valeur"] is None for p in swaps)


def test_slack_shows_raw_ms_for_minus_100_percent_latency(proposals):
    """Même bascule que le tableau du testeur (scripts.tester_ui.latency_cell) : « X ms → Y ms »
    plutôt qu'un « -100 % » qui ressemble à un bug."""
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    assert triage["mesures"]["latence_mediane"]["valeur"] == -100.0
    text = message(proposals, total_spent=1.0)
    assert "latence médiane -100%" not in text.replace(" ", "")
    ms = triage["latence_ms"]
    assert f"{ms['avant']:.0f} ms → {ms['apres']:.0f} ms" in text


def test_slack_totals_only_proven_measured_gains(proposals):
    text = message(proposals, total_spent=1.0)
    n_pass = sum(p["verdict"] == "pass" for p in proposals)
    assert f"{n_pass} optimisation" in text and "100 % minimum" in text
    assert "précision +" not in text                      # un niveau, pas une variation
    assert "~" in text                                    # les estimations restent marquées
    body = text.replace(LEGEND, "")  # la légende cite les trois icônes ; le corps ne montre que les gains
    assert body.count("✅") == sum(p["verdict"] == "pass" for p in proposals)
    assert "⛔" not in body and "◻️" not in body and "page développeur" in text  # un décideur ne voit que les gains


def test_slack_line_states_the_per_task_gain_in_order_and_its_share_of_total(proposals):
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    total = triage["cout_usd"]["avant"]  # dépense totale = celle de cette seule tâche ici : part = 100 %
    text = message(proposals, total_spent=total)
    lines = text.splitlines()
    # "mail-triage" a aussi une proposition "cache" (R8) désormais : la ligne cherchée se distingue
    # par le début de son texte, propre à _rules (optimize.propose).
    i = next(i for i, line_ in enumerate(lines) if "mail-triage" in line_ and "Remplacer les appels" in line_)
    detail = lines[i + 1]
    assert "Pour cette tâche : contexte envoyé" in detail
    # ordre imposé : contexte envoyé, coût, latence médiane, précision
    assert detail.index("contexte envoyé") < detail.index("coût") < detail.index("latence médiane") \
        < detail.index("précision")
    assert "% de la dépense totale" in text


def test_demo_mode_and_dev_page_show_everything(proposals):
    from optimize.devpage import render
    assert "⛔" in message(proposals, show_all=True)
    page = render(proposals)
    assert page.count('class="card"') == len(proposals) and "Refusée" in page and "Non testée" in page


def test_inconclusive_proposal_has_its_own_label_and_is_not_counted_as_proven(proposals):
    """ADR 0002 : « non conclu » n'est ni prouvé ni refusé ; il ne compte pas dans les gains."""
    from optimize.devpage import render
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    fake = {**triage, "verdict": "inconclusive", "raisons": ["trop peu de textes distincts (3 sur 20)"]}
    page = render([fake])
    assert "Non conclue" in page and "Prouvée" not in page and "0 prouvée sur 1" in page
    demo = message([fake], show_all=True)
    assert "❔ *mail-triage*" in demo and "trop peu de textes distincts" in demo and "✅ *" not in demo
    assert "0 optimisation prouvée" in demo
    hidden = message([triage, fake]).replace(LEGEND, "")
    assert "1 non conclue, 0 rejetée" in hidden



def test_dev_page_shows_the_by_heart_alert_and_the_distinct_texts_replayed(proposals):
    """ADR 0002 : la page développeur montre les règles signalées par-cœur et le nombre de textes distincts."""
    from optimize.devpage import render
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    proof = {**triage["preuve"], "n_replayed": 397, "n_distinct": 64, "memorized_rules": [
        {"category": "facture", "alternative": "le montant a doublé"},
        {"category": "support", "alternative": "page blanche", "example": "Bonjour, page blanche <b>"}]}
    page = render([{**triage, "preuve": proof}])
    assert "397 appels rejoués, 64 textes distincts" in page
    assert "par-cœur" in page and "le montant a doublé" in page and "facture" in page
    assert "Bonjour, page blanche &lt;b&gt;" in page  # l'exemple recopié, échappé
    assert "Prouvée" in page  # signalé, le verdict ne change pas
    plain = render([{**triage, "preuve": {**proof, "memorized_rules": []}}])
    assert "par-cœur" not in plain and "64 textes distincts" in plain

def _repo(tmp_path):
    repo = tmp_path / "client"
    repo.mkdir()
    (repo / "app.py").write_text(
        'client = OpenAI(default_headers={"x-deadweight-app": "mail-triage"})\n'
        'r = client.chat.completions.create(model="gpt-4o", messages=m)\n')
    (repo / ".env.example").write_text("OPENAI_API_KEY=\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                                               "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


def test_rules_patch_touches_no_code_and_is_reversible(proposals, tmp_path):
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    diff, notes = make_patch(_repo(tmp_path), triage)
    assert "deadweight/preuves/proof-mail-triage.json" in diff and "+GATEWAY_SHORTCIRCUIT=deadweight/preuves" in diff
    assert "app.py" not in diff and notes == []
    title, body = pr_text(triage, notes)
    assert title.startswith("Deadweight : ") and "| precision | 100.0 % | mesuré |" in body


def test_patch_survives_broken_symlinks_in_the_client_repo(proposals, tmp_path):
    """Un vrai dépôt (workflow de Miguel) contient des liens vers des médias absents : la copie ne doit pas échouer."""
    repo = _repo(tmp_path)
    (repo / "assets").symlink_to(tmp_path / "medias-absents")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "lien"], cwd=repo, check=True)
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    diff, _ = make_patch(repo, triage)
    assert "deadweight/preuves/proof-mail-triage.json" in diff and "assets" not in diff
    assert (repo / "assets").is_symlink()  # le dépôt du client n'est pas touché


def test_model_and_cap_patches(tmp_path):
    repo = _repo(tmp_path)
    swap = {"type": "modele", "app_id": "mail-triage", "model": "gpt-4o", "nouveau_modele": "gpt-4o-mini"}
    diff, notes = make_patch(repo, swap)
    assert '-r = client.chat.completions.create(model="gpt-4o"' in diff and '+r = client.chat.completions.create(model="gpt-4o-mini"' in diff
    cap = {"type": "plafond", "app_id": "mail-triage", "plafond": 300}
    diff, _ = make_patch(repo, cap)
    assert "chat.completions.create(max_tokens=300, model=" in diff


def test_slack_latence_mediane_a_moins_100_affichee_en_millisecondes():
    from optimize.slack import _line
    p = {"verdict": "pass", "app_id": "mail-triage", "changement": "Règles.", "raisons": [],
         "mesures": {"latence_mediane": {"valeur": -100.0, "statut": "mesuré", "unite": "%"}},
         "latence_ms": {"avant": 633.2, "apres": 0.004, "statut": "mesuré"}}
    line = _line(p, None)
    assert "latence médiane 633 ms → 0 ms" in line
    assert "-100" not in line


def test_slack_legend_first_and_no_pr_promise_without_diff(proposals):
    lines = message(proposals, total_spent=1.0).splitlines()
    assert lines[1] == LEGEND
    text = "\n".join(lines)
    assert "acceptant sa micro-PR" not in text and "--repo <dossier>" in text
    assert "diff et le texte" in message(proposals, total_spent=1.0, with_diffs=True)
    assert "acceptant sa micro-PR" in message(proposals, {proposals[0]["finding_id"] + proposals[0]["type"]: "u"})


def test_slack_unproven_collapsed_in_one_line_even_in_demo(proposals):
    text = message(proposals, total_spent=1.0, show_all=True)
    assert text.count("⛔ *") == 0 and text.count("◻️ *") == 0 and "autres pistes" in text


def test_slack_quoi_changer_for_changes_without_diff():
    from optimize.slack import quoi_changer
    assert "max_tokens=120" in quoi_changer({"type": "plafond", "plafond": 120, "model": "gpt-4o"})
    assert 'reasoning_effort="low"' in quoi_changer({"type": "raisonnement", "model": "o4-mini", "preuve": {"effort": "low"}})
    assert "cache_control" in quoi_changer({"type": "cache_prompt", "model": "claude-sonnet-4-5"})
    assert "automatiquement" in quoi_changer({"type": "cache_prompt", "model": "gpt-4o"})
    assert quoi_changer({"type": "regles", "model": "gpt-4o"}) is None
