"""Jeu de test v2 (#5) : ~300 tickets de support variés, avec les réponses du modèle d'origine.

Deux étapes, chacune faite une seule fois (relancer reprend où on s'était arrêté, sans repayer) :
  1. un LLM écrit les tickets à partir de consignes tirées au hasard (graine fixe) → v2/tickets.jsonl ;
  2. chaque ticket passe une fois dans le modèle d'origine sous les deux consignes → v2/events.jsonl.
Les contrôles (jumeaux, longueurs, catégories, débuts et fins répétés) sont affichés à la fin.

    OPENAI_API_KEY=... python3 fixtures/dataset/gen_dataset_v2.py   # ou : make dataset-v2

Jamais lancé par la CI : les tests lisent le jeu enregistré dans v2/.
"""
import json
import os
import random
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "v2"
CATEGORIES = ("billing", "technical", "account", "other")
ORIGIN_MODEL = "gpt-4o-mini"  # modèle d'origine des deux workflows de test
WRITER_MODEL = os.environ.get("DW_V2_WRITER_MODEL", "gpt-4o-mini")  # écrit les tickets ; un plus gros modèle : quelques dizaines de centimes
N_TICKETS, BATCH, SEED = 300, 10, 2026

# Consignes recopiées des workflows de test (workflows/support-ticket-triage.json, et le nœud « Spam checker » de
# workflows/my-workflow.json, identique dans my-workflow-sandboxed.json), fautes comprises : le modèle d'origine doit recevoir exactement ce qu'il reçoit en production.
TRIAGE_APP, SPAM_APP = "support-ticket-triage", "spam-checker"
TRIAGE_PROMPT = "Classe ce ticket parmi billing, technical, account, other. Reponds uniquement par le mot.\n\nTicket: "
SPAM_PROMPT = (
    "You are a e-mail assistant. You have to check if the received e-mail are spam or not.\n"
    "You have to check not only normal spam, but everything is not sent from a person, for example, automatic "
    "e-mail, google email, and anything out of a possible client.\n\n"
    "If an e-mail is considered spam, as I sayd befor, your output will be \"spam\". If not, say \"no spam\".\n\n"
    "Don't respond anything else \"spam\" or \"not spam\".")

# --- jumeaux (GLOSSARY.md) -----------------------------------------------------------------------

MONTHS = ("janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre "
          "janv fev avr juil sept oct nov dec").split()
GREETINGS = r"(?:bonjour|bonsoir|salut|hello|coucou|madame|monsieur|messieurs|mesdames|cher|chere|a tous|a l equipe)"
SIGNOFFS = (r"(?:merci(?: beaucoup| bien| d avance| par avance| pour votre aide| de votre aide| de votre retour)?"
            r"|cordialement|bien cordialement|bien a vous|salutations|bonne journee|bonne soiree|a bientot"
            r"|dans l attente de votre retour|en vous remerciant)")


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]|_|\d", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """Forme d'un texte sans politesse de début et de fin, chiffres, mois ni ponctuation."""
    words = [w for w in _plain(text).split() if w not in MONTHS]
    text = " ".join(words)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(rf"^(?:{GREETINGS}\b\s*)+", "", text).strip()
        text = re.sub(rf"(?:\s*\b{SIGNOFFS})+$", "", text).strip()
    return text


# --- contrôles de fin de génération --------------------------------------------------------------

SHORT_WORDS, LONG_WORDS = 25, 80   # court < 25 mots, long > 80 mots
MIN_BUCKET_SHARE = 0.15            # chaque tranche de longueur pèse au moins 15 % du jeu
EDGE_WORDS = 3                     # début et fin de ticket comparés sur leurs trois premiers / derniers mots
MAX_EDGE_SHARE = 0.10              # un même début (ou une même fin) dans plus de 10 % des tickets : répété en masse

def checks(tickets: list[dict], triage: dict[str, str]) -> dict:
    by_form = defaultdict(list)
    for t in tickets:
        by_form[normalize(t["text"])].append(t["id"])
    twins = [ids for ids in by_form.values() if len(ids) > 1]

    buckets = {"court": 0, "moyen": 0, "long": 0}
    for t in tickets:
        n = len(t["text"].split())
        buckets["court" if n < SHORT_WORDS else "long" if n > LONG_WORDS else "moyen"] += 1
    varied = all(count >= MIN_BUCKET_SHARE * len(tickets) for count in buckets.values())

    categories = {c: 0 for c in CATEGORIES}
    for answer in triage.values():
        key = _plain(answer or "")
        if key in categories:
            categories[key] += 1

    return {"jumeaux": {"ok": not twins, "groupes": twins},
            "longueurs": {"ok": varied, "repartition": buckets},
            "categories": {"ok": all(categories.values()), "repartition": categories},
            "debuts": _repeated(tickets, slice(None, EDGE_WORDS)),
            "fins": _repeated(tickets, slice(-EDGE_WORDS, None))}


def _repeated(tickets: list[dict], edge: slice) -> dict:
    counts = Counter(" ".join(_plain(t["text"]).split()[edge]) for t in tickets)
    top, n = counts.most_common(1)[0] if counts else ("", 0)
    return {"ok": n <= MAX_EDGE_SHARE * len(tickets), "plus_frequent": [top, n]}


# --- passage dans le modèle d'origine ------------------------------------------------------------

def triage_messages(t: dict) -> list[dict]:
    """Nœud chainLlm du tri : un seul message utilisateur, consigne puis ticket."""
    return [{"role": "user", "content": TRIAGE_PROMPT + t["text"]}]


def spam_messages(t: dict) -> list[dict]:
    """Nœud OpenAI du détecteur : consigne système, puis `headers.subject`, `headers.from` et le corps collés.

    En production, le nœud Gmail (get, simple: false) rend les lignes d'en-tête brutes (« Subject: … »).
    """
    return [{"role": "system", "content": SPAM_PROMPT},
            {"role": "user", "content": f"Subject: {t['subject']}From: {t['from']}{t['text']}"}]


def build_events(tickets: list[dict], call) -> list[dict]:
    """Passe chaque ticket une fois sous chaque consigne. `call(model, messages)` rend la réponse brute."""
    events = []
    for t in tickets:
        for app, suffix, messages in ((TRIAGE_APP, "tri", triage_messages(t)), (SPAM_APP, "spam", spam_messages(t))):
            answer = call(ORIGIN_MODEL, messages)
            events.append(_event(f"v2_{t['id']}_{suffix}", app, messages, answer))
    return events


FINISH = {"stop", "length", "tool_calls", "content_filter"}  # valeurs du contrat ; le reste devient « other »


def _event(event_id: str, app: str, messages: list[dict], answer: dict) -> dict:
    start = datetime.fromisoformat(answer["ts_start"].replace("Z", "+00:00"))
    end = start + timedelta(milliseconds=answer["latency_ms"])
    system = "\n".join(m["content"] for m in messages if m["role"] == "system") or None
    return {
        "schema_version": "1",
        "event_id": event_id,
        "trace": {"id": None, "source": None, "step": None},
        "app_id": app,
        "ts_start": _iso(start),
        "ts_end": _iso(end),
        "latency_ms": answer["latency_ms"],
        "ttft_ms": None,
        "provider": "openai",
        "upstream": "api.openai.com",
        "endpoint": "/v1/chat/completions",
        "model": ORIGIN_MODEL,
        "model_resolved": answer.get("model_resolved"),
        "request": {"system": system, "messages": [m for m in messages if m["role"] != "system"], "tools": [],
                    "params": {"stream": False, "temperature": None, "max_tokens": None, "response_format": None}},
        "response": {"content": answer["content"], "tool_calls": [],
                     "finish_reason": answer["finish_reason"] if answer["finish_reason"] in FINISH else "other",
                     "finish_reason_raw": answer["finish_reason"]},
        "usage": {"input_tokens": answer["input_tokens"], "output_tokens": answer["output_tokens"],
                  "cached_input_tokens": answer.get("cached_input_tokens", 0), "reasoning_tokens": None},
        "http_status": 200,
        "error": None,
    }


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --- étape 1 : écriture des tickets --------------------------------------------------------------

INTENTS = [  # (part du jeu, ce que le ticket demande)
    (0.22, "un problème de facturation, de paiement, de remboursement, d'abonnement ou de prix"),
    (0.28, "un problème technique : bug, erreur, lenteur, intégration, appli mobile, export, API"),
    (0.20, "un problème de compte : connexion, mot de passe, double authentification, droits, suppression, "
           "changement d'adresse e-mail, utilisateurs de l'équipe"),
    (0.12, "autre chose : question commerciale, suggestion, partenariat, demande de devis, presse, recrutement, "
           "remerciement, plainte générale, RGPD"),
    (0.18, "un message envoyé par une machine et pas par une personne : notification automatique, alerte de "
           "monitoring, newsletter, accusé de réception, relance de facture d'un fournisseur, prospection de masse, "
           "hameçonnage, réponse d'absence"),
]
PERSONAS = ["particulier peu à l'aise avec l'informatique", "gérant de PME pressé", "développeur dans une start-up",
            "comptable d'un cabinet", "étudiant", "responsable informatique d'une collectivité",
            "assistante de direction", "artisan", "retraitée", "freelance graphiste", "commerçant en ligne",
            "directrice financière", "association loi 1901", "agence web qui gère plusieurs clients",
            "infirmier libéral", "restaurateur", "chef de projet dans un grand groupe", "auto-entrepreneur"]
TONES = ["poli et formel", "agacé", "très en colère, majuscules par endroits", "confus, s'excuse beaucoup",
         "direct, sans politesse", "familier, tutoiement", "style SMS avec fautes de frappe", "inquiet",
         "ironique", "neutre et factuel", "pressé, phrases incomplètes", "chaleureux"]
# Écrits par lots, les longs messages sortent deux fois trop courts (médiane 55 mots au premier essai) :
# chaque fiche longue part donc seule, avec un nombre de mots explicite.
LONG_BRIEF = "un long message de 100 à 200 mots (au moins 100 mots, compte-les), avec du contexte et des détails"
LENGTHS = [(0.30, "une à deux phrases, moins de 20 mots"), (0.40, "un paragraphe de 30 à 70 mots"),
           (0.30, LONG_BRIEF)]
FEATURES = ["pas de formule de politesse du tout", "un numéro de commande ou de facture inventé",
            "une citation d'un message d'erreur", "une signature avec nom et fonction", "une question à la fin",
            "une liste à puces", "une allusion à un échange précédent", "une date précise",
            "un mot d'anglais technique", "plusieurs problèmes mêlés, dont un principal",
            "aucune ponctuation ou presque", "commence directement par le problème"]

WRITER_SYSTEM = (
    "Tu écris des e-mails réalistes reçus par le support d'un éditeur de logiciel SaaS français (facturation, "
    "comptes, application web et mobile). Chaque e-mail suit sa fiche à la lettre : intention, auteur, ton, "
    "longueur, particularité. Aucun gabarit : pas deux e-mails qui commencent ou finissent pareil, évite les "
    "formules toutes faites (« Je me permets de vous contacter », « Merci d'avance pour votre aide »), varie le "
    "vocabulaire, les détails concrets et la structure. Les messages de machines ressemblent à de vrais messages "
    "automatiques. Réponds en JSON : {\"tickets\": [{\"fiche\": <numéro de la fiche>, \"subject\": ..., "
    "\"from\": ..., \"text\": ...}]}, un e-mail par fiche, où from est une adresse e-mail plausible.")


def briefs(n: int, seed: int = SEED) -> list[dict]:
    """Fiches de rédaction tirées au hasard (graine fixe) : la variété vient des combinaisons, pas du LLM."""
    rng = random.Random(seed)
    pick = lambda weighted: rng.choices([v for _, v in weighted], [w for w, _ in weighted])[0]  # noqa: E731
    return [{"intention": pick(INTENTS), "auteur": rng.choice(PERSONAS), "ton": rng.choice(TONES),
             "longueur": pick(LENGTHS), "particularite": rng.choice(FEATURES)} for _ in range(n)]


def write_tickets(client, n: int, path: Path) -> list[dict]:
    """Complète path jusqu'à n tickets sans jumeau ; les tickets déjà écrits sont gardés tels quels.

    Chaque ticket garde le numéro de sa fiche : une relance repart après la dernière fiche utilisée.
    """
    tickets = read_jsonl(path)
    forms = {normalize(t["text"]) for t in tickets}
    sheets = briefs(n * 2)  # réserve de fiches pour remplacer les jumeaux écartés
    nxt = max((t["fiche_n"] for t in tickets), default=-1) + 1
    while len(tickets) < n and nxt < len(sheets):
        batch = _next_batch(sheets, nxt)
        nxt += len(batch)
        listing = "\n".join(f"{i}. " + " ; ".join(f"{k} : {v}" for k, v in b.items()) for i, b in batch)
        resp = client.chat.completions.create(
            model=WRITER_MODEL, temperature=1.0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": WRITER_SYSTEM},
                      {"role": "user", "content": f"Écris {len(batch)} e-mails, un par fiche :\n{listing}"}])
        written = _written(resp.choices[0].message.content)
        with path.open("a") as f:
            for i, brief in batch:
                w = written.get(i)
                text = str((w or {}).get("text") or "").strip()
                form = normalize(text)
                if not form or form in forms or len(tickets) >= n:
                    continue
                forms.add(form)
                t = {"id": f"t{len(tickets) + 1:03d}", "subject": str(w.get("subject") or "").strip(),
                     "from": str(w.get("from") or "").strip(), "text": text, "fiche_n": i, "fiche": brief}
                tickets.append(t)
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"  {len(tickets)}/{n} tickets écrits", file=sys.stderr)
    return tickets


def _next_batch(sheets: list[dict], start: int) -> list[tuple[int, dict]]:
    """Jusqu'à BATCH fiches à la suite ; une fiche longue part toujours seule."""
    batch = []
    for i in range(start, min(start + BATCH, len(sheets))):
        is_long = sheets[i]["longueur"] == LONG_BRIEF
        if is_long and batch:
            break
        batch.append((i, sheets[i]))
        if is_long:
            break
    return batch


def _written(content: str | None) -> dict[int, dict]:
    """Réponse du rédacteur → {numéro de fiche: e-mail} ; tout ce qui est mal formé est ignoré."""
    try:
        items = json.loads(content or "").get("tickets", [])
    except (ValueError, AttributeError):
        return {}
    out = {}
    for w in items if isinstance(items, list) else []:
        if isinstance(w, dict) and isinstance(w.get("fiche"), int):
            out.setdefault(w["fiche"], w)
    return out


def read_jsonl(path: Path) -> list[dict]:
    """Lit un fichier JSONL ; une dernière ligne coupée par une interruption est ignorée."""
    if not path.exists():
        return []
    rows = []
    lines = path.read_text().splitlines()
    for k, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except ValueError:
            if k != len(lines) - 1:
                raise
    return rows


# --- étape 2 : appel réel au modèle d'origine ----------------------------------------------------

def openai_call(client):
    def call(model: str, messages: list[dict]) -> dict:
        start = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        resp = client.chat.completions.create(model=model, messages=messages)
        usage = resp.usage
        details = getattr(usage, "prompt_tokens_details", None)
        return {"content": resp.choices[0].message.content, "finish_reason": resp.choices[0].finish_reason,
                "input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens,
                "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0,
                "latency_ms": round((time.perf_counter() - t0) * 1000), "ts_start": _iso(start),
                "model_resolved": resp.model}
    return call


def triage_answers(events: list[dict]) -> dict[str, str]:
    return {e["event_id"].removeprefix("v2_").removesuffix("_tri"): e["response"]["content"]
            for e in events if e["app_id"] == TRIAGE_APP}


def render(report: dict) -> str:
    lines = [f"{'OK ' if r['ok'] else 'KO '} {name} : " + json.dumps({k: v for k, v in r.items() if k != 'ok'},
                                                                     ensure_ascii=False)
             for name, r in report.items()]
    return "\n".join(lines)


def main() -> int:
    from openai import OpenAI  # importé ici : les tests n'en ont pas besoin

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY manquante (mettez-la dans .env.local, jamais dans le dépôt).", file=sys.stderr)
        return 2
    OUT.mkdir(exist_ok=True)
    client = OpenAI(max_retries=6)  # 429 et erreurs passagères : le SDK réessaie avec attente
    tickets_path, events_path = OUT / "tickets.jsonl", OUT / "events.jsonl"
    print(f"Étape 1 : écriture des tickets ({WRITER_MODEL})", file=sys.stderr)
    tickets = write_tickets(client, N_TICKETS, tickets_path)
    # étape 2, ticket par ticket : chaque réponse est écrite aussitôt, une relance ne repaie que ce qui manque
    events = read_jsonl(events_path)
    done = {e["event_id"] for e in events}
    todo = [t for t in tickets if not {f"v2_{t['id']}_tri", f"v2_{t['id']}_spam"} <= done]
    print(f"Étape 2 : {len(todo)} tickets × 2 consignes dans {ORIGIN_MODEL} "
          f"({len(tickets) - len(todo)} déjà faits)", file=sys.stderr)
    call = openai_call(client)
    with events_path.open("a") as f:
        for k, t in enumerate(todo, 1):
            for e in build_events([t], call):
                if e["event_id"] not in done:
                    events.append(e)
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            if k % 50 == 0:
                print(f"  {k}/{len(todo)}", file=sys.stderr)
    report = checks(tickets, triage_answers(events))
    print(render(report))
    return 0 if all(r["ok"] for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
