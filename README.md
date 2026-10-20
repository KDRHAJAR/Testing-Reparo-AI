# POC : auto-réparation des tests Robot Framework

Une campagne **TNR0** d'un seul test, exécutée dans **GitHub Actions**. Le test contient
un localisateur volontairement faux (`id=login-buton` au lieu de `id=login-button`) sur
https://www.saucedemo.com. Pendant l'exécution, la bibliothèque `SelfHealing` demande à
Gemini un localisateur de remplacement, le vérifie, continue le test et note la réparation
dans `healing.json`. Un second job applique la correction et ouvre une **Pull Request**
qui t'est assignée : GitHub t'envoie alors un email.

```
              PRÉPARATION                 CAMPAGNE                 RÉPARATION
         ┌─────────────────┐
Run  ──▶ │ tests_unitaires │──┐
workflow │ dry_run_robot   │──┴──▶ tnr0 : robot --include TNR0 ──▶ pull_request ──▶ email
         └─────────────────┘        (healing.json en artefact)    (si ≥ 1 réparation)
```

`tnr0` ne démarre que si les tests unitaires et le dry run Robot ont réussi.

## Fichiers

| Fichier | Rôle |
|---|---|
| `libraries/SelfHealing.py` | Les mots-clés `Cliquer Avec Auto Reparation` et `Saisir Avec Auto Reparation` |
| `tests/connexion.robot` | Le test unique, tag `TNR0` |
| `scripts/appliquer_reparations.py` | Applique `healing.json` aux fichiers `.robot` (seulement dans les cellules de mots-clés, jamais dans la Documentation) et écrit le texte de la Pull Request |
| `.github/workflows/tnr0.yml` | Le workflow, lancé à la main |
| `tests_unitaires/` | Les tests de la logique, avec un faux navigateur et un faux Gemini |

## Règles de sécurité de la réparation

- La proposition de Gemini est utilisée seulement si sa **confiance ≥ 0,8** (variable `SEUIL_CONFIANCE`)
  **et** si elle désigne **exactement un élément** de la page.
- Sinon, le test échoue normalement, avec le message « Changement de comportement possible ou bug : à analyser ».
- Le code des tests n'est jamais modifié pendant l'exécution : la correction passe par une Pull Request à valider.
- Le HTML de la page est envoyé à Gemini. C'est sans risque pour saucedemo.com (site public de démonstration),
  mais vérifie la politique de ton entreprise avant de l'utiliser sur une application interne.

## Configuration sur GitHub (une seule fois)

1. Pousse ce dossier dans un nouveau dépôt GitHub.
2. **Settings → Secrets and variables → Actions → New repository secret** :
   nom `GEMINI_API_KEY`, valeur = ta clé Gemini.
3. Facultatif, dans l'onglet **Variables** : `GEMINI_MODEL` (par exemple `gemini-3.8-flash`).
   Sans cette variable, le modèle est `gemini-2.5-flash`.
4. **Settings → Actions → General → Workflow permissions** :
   coche **Allow GitHub Actions to create and approve pull requests**, puis **Save**.
5. Pour recevoir l'email : **Settings (de ton profil) → Notifications** → active les emails pour « Participating ».

## Lancer la campagne

**Actions → Campagne TNR0 (auto-réparation) → Run workflow**.

Résultat attendu :
- le job `tnr0` est vert, avec un avertissement `Auto-réparé : id=login-buton → id=login-button` dans le log Robot ;
- l'artefact `resultats-tnr0` contient `log.html`, `report.html`, `output.xml` et `healing.json` ;
- le job `pull_request` ouvre une Pull Request qui t'est assignée, avec le tableau des réparations.

Après la fusion de la Pull Request, relance la campagne : le test passe sans réparation, et aucune nouvelle Pull Request n'est créée.

## Tests en local

```bash
pip install -r requirements.txt
python -m pytest -q tests_unitaires
robot --dryrun --include TNR0 --outputdir results tests
```

Pour exécuter le vrai test en local, il faut Google Chrome et la variable `GEMINI_API_KEY` :
`robot --include TNR0 --outputdir results tests`.