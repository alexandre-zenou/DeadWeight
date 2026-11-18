# Le seuil de preuve suit la stabilité du modèle d'origine

Un seuil fixe à 95 % peut être plus exigeant que le modèle d'origine lui-même : sur le Récap Gmail (100 mails
variés), gpt-4o-mini redonné les mêmes mails avec la même consigne ne redonne la même case que 92 fois sur 100.
Même une copie du modèle serait refusée. Le seuil devient donc la stabilité mesurée moins 2 points, sans jamais
dépasser 95 % ni descendre sous 80 % (sous ce plancher, c'est le modèle d'origine qu'on signale comme instable).
Mesurer la stabilité demande de rappeler le modèle d'origine, avec ses réglages d'origine, sur les textes de la
preuve : on ne le fait qu'avec la clé que le client a donnée exprès, jamais avec celle qui transite par la
passerelle. Sans clé, on mesure la stabilité gratuitement sur les jumeaux de l'historique : un groupe de jumeaux
rangé dans plusieurs cases montre que le modèle change d'avis tout seul. Si les deux mesures sont possibles, la clé l'emporte : elle porte sur les textes mêmes de la preuve. Sans mesure possible (moins de 30 textes
rappelés ou de 30 groupes de jumeaux), le seuil reste 95 %.

## Options écartées

- Garder 95 % partout : refuse des remplaçants aussi fiables que le modèle d'origine.
- Utiliser la clé vue par la passerelle : elle n'est jamais gardée, c'est une promesse du produit, et ces appels
  seraient facturés au client sans son accord.
