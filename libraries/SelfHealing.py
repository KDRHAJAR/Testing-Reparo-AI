"""Auto-réparation des localisateurs SeleniumLibrary avec Gemini.

Quand un localisateur ne trouve plus aucun élément, la bibliothèque envoie
l'ancien localisateur, la description de l'élément et le HTML de la page à Gemini.
La proposition n'est utilisée que si la confiance dépasse le seuil ET si elle
désigne exactement un élément. Chaque réparation est notée dans healing.json
(dans le dossier de sortie Robot) pour être relue et validée par un humain.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn, RobotNotRunningError

SEUIL_CONFIANCE = float(os.environ.get("SEUIL_CONFIANCE", "0.8"))
MODELE = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
TAILLE_MAX_HTML = 60_000

PROMPT_SYSTEME = """Tu répares des localisateurs Selenium cassés.
On te donne un localisateur qui ne trouve plus aucun élément, la description de l'élément
recherché, et le HTML de la page.
Propose le localisateur de l'élément qui correspond à la description, au format
SeleniumLibrary : id=..., name=..., css=... ou xpath=... Préfère id= quand c'est possible.
N'invente rien : si aucun élément ne correspond clairement, donne une confiance inférieure à 0.5.
Réponds uniquement avec ce JSON : {"localisateur": "...", "confiance": 0.0, "raison": "..."}"""


def nettoyer_html(html):
    """Retire scripts, styles, SVG et commentaires, puis tronque : moins de tokens, même structure."""
    html = re.sub(r"<(script|style|svg)\b.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"\s+", " ", html)
    return html[:TAILLE_MAX_HTML]


def demander_gemini(localisateur, description, html):
    from google import genai
    from google.genai import types

    prompt = (
        f"Localisateur cassé : {localisateur}\n"
        f"Élément recherché : {description}\n"
        f"HTML de la page :\n{html}"
    )
    # Le client doit rester ouvert pendant la requête : il se ferme tout seul quand il est détruit.
    with genai.Client() as client:
        reponse = client.models.generate_content(
            model=MODELE,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=PROMPT_SYSTEME,
                temperature=0,
                response_mime_type="application/json",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
    return json.loads(reponse.text)


class SelfHealing:
    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, fichier="healing.json", demander_llm=None, selenium=None, executer=None, contexte=None):
        self._fichier = fichier
        self._demander_llm = demander_llm or demander_gemini
        self._selenium_injecte = selenium
        self._executer = executer or BuiltIn().run_keyword
        self._contexte = contexte

    # ------------------------------------------------------------ mots-clés Robot

    def cliquer_avec_auto_reparation(self, localisateur, description):
        """Clique sur l'élément ; répare le localisateur s'il est introuvable."""
        self._executer("SeleniumLibrary.Click Element", self._localisateur_utilisable(localisateur, description))

    def saisir_avec_auto_reparation(self, localisateur, texte, description):
        """Saisit le texte dans l'élément ; répare le localisateur s'il est introuvable."""
        self._executer("SeleniumLibrary.Input Text", self._localisateur_utilisable(localisateur, description), texte)

    # ------------------------------------------------------------ logique de réparation

    def _localisateur_utilisable(self, localisateur, description):
        if self._compter(localisateur) > 0:
            return localisateur

        logger.info(f"Localisateur introuvable : {localisateur}. Demande d'auto-réparation.")
        try:
            proposition = self._demander_llm(localisateur, description, nettoyer_html(self._html_de_la_page()))
            nouveau = str(proposition.get("localisateur", "")).strip()
            confiance = float(proposition.get("confiance", 0))
            raison = str(proposition.get("raison", ""))
        except Exception as erreur:  # le LLM ne doit jamais faire planter la campagne autrement
            raise AssertionError(f"Élément introuvable : {localisateur}. Auto-réparation impossible : {erreur}") from erreur

        if not nouveau or confiance < SEUIL_CONFIANCE:
            raise AssertionError(
                f"Élément introuvable : {localisateur}. Aucun équivalent fiable "
                f"(confiance {confiance:.2f} < {SEUIL_CONFIANCE}). "
                "Changement de comportement possible ou bug : à analyser."
            )
        if self._compter(nouveau) != 1:
            raise AssertionError(
                f"Élément introuvable : {localisateur}. Le localisateur proposé « {nouveau} » "
                "ne désigne pas un élément unique : réparation refusée."
            )

        logger.warn(f"Auto-réparé : {localisateur} → {nouveau} (confiance {confiance:.2f}). {raison}")
        self._enregistrer(
            {
                "test": self._variable("${TEST NAME}", "inconnu"),
                "fichier": self._fichier_source(),
                "ancien_localisateur": localisateur,
                "nouveau_localisateur": nouveau,
                "confiance": confiance,
                "raison": raison,
                "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        return nouveau

    # ------------------------------------------------------------ accès à Robot / Selenium

    @property
    def _selenium(self):
        return self._selenium_injecte or BuiltIn().get_library_instance("SeleniumLibrary")

    def _compter(self, localisateur):
        try:
            return len(self._selenium.find_elements(localisateur))
        except Exception:  # syntaxe de localisateur invalide = aucun élément
            return 0

    def _html_de_la_page(self):
        return self._selenium.driver.page_source

    def _variable(self, nom, defaut):
        if self._contexte is not None:
            return self._contexte.get(nom, defaut)
        try:
            return BuiltIn().get_variable_value(nom, defaut)
        except RobotNotRunningError:
            return defaut

    def _fichier_source(self):
        source = self._variable("${SUITE SOURCE}", "")
        racine = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
        try:
            return Path(source).resolve().relative_to(Path(racine).resolve()).as_posix()
        except ValueError:
            return source

    def _enregistrer(self, reparation):
        chemin = Path(self._variable("${OUTPUT DIR}", ".")) / self._fichier
        reparations = json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else []
        reparations.append(reparation)
        chemin.write_text(json.dumps(reparations, ensure_ascii=False, indent=2), encoding="utf-8")