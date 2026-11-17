"""Enregistrement et rejeu des reponses fournisseurs (vcrpy via pytest-recording).

Un test marque @pytest.mark.vcr rejoue sa cassette dans tests/cassettes/.
Par defaut (make test, CI) : rejeu seul, aucun appel reseau, aucune cle.
Pour enregistrer : make record (lit les cles de .env.local).

Les cles ne sont jamais ecrites dans une cassette : en-tetes d'auth et
parametre ?key= de Gemini sont retires avant l'ecriture.
"""
import os

import pytest

SECRET_HEADERS = ["authorization", "x-api-key", "x-goog-api-key", "openai-organization", "openai-project"]
SECRET_RESPONSE_HEADERS = {"openai-organization", "openai-project", "set-cookie"}


def scrub_response(response):
    # une erreur n'est jamais enregistree : rejouee, elle ferait echouer le test pour toujours,
    # et le corps d'une 401 recopie la cle fautive ("Incorrect API key provided: sk-...")
    if response.get("status", {}).get("code", 200) >= 400:
        return None
    headers = response.get("headers", {})
    for name in list(headers):
        if name.lower() in SECRET_RESPONSE_HEADERS:
            del headers[name]
    return response


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": SECRET_HEADERS,
        "filter_query_parameters": ["key"],
        "before_record_response": scrub_response,
        "decode_compressed_response": True,
    }


@pytest.fixture(scope="module")
def vcr_cassette_dir():
    return os.path.join(os.path.dirname(__file__), "cassettes")


@pytest.fixture(autouse=True)
def _fake_keys(monkeypatch):
    # en rejeu, les SDK exigent une cle : une fausse suffit, la cassette repond
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        if not os.environ.get(var):
            monkeypatch.setenv(var, "test-key")


# Jeu v1 et preuve sur textes distincts (#7, ADR 0002) : mail-triage n'y garde que 26 textes distincts
# remplacés, sous le minimum de 30 ; il passe « non conclu ». Les tests des modules qui ont besoin d'une
# preuve « prouvé » sur v1 abaissent le minimum, comme DW_MIN_CALLS pour une démo sur peu de données.
MIN_REPLAY_V1 = 25


@pytest.fixture(scope="module")
def minimum_v1():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("proof.replay.MIN_REPLAY", MIN_REPLAY_V1)
        yield
