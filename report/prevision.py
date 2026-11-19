"""#45 : le texte de la prévision de plantage d'une mémoire sans fin (evidence.forecast de endless_memory),
le même dans le rapport, la page développeur et Slack. Une prévision est toujours dite « à ce rythme » ;
seuls les appels déjà refusés sont dits comme un fait."""


def _n(v):
    return f"{v:,.0f}".replace(",", " ")


def texte(fc):
    """Une phrase, ou None si le constat n'a pas de prévision (constat antérieur à #45)."""
    if not fc:
        return None
    statut = fc.get("statut")
    if statut == "depassee":
        n = fc["appels_refuses"]
        limite = f" (limite du modèle : {_n(fc['fenetre_tokens'])} jetons)" if fc.get("fenetre_tokens") else ""
        return (f"Déjà constaté : {n} appel{'s' if n > 1 else ''} refusé{'s' if n > 1 else ''} car la conversation "
                f"dépasse la limite du modèle{limite}. L'assistant a déjà cessé de répondre.")
    if statut == "inconnue":
        return f"Pas de prévision de plantage : {fc['raison']}."
    pente = f"+{_n(fc['pente_tokens_par_appel'])} jetons par appel"
    fenetre = f"limite du modèle : {_n(fc['fenetre_tokens'])} jetons"
    if statut == "imminente":
        return (f"Prévision : la limite est presque atteinte ({fenetre}) : à ce rythme ({pente}), l'assistant "
                f"cessera de répondre d'ici environ {fc['appels_restants']} appel"
                f"{'s' if fc['appels_restants'] > 1 else ''}.")
    return (f"Prévision : à ce rythme ({pente}), l'assistant cessera de répondre vers le {fc['appel_limite']}e "
            f"appel de la conversation ({fenetre}). Il en reste environ {fc['appels_restants']}.")


def html_constats(constats, nommer=None):
    """Paragraphes HTML des prévisions d'une carte ; ``nommer`` (app_id -> nom) préfixe chaque phrase quand la
    carte regroupe plusieurs workflows."""
    import html
    out = []
    for c in constats:
        t = texte((c.get("evidence") or {}).get("forecast"))
        if t:
            out.append(f'<p class="todo">{html.escape((nommer(c["app_id"]) + " : ") if nommer else "")}'
                       f'{html.escape(t)}</p>')
    return "".join(out)
