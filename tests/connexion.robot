*** Settings ***
Documentation     Campagne TNR0 : un seul test, avec un localisateur volontairement faux
...               (id=login-buton au lieu de id=login-button) pour démontrer l'auto-réparation.
Library           SeleniumLibrary
Library           ../libraries/SelfHealing.py
Test Teardown     Close All Browsers

*** Variables ***
${URL}            https://www.saucedemo.com/
${OPTIONS}        add_argument("--headless=new");add_argument("--no-sandbox");add_argument("--window-size=1280,900")

*** Test Cases ***
Connexion avec un utilisateur standard
    [Tags]    TNR0
    Open Browser    ${URL}    chrome    options=${OPTIONS}
    Saisir Avec Auto Reparation     id=user-name     standard_user    Champ nom d'utilisateur
    Saisir Avec Auto Reparation     id=password      secret_sauce     Champ mot de passe
    Cliquer Avec Auto Reparation    id=login-buton   Bouton de connexion « Login »
    Wait Until Page Contains Element    css=.inventory_list    10s
