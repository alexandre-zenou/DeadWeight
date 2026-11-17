# Les règles d'aiguillage sont fidèles au modèle d'origine, pas à la vérité

Quand DeadWeight remplace un aiguillage par des règles, la cible est la réponse que le modèle d'origine donnait, y
compris quand elle était fausse (exemple : « je veux supprimer mon compte définitivement » classé spam par
gpt-4o-mini). On remplace sans changer le comportement, et c'est ce qui permet une preuve sur le trafic du client sans
étiquettes humaines, qu'on n'a pas. Une erreur du modèle d'origine fait l'objet d'un constat à part, jamais d'une
correction cachée dans les règles.
