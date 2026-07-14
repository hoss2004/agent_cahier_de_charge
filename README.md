# ReqBot - Assistant multi-agent pour la génération de cahier des charges

ReqBot est une plateforme intelligente de spécification logicielle basée sur une architecture multi-agent. Son objectif est de transformer une demande client brute en livrables exploitables pour un projet informatique : requirements structurés, backlog agile, user stories, critères d’acceptation et cahier des charges complet.

Le système fonctionne avec une logique human-in-the-loop : l’utilisateur décrit son besoin, les agents analysent la demande, détectent les informations manquantes, posent des questions de clarification, puis enrichissent progressivement le contexte du projet avant de générer les documents finaux.

## Objectif du projet

Ce projet vise à assister les analystes fonctionnels, product owners et équipes projet dans la phase de cadrage d’un besoin client. ReqBot permet de réduire les ambiguïtés, d’améliorer la qualité des exigences et de produire automatiquement une base documentaire claire pour lancer un projet logiciel.

## Architecture multi-agent

ReqBot repose sur trois agents principaux :

- **Agent 1 - Intake & Clarification**  
  Analyse la demande client initiale, identifie le domaine, les acteurs, l’objectif principal et les informations manquantes. Il génère ensuite des questions ciblées pour clarifier le besoin avec l’utilisateur.

- **Agent 2 - Validation & Analysis**  
  Valide la qualité des informations collectées, détecte les ambiguïtés ou contradictions, puis génère des requirements structurés sous forme `REQ-001`, `REQ-002`, etc. Si les informations sont insuffisantes, il renvoie un feedback à l’Agent 1.

- **Agent 3 - Agile & Backlog**  
  Transforme les requirements en artefacts agiles : epics, features, user stories, critères d’acceptation, priorités MoSCoW, story points et backlog initial.

## Fonctionnalités principales

- Analyse intelligente d’une demande client en texte libre
- Support de fichiers client : texte, PDF, Word et image selon les outils disponibles
- Génération automatique de questions de clarification
- Interaction humaine pour compléter les informations manquantes
- Boucle A2A entre Agent 1 et Agent 2 en cas d’informations insuffisantes
- Génération de requirements fonctionnels et non fonctionnels
- Création d’epics, user stories et critères d’acceptation
- Construction d’un backlog agile initial
- Traçabilité entre requirements, user stories et critères d’acceptation
- Génération d’un cahier des charges complet
- Interface web locale interactive
- Export en Markdown, JSON et PDF

## Cahier des charges généré

Le document final contient notamment :

1. Présentation générale du projet
2. Description des besoins
3. Parties prenantes
4. Spécifications techniques
5. Contraintes du projet
6. Livrables attendus
7. Planning prévisionnel
8. Cas d’usage de test
9. Risques du projet
10. Perspectives d’évolution
11. Requirements détaillés
12. Backlog agile
13. Matrice de traçabilité

## Technologies utilisées

- Python
- Architecture multi-agent
- LangGraph pour l’orchestration
- Gemini / LLM pour l’analyse intelligente
- Interface web HTML, CSS et JavaScript
- Export Markdown, JSON et PDF

## Lancement local

```powershell
cd C:\Users\KATANAPC\Desktop\projet_stage
.\.venv\Scripts\python.exe -B -m interface.web_app