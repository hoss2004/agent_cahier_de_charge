"""
core/llm_client.py
------------------
Point d'entree unique pour appeler le LLM.
Les tools importent call_llm() depuis ici, jamais directement le SDK Google.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

from dotenv import load_dotenv


_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ENV_PATH)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_API_KEY = os.getenv("GEMINI_API_KEY")
_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
_MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.5-flash")
_MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))
_REQUEST_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "60"))
_REQUEST_RETRIES = int(os.getenv("GEMINI_RETRIES", "2"))
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
_OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", str(_REQUEST_TIMEOUT)))
_MOCK_LLM = _env_flag("MOCK_LLM")

_model = None

if not _MOCK_LLM and _LLM_PROVIDER == "gemini":
    if not _API_KEY:
        raise EnvironmentError(
            f"GEMINI_API_KEY manquant. Fichier .env attendu ici : {_ENV_PATH}"
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai

    genai.configure(api_key=_API_KEY)

    _model = genai.GenerativeModel(
        model_name=_MODEL_NAME,
        generation_config=genai.GenerationConfig(
            max_output_tokens=_MAX_TOKENS,
            temperature=0.2,
            response_mime_type="text/plain",
        ),
    )
elif _LLM_PROVIDER not in {"gemini", "ollama", "local"}:
    raise ValueError("LLM_PROVIDER doit etre 'gemini', 'ollama' ou 'local'.")


def _has_any(text: str, words: list[str]) -> bool:
    for word in words:
        pattern = rf"(?<!\w){re.escape(word)}(?!\w)"
        if re.search(pattern, text):
            return True
    return False


def _extract_client_text(user_message: str) -> str:
    markers = [
        "Demande client a analyser :",
        "Demande client à analyser :",
        "Demande client Ã  analyser :",
        "Demande originale :",
        "Demande originale:",
        "Demande originale Ã:",
    ]
    for marker in markers:
        if marker in user_message:
            return user_message.split(marker, 1)[1].strip()
    return user_message.strip()


def _extract_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _detect_domain(text: str) -> tuple[str, list[str]]:
    rules = [
        ("RH", ["conge", "conges", "absence", "absences", "employe", "employes", "manager", "rh", "recrutement", "paie"], ["employe", "manager", "RH", "admin"]),
        ("e-commerce", ["produit", "panier", "commande", "paiement", "livraison", "client", "boutique", "stock"], ["client", "admin", "vendeur"]),
        ("sante", ["patient", "medecin", "rendez-vous", "consultation", "clinique", "dossier medical", "pharmacie"], ["patient", "medecin", "secretaire", "admin"]),
        ("education", ["etudiant", "cours", "enseignant", "formation", "classe", "examen", "note"], ["etudiant", "enseignant", "admin"]),
        ("culture / patrimoine", ["patrimoine", "culture", "culturel", "musee", "monument", "archive", "tourisme"], ["visiteur", "administrateur", "contributeur culturel"]),
        ("finance", ["facture", "budget", "paiement", "transaction", "banque", "credit", "comptabilite"], ["client", "agent financier", "admin"]),
        ("logistique", ["livraison", "chauffeur", "vehicule", "colis", "trajet", "entrepot"], ["operateur", "chauffeur", "admin"]),
    ]
    for domain, keywords, actors in rules:
        if _has_any(text, keywords):
            return domain, actors
    return "Non determine", ["utilisateur", "admin"]


def _detect_project_type(text: str) -> str:
    if _has_any(text, ["mobile", "android", "ios"]):
        return "application mobile"
    if _has_any(text, ["api", "rest", "endpoint"]):
        return "API REST"
    if _has_any(text, ["site", "web", "dashboard", "tableau de bord", "plateforme", "application", "boutique"]) or "en ligne" in text:
        return "application web"
    if _has_any(text, ["iot", "capteur", "embarque"]):
        return "systeme embarque"
    if _has_any(text, ["chatbot", "assistant"]):
        return "assistant conversationnel"
    return "application logicielle"


def _detect_features(text: str, domain: str) -> list[str]:
    feature_rules = [
        ("authentification et gestion des comptes", ["login", "connexion", "inscription", "compte", "mot de passe"]),
        ("soumission de demandes", ["demande", "soumettre", "deposer", "reservation", "rendez-vous"]),
        ("validation ou refus par un responsable", ["valider", "approuver", "refuser", "manager", "responsable"]),
        ("notifications", ["notification", "email", "sms", "alerte"]),
        ("tableau de bord et statistiques", ["dashboard", "tableau de bord", "statistique", "rapport"]),
        ("recherche et filtrage", ["rechercher", "filtrer", "tri"]),
        ("export de donnees", ["export", "pdf", "excel", "csv"]),
        ("gestion des documents", ["document", "fichier", "pdf", "word", "upload"]),
        ("paiement en ligne", ["paiement", "payer", "transaction"]),
        ("gestion du stock", ["stock", "inventaire"]),
        ("suivi de statut", ["suivi", "statut", "historique"]),
    ]
    features = [label for label, keywords in feature_rules if _has_any(text, keywords)]

    if domain == "RH" and _has_any(text, ["conge", "conges", "absence", "absences"]):
        features.insert(0, "gestion des absences et conges")
    if domain == "e-commerce" and _has_any(text, ["produit", "commande", "panier"]):
        features.insert(0, "catalogue produits et gestion des commandes")
    if domain == "sante" and _has_any(text, ["rendez-vous", "patient", "consultation"]):
        features.insert(0, "gestion des patients et rendez-vous")
    if domain == "culture / patrimoine" and _has_any(text, ["patrimoine", "culture", "musee", "monument", "archive"]):
        features.insert(0, "valorisation et conservation du patrimoine culturel")

    if not features:
        features = ["gestion des donnees principales", "consultation et mise a jour des informations"]

    return list(dict.fromkeys(features))


def _detect_missing_info(text: str, domain: str, project_type: str) -> list[str]:
    missing = []
    if domain == "Non determine":
        missing.append("domaine metier exact")
    if project_type == "application logicielle":
        missing.append("type de solution attendu")
    if not _has_any(text, ["role", "roles", "profil", "profils", "admin", "manager", "client", "employe", "patient"]):
        missing.append("roles et permissions")
    if _has_any(text, ["demande", "soumettre", "validation", "valider", "approuver"]) and not _has_any(text, ["qui valide", "manager", "responsable", "rh", "admin"]):
        missing.append("workflow de validation")
    if not _has_any(text, ["notification", "email", "sms", "alerte"]):
        missing.append("notifications")
    if not _has_any(text, ["securite", "authentification", "connexion", "mot de passe"]):
        missing.append("securite et authentification")
    if len(re.findall(r"\w+", text)) < 18:
        missing.append("perimetre fonctionnel detaille")
    if domain in {"RH", "finance", "sante"} and not _has_any(text, ["rgpd", "confidentialite", "donnees personnelles"]):
        missing.append("contraintes de confidentialite")
    return missing[:6]


def _local_analyze(user_message: str) -> dict:
    client_text = _extract_client_text(user_message)
    normalized = client_text.lower()
    domain, actors = _detect_domain(normalized)
    project_type = _detect_project_type(normalized)
    features = _detect_features(normalized, domain)
    missing = _detect_missing_info(normalized, domain, project_type)

    objective = client_text.strip().rstrip(".")
    if objective:
        objective = objective[0].upper() + objective[1:]
    else:
        objective = "Clarifier la demande client et definir le besoin."

    return {
        "domaine": domain,
        "type_projet": project_type,
        "acteurs": actors,
        "objectif_principal": objective,
        "fonctionnalites_identifiees": features,
        "informations_manquantes": missing,
    }


def _question_for_missing_item(item: str, domain: str) -> str:
    if "domaine" in item:
        return "Quel est le domaine metier exact du projet ?"
    if "type de solution" in item:
        return "La solution attendue est-elle une application web, mobile, API ou autre ?"
    if "roles" in item or "permissions" in item:
        return "Quels profils utilisateurs doivent acceder au systeme et avec quels droits ?"
    if "workflow" in item or "validation" in item:
        return "Qui valide les demandes et quelles sont les etapes de validation ?"
    if "notifications" in item:
        return "Faut-il envoyer des notifications, et par quel canal : email, SMS ou notification interne ?"
    if "securite" in item or "authentification" in item:
        return "Quel niveau d'authentification et de securite est attendu ?"
    if "perimetre" in item:
        return "Quelles fonctionnalites sont obligatoires dans la premiere version ?"
    if "confidentialite" in item:
        return "Quelles contraintes de confidentialite ou de protection des donnees doivent etre respectees ?"
    return f"Pouvez-vous preciser le point suivant : {item} ?"


def _local_questions(user_message: str) -> list[str]:
    info = _extract_json_object(user_message) or _local_analyze(user_message)
    domain = info.get("domaine", "Non determine")
    missing_items = info.get("informations_manquantes", [])
    questions = [_question_for_missing_item(item, domain) for item in missing_items]

    if domain == "RH":
        questions.insert(0, "Quels types d'absences ou de conges doivent etre geres ?")
    elif domain == "e-commerce":
        questions.insert(0, "Quels types de produits, commandes et paiements doivent etre geres ?")
    elif domain == "sante":
        questions.insert(0, "Quels types de donnees patients ou rendez-vous doivent etre geres ?")
    elif domain == "culture / patrimoine":
        questions.insert(0, "Quels types de contenus patrimoniaux doivent etre conserves et presentes ?")

    if not questions:
        questions = [
            "Quels sont les objectifs prioritaires du projet ?",
            "Quels utilisateurs utiliseront le systeme ?",
            "Quelles fonctionnalites sont obligatoires dans la premiere version ?",
        ]

    return list(dict.fromkeys(questions))[:5]


def _mock_response(system_prompt: str, user_message: str) -> str:
    """Mode de secours pour demo locale quand l'API Gemini est indisponible."""
    prompt = system_prompt.lower()

    if "tableau json" in prompt or "questions de clarification" in prompt:
        return json.dumps(_local_questions(user_message), ensure_ascii=False)

    return json.dumps(_local_analyze(user_message), ensure_ascii=False)


def _call_ollama(system_prompt: str, user_message: str) -> str:
    prompt = f"{system_prompt}\n\n---\n\n{user_message}"
    payload = {
        "model": _OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": _MAX_TOKENS,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{_OLLAMA_URL}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_OLLAMA_TIMEOUT) as response:
            body = response.read().decode("utf-8")
    except TimeoutError as e:
        raise RuntimeError(
            f"Ollama a depasse le timeout ({_OLLAMA_TIMEOUT}s). "
            "Reduis la sortie demandee ou augmente OLLAMA_TIMEOUT."
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            "Ollama n'est pas joignable sur "
            f"{_OLLAMA_URL}. Lance d'abord : ollama serve"
        ) from e

    try:
        result = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Reponse Ollama invalide : {body[:300]}") from e

    text = result.get("response", "").strip()
    if not text:
        raise RuntimeError("Reponse vide recue de Ollama.")
    return text


def call_llm(system_prompt: str, user_message: str) -> str:
    """
    Appelle Gemini avec un system prompt et un message utilisateur.
    Si MOCK_LLM=true, utilise un mode de secours local non destine a la production.
    """
    if _MOCK_LLM or _LLM_PROVIDER == "local":
        return _mock_response(system_prompt, user_message)

    if _LLM_PROVIDER == "ollama":
        return _call_ollama(system_prompt, user_message)

    if _model is None:
        raise RuntimeError("Client Gemini non initialise.")

    full_prompt = f"{system_prompt}\n\n---\n\n{user_message}"

    last_error: Exception | None = None
    for attempt in range(1, _REQUEST_RETRIES + 2):
        try:
            response = _model.generate_content(
                full_prompt,
                request_options={"timeout": _REQUEST_TIMEOUT},
            )
            text = response.text.strip()
            if not text:
                raise RuntimeError("Reponse vide recue de Gemini.")
            return text
        except Exception as e:
            message = str(e).lower()
            last_error = e

            if "429" in message or "quota" in message:
                raise RuntimeError(
                    "Quota Gemini depasse. L'agent intelligent a besoin d'un appel LLM reel. "
                    "Attends le reset du quota, change de cle API/projet, ou active MOCK_LLM=true "
                    "uniquement pour une demo locale."
                ) from e

            retryable = any(
                marker in message
                for marker in ("504", "deadline", "timeout", "temporarily", "unavailable")
            )
            if retryable and attempt <= _REQUEST_RETRIES:
                time.sleep(min(2 * attempt, 8))
                continue

            break

    raise RuntimeError(f"Erreur API Gemini apres retries : {last_error}") from last_error


def call_llm_json(system_prompt: str, user_message: str) -> dict | list:
    """
    Appelle le LLM et parse la reponse en JSON.
    Le system_prompt doit demander explicitement une reponse JSON pure.
    """
    raw = call_llm(system_prompt, user_message)

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        candidates = []
        object_start = cleaned.find("{")
        object_end = cleaned.rfind("}")
        if object_start != -1 and object_end > object_start:
            candidates.append(cleaned[object_start : object_end + 1])

        array_start = cleaned.find("[")
        array_end = cleaned.rfind("]")
        if array_start != -1 and array_end > array_start:
            candidates.append(cleaned[array_start : array_end + 1])

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        raise ValueError(
            f"Impossible de parser la reponse JSON du LLM.\n"
            f"Erreur : {e}\n"
            f"Reponse brute :\n{raw[:500]}"
        ) from e
