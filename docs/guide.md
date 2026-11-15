# DeadWeight : guide complet

Retour à l'accueil : [README](../README.md).

## Essayer en 5 minutes

Prérequis : Python 3.11+, git, make (macOS ou Linux). Aucune clé, aucun appel payant.

```sh
git clone https://github.com/hugogsld/DeadWeight.git && cd DeadWeight
make install        # crée .venv et installe
make demo           # 36 appels simulés → out/demo-…/audit.html (ouvrez-le)
```

Puis, avec votre propre usage de Claude Code (aucun zip, vos journaux restent sur votre machine) :

```sh
make audit-complet SOURCE=~/.claude/projects/<un-projet>    # un projet ; la liste s'affiche si vous oubliez
make audit-complet SOURCE=~/.claude/projects ALL=1          # tous vos projets : plus de volume, plus de constats
```

Enfin, pour votre propre application (OpenAI, Anthropic, Gemini) : `make dev` lance la passerelle locale sur
`http://127.0.0.1:8080/v1` ; vous ne changez que le `base_url` de votre client ([sections 1 à 4](#1-installer-et-lancer-la-passerelle)).

Pour voir le message Slack et la page développeur sur l'historique d'exemple :

```sh
.venv/bin/python -m optimize fixtures/dataset/v1/events.jsonl --out out/optim --demo
```

Cette commande rejoue l'historique d'exemple, propose une modification par constat, la teste
(précision, latence, coût) et écrit `out/optim/slack.md` (le message Slack, avec sa légende ✅ ◻️ ⛔) et
`out/optim/propositions.html` (la page développeur). Ajoutez `--repo <chemin/du/depot>` pour obtenir aussi le
diff et le texte de chaque micro-PR ; le dépôt n'est pas modifié. Pour tout vérifier d'un coup : `make e2e`.

**Ce qui quitte votre machine.** Tout reste local (passerelle, base, rapports, rejeu des règles), sauf deux
fonctions que vous activez vous-même avec votre clé : l'agent auditeur (`DW_LLM_API_KEY`) et le banc de modèles
(`bench`) envoient des extraits de vos données (prompts, réponses) au fournisseur LLM que vous avez choisi.
Sans ces clés, rien n'est envoyé.

### Scénario testeur (workflow 4553)

```sh
make tester WF=4553                               # parcours guidé, questions [O/n]
make tester WF=4553 REPO=~/mon-depot OUI=1        # tout accepter (tournage)
make tester WF=4553 SOURCE=fixtures/dataset/v1/events.jsonl   # répétition sur l'historique d'exemple
make tester WF=4553 MIN_APPELS=3                  # démo sur un workflow à peu d'exécutions (défaut : 30)
```

Prérequis réels : le workflow [4553](https://n8n.io/workflows/4553) importé dans votre n8n **et exécuté
plusieurs fois** ; `N8N_URL` et
`N8N_API_KEY` dans `.env.local` (sinon, un dossier déjà téléchargé dans `private/n8n/4553`) ; la clé du
fournisseur (`OPENAI_API_KEY`) seulement pour le banc « modèle plus petit ». Attention : `WF` est l'id
du workflow **dans votre instance** n8n, pas forcément 4553. Le parcours affiche l'analyse du workflow,
les modifications proposées, leur rejeu, puis un tableau des gains (précision, coût, latences, jetons ;
`~` estimé, `—` non mesuré) : sous 95 % de précision (même seuil que le rejeu des règles), une modification
n'apparaît nulle part, ni dans le tableau ni dans la PR. Suivent les gains sur l'ensemble du workflow (coût
total avant/après, coût par exécution) et un menu Review / Push / Quitter (raccourcis R/P/Q), dès qu'un
gain est prouvé. Sans `REPO` : Review montre la page développeur, Push donne la commande exacte à relancer
avec `REPO=…`. Slack n'est proposé qu'avec `SLACK_WEBHOOK_URL` ; sinon le message et la page développeur
s'affichent.
Les seuils des règles comptent des **appels IA par étape**, pas des exécutions : avec 1 à 3 exécutions, la
commande liste les vérifications en attente (« modèle trop gros : 30 appels nécessaires, 18 présents »),
ce n'est pas un échec. Sans aucune exécution, elle lit la structure seule (workflow téléchargé ou
bibliothèque publique n8n.io, sans clé) et n'affiche que des estimations `~`, puis explique comment mesurer.

### Audit complet en une commande

```sh
make audit-complet SOURCE=n8n:<id>                         # ou un dossier n8n, gateway, out/events.db,
make audit-complet SOURCE=~/.claude/projects/<projet> REPO=../mon-app   # events.jsonl, journaux Claude Code / Codex
```

Enchaîne détection de la source (n8n : `check` puis `fetch` avec `N8N_URL` / `N8N_API_KEY` ; passerelle :
trafic déjà capturé ; journaux Claude Code / Codex), rapport (`out/audit-complet/audit.html`), propositions
testées puis, avec `REPO=…`, ouverture des micro-PR prouvées (gh). Enfin le message Slack part par
`SLACK_WEBHOOK_URL` (webhook entrant) avec un bouton « Voir la PR » par micro-PR : un simple lien vers GitHub,
rien ne se fusionne depuis Slack. Il ne part que s'il y a un gain prouvé (`DEMO=1` montre tout) ; sans webhook,
le message reste dans `out/audit-complet/optim/slack.md` et la commande le dit.

## Brancher Deadweight sur vos workflows : cinq voies

| Vous utilisez… | Voie | Commande | Section |
|---|---|---|---|
| une application qui appelle OpenAI, Anthropic ou Gemini | passerelle (seul le `base_url` change) | `make dev` | [1 à 4](#1-installer-et-lancer-la-passerelle) |
| LangChain, SDK d'agents OpenAI, Vercel AI… | OpenTelemetry | `.venv/bin/python -m connectors.otel traces.json` | [OpenTelemetry](#opentelemetry) |
| Amazon Bedrock (Converse, InvokeModel, agents Strands/AgentCore) | journaux d'invocation exportés par le client | `python3 -m connectors.bedrock_logs export/` | [Bedrock](#brancher-deadweight-sur-bedrock) |
| Claude Code ou Codex | journaux de session | `make audit-complet SOURCE=~/.claude/projects/<projet>` | [Journaux](#journaux-claude-code-et-codex-b1) |
| n8n | historique d'exécution | `python3 -m importers.n8n check / fetch / convert` | [n8n](#importer-lhistorique-n8n-b1) |

Chaque voie a été vérifiée sur un clone neuf avec de vraies applications, temps et messages d'erreur
relevés : [docs/verification-voies-de-connexion.md](verification-voies-de-connexion.md).

Ensuite, pour toutes les voies : `.venv/bin/python -m report.audit` (rapport), `make audit` (agent auditeur, avec
votre clé) et `.venv/bin/python -m optimize` (propositions prouvées et micro-PR). Tout tourne sur votre machine.

## Prérequis

- **Python 3.11 ou plus récent**, avec `venv` et `pip` (`python3 --version`).
- **Git** et **Make** (`git --version`, `make --version`).
- macOS ou Linux ; sous Windows, utilisez WSL2 et suivez les commandes Linux.
- Une connexion Internet pour cloner et installer les dépendances. La démo n’appelle
  aucun fournisseur ; votre trafic réel nécessite votre accès habituel à votre fournisseur
  (OpenAI, Anthropic ou Gemini).

Sur Debian/Ubuntu, si nécessaire : `sudo apt install python3 python3-venv make git`.
Sur macOS, installez les outils de ligne de commande (`xcode-select --install`) et
Python 3.11+ avant de commencer. Les commandes ci-dessous sont à lancer depuis le repo.

## 1. Installer et lancer la passerelle

```sh
git clone https://github.com/hugogsld/DeadWeight.git
cd DeadWeight
make dev
```

`make dev` crée `.venv`, installe les dépendances, prépare `.env.local` puis lance
la passerelle sur **http://127.0.0.1:8080/v1**. Gardez ce terminal ouvert.
Vous n’avez aucune clé à renseigner dans DeadWeight : l’application continue
à transmettre sa propre clé. Si Python est nommé autrement : `make dev PY=python3.11`.

**Vérifier sans clé avant de brancher votre application :** dans un second terminal,
placez-vous dans le même dossier puis lancez :

```sh
make demo
```

La démo démarre un faux serveur OpenAI et une passerelle sur des ports locaux libres,
envoie 36 appels, puis affiche le chemin `out/demo-…/audit.html`. Ouvrez-le dans votre
navigateur. Chaque lancement utilise une base séparée et arrête ses serveurs à la fin :
votre passerelle et vos captures réelles restent intactes. Les chiffres de ce rapport
sont **fictifs**, destinés à vérifier le parcours. Après installation des dépendances,
la démo doit prendre moins d’une minute ; elle fonctionne sans Internet ni clé API.

## 2. Changer uniquement l’adresse dans votre application

Python, avec votre SDK OpenAI et votre clé habituelle :

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8080/v1")
# OPENAI_API_KEY reste configurée dans votre application, comme avant.
```

JavaScript / Node.js, avec votre SDK OpenAI existant :

```javascript
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "http://127.0.0.1:8080/v1" });
// OPENAI_API_KEY reste configurée dans votre application, comme avant.
```

Anthropic et Gemini, en Python, même principe (seule l'adresse change) :

```python
from anthropic import Anthropic
from google import genai

client = Anthropic(base_url="http://127.0.0.1:8080/anthropic")
client = genai.Client(http_options={"base_url": "http://127.0.0.1:8080/gemini"})
```

Si vous passiez déjà `api_key` / `apiKey` au constructeur, conservez-le. Ne changez
ni le modèle ni les messages. Sont capturés : OpenAI **Chat Completions**
(`/v1/chat/completions`), Anthropic `/v1/messages` et Gemini `generateContent` /
`streamGenerateContent`. Les autres routes sont relayées sans capture.
L’application et la passerelle doivent tourner sur la même machine : `127.0.0.1`
dans un conteneur désigne ce conteneur, pas la machine hôte.

## 3. Laisser passer votre trafic

Utilisez votre application normalement. Les événements sont écrits dans
`out/events.db` au fil des appels. Pour vérifier le compteur depuis un second terminal :

```sh
.venv/bin/python -m gateway.store count
```

Quelques appels suffisent pour produire un rapport ; certaines règles exigent au moins
30 appels comparables. « Aucun gaspillage détecté » est un résultat possible.
En streaming, OpenAI ne fournit les tokens que si votre application demande
`stream_options={"include_usage": True}` (Python) ou
`stream_options: { include_usage: true }` (JS). Sans usage, le rapport affiche les
coûts indisponibles : il n’invente pas de mesure.

## 4. Générer le rapport en une commande

Dans le second terminal, depuis le même dossier :

```sh
make audit
```

Cette commande enchaîne l’export SQLite et `report.audit`, puis écrit **`out/audit.html`**.
Ouvrez ce fichier dans votre navigateur. La passerelle peut rester active pendant
l’audit. L’export intermédiaire est temporaire et supprimé après usage. Pour choisir
le fichier final : `make audit AUDIT_OUT=out/mon-rapport.html`.

La base par défaut est `out/events.db`. Pour la changer, définissez
`GATEWAY_DB=/chemin/vers/events.db` dans `.env.local`, puis relancez `make dev`.
`make audit` charge le même fichier de configuration. Pour le compteur manuel,
ajoutez `--db /chemin/vers/events.db`.

## Agent auditeur

Avec une clé dans `.env.local` (`DW_LLM_API_KEY`, la vôtre : l'audit tourne chez vous), `make audit`
confie l'enquête à un agent. Il regarde votre trafic, choisit les constats qui coûtent le plus, prouve
par rejeu ceux qui peuvent l'être, et publie un plan d'action priorisé en tête du rapport, avec le
détail de sa démarche. Il ne calcule rien lui-même : un plan qui cite un chiffre absent des
vérifications est refusé et l'agent doit se corriger. Sans clé, le rapport est le même, sans plan.

## Test de bout en bout

    make e2e

Installe, lance la démo, puis une vraie passerelle devant trois fournisseurs simulés (OpenAI, Anthropic,
Gemini) : trafic simple, en streaming et en boucle d'agent, capture, traces, rapport, rejeu, miroir et
court-circuit. Aucune clé, aucun appel payant. La CI le lance à chaque PR.

## Workflows de test

De vrais workflows d'agents, passés par la passerelle pour tester Deadweight hors des fixtures, sont
dans le repo **[Workflow-test-hackathon-agentique-25-09-2026](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026)** :

| Workflow | Ce qu'il fait |
| --- | --- |
| [workflow 1 - Miguel short](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%201%20-%20Miguel%20short) | pipeline de production de shorts vidéo piloté par des agents Claude Code (snapshot) |
| [workflow 2 - Recap Gmail](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%202%20-%20Recap%20Gmail) | un agent lit les mails des dernières 24 h et rédige un récap |
| [workflow 3 - OpenAI story flow](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%203%20-%20OpenAI%20story%20flow) | exemple officiel `deterministic.py` du SDK Agents d'OpenAI : trois agents à la suite |
| [workflow 4 - Tri tickets support](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%204%20-%20Tri%20tickets%20support) | un appel `gpt-4o-mini` par ticket de support, 4 catégories : testé jusqu'à la PR d'optimisation |

Ce que chaque test a donné, et les problèmes à corriger : [docs/retours-tests-workflows.md](retours-tests-workflows.md).

## OpenTelemetry

Vos agents sont déjà instrumentés avec OpenTelemetry (LangChain, SDK d'agents OpenAI, Vercel AI, LiteLLM,
Langfuse…) ? Deux façons de les auditer, sans rien changer à votre code :

    # 1. un export de traces (OTLP/JSON)
    .venv/bin/python -m connectors.otel traces.json -o out/otel-events.jsonl
    .venv/bin/python -m agent.audit out/otel-events.jsonl -o out/audit.html

    # 2. en direct : ajoutez la passerelle comme destination de vos traces
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:8080/v1/traces

La passerelle lit l'OTLP/HTTP en JSON **et** en protobuf : l'exportateur Python officiel (protobuf) et celui
de Node.js (JSON) marchent tels quels, sans régler `OTEL_EXPORTER_OTLP_PROTOCOL`. Le gRPC (port 4317) n'est
pas lu : utilisez l'exportateur HTTP.

Par défaut, OpenTelemetry transmet l'usage (modèles, jetons, durées) et l'enchaînement des appels : on
chiffre et on repère des pistes. Pour les preuves (rejeu, banc de modèles), activez la capture du contenu
dans votre instrumentation. Méthode : `docs/analyser-un-workflow.md`.

## Journaux Claude Code et Codex (B1)

Si vos agents sont Claude Code ou Codex, leurs journaux de session contiennent déjà chaque appel de modèle.
Pas de zip : pointez le dossier.

    make audit-complet SOURCE=~/.claude/projects/<un-projet>        # Claude Code, un projet
    make audit-complet SOURCE=~/.claude/projects ALL=1              # tous les projets
    make audit-complet SOURCE=~/.claude/projects PROJECT=mon-app    # les projets dont le nom contient ce texte
    make audit-complet SOURCE=~/.codex/sessions                     # Codex

Un dossier qui range plusieurs projets (comme `~/.claude/projects`) exige `PROJECT=` ou `ALL=1` (`--project` /
`--all-projects` en ligne de commande) : sinon la commande liste les projets et s'arrête, pour ne pas mélanger
des projets sans rapport. Le rapport est `out/audit-complet/audit.html`, le message Slack
`out/audit-complet/optim/slack.md`.

Sous la barre de volume (30 appels par tâche pour les règles de fréquence), le rapport ne reste pas muet : une
section « Pourquoi aucun constat » donne le volume lu, ce que la source ne montre pas, la suite, et ce qui est
déjà utile (coût par session, part du cache, part du contexte relu dans le coût).

Facturation : `~/.claude.json` est lu (seulement le type de facturation du compte, jamais un jeton) pour savoir
si Claude Code tourne sur abonnement ou à l'usage ; `--billing abonnement|api` force le choix. Sur abonnement,
les dollars sont une valeur équivalente API, pas une économie sur la facture.

Chaque appel devient un événement : modèle, jetons (cache compris), heure, messages du tour,
réponse, appels d'outils ; la session sert de trace, un sous-agent a son propre `app_id`
(`claude-code:<projet>/sous-agent`). Les clés d'API affichées dans les journaux sont masquées.
`comprehension.json` dit, par outil, les appels lus, ignorés et pourquoi, le niveau atteint et la facturation.
Limites : le prompt système et la liste des outils ne sont pas journalisés ; les jetons écrits en
cache par Claude Code sont comptés au prix normal (facturés 1,25× à 2×), le coût est donc un
peu sous-estimé sur cette part.

Étapes séparées (équivalent manuel) :

    python3 -m connectors.agent_logs ~/.claude/projects/<un-projet> -o private/agent-logs/events.jsonl
    python3 -m report.audit private/agent-logs/events.jsonl --comprehension private/agent-logs/comprehension.json -o out/audit.html

`--comprehension` apporte au rapport le mode de facturation détecté.

## Brancher Deadweight sur Bedrock

Lecture seule, sans toucher au code du client ni à ses accès : le client active le journal d'invocation de
Bedrock et nous remet l'export. Les journaux ne couvrent que les appels faits par le endpoint `bedrock-runtime`
(Converse, ConverseStream, InvokeModel, InvokeModelWithResponseStream), donc aussi les agents Strands ou AgentCore qui passent par lui.

**Ce que le client active** (console : Bedrock > Settings > Model invocation logging, cocher *Text*, choisir S3 et/ou
CloudWatch Logs ; ou une commande, syntaxe relue contre le modèle de service botocore 1.44, `--logging-config` est
l'option obligatoire) :

    aws bedrock put-model-invocation-logging-configuration --region eu-west-1 --logging-config \
      '{"s3Config":{"bucketName":"MON-BUCKET","keyPrefix":"bedrock"},"textDataDeliveryEnabled":true,"imageDataDeliveryEnabled":false,"embeddingDataDeliveryEnabled":false}'

Le bucket doit être dans le même compte et la même région que la configuration (AWS pose sa politique de bucket
si le client a les droits `s3:GetBucketPolicy` et `s3:PutBucketPolicy`). Pour CloudWatch Logs, remplacer `s3Config`
par `cloudWatchConfig` (`logGroupName` et `roleArn` obligatoires, `largeDataDeliveryS3Config` pour les corps de plus
de 100 Ko). Ne sont journalisés que les appels du endpoint `bedrock-runtime`, pas ceux de `bedrock-mantle`.

Le journal ne remonte pas dans le passé : il faut laisser tourner quelques jours de trafic réel. Pour reconnaître
les workflows, le client peut ajouter `requestMetadata` (`workflow_id`, `agent`) à ses appels Converse ; sans cela,
l'application est déduite du rôle IAM.

**Ce qu'on nous remet** : le dossier du bucket (`AWSLogs/<compte>/BedrockModelInvocationLogs/...`, fichiers `.json.gz`,
sous-dossier `data/` compris pour les corps de plus de 100 Ko), ou un export CloudWatch, en dossier ou en `.zip`.

    python3 -m connectors.bedrock_logs export/ -o private/bedrock/events.jsonl
    .venv/bin/python -m report.audit private/bedrock/events.jsonl

La commande dit ce qu'elle a lu, ignoré et pourquoi ; elle sort en erreur (code non nul) si elle ne lit aucun appel.
Sans le dossier `data/`, les gros corps restent absents : les jetons et le coût sont comptés, pas le contenu.

**Ce qu'on lit** : modèle, horodatage, région, jetons (entrée, sortie, cache lu, cache écrit), messages, prompt système,
outils, réponses et étiquettes `requestMetadata`. Le coût est calculé avec les tarifs publics AWS à la demande
(`fixtures/pricing.bedrock.json`, lus dans le catalogue AWS Price List, source et date dans le fichier ; tarif
« global » pour un profil `global.`, régional sinon). Un appel direct dans une région est supposé au tarif régional.

**Ce qu'on ne lit ni ne garde** : aucune clé ni accès AWS (aucun appel réseau vers AWS), l'ARN de l'appelant sert
seulement à nommer l'application (non stocké), les images sont comptées, jamais lues, les chaînes qui ressemblent
à une clé sont masquées. Tout reste sur la machine qui lance la commande.

## Proposer et prouver des micro-modifications

Après la capture, **une seule commande** enchaîne le bilan, les propositions testées sur l'historique et
les micro-PR :

    make optimiser REPO=chemin/du/depot            # bilan + propositions + un diff et un texte de PR par gain prouvé
    make optimiser REPO=chemin/du/depot PR=oui     # ... et ouvre réellement les PR (gh), sur un dépôt que vous contrôlez

Résultats dans `out/optimiser/` : `audit.html`, `propositions/propositions.html` (page développeur),
`propositions/slack.md`, les `*.diff` et `*.pr.md`. Sans `REPO`, seulement le bilan et les propositions.
`BANC=oui` teste aussi des modèles moins chers (appels payants, clé nécessaire). Même base que
`make audit` (`GATEWAY_DB`). Le détail, commande par commande :

    .venv/bin/python -m optimize events.jsonl --out private/optim --repo chemin/du/depot

Pour chaque constat : une seule modification (règles à la place d'un LLM qui aiguille, modèle plus petit,
plafond de longueur), **testée sur votre historique** (mêmes entrées rejouées, comparées aux anciennes
réponses), puis un diff et un texte de micro-PR par modification validée, le message Slack (gains prouvés
seulement ; `--demo` montre aussi les pistes refusées) et `propositions.html`, la page développeur qui montre tout. Chaque chiffre
porte son statut : mesuré, estimé (hypothèse nommée) ou non testé. `--open-prs` ouvre réellement les PR (gh).

## Prix des modèles

Les coûts viennent de `fixtures/pricing.json`, le catalogue public d'OpenRouter (prix d'entrée,
de sortie et du cache, en dollars par million de jetons). Pour le rafraîchir :

    make prices

Les noms des API sont reconnus tels quels (`claude-sonnet-4-5`, `gpt-4o-2024-08-06`). Si un
modèle reste inconnu, le rapport chiffre les autres appels et indique la part couverte.

Origine et hébergement de chaque éditeur (pays, traitement possible dans l'UE, option souveraine)
dans `fixtures/providers.json`, chaque fiche avec sa source ; un point non vérifié vaut `null`.
Pour rafraîchir les prix et contrôler le catalogue, puis voir la latence mesurée sur votre trafic :

    make catalog
    .venv/bin/python -m catalog --events events.jsonl

Quand le rapport signale un modèle surdimensionné pour une tâche simple, il propose aussi d'autres
modèles, tous fournisseurs confondus : le moins cher, le moins cher chez le même éditeur, et le
moins cher d'un éditeur européen. Chacun sait faire ce que fait votre trafic (outils, JSON, images,
taille du plus gros appel, d'après `fixtures/capabilities.json`) et son coût est recalculé sur vos
propres jetons. Les options « même éditeur » et « souverain » sont chiffrées au prix de la route de
l'éditeur lui-même, pas à celui d'un hébergeur tiers moins cher. Un modèle à raisonnement est
signalé : ses jetons de réflexion ne sont pas dans votre trafic, son coût est donc sous-estimé.
Leur qualité n'est pas prouvée : à vérifier par rejeu avant de changer de modèle.

Le rapport indique aussi **où partent vos données** : pour chaque application, la destination réelle
des appels (capturée par la passerelle) et si elle est traitée dans l'Union européenne. Quand elle ne
l'est pas, il propose d'abord le même modèle en région UE si le fournisseur l'offre, puis un modèle
d'éditeur européen, à tester avant de changer.

## Importer l'historique n8n (B1)

Sans passerelle : si vos agents tournent dans n8n, l'historique des exécutions contient déjà
vos vrais appels LLM. Deux commandes, à lancer chez vous, avec seulement Python 3.9+ (rien à
installer). La clé se crée dans n8n, *Settings → n8n API*, et reste dans votre environnement.

    export N8N_API_KEY=...
    python3 -m importers.n8n check --url https://votre-n8n.exemple.com
    python3 -m importers.n8n fetch --url https://votre-n8n.exemple.com --workflow <id> [--limit 500] [--since 2026-09-01]

`check` dit, pour chaque workflow, s'il appelle un LLM, si les exécutions réussies sont
enregistrées, combien il y en a et sur quelle période. `fetch` écrit
`private/n8n/<id>/workflow.json` et `executions.jsonl` (une exécution par ligne) ; relancée,
elle reprend sans retélécharger. Le dossier `private/` est ignoré par git : relisez-le avant
de nous l'envoyer, il contient les messages traités par vos workflows.

Puis la conversion en événements, et le même rapport que pour la passerelle :

    python3 -m importers.n8n convert private/n8n/<id>
    python3 -m report.audit private/n8n/<id>/events.jsonl -o out/audit.html

Chaque appel d'un nœud « Chat Model » (OpenAI, Anthropic, Gemini, Mistral, Groq, Ollama…)
devient un événement : prompt, réponse, jetons, durée ; l'exécution n8n sert de trace (exacte),
`app_id` = `n8n:<workflow>/<nœud racine>`. n8n ne garde pas les appels d'outils du modèle : on
les reconstitue depuis les nœuds outils. Il ne sépare pas non plus la part servie par le cache :
le coût est donc un plafond (tout au prix plein). `comprehension.json` dit ce qui a été lu :
jetons réels, estimés par n8n, appels illisibles — et le **taux d'appels LLM compris**.

Données personnelles : `convert --anonymize` remplace emails, téléphones, IBAN et numéros de
carte par des étiquettes stables (`[email-1]`, `[telephone-2]`…) ; une même valeur garde la
même étiquette, les règles gardent donc leur signal. Envoyez-nous alors seulement
`events.jsonl`, pas `executions.jsonl` (brut). Après l'analyse :

    python3 -m importers.n8n purge private/n8n/<id>

Pour vérifier notre lecture sur des workflows réels, la bibliothèque publique n8n.io (sans clé) :

    python3 -m importers.n8n library fetch --limit 1000     # les plus consultés de la catégorie AI
    python3 -m importers.n8n library coverage               # nœuds LLM, fournisseur, modèle lu

Les workflows vont dans `private/n8n-library/` (ignoré par git : ils appartiennent à leurs
auteurs). `coverage` liste ce qu'on ne sait pas lire : fournisseurs inconnus, nœuds d'IA non
reconnus, modèle introuvable. Un modèle laissé au réglage par défaut n'est pas écrit dans le
workflow (et ce défaut change selon la version de n8n) : seul l'historique d'exécution le donne.
La liste des 1 000 workflows de test et ce qu'on y lit : [docs/bibliotheque-n8n.md](bibliotheque-n8n.md).

## Confidentialité

- **La clé n’est jamais stockée** par la passerelle : l’en-tête d’autorisation est
  relayé au fournisseur sans être enregistré dans SQLite ou les journaux.
- **La base reste chez vous.** Elle contient les prompts et réponses : traitez-la
  comme les données de votre application. Le rapport peut aussi contenir des informations
  sur vos applications ; partagez-le uniquement avec les personnes concernées.
- Le fournisseur reçoit toujours vos appels habituels. La génération du rapport ne
  transmet aucune donnée à DeadWeight ou à un modèle externe, sauf l'agent auditeur
  (`DW_LLM_API_KEY`) et le banc de modèles (`bench`) : ils envoient des extraits de vos données au
  fournisseur LLM que vous avez choisi.
- La démo utilise exclusivement des serveurs locaux et ne lit aucune clé client.

## Si ça ne marche pas

| Symptôme | Action |
| --- | --- |
| `python3`, `make` ou `git` introuvable | Installez les prérequis ci-dessus ; vérifiez Python 3.11+. |
| Création de `.venv` impossible | Sur Debian/Ubuntu, installez `python3-venv` ; vérifiez les droits du dossier. |
| Installation des paquets impossible | Vérifiez Internet et l’accès à PyPI, puis relancez `make dev`. |
| Port 8080 déjà utilisé | Arrêtez l’autre service, ou réglez `GATEWAY_PORT=8081` dans `.env.local` et utilisez ce port dans votre `base_url`. |
| Connexion refusée par votre application | Gardez `make dev` ouvert et vérifiez l’adresse, le port et que l’application tourne sur le même hôte. |
| Réponse 401 / 429 / 502 | Vérifiez respectivement votre clé dans l’application, votre quota fournisseur, ou l’accès réseau au fournisseur. |
| Base absente ou vide | Lancez `make dev`, envoyez des appels Chat Completions via le nouveau `base_url`, puis relancez `make audit`. Vérifiez `GATEWAY_DB`. |
| Rapport sans constat | Collectez davantage de trafic comparable ; les règles peuvent aussi n’avoir rien à signaler. |
| Coût « non disponible » | Vérifiez l’usage des tokens et la présence du modèle dans `fixtures/pricing.json` ; aucune valeur de remplacement n’est utilisée. |
| Démo impossible | Vérifiez les droits dans `out/` et l’autorisation des connexions locales, puis relancez `make demo`. |

Pour diagnostiquer l’installation : `make test` puis `make lint`. `make demo` permet
de distinguer un problème local d’un problème de clé ou de fournisseur.

