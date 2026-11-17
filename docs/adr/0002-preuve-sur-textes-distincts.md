# La preuve se fait sur des textes distincts, et juge le résultat, pas la forme des règles

Exclure de la preuve les appels montrés à l'extraction ne suffit pas : un trafic répétitif contient des jumeaux de ces
exemples, et des règles par-cœur (phrases entières recopiées) y passent à 95 % sans rien généraliser. La preuve exclut
donc aussi les jumeaux des exemples d'extraction. En revanche, on n'interdit pas les règles par-cœur : chez un client
dont le trafic se répète vraiment (e-mails automatiques, formulaires), elles sont justes et utiles. Si la preuve sur
textes distincts passe, la règle est acceptée ; le verdict signale seulement les règles qui ressemblent à du par-cœur.

## Options écartées

- Exclure seulement les appels d'extraction (l'existant) : la preuve mesure la mémoire, pas la généralisation.
- Interdire les phrases longues à l'extraction : casse le cas légitime du trafic répétitif.

## Conséquences

- L'accord se compte par texte distinct (une voix par groupe de jumeaux) : sinon une phrase facile répétée trente
  fois cache les échecs sur les phrases rares. Les économies, elles, se comptent toujours par appel.
- Sur un trafic trop répétitif, il reste moins de textes distincts que le minimum : le verdict est « non conclu »,
  pas « refusé ». Des verdicts « prouvé » obtenus sur le jeu de test v1 (groupe `reviews`) deviennent « non conclu ».
