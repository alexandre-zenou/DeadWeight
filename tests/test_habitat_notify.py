"""Notification habitat : « non conclu » (ADR 0002) n'est ni un PASS ni un REJECTED, et n'offre aucun bouton."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("habitat_notify", ROOT / "habitat/notify.py")
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)

PROOF = {"verdict": "inconclusive", "agreement_rate": 1.0, "threshold": 0.95, "n_replayed": 12,
         "patch_id": "p_1", "reasons": ["4 textes distincts, minimum 30"]}


def test_inconclusive_is_labelled_and_offers_no_button():
    payload = notify.build(PROOF, json.loads((ROOT / "fixtures/finding.json").read_text()))
    text = json.dumps(payload, ensure_ascii=False)
    assert "NON CONCLU" in text and "4 textes distincts, minimum 30" in text
    assert "PASS" not in text and "REJECTED" not in text and "dw_apply" not in text


def test_pass_still_offers_the_apply_button():
    payload = notify.build({**PROOF, "verdict": "pass"}, {})
    assert "dw_apply" in json.dumps(payload)
