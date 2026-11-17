"""Mails de tri pour la boucle e2e : des textes vraiment distincts (aucun jumeau, ADR 0002).

Le faux OpenAI répond toujours la même phrase : il ne peut pas servir de modèle d'origine pour une
preuve. Ce module écrit donc l'historique de tri (réponses du modèle d'origine comprises) sur lequel
l'e2e prouve les règles, et fournit au trafic d'autres mails du même genre, jamais vus par la preuve.

    python tests/e2e/mails.py out/e2e/triage.jsonl
"""
import json
import sys

SYSTEM = "Classe le mail en une seule etiquette : spam, facture ou support."
APP, MODEL = "mail-triage", "gpt-4o"
# un mot d'ancrage par réponse (gratuit, facture, connexion) ; le reste varie d'un mail à l'autre
PHRASES = {
    "spam": ["Gagnez {o} gratuit aujourd'hui", "Offre gratuite : {o} pour les premiers inscrits",
             "{o} gratuit, cliquez vite", "Votre cadeau gratuit vous attend : {o}"],
    "facture": ["La facture pour {o} me semble trop élevée", "Je ne retrouve pas la facture de {o}",
                "Facture en double pour {o}", "Pouvez-vous corriger la facture concernant {o} ?"],
    "support": ["Problème de connexion sur {o}", "Depuis hier, la connexion à {o} échoue",
                "{o} : connexion impossible malgré un nouveau mot de passe",
                "Message d'erreur à la connexion pour {o}"],
}
OBJETS = ["la tablette", "le voyage à Lisbonne", "l'abonnement premium", "la carte cadeau", "le forfait mobile",
          "la livraison express", "le colis suivi", "la montre connectée", "le casque audio", "la console de jeu",
          "le vélo électrique", "la croisière", "le séjour à la montagne", "la box internet", "le contrat d'entretien",
          "l'assurance habitation", "la location de voiture", "le billet de train", "le réfrigérateur",
          "l'aspirateur robot", "la machine à café", "le téléviseur", "l'ordinateur portable", "l'imprimante",
          "le logiciel de comptabilité", "l'application mobile", "le site web", "l'espace client", "la messagerie",
          "le panier d'achat", "la réservation d'hôtel", "le parking", "la salle de sport", "le cours de yoga",
          "la formation en ligne", "le magazine", "la lettre d'information", "le stockage en ligne",
          "la clé de sécurité", "le portail fournisseur"]
LABELS = list(PHRASES)


def mail(i, decalage=0):
    """i-ème mail (texte, réponse) ; un autre ``decalage`` donne d'autres phrases pour les mêmes objets."""
    label, j = LABELS[i % 3], i // 3
    phrase = PHRASES[label][(j + decalage) % 4].format(o=OBJETS[j % len(OBJETS)])
    return phrase[0].upper() + phrase[1:], label


def historique(n=120):
    """Événements au schéma v1 : le tri tel que le modèle d'origine l'a fait."""
    events = []
    for i in range(n):
        text, label = mail(i)
        t = f"2026-09-20T09:{i // 60:02d}:{i % 60:02d}"
        events.append({
            "schema_version": "1", "event_id": f"e2e_{i:03d}", "trace": {"id": None, "source": None, "step": None},
            "app_id": APP, "ts_start": t + "Z", "ts_end": t + ".600Z", "latency_ms": 600.0, "ttft_ms": None,
            "provider": "openai", "endpoint": "/v1/chat/completions", "model": MODEL, "model_resolved": MODEL,
            "request": {"system": SYSTEM, "messages": [{"role": "user", "content": text}], "tools": [],
                        "params": {"stream": False, "temperature": 0.0, "max_tokens": None,
                                   "response_format": "text"}},
            "response": {"content": label, "tool_calls": [], "finish_reason": "stop", "finish_reason_raw": "stop"},
            "usage": {"input_tokens": 60, "output_tokens": 2, "cached_input_tokens": 0, "reasoning_tokens": None},
            "http_status": 200, "error": None})
    return events


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as out:
        out.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in historique())
