# Le workflow Claude Code, de l'idée à la pull request

Pour Ugo et l'équipe Speakli. Auguste, 16 novembre 2026.

Ce fichier explique comment installer et utiliser la suite que je t'ai montrée. Tu peux le donner tel quel à Claude
Code dans votre dépôt : il fera l'installation avec toi. Ce qui est marqué « non testé » ne l'a pas été chez moi.

## Le principe

Tu ne t'occupes que du produit et du design. Claude écrit la spec, découpe les tickets, code, teste et ouvre les pull
requests. Trois choses font que ça tient dans la durée :

- **Les décisions écrites** : un glossaire du domaine et des ADR (`docs/adr/`), une par décision durable. Chaque session
  les relit et te signale quand une demande contredit une décision passée : tu choisis entre le toi d'avant et le toi
  d'aujourd'hui.
- **Ce que tu aimes, écrit** : `PRODUCT.md` (pour qui, pourquoi, la barre de qualité) et `DESIGN.md` (les règles
  visuelles). Ils font foi pour chaque écran.
- **Tout dans GitHub** : la spec est une issue, chaque ticket est une issue avec ses blocages, chaque ticket donne une
  pull request.

Les étapes clés sont des skills que tu lances toi-même, jamais Claude.

## Installer, une fois

1. Les prérequis : Claude Code, `gh` connecté à votre GitHub, Node.
2. Un plan Claude d'entreprise : Team, Enterprise ou l'API, pas des comptes Max personnels. Voir « Les données de
   santé », plus bas.
3. Les skills de Matt Pocock (de l'idée aux tickets) et impeccable (le design), depuis la racine du dépôt :

   ```
   for s in setup-matt-pocock-skills grill-with-docs grilling domain-modeling to-spec to-tickets implement tdd triage diagnosing-bugs prototype handoff; do
     npx -y skills add mattpocock/skills -s "$s" -y
   done
   npx -y skills add pbakaus/impeccable -s impeccable -y
   ```

   Sans `-g`, elles s'installent dans le dépôt : une fois commitées, toute l'équipe a les mêmes (non testé, je les
   installe en global). Mise à jour une fois par mois : `npx -y skills update`.
4. Dans Claude Code, à la racine du dépôt :
   - `/setup-matt-pocock-skills` : le tracker (GitHub Issues), les labels de tri, l'emplacement du glossaire et des ADR.
   - `/impeccable init` : écrit `PRODUCT.md`, par questions.
   - `/impeccable document` : écrit `DESIGN.md` à partir de votre code actuel.
5. Pour les maquettes en image, impeccable lit une clé `OPENAI_API_KEY` dans l'environnement de Claude Code. Sans elle,
   il s'en tient aux esquisses en HTML.
6. Dans votre `CLAUDE.md`, deux choses :
   - Un tableau « quand je dis… → la skill ». C'est ce qui fait qu'une idée écrite en clair part sur le bon chemin :
     Claude te donne la commande à taper.

     ```
     | Quand je… | Skill |
     |---|---|
     | ai une idée de fonction | /grill-with-docs <l'idée> |
     | ai un écran à concevoir | /impeccable shape |
     | ai fini le grill | /to-spec, puis /to-tickets |
     | ai des retours en vrac | /triage |
     | ai un bug têtu | /diagnosing-bugs |
     ```

   - Rien d'autre qu'un index court. Chaque appel de chaque session relit ce fichier : les règles détaillées vont dans
     des pages par domaine, sous `docs/`, que le `CLAUDE.md` liste. Le nôtre a atteint 475 Ko ; un test le tient
     maintenant sous 32 Ko.

## Le chemin d'une fonction

| Étape | Commande | Ce qui en sort |
|---|---|---|
| 1. Le grill | `/grill-with-docs <l'idée>` | Des rondes de questions jusqu'à une compréhension partagée ; glossaire et ADR à jour |
| 2. La direction visuelle, s'il y a un écran | `/impeccable shape`, puis `/impeccable live` | Trois propositions par écran clé ; la retenue devient la maquette qui fait foi |
| 3. La spec | `/to-spec` | Une issue GitHub |
| 4. Les tickets | `/to-tickets` | Des issues avec leurs blocages, taillées pour partir en parallèle |
| 5. L'implémentation | `/implement`, une session neuve par ticket | Une pull request par ticket |
| 6. La finition | `/impeccable critique`, `polish`, `harden` | Des constats, triés par `/triage` |

- Les étapes 1, 3 et 4 se font dans la même session, sans `/clear` : la spec et les tickets s'appuient sur la réflexion
  du grill. Si la session approche de sa limite, `/compact` entre deux étapes, jamais au milieu.
- Le grill part de votre page Discovery dans Notion : colle-la, ou branche Notion à Claude Code. Notion garde l'Icebox et
  le pilotage mensuel ; la spec et les tickets vivent dans GitHub, et la page Notion du projet pointe vers la spec.
- Une fonction sans écran saute l'étape 2 ; une petite fonction peut finir en un seul ticket.
- `/prototype` répond, sur une branche jetable, à une question qu'une maquette ne tranche pas.

## Les règles qui font que ça marche

- **Une session par ticket**, dans son propre worktree et sur sa branche. Elle ne fusionne pas, ne pousse pas sur
  `main`, ne déploie pas. S'il lui manque une décision, elle s'arrête et l'écrit dans le ticket.
- **Les tickets se tiennent à jour entre eux** : une décision prise en cours de route s'écrit en commentaire sur la spec
  et sur chaque ticket qui en dépend. Aucune session ne part sur une information périmée.
- **La maquette retenue fait foi.** Un ticket d'écran la cite. Avant la fusion, la session prend des captures
  ordinateur et téléphone de chaque écran et les compare à la maquette.
- **Avec impeccable, dis « nouvelles surfaces dans l'identité documentée », jamais « refonte » ni « redesign »** : ces
  deux mots lui font remplacer votre identité visuelle.
- **Claude écrit trop de tests.** C'est le piège qui m'a le plus ralenti. Une pull request ne lance que les tests liés à ce
  qu'elle touche, `main` lance toute la suite ; en local, une session ne lance que les tests qu'elle touche. Et chaque
  session vérifie la pertinence de chaque test qu'elle ajoute.
- **Les retours d'utilisateurs** : rien ne remplace une heure de conversation. Pour un gros écran, je fais en plus
  naviguer cinq sous-agents, chacun dans la peau d'un utilisateur, sur un petit modèle (Haiku) qui ne connaît pas le
  code : ils disent où ils bloquent.
- **Un bug têtu** : `/diagnosing-bugs`, qui commence par une commande qui le reproduit. Des retours en vrac : `/triage`.

## Les données de santé

Ce que je t'ai dit au call est faux sur un point : **Claude ne peut pas anonymiser des données avant de les envoyer à
Anthropic.** Tout ce qu'il lit est déjà parti chez le fournisseur du modèle. Le filtrage se fait donc chez vous, dans
vos vues : Claude ne doit avoir accès qu'à ce qui est déjà filtré. Tu avais raison.

- **Le plan.** Pro et Max relèvent des conditions grand public : chaque titulaire choisit si ses sessions servent à
  entraîner les modèles, et elles sont gardées cinq ans s'il accepte. Team, Enterprise et l'API relèvent des conditions
  commerciales, sans entraînement sur vos données par défaut.
- **La boucle sur le comportement des soignants**, ta vraie question. Une base d'événements à part, hors de la base de
  santé : l'écran, le geste, l'heure, un identifiant pseudonyme du soignant. Jamais le contenu d'une note, jamais un
  identifiant de patient, jamais un texte libre. Claude la lit par une vue en lecture seule, avec un jeton qui n'a que
  ce droit. Tu peux alors lui demander comment une utilisatrice s'est servie de Speakli ces deux dernières semaines.
- **Les tests et les captures** se font sur des patients inventés, jamais sur un export de la production : une capture
  d'écran de Speakli montre les notes d'un patient.
- **Un Claude intégré à Speakli**, qui lirait les données de santé pour l'utilisateur, demande un modèle servi dans
  votre périmètre HDS. Claude existe sur Vertex AI, chez Google Cloud, où vous êtes déjà. Je n'ai rien trouvé qui dise
  que la certification HDS de Google couvre ce service : à demander à Google.
- Je ne suis pas juriste : fais valider tout ça par ton DPO avant de brancher quoi que ce soit.

## Le test

1. **Pose le contexte d'abord** : `/setup-matt-pocock-skills`, `/impeccable init` et `/impeccable document`. Sans
   glossaire, sans ADR et sans `DESIGN.md`, la première passe sera plus faible que les suivantes : ne juge pas la
   méthode là-dessus.
2. **Commence par une fonction que vos développeurs ont déjà livrée.** Repars de sa page Discovery, fais le grill, la
   spec et les tickets, puis compare aux tickets de l'époque et à ce qui a été livré : le découpage, les blocages, les
   cas oubliés, le plan de test, le temps passé. C'est la seule fonction où tu as une référence.
3. **Puis une nouvelle**, avec la direction visuelle.
4. **Fais mener la session par un de tes développeurs.** Il jugera une méthode qu'il a pratiquée, et c'est lui qui la
   fera vivre dans le dépôt.

## Plus tard : le pilotage et le travail à plusieurs

Une session longue lance un `/implement` par ticket, en parallèle, sur des machines dans le cloud. Elle relit chaque
pull request, fusionne, déploie, et ne te remonte que ce qui demande une décision. La mienne est trop liée à ma machine
et à mes comptes pour se copier telle quelle : on en reparle quand votre file de tickets dépassera ce que vous lancez à
la main.

À plusieurs, tout ce qui règle la méthode vit dans le dépôt (`CLAUDE.md`, `docs/agents/`, le glossaire, `docs/adr/`,
`PRODUCT.md`, `DESIGN.md`), pas dans un `~/.claude` personnel : c'est ce qui la rend commune à toute l'équipe.
