---
title: ReqBot
emoji: 🧩
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
fullWidth: true
header: mini
short_description: Multi-agent requirements assistant with HITL, A2A feedback, backlog and cahier des charges export.
tags:
  - agents
  - requirements
  - langgraph
  - product-management
  - software-engineering
---

# ReqBot — Assistant multi-agent de spécification

ReqBot transforme une demande client brute en cahier des charges exploitable :

- Agent 1 : intake, analyse et clarification human-in-the-loop.
- Agent 2 : validation, détection d'ambiguïtés, feedback A2A et requirements.
- Agent 3 : epics, features, user stories, critères d'acceptation et backlog.
- Export : Markdown, PDF et JSON SharedState.

## Déploiement Hugging Face Spaces

Ce dépôt est prêt pour un Space Docker. Hugging Face lit le bloc YAML ci-dessus ; `sdk: docker` active le runtime Docker et `app_port: 7860` expose le port de l'application.

Par défaut, le Dockerfile démarre en mode démo local :

```text
MOCK_LLM=true
LLM_PROVIDER=local
```

Pour utiliser un vrai LLM dans le Space, ajoute ces variables dans **Settings → Variables and secrets** :

```text
MOCK_LLM=false
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
MODEL_NAME=gemini-3.5-flash
```

## Lancement local

```powershell
python -m interface.web_app
```

Puis ouvrir :

```text
http://127.0.0.1:8000
```

## Notes

- Ne pousse jamais `.env` sur Hugging Face ou GitHub.
- Les exports générés localement sont ignorés par Git.
- Sur Hugging Face, les fichiers temporaires sont écrits dans `/tmp`.
"# agent_cahier_de_charge" 
