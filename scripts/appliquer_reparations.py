"""Applique les réparations de healing.json aux fichiers .robot et écrit le texte de la Pull Request."""

import argparse
import json
import re
import sys
from pathlib import Path


def cellule(localisateur):
    """Le localisateur comme cellule entière d'une ligne Robot (séparée par 2 espaces ou une tabulation).
    Ainsi, le même texte dans une Documentation ou un commentaire n'est pas modifié."""
    return re.compile(r"(?:(?<=  )|(?<=\t))" + re.escape(localisateur) + r"(?=  |\t|$)", re.MULTILINE)


def appliquer(reparations, racine="."):
    """Remplace chaque ancien localisateur par le nouveau. Renvoie les fichiers modifiés."""
    modifies = set()
    for r in reparations:
        chemin = Path(racine) / r["fichier"]
        contenu = chemin.read_text(encoding="utf-8")
        nouveau_contenu, nombre = cellule(r["ancien_localisateur"]).subn(r["nouveau_localisateur"], contenu)
        if nombre:
            chemin.write_text(nouveau_contenu, encoding="utf-8")
            modifies.add(r["fichier"])
    return sorted(modifies)


def corps_pull_request(reparations):
    lignes = [
        "## Auto-réparation des localisateurs",
        "",
        "Ces localisateurs ont été réparés automatiquement pendant la campagne TNR0.",
        "**Vérifie chaque ligne avant de fusionner** : une réparation peut masquer un vrai changement de comportement.",
        "",
        "| Test | Fichier | Ancien | Nouveau | Confiance | Raison |",
        "|---|---|---|---|---|---|",
    ]
    for r in reparations:
        lignes.append(
            f"| {r['test']} | `{r['fichier']}` | `{r['ancien_localisateur']}` | "
            f"`{r['nouveau_localisateur']}` | {r['confiance']:.2f} | {r['raison']} |"
        )
    return "\n".join(lignes) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("healing", help="Chemin de healing.json")
    parser.add_argument("--corps", default="pr_body.md", help="Fichier où écrire le texte de la Pull Request")
    args = parser.parse_args()

    reparations = json.loads(Path(args.healing).read_text(encoding="utf-8"))
    modifies = appliquer(reparations)
    if not modifies:
        print("Aucune réparation applicable.")
        return 1
    Path(args.corps).write_text(corps_pull_request(reparations), encoding="utf-8")
    print("Fichiers corrigés :", ", ".join(modifies))
    return 0


if __name__ == "__main__":
    sys.exit(main())