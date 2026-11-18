"""Construction du jeu de test : echantillon d'un groupe (app_id x modele x gabarit
de prompt), comme le regroupement de rules.low_entropy._groups.

Chaque cas = les messages envoyes au modele d'origine + sa reponse, qui sert de
reference pour juger un candidat. Les appels en erreur ou sans reponse exploitable
sont exclus. Une reponse donnee par un appel d'outil (sortie JSON structuree d'n8n,
outil format_final_json_response, texte vide) est gardee : sa reference est l'etiquette
de rules.low_entropy.output_of, et le cas emporte les outils declares (#24).
Le tirage est deterministe (tri par hachage de l'event_id, pas par ordre
chronologique) : deux lancees sur le meme trafic produisent le meme jeu, et
l'echantillon n'est pas biaise vers une seule periode.
"""
import hashlib

from bench.models import BenchCase
from rules.low_entropy import output_kind, output_of, template_of

DEFAULT_MAX_CASES = 50


def _sample_key(event_id):
    return hashlib.sha1(event_id.encode('utf-8')).hexdigest()


def _usable_messages(event):
    """La conversation telle que le client l'a envoyée. Le prompt système est un champ à part
    du schéma d'événement (request.system) : sans lui, le candidat ne connaît pas la tâche."""
    request = event.get('request', {})
    messages = request.get('messages', [])
    turns = [{'role': m['role'], 'content': m.get('content') or ''}
             for m in messages if isinstance(m, dict) and m.get('role') in ('user', 'assistant', 'tool')]
    if not turns:
        return []
    system = request.get('system')
    return ([{'role': 'system', 'content': system}] if system else []) + turns


def _answered_by_tool(event):
    """Texte vide (None ou "") et appel d'outil qui repond directement a l'utilisateur, pas
    une etape de boucle d'agent (meme critere que la regle low_entropy_output)."""
    response = event.get('response')
    return isinstance(response, dict) and not response.get('content') and output_kind(event) == 'appel_outil'


def _reference(event):
    """L'etiquette output_of si l'origine a repondu par un outil, sinon le texte tel quel."""
    return output_of(event) if _answered_by_tool(event) else (event.get('response') or {}).get('content')


def build_test_cases(events, app_id, model, template=None, max_cases=DEFAULT_MAX_CASES):
    """events : liste au schema event v1 (dicts). Groupe filtre par app_id et model,
    et par gabarit si fourni (meme fonction que la regle low_entropy_output)."""
    group = []
    for event in events:
        if not isinstance(event, dict) or event.get('app_id') != app_id or event.get('model') != model:
            continue
        if event.get('error') is not None or _reference(event) is None:
            continue
        if template is not None and template_of(event) != template:
            continue
        if not _usable_messages(event):
            continue
        group.append(event)
    group.sort(key=lambda e: _sample_key(e['event_id']))

    cases = []
    for event in group[:max_cases]:
        usage = event.get('usage') or {}
        cases.append(BenchCase(
            event_id=event['event_id'],
            messages=tuple(_usable_messages(event)),
            reference=_reference(event),
            origin_input_tokens=usage.get('input_tokens'),
            origin_output_tokens=usage.get('output_tokens'),
            tools=tuple(event['request'].get('tools') or ()) if _answered_by_tool(event) else (),
        ))
    return cases
