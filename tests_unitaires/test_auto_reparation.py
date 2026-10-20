import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "libraries"))
sys.path.insert(0, str(RACINE / "scripts"))

import appliquer_reparations as script  # noqa: E402
from SelfHealing import SelfHealing, nettoyer_html  # noqa: E402

PAGE = '<html><script>var x=1;</script><input id="user-name"><button id="login-button">Login</button></html>'


class FauxSelenium:
    def __init__(self, elements):
        self.elements = elements  # localisateur -> nombre d'éléments trouvés
        self.driver = SimpleNamespace(page_source=PAGE)

    def find_elements(self, localisateur):
        return [object()] * self.elements.get(localisateur, 0)


def creer(tmp_path, proposition, elements=None):
    actions, appels_llm = [], []

    def faux_llm(localisateur, description, html):
        appels_llm.append((localisateur, description, html))
        if isinstance(proposition, Exception):
            raise proposition
        return proposition

    lib = SelfHealing(
        demander_llm=faux_llm,
        selenium=FauxSelenium(elements or {"id=login-button": 1, "id=user-name": 1}),
        executer=lambda *args: actions.append(args),
        contexte={
            "${TEST NAME}": "Connexion avec un utilisateur standard",
            "${SUITE SOURCE}": str(tmp_path / "tests" / "connexion.robot"),
            "${OUTPUT DIR}": str(tmp_path),
        },
    )
    return lib, actions, appels_llm


def lire_healing(tmp_path):
    chemin = tmp_path / "healing.json"
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else []


def test_localisateur_valide_aucun_appel_au_llm(tmp_path):
    lib, actions, appels = creer(tmp_path, {})
    lib.cliquer_avec_auto_reparation("id=login-button", "Bouton Login")
    assert actions == [("SeleniumLibrary.Click Element", "id=login-button")]
    assert appels == [] and lire_healing(tmp_path) == []


def test_localisateur_casse_est_repare_et_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    lib, actions, appels = creer(tmp_path, {"localisateur": "id=login-button", "confiance": 0.95, "raison": "Même texte Login"})
    lib.cliquer_avec_auto_reparation("id=login-buton", "Bouton Login")

    assert actions == [("SeleniumLibrary.Click Element", "id=login-button")]
    assert "<script>" not in appels[0][2]  # le HTML envoyé au LLM est nettoyé
    [reparation] = lire_healing(tmp_path)
    assert reparation["ancien_localisateur"] == "id=login-buton"
    assert reparation["nouveau_localisateur"] == "id=login-button"
    assert reparation["fichier"] == "tests/connexion.robot"
    assert reparation["test"] == "Connexion avec un utilisateur standard"


def test_saisie_reparee(tmp_path):
    lib, actions, _ = creer(tmp_path, {"localisateur": "id=user-name", "confiance": 0.9, "raison": ""})
    lib.saisir_avec_auto_reparation("id=username", "standard_user", "Champ utilisateur")
    assert actions == [("SeleniumLibrary.Input Text", "id=user-name", "standard_user")]


def test_confiance_trop_basse_pas_de_reparation(tmp_path):
    lib, actions, _ = creer(tmp_path, {"localisateur": "id=login-button", "confiance": 0.4, "raison": "Page différente"})
    with pytest.raises(AssertionError, match="Changement de comportement possible ou bug"):
        lib.cliquer_avec_auto_reparation("id=page-supprimee", "Bouton Payer")
    assert actions == [] and lire_healing(tmp_path) == []


def test_proposition_non_unique_refusee(tmp_path):
    lib, actions, _ = creer(
        tmp_path, {"localisateur": "css=button", "confiance": 0.9, "raison": ""}, elements={"css=button": 3}
    )
    with pytest.raises(AssertionError, match="élément unique"):
        lib.cliquer_avec_auto_reparation("id=login-buton", "Bouton Login")
    assert actions == [] and lire_healing(tmp_path) == []


def test_proposition_inexistante_refusee(tmp_path):
    lib, actions, _ = creer(tmp_path, {"localisateur": "id=invente", "confiance": 0.99, "raison": ""})
    with pytest.raises(AssertionError, match="élément unique"):
        lib.cliquer_avec_auto_reparation("id=login-buton", "Bouton Login")
    assert actions == []


def test_erreur_du_llm_fait_echouer_proprement(tmp_path):
    lib, actions, _ = creer(tmp_path, RuntimeError("quota dépassé"))
    with pytest.raises(AssertionError, match="Auto-réparation impossible : quota dépassé"):
        lib.cliquer_avec_auto_reparation("id=login-buton", "Bouton Login")
    assert actions == []


def test_plusieurs_reparations_sont_ajoutees(tmp_path):
    lib, _, _ = creer(tmp_path, {"localisateur": "id=login-button", "confiance": 0.95, "raison": ""})
    lib.cliquer_avec_auto_reparation("id=login-buton", "Bouton Login")
    lib.cliquer_avec_auto_reparation("id=btn-login", "Bouton Login")
    assert len(lire_healing(tmp_path)) == 2


def test_nettoyer_html():
    html = nettoyer_html('<style>a{}</style><!-- note --><svg><path/></svg><p>  Bonjour   </p>')
    assert html == "<p> Bonjour </p>"


def test_appliquer_corrige_le_fichier_robot(tmp_path):
    (tmp_path / "tests").mkdir()
    robot = tmp_path / "tests" / "connexion.robot"
    robot.write_text("    Cliquer Avec Auto Reparation    id=login-buton   Bouton\n", encoding="utf-8")
    reparations = [
        {"test": "T", "fichier": "tests/connexion.robot", "ancien_localisateur": "id=login-buton",
         "nouveau_localisateur": "id=login-button", "confiance": 0.95, "raison": "Même texte"}
    ]
    assert script.appliquer(reparations, racine=tmp_path) == ["tests/connexion.robot"]
    assert "id=login-button " in robot.read_text(encoding="utf-8")
    assert "login-buton " not in robot.read_text(encoding="utf-8")

    corps = script.corps_pull_request(reparations)
    assert "| T | `tests/connexion.robot` | `id=login-buton` | `id=login-button` | 0.95 | Même texte |" in corps
    assert "Vérifie chaque ligne" in corps


def test_appliquer_sans_correspondance(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "connexion.robot").write_text("rien\n", encoding="utf-8")
    reparations = [{"fichier": "tests/connexion.robot", "ancien_localisateur": "id=x", "nouveau_localisateur": "id=y"}]
    assert script.appliquer(reparations, racine=tmp_path) == []


class FausseConnexion:
    ferme = False


class FauxClientGemini:
    """Imite le vrai client : il se ferme quand il est détruit (__del__) ou à la sortie du bloc with."""

    def __init__(self):
        connexion = self.connexion = FausseConnexion()
        FauxClientGemini.derniere_connexion = connexion

        def generate_content(**kwargs):
            if connexion.ferme:
                raise RuntimeError("Cannot send a request, as the client has been closed.")
            return SimpleNamespace(text='{"localisateur": "id=login-button", "confiance": 0.93, "raison": "ok"}')

        self.models = SimpleNamespace(generate_content=generate_content)

    def close(self):
        self.connexion.ferme = True

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_demander_gemini_garde_le_client_ouvert_pendant_la_requete(monkeypatch):
    import SelfHealing as module

    monkeypatch.setattr("google.genai.Client", FauxClientGemini)
    proposition = module.demander_gemini("id=login-buton", "Bouton Login", "<button id='login-button'>")
    assert proposition == {"localisateur": "id=login-button", "confiance": 0.93, "raison": "ok"}
    assert FauxClientGemini.derniere_connexion.ferme  # fermé proprement APRÈS la requête