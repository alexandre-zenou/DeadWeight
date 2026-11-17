# DeadWeight

DeadWeight lit l'historique des appels d'IA d'une entreprise, repère ceux qui coûtent pour rien, et prouve chaque
économie sur le vrai trafic avant de la proposer.

## Remplacer une IA par des règles

**Aiguillage** :
Un appel d'IA dont la réponse ne prend qu'une poignée de valeurs (« spam » / « no spam », une catégorie de ticket) :
il choisit une branche, il ne produit pas d'information.
_Éviter_ : routage, classification (pour le constat lui-même)

**Modèle d'origine** :
L'IA qui fait l'aiguillage aujourd'hui chez le client ; ses réponses passées sont la référence.
_Éviter_ : modèle de base, modèle actuel

**Règle d'aiguillage** :
Une correspondance de mots qui donne directement la réponse du modèle d'origine, sans appel d'IA.
_Éviter_ : regex, heuristique

**Modèle de secours** :
L'IA, souvent plus petite, appelée seulement pour les entrées qu'aucune règle d'aiguillage ne couvre.
_Éviter_ : fallback, repli

**Fidélité** :
Ce que vise une règle d'aiguillage : redonner la réponse du modèle d'origine, y compris quand celui-ci se trompait.
_Éviter_ : justesse, précision (quand on parle de ce que vise la règle)

## Prouver

**Exemple d'extraction** :
Un appel passé, montré à l'extraction pour écrire les règles d'aiguillage ; il ne peut plus servir à les prouver.
_Éviter_ : échantillon d'entraînement

**Jumeau** :
Un texte quasi identique à un autre une fois retirés les formules de politesse, les chiffres et les dates : pour la
preuve, deux jumeaux sont le même texte.
_Éviter_ : doublon (réservé aux appels identiques facturés deux fois)

**Preuve** :
Le rejeu des règles d'aiguillage sur des appels passés qui ne sont ni des exemples d'extraction ni leurs jumeaux,
comparé aux réponses du modèle d'origine ; elle se termine par un verdict.
_Éviter_ : test, validation

**Accord** :
La part des textes distincts (une voix par groupe de jumeaux) où les règles d'aiguillage redonnent la réponse du
modèle d'origine.
_Éviter_ : précision, taux de réussite

**Verdict** :
L'issue d'une preuve : prouvé (accord au-dessus du seuil), refusé (accord en dessous), ou non conclu (pas assez de
textes distincts pour trancher, ce qui n'est pas un échec des règles).
_Éviter_ : pass/reject dans les textes pour les humains

**Par-cœur** :
Une règle d'aiguillage qui recopie un exemple d'extraction (une phrase entière) au lieu de reconnaître un sujet.
_Éviter_ : surapprentissage, overfitting
