# Le workflow Claude Code, de l'idée à la pull request

Pour l'équipe DeadWeight (Natan, Hugo, Thibault, Alexandre). Adapté du guide d'Auguste (16 novembre 2026).

Ce fichier explique comment on travaille avec Claude Code dans ce dépôt, de l'idée à la PR. Il complète
[AGENTS.md](AGENTS.md), qui reste la règle pour tout agent qui code ici (Claude Code comme Codex).

## Le principe

On s'occupe du produit : quoi détecter, quoi prouver, quoi montrer. Claude écrit la spec, découpe les tickets,
code, teste et ouvre les PR. Trois choses font que ça tient dans la durée :

- **Les décisions écrites** : un glossaire du domaine (`GLOSSARY.md`) et des ADR (`docs/adr/`), une par décision
  durable (par exemple : « rien n'est recommandé sans rejeu sur le vrai trafic, seuil 95 % »). Chaque session les
  relit et signale quand une demande contredit une décision passée : on choisit entre la décision d'avant et celle
  d'aujourd'hui.
- **Ce qu'on veut, écrit** : `PRODUCT.md` (pour qui, pourquoi, la barre de qualité) et `DESIGN.md` (les règles
  visuelles du rapport et de la page développeur). Ils font foi pour chaque écran.
- **Tout dans GitHub** : la spec est une issue, chaque ticket est une issue avec ses blocages, chaque ticket donne une
  PR. C'est déjà la règle d'`AGENTS.md` (une tâche = une issue = une branche = une PR).

Les étapes clés sont des skills qu'un humain lance lui-même, jamais Claude.

## Ce qui est déjà installé

Les skills sont dans le dépôt, donc toute l'équipe a les mêmes :

- `.agents/skills/` : les skills elles-mêmes (lues aussi par Codex) ;
- `.claude/skills/` : des liens vers `.agents/skills/`, là où Claude Code les cherche ;
- `skills-lock.json` : la version exacte de chaque skill.

| Famille | Skills |
|---|---|
| Matt Pocock (de l'idée aux tickets) | `setup-matt-pocock-skills`, `grill-with-docs`, `grilling`, `domain-modeling`, `to-spec`, `to-tickets`, `implement`, `tdd`, `triage`, `diagnosing-bugs`, `prototype`, `handoff` |
| impeccable (le design) | `impeccable` |

Mise à jour une fois par mois, depuis la racine : `npx -y skills update`, puis une PR. Les skills tournent avec tous
les droits de l'agent : on relit le diff d'une mise à jour avant de la fusionner.

Pour les réinstaller de zéro (prérequis : Claude Code, `gh` connecté, Node) :

```
for s in setup-matt-pocock-skills grill-with-docs grilling domain-modeling to-spec to-tickets implement tdd triage diagnosing-bugs prototype handoff; do
  npx -y skills add mattpocock/skills -s "$s" -y
done
npx -y skills add pbakaus/impeccable -s impeccable -y
```

## Poser le contexte, une fois

À faire par un humain, dans une session Claude Code ouverte à la racine du dépôt. Claude rédige en posant des
questions ; on répond et on valide.

1. `/setup-matt-pocock-skills` : le tracker (GitHub Issues du dépôt), les étiquettes de tri (`needs-triage`,
   `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), l'emplacement du glossaire et des ADR. Écrit
   `docs/agents/` et une section `## Agent skills` dans `CLAUDE.md`.
2. `/impeccable init` : écrit `PRODUCT.md`.
3. `/impeccable document` : écrit `DESIGN.md` à partir de nos écrans actuels (voir « Nos écrans » plus bas). Moins
   urgent : on a peu d'écrans.
4. Dans `CLAUDE.md`, un tableau « quand je… → la skill ». C'est ce qui fait qu'une idée écrite en clair part sur le
   bon chemin : Claude répond avec la commande à taper.

   ```
   | Quand je… | Skill |
   |---|---|
   | ai une idée (règle, levier, connecteur) | /grill-with-docs <l'idée> |
   | ai un écran à concevoir ou revoir | /impeccable shape |
   | ai fini le grill | /to-spec, puis /to-tickets |
   | ai des retours en vrac (tests de workflows, retours clients) | /triage |
   | ai un bug têtu | /diagnosing-bugs |
   ```

   `CLAUDE.md` reste un index court : chaque appel de chaque session le relit. Les règles détaillées vont dans des
   pages par domaine sous `docs/`, que `CLAUDE.md` liste.

## Le chemin d'une fonction

| Étape | Commande | Ce qui en sort |
|---|---|---|
| 1. Le grill | `/grill-with-docs <l'idée>` | Des rondes de questions jusqu'à une compréhension partagée ; glossaire et ADR à jour |
| 2. La direction visuelle, s'il y a un écran | `/impeccable shape`, puis `/impeccable live` | Trois propositions par écran ; la retenue devient la maquette qui fait foi |
| 3. La spec | `/to-spec` | Une issue GitHub |
| 4. Les tickets | `/to-tickets` | Des issues avec leurs blocages, taillées pour partir en parallèle |
| 5. L'implémentation | `/implement`, une session neuve par ticket | Une PR par ticket |
| 6. La finition, s'il y a un écran | `/impeccable critique`, `polish`, `harden` | Des constats, triés par `/triage` |

- Les étapes 1, 3 et 4 se font dans la même session, sans `/clear` : la spec et les tickets s'appuient sur la
  réflexion du grill. Si la session approche de sa limite, `/compact` entre deux étapes, jamais au milieu.
- Le grill part de nos sources d'idées : [ROADMAP_V2.md](ROADMAP_V2.md), les fiches [leviers/](leviers/) et
  [docs/retours-tests-workflows.md](docs/retours-tests-workflows.md). Colle la fiche ou le problème concerné.
- Une nouvelle règle dans `rules/`, un connecteur ou un importeur n'a pas d'écran : elle saute les étapes 2 et 6. Une
  petite fonction peut finir en un seul ticket.
- `/prototype` répond, sur une branche jetable, à une question qu'une maquette ne tranche pas (par exemple : un seuil
  de détection, sur les données de `fixtures/`).

### Nos écrans

Ce que voit un utilisateur de DeadWeight, et donc ce que `DESIGN.md` et impeccable couvrent :

- le rapport d'audit (`audit.html`, produit par `report/`) ;
- la page développeur (`propositions.html`, produite par `optimize/devpage.py`) ;
- le message Slack (`slack.md`, produit par `optimize/slack.py`).

## Les règles qui font que ça marche

- **Une session par ticket**, dans son propre worktree et sur sa branche (nommage d'`AGENTS.md` :
  `feat/<id>-<sujet>`). Elle pose son étiquette `agent:claude` ou `agent:codex` sur l'issue, ne fusionne pas, ne
  pousse pas sur `main`. S'il lui manque une décision, elle s'arrête et l'écrit en commentaire sur l'issue au lieu
  de deviner.
- **Les tickets se tiennent à jour entre eux** : une décision prise en cours de route s'écrit en commentaire sur la
  spec et sur chaque ticket qui en dépend. Aucune session ne part sur une information périmée.
- **Les contrats ne bougent pas en douce** : `schemas/` et `fixtures/` sont codés par quatre personnes. Un ticket qui
  doit les changer le dit dans sa description, et le changement passe par une ADR s'il est cassant.
- **La maquette retenue fait foi.** Un ticket d'écran la cite. Avant la PR, la session génère l'écran sur la démo
  (`make demo`), en prend des captures ordinateur et téléphone, et les compare à la maquette.
- **Avec impeccable, dis « nouvelles surfaces dans l'identité documentée », jamais « refonte » ni « redesign »** : ces
  deux mots lui font remplacer l'identité visuelle.
- **Claude écrit trop de tests.** En local, une session ne lance que les tests liés à ce qu'elle touche
  (`.venv/bin/python -m pytest tests/test_<module>.py`), puis `make lint`. La CI lance toute la suite (`make test`,
  `make e2e`) à chaque PR. Chaque session vérifie la pertinence de chaque test qu'elle ajoute : un test qui ne peut
  pas échouer pour une vraie raison est supprimé.
- **Si la PR ajoute une commande, le README est mis à jour dans la même PR** (règle d'`AGENTS.md`).
- **Un bug têtu** : `/diagnosing-bugs`, qui commence par une commande qui le reproduit. Des retours en vrac (une série
  de tests de workflows, des retours d'un client) : `/triage`.

## Les données de nos clients

DeadWeight lit des données sensibles : les prompts des clients, les réponses de leurs IA, leurs workflows n8n, leurs
journaux Claude Code et Codex. Il faut séparer deux choses.

- **DeadWeight qui lit ces données** : aucun problème. Passerelle, base, rapports et rejeu tournent en local ; rien ne
  sort, sauf l'agent auditeur (`DW_LLM_API_KEY`) et le banc de modèles, qui envoient des extraits au fournisseur LLM
  choisi. Le README le dit déjà.
- **Claude Code qui lit ces données** : tout ce qu'il lit (un fichier ouvert, la sortie d'une commande) part chez
  Anthropic. Claude ne peut pas anonymiser avant d'envoyer : le filtrage se fait avant qu'il lise.

D'où les règles :

- **Le plan.** Pro et Max relèvent des conditions grand public : chaque titulaire choisit si ses sessions servent à
  entraîner les modèles. Team, Enterprise et l'API relèvent des conditions commerciales, sans entraînement par défaut.
  Pour des données de client : Team, Enterprise ou l'API uniquement.
- **Les vraies données vivent dans `private/`** (ignoré par git). Sur nos propres workflows, ou ceux d'un client qui a
  donné son accord, Claude peut lancer DeadWeight dessus et lire le rapport (des chiffres, des constats). Il n'ouvre
  pas les fichiers bruts de `private/` (événements, exécutions n8n, journaux) sans qu'on le lui demande.
- **Les tests, les captures et les exemples des docs** se font sur des données fictives : `fixtures/`, `make demo`,
  les workflows de [workflows/](workflows/). Jamais sur un export client : un rapport d'audit montre des extraits de
  prompts.
- **Les clés** (`DW_LLM_API_KEY`, `N8N_API_KEY`, `SLACK_WEBHOOK_URL`) restent dans `.env.local`, jamais dans le dépôt
  ni dans une issue.
- Avant de brancher DeadWeight chez un client, on lui dit ce qui sort de sa machine et vers qui.

## Le test de la méthode

1. **Poser le contexte d'abord** (section plus haut). Sans glossaire, sans ADR et sans `PRODUCT.md`, la première passe
   sera plus faible que les suivantes : ne pas juger la méthode là-dessus.
2. **Commencer par une fonction déjà livrée.** Par exemple une règle du hackathon, comme `tool_bloat` (levier 15) :
   repartir de sa fiche dans `leviers/`, faire le grill, la spec et les tickets, puis comparer à l'issue et à la PR de
   l'époque : le découpage, les blocages, les cas oubliés, les tests, le temps passé. C'est la seule fonction où on a
   une référence.
3. **Puis une nouvelle**, par exemple un levier encore « à faire » dans [leviers/README.md](leviers/README.md), ou un
   problème ouvert de [docs/retours-tests-workflows.md](docs/retours-tests-workflows.md).
4. **Chacun mène au moins une session.** On juge une méthode qu'on a pratiquée.

## Plus tard : le pilotage et le travail à plusieurs

Une session longue lance un `/implement` par ticket, en parallèle (Claude Code et Codex, chacun dans son worktree, ou
sur des machines dans le cloud). Elle relit chaque PR et ne remonte que ce qui demande une décision. La fusion reste
humaine (`AGENTS.md`). On en reparle quand la file de tickets dépassera ce qu'on lance à la main.

Tout ce qui règle la méthode vit dans le dépôt (`AGENTS.md`, `CLAUDE.md`, `docs/agents/`, `GLOSSARY.md`, `docs/adr/`,
`PRODUCT.md`, `DESIGN.md`, `.agents/skills/`), pas dans un `~/.claude` personnel : c'est ce qui la rend commune à
toute l'équipe.
