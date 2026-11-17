"""La page développeur : toutes les propositions, y compris celles qui ont échoué, avec leurs mesures,
le statut de chaque chiffre, les raisons d'un refus ou d'une preuve non conclue et la micro-PR préparée.
Slack ne montre que les gains prouvés ; ici, rien n'est caché."""
import html

# « non conclu » (ADR 0002) : trop peu de textes distincts pour trancher ; pas prouvé, pas refusé non plus.
VERDICT = {"pass": ("Prouvée", "ok"), "reject": ("Refusée", "ko"), "inconclusive": ("Non conclue", "na"),
           "non_teste": ("Non testée", "na")}
CSS = """:root{--ink:#1d1d1f;--mute:#6e6e73;--line:#e5e5ea;--ok:#1a7f37;--ko:#b3261e;--na:#8a6d00;--bg:#fff}
@media (prefers-color-scheme:dark){:root{--ink:#f2f2f7;--mute:#a1a1a6;--line:#38383a;--bg:#161618}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px}h1{font-size:22px}.mute{color:var(--mute)}
.card{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.tag{font-size:12px;font-weight:600;padding:2px 8px;border-radius:99px;border:1px solid currentColor}
.ok{color:var(--ok)}.ko{color:var(--ko)}.na{color:var(--na)}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}td,th{text-align:left;padding:5px 4px;
border-bottom:1px solid var(--line)}th{color:var(--mute);font-weight:500}pre{overflow-x:auto;font-size:12px}"""


def _row(key, m):
    e = html.escape
    unit = f" {m['unite']}" if m.get("unite") else ""
    value = "—" if m["valeur"] is None else f"{m['valeur']:g}{unit}"
    return (f"<tr><td>{e(key.replace('_', ' '))}</td><td>{e(value)}</td><td>{e(m['statut'])}</td>"
            f"<td class='mute'>{e(m.get('hypothese') or '')}</td></tr>")


def _proof_notes(proof):
    """Textes distincts rejoués et alerte par-cœur (ADR 0002) : ici seulement, jamais dans le rapport
    dirigeant. L'alerte signale, elle ne change pas le verdict."""
    e = html.escape
    out = ""
    if proof.get("n_distinct") is not None:
        out += (f"<p class='mute'>{proof['n_replayed']} appels rejoués, {proof['n_distinct']} textes distincts "
                "(l'accord se compte une fois par texte distinct).</p>")
    flagged = proof.get("memorized_rules") or []
    if flagged:
        items = "".join(
            f"<li><b>{e(m['category'])}</b> : « {e(m['alternative'])} »"
            + (f" recopie l'exemple d'extraction « {e(m['example'])} »" if m.get("example") else "") + "</li>"
            for m in flagged)
        out += (f"<p class='na'>Règles qui ressemblent à du par-cœur ({len(flagged)}) : justes si votre trafic "
                f"se répète vraiment, fragiles sur une formulation nouvelle.</p><ul class='na'>{items}</ul>")
    return out


def render(proposals, diffs=None):
    """``diffs`` : {index: texte du diff} pour les propositions dont une micro-PR a été préparée."""
    e, diffs = html.escape, diffs or {}
    ok = sum(p["verdict"] == "pass" for p in proposals)
    cards = []
    for i, p in enumerate(proposals):
        label, cls = VERDICT.get(p["verdict"], (p["verdict"], "na"))
        rows = "".join(_row(k, m) for k, m in p["mesures"].items())
        why = "".join(f"<li>{e(r)}</li>" for r in p.get("raisons") or [])
        diff = f"<details><summary>Micro-PR préparée</summary><pre>{e(diffs[i])}</pre></details>" if i in diffs else ""
        cards.append(f"""<div class="card"><span class="tag {cls}">{label}</span>
<b> {e(p['app_id'])}</b> <span class="mute">· {e(p['type'])} · {e(p.get('model') or '')}</span>
<p>{e(p['changement'])}</p>{f'<ul class="{cls}">{why}</ul>' if why else ''}{_proof_notes(p.get('preuve') or {})}
<table><tr><th>Mesure</th><th>Valeur</th><th>Statut</th><th>Hypothèse</th></tr>{rows}</table>{diff}</div>""")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Propositions Deadweight</title>
<style>{CSS}</style></head><body><main><h1>Propositions testées</h1>
<p class="mute">{ok} prouvée{'s' if ok > 1 else ''} sur {len(proposals)}. Mesuré = rejeu des mêmes entrées sur
l'historique ; estimé = calcul avec l'hypothèse écrite ; non testé = aucune preuve possible ici.</p>
{''.join(cards)}</main></body></html>"""
