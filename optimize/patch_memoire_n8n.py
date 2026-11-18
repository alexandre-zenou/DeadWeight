"""Recette ``memoire`` sur un workflow n8n : borner la mémoire de conversation au nombre d'échanges prouvé
par rejeu (bench.memory), et remplacer une clé de session fixe par une clé par utilisateur.

Trois changements, chacun écrit dans les notes de la PR :
- chaque nœud mémoire (``memoryBufferWindow``, Postgres, Redis…) reçoit ``contextWindowLength`` = N : un
  agent ou une chaîne branché directement sur la mémoire ne lit plus que les N derniers échanges ;
- chaque nœud ``memoryManager`` en lecture (« Get Chat ») lit TOUT l'historique, sans tenir compte de la
  fenêtre (cas réel #40 : fenêtre par défaut, et pourtant 39 échanges renvoyés) : un nœud Limit (garder les N
  derniers éléments, un élément par échange) est inséré juste après lui ;
- une clé de session fixe (``sessionIdType`` = ``customKey`` et une valeur qui n'est pas une expression) fait
  partager la même conversation à tous les utilisateurs. Avec un déclencheur de chat, la clé vient de l'entrée
  (``fromInput``, l'identifiant de session du chat) ; avec un webhook, une expression lit ``body.sessionId``
  du webhook, à adapter au champ réellement envoyé : la note le dit. C'est une correction (confidentialité),
  pas un gain : elle n'entre dans aucune mesure.

Le dict d'origine n'est jamais modifié ; aucun appel LLM ici.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

MEMORY = "@n8n/n8n-nodes-langchain.memory"
NOT_A_STORE = {"@n8n/n8n-nodes-langchain.memoryManager", "@n8n/n8n-nodes-langchain.memoryChatRetriever"}
MANAGER = "@n8n/n8n-nodes-langchain.memoryManager"


def _is_workflow(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("connections"), dict)


def _memories(wf: dict) -> list[dict]:
    return [n for n in wf["nodes"] if str(n.get("type", "")).startswith(MEMORY) and n.get("type") not in NOT_A_STORE]


def _fixed_key(params: dict) -> str | None:
    key = params.get("sessionKey")
    if params.get("sessionIdType", "customKey") != "customKey" or not isinstance(key, str):
        return None
    return None if key.startswith("=") else key


def _per_user_key(wf: dict, node: dict, key: str) -> str:
    """Remplace la clé fixe si un déclencheur le permet ; rend la note de relecture."""
    params = node["parameters"]
    nodes = wf["nodes"]
    chat = next((n for n in nodes if str(n.get("type", "")).endswith("chatTrigger")), None)
    hook = next((n for n in nodes if str(n.get("type", "")).endswith(".webhook")), None)
    head = (f"« {node['name']} » : clé de session fixe « {key} », tous les utilisateurs partagent la même "
            "conversation (et la voient)")
    if chat:
        params["sessionIdType"] = "fromInput"
        params.pop("sessionKey", None)
        return head + f" ; remplacée par l'identifiant de session du chat (« {chat['name']} »)"
    if hook:
        params["sessionKey"] = f"={{{{ $('{hook['name']}').item.json.body.sessionId }}}}"
        return (head + f" ; remplacée par `body.sessionId` du webhook « {hook['name']} » : à adapter au champ "
                "qui identifie vraiment l'utilisateur (correction de confidentialité, pas un gain mesuré)")
    return head + " ; aucun déclencheur reconnu : remplacez-la par un identifiant par utilisateur"


def _limit_name(wf: dict, window: int) -> str:
    names = {n["name"] for n in wf["nodes"]}
    base = f"Garder les {window} derniers échanges"
    return next(name for name in (base if i == 0 else f"{base} ({i + 1})" for i in range(len(names) + 1))
                if name not in names)


def bound_memory(original: dict, window: int) -> tuple[dict, list[str]]:
    """Nouveau workflow borné à ``window`` échanges, et les notes pour la relecture."""
    wf = copy.deepcopy(original)
    conns = wf["connections"]
    notes = []
    for node in _memories(wf):
        params = node.setdefault("parameters", {})
        params["contextWindowLength"] = window
        notes.append(f"« {node['name']} » : fenêtre réglée à {window} échanges (contextWindowLength)")
        key = _fixed_key(params)
        if key is not None:
            notes.append(_per_user_key(wf, node, key))
    for node in [n for n in wf["nodes"] if n.get("type") == MANAGER]:
        params = node.get("parameters") or {}
        outs = (conns.get(node["name"]) or {}).get("main")
        if params.get("mode", "load") != "load" or not outs or not any(outs):
            continue
        if (params.get("options") or {}).get("groupMessages"):
            notes.append(f"« {node['name']} » lit tout l'historique en un seul élément (groupMessages) : "
                         f"à borner à la main aux {window} derniers échanges")
            continue
        name = _limit_name(wf, window)
        x, y = (node.get("position") or [0, 0])[:2]
        wf["nodes"].append({
            "parameters": {"maxItems": window, "keep": "lastItems"},
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"deadweight/memoire/{node['name']}")),
            "name": name, "type": "n8n-nodes-base.limit", "typeVersion": 1, "position": [x + 100, y + 160],
        })
        conns[name] = {"main": outs}
        conns[node["name"]]["main"] = [[{"node": name, "type": "main", "index": 0}]]
        notes.append(f"« {node['name']} » lit tout l'historique sans tenir compte de la fenêtre : « {name} » "
                     f"(Limit) ne garde que les {window} derniers échanges")
    return wf, notes


def _dump(data: dict, original_text: str) -> str:
    lines = original_text.splitlines()
    indent = len(lines[1]) - len(lines[1].lstrip(" ")) if len(lines) > 1 else None
    text = json.dumps(data, ensure_ascii="\\u" in original_text, indent=indent or None,
                      separators=None if indent else (",", ":"))
    return text + ("\n" if original_text.endswith("\n") else "")


def apply_memoire_n8n(repo: str | Path, proposal: dict[str, Any], files: list[Path]) -> list[str]:
    """Borne la mémoire dans chaque workflow n8n de ``files`` qui en a une (limité au workflow du constat si
    ``app_id`` est ``n8n:<workflow>/<nœud>`` et qu'il est dans le dépôt). Rend les notes de relecture."""
    window = proposal["fenetre"]
    found = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if _is_workflow(data) and _memories(data):
            found.append((path, text, data))
    app = str(proposal.get("app_id") or "")
    if app.startswith("n8n:"):
        wf_id = app[4:].split("/", 1)[0]
        found = [f for f in found if f[2].get("id") == wf_id] or found
    if not found:
        return [f"aucun workflow n8n avec une mémoire de conversation dans le dépôt : bornez la mémoire dans le "
                f"code (garder les {window} derniers échanges)"]
    notes = []
    for path, text, data in found:
        patched, file_notes = bound_memory(data, window)
        path.write_text(_dump(patched, text), encoding="utf-8")
        rel = path.relative_to(repo)
        notes += [f"{rel} — {n}" for n in file_notes]
    if len(found) > 1:
        notes.append(f"{len(found)} workflows ont une mémoire : vérifier que chacun relève bien de ce constat")
    return notes
