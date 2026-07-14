"""
interface/web_app.py
--------------------
Petite plateforme web locale pour piloter les agents depuis le navigateur.

Lancement :
    python -m interface.web_app
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import uuid
import warnings
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.state import SharedState, initial_state
from core.tracing import add_trace
from tools.file_reader import file_reader


with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import cgi


ROOT_DIR = Path(__file__).resolve().parents[1]
INTERFACE_DIR = ROOT_DIR / "interface"
INDEX_PATH = INTERFACE_DIR / "index.html"
UPLOAD_DIR = Path(os.getenv("REQBOT_UPLOAD_DIR", ROOT_DIR / ".tmp" / "uploads"))
OUTPUT_DIR = Path(os.getenv("REQBOT_OUTPUT_DIR", ROOT_DIR / "outputs"))
DEFAULT_HOST = "0.0.0.0" if os.getenv("SPACE_ID") else "127.0.0.1"
HOST = os.getenv("REQBOT_HOST", DEFAULT_HOST)
PORT = int(os.getenv("PORT") or os.getenv("REQBOT_PORT", "8000"))
os.environ.setdefault("OLLAMA_TIMEOUT", os.getenv("REQBOT_OLLAMA_TIMEOUT", "45"))
os.environ.setdefault("GEMINI_TIMEOUT", os.getenv("REQBOT_GEMINI_TIMEOUT", "45"))

PROJECTS: dict[str, dict] = {}


def _norm_text(text: object) -> str:
    normalized = str(text or "").strip().lower()
    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "â": "a",
        "î": "i",
        "ô": "o",
        "ù": "u",
        "û": "u",
        "ç": "c",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"\s+", " ", normalized)


def _looks_like_project_request(text: str) -> bool:
    normalized = _norm_text(text)
    if not normalized:
        return False
    greetings = {"bonjour", "salut", "hello", "hi", "bonsoir", "coucou", "slt", "cc"}
    if normalized in greetings:
        return False
    project_keywords = (
        "je veux",
        "application",
        "site",
        "plateforme",
        "systeme",
        "web",
        "mobile",
        "projet",
        "gerer",
        "gestion",
        "creer",
        "besoin",
        "client",
        "utilisateur",
        "fonctionnalite",
        "exigence",
    )
    if any(keyword in normalized for keyword in project_keywords):
        return True
    return len(normalized.split()) >= 8


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name or "upload")
    return cleaned.strip("._")[:80] or "upload"


def _write_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _write_error(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    _write_json(handler, {"ok": False, "error": message}, status=status)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _read_start_payload(handler: BaseHTTPRequestHandler) -> tuple[str, Path | None]:
    content_type = handler.headers.get("Content-Type", "")
    if content_type.startswith("multipart/form-data"):
        form = cgi.FieldStorage(
            fp=handler.rfile,
            headers=handler.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
            },
        )
        raw_input = ""
        if "raw_input" in form:
            field = form["raw_input"]
            raw_input = str(field.value or "").strip()

        upload_path = None
        if "file" in form:
            file_field = form["file"]
            if getattr(file_field, "filename", None):
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                safe_name = _safe_filename(file_field.filename)
                upload_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{safe_name}"
                with upload_path.open("wb") as target:
                    target.write(file_field.file.read())
        return raw_input, upload_path

    payload = _read_json(handler)
    return str(payload.get("raw_input", "")).strip(), None


def _initial_state_from_input(raw_input: str, upload_path: Path | None) -> SharedState:
    state = initial_state(raw_input=raw_input)

    if upload_path is None:
        return state

    file_state = initial_state(raw_input="")
    file_state = file_reader(file_state, file_path=str(upload_path))
    state["errors"].extend(file_state.get("errors", []))
    file_text = str(file_state.get("raw_input", "") or "").strip()

    if raw_input and file_text:
        state["raw_input"] = (
            f"{raw_input}\n\n--- Contenu du fichier joint ---\n{file_text}"
        )
    elif file_text:
        state["raw_input"] = file_text

    return state


def _fallback_a2a_questions(state: SharedState) -> list[str]:
    from agents.agent2_validation import get_a2a_questions

    questions = get_a2a_questions(state)
    if questions:
        return questions

    if not state.get("a2a_feedback"):
        return []

    validation = (state.get("consolidated_data") or {}).get("agent2_validation", {}) or {}
    missing = validation.get("missing_information", []) or []
    ambiguities = validation.get("ambiguities", []) or []

    fallback = [f"Pouvez-vous preciser : {item} ?" for item in missing]
    fallback.extend(f"Pouvez-vous clarifier l'ambiguite suivante : {item} ?" for item in ambiguities)
    if not fallback:
        fallback = [
            "Pouvez-vous donner une reponse plus concrete avec roles, regles, statuts, donnees ou delais ?"
        ]
    return fallback[:5]


def _phase(state: SharedState, pending_a2a_questions: list[str] | None = None) -> str:
    if pending_a2a_questions:
        return "a2a"
    if state.get("user_stories"):
        return "complete"
    if state.get("requirements"):
        return "requirements"
    if state.get("ready_for_agent2"):
        return "ready_for_agent2"
    if state.get("human_input_required"):
        return "clarification"
    return state.get("workflow_status", "unknown")


def _summary(project_id: str) -> dict:
    project = PROJECTS[project_id]
    state = project["state"]
    pending_a2a_questions = project.get("pending_a2a_questions", [])
    validation = (state.get("consolidated_data") or {}).get("agent2_validation", {})

    return {
        "ok": True,
        "project_id": project_id,
        "phase": _phase(state, pending_a2a_questions),
        "workflow_status": state.get("workflow_status"),
        "current_agent": state.get("current_agent"),
        "next_agent": state.get("next_agent"),
        "human_input_required": state.get("human_input_required"),
        "ready_for_agent2": state.get("ready_for_agent2"),
        "raw_input": state.get("raw_input"),
        "extracted_info": state.get("extracted_info"),
        "clarification_questions": state.get("clarification_questions", []),
        "stakeholder_answers": state.get("stakeholder_answers", []),
        "answer_quality_issues": state.get("answer_quality_issues", []),
        "a2a_questions": pending_a2a_questions,
        "validation": validation,
        "requirements": state.get("requirements", []),
        "epics": state.get("epics", []),
        "features": state.get("features", []),
        "user_stories": state.get("user_stories", []),
        "backlog": state.get("backlog", []),
        "traceability_matrix": state.get("traceability_matrix", []),
        "agent_trace": state.get("agent_trace", []),
        "errors": state.get("errors", []),
        "exports": project.get("exports", {}),
        "chat_history": project.get("chat_history", []),
    }


def _get_project(handler: BaseHTTPRequestHandler, payload: dict | None = None) -> tuple[str, dict] | None:
    if payload is None:
        query = parse_qs(urlparse(handler.path).query)
        project_id = (query.get("id") or [""])[0]
    else:
        project_id = str(payload.get("project_id", "")).strip()

    if not project_id or project_id not in PROJECTS:
        _write_error(handler, "Projet introuvable.", status=HTTPStatus.NOT_FOUND)
        return None
    return project_id, PROJECTS[project_id]


def _clear_generated_state(state: SharedState) -> None:
    state["a2a_feedback"] = None
    state["conflicts"] = []
    state["requirements"] = []
    state["epics"] = []
    state["features"] = []
    state["user_stories"] = []
    state["acceptance_criteria"] = []
    state["backlog"] = []
    state["traceability_matrix"] = []


def _pending_questions(project: dict) -> tuple[str, list[str]]:
    a2a_questions = project.get("pending_a2a_questions", [])
    if a2a_questions:
        return "a2a", a2a_questions

    state = project["state"]
    questions = state.get("clarification_questions", [])
    answers = state.get("stakeholder_answers", [])
    if state.get("human_input_required") and len(answers) < len(questions):
        return "clarification", questions[len(answers) :]
    if state.get("answer_quality_issues"):
        return "clarification", [issue["question"] for issue in state["answer_quality_issues"]]
    return "", []


def _extract_numbered_answers(message: str, expected_count: int) -> list[str]:
    pattern = re.compile(
        r"(?:^|\n)\s*(?:r|q|reponse|réponse)?\s*(\d+)\s*[\).:\-]\s*(.+?)(?=(?:\n\s*(?:r|q|reponse|réponse)?\s*\d+\s*[\).:\-])|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    matches = pattern.findall(message.strip())
    if matches:
        by_index: dict[int, str] = {}
        for raw_index, answer in matches:
            try:
                index = int(raw_index)
            except ValueError:
                continue
            by_index[index] = answer.strip()
        return [by_index.get(index, "") for index in range(1, expected_count + 1)]

    compact = message.strip()
    if expected_count == 1 and len(compact.split()) >= 4 and "?" not in compact:
        return [compact]
    return []


def _project_brief(state: SharedState) -> str:
    info = state.get("extracted_info") or {}
    features = info.get("fonctionnalites_identifiees", []) or []
    actors = info.get("acteurs", []) or []
    lines = [
        "Voici ce que j'ai compris pour l'instant :",
        f"- Domaine : {info.get('domaine') or 'non determine'}",
        f"- Type de projet : {info.get('type_projet') or 'non determine'}",
        f"- Acteurs : {', '.join(actors) if actors else 'a confirmer'}",
        f"- Objectif : {info.get('objectif_principal') or 'a clarifier'}",
    ]
    if features:
        lines.append(f"- Fonctionnalites detectees : {', '.join(features)}")
    if state.get("requirements"):
        lines.append(f"- Requirements generes : {len(state.get('requirements', []))}")
    if state.get("user_stories"):
        lines.append(f"- User stories generees : {len(state.get('user_stories', []))}")
    return "\n".join(lines)


def _question_help(project: dict) -> str:
    _, questions = _pending_questions(project)
    if not questions:
        return (
            "Pour l'instant, je n'ai pas de question bloquante. "
            "Tu peux me demander un resume, corriger le contexte, ou lancer la generation."
        )
    lines = ["Ces questions servent a produire des requirements precis et testables :"]
    for index, question in enumerate(questions, 1):
        lines.append(f"{index}. {question}")
        lines.append(
            "   Exemple de reponse utile : role exact, regle concrete, statut, delai, donnee ou canal attendu."
        )
    lines.append("Tu peux repondre directement ici avec : 1) ... 2) ... 3) ...")
    return "\n".join(lines)


def _result_brief(state: SharedState, exports: dict) -> str:
    if state.get("user_stories"):
        lines = [
            "Le pipeline a produit les artefacts principaux :",
            f"- Requirements : {len(state.get('requirements', []))}",
            f"- User stories : {len(state.get('user_stories', []))}",
            f"- Backlog : {len(state.get('backlog', []))}",
        ]
        if exports:
            lines.append("Le cahier des charges est disponible dans l'onglet Export.")
        return "\n".join(lines)
    if state.get("requirements"):
        return f"Agent 2 a genere {len(state.get('requirements', []))} requirement(s). Agent 3 peut maintenant produire le backlog."
    return "Les resultats ne sont pas encore generes. Termine la collecte puis lance Agent 2 et Agent 3."


def _apply_context_correction(state: SharedState, message: str) -> list[str]:
    info = state.get("extracted_info")
    if not info:
        return []

    changes = []
    patterns = [
        ("domaine", r"(?:le\s+)?domaine\s*(?:est|=|:)\s*([^.;\n]+)"),
        ("type_projet", r"(?:le\s+)?type(?:\s+de\s+projet)?\s*(?:est|=|:)\s*([^.;\n]+)"),
        ("objectif_principal", r"(?:l[' ]?objectif|objectif principal)\s*(?:est|=|:)\s*([^.;\n]+)"),
    ]
    for key, pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                info[key] = value
                changes.append(f"{key} -> {value}")

    actors_match = re.search(
        r"(?:les\s+)?acteurs?\s*(?:sont|=|:)\s*([^.;\n]+)",
        message,
        re.IGNORECASE,
    )
    if actors_match:
        actors = [
            part.strip()
            for part in re.split(r",|\bet\b|;", actors_match.group(1), flags=re.IGNORECASE)
            if part.strip()
        ]
        if actors:
            info["acteurs"] = actors
            changes.append(f"acteurs -> {', '.join(actors)}")

    if changes:
        _clear_generated_state(state)
        state["extracted_info"] = info
        state = add_trace(
            state,
            agent="Chatbot ReqBot",
            step="Correction contexte",
            observation="L'utilisateur a corrige le contexte depuis le chat.",
            decision="Mettre a jour extracted_info et invalider les artefacts generes.",
            rationale="Les requirements/backlog doivent suivre le contexte corrige.",
        )
    return changes


def _chat_response(project_id: str, message: str) -> dict:
    project = PROJECTS[project_id]
    state = project["state"]
    exports = project.get("exports", {})
    normalized = _norm_text(message)
    project.setdefault("chat_history", []).append({"role": "user", "content": message})

    pending_kind, questions = _pending_questions(project)
    extracted_answers = _extract_numbered_answers(message, len(questions)) if questions else []
    if extracted_answers and len(extracted_answers) == len(questions):
        if pending_kind == "a2a":
            state = _append_human_answers_for_questions(state, questions, extracted_answers)
            project["state"] = state
            project["pending_a2a_questions"] = []
            if state.get("ready_for_agent2"):
                _run_agent2_and_maybe_agent3(project_id)
            reply = "J'ai pris tes reponses comme clarification A2A et j'ai relance Agent 2."
        else:
            from agents.agent1_intake import submit_stakeholder_answers

            state = submit_stakeholder_answers(state, extracted_answers)
            project["state"] = state
            if state.get("answer_quality_issues"):
                reply = (
                    "J'ai bien lu tes reponses, mais Agent 1 en trouve encore certaines trop vagues. "
                    "Je te montre les points a preciser dans le panneau de collecte."
                )
            else:
                if state.get("ready_for_agent2"):
                    _run_agent2_and_maybe_agent3(project_id)
                    reply = (
                        "Parfait, j'ai stocke ces reponses dans le SharedState. "
                        "Agent 2 puis Agent 3 ont ete lances automatiquement."
                    )
                else:
                    reply = "Parfait, j'ai stocke ces reponses dans le SharedState."
        project.setdefault("chat_history", []).append({"role": "assistant", "content": reply})
        return {"reply": reply, "summary": _summary(project_id)}

    changes = _apply_context_correction(state, message)
    if changes:
        reply = (
            "C'est corrige dans le contexte du projet :\n- "
            + "\n- ".join(changes)
            + "\nSi des requirements existaient deja, je les ai invalides pour eviter un resultat incoherent."
        )
        project["state"] = state
        project["exports"] = {}
        project.setdefault("chat_history", []).append({"role": "assistant", "content": reply})
        return {"reply": reply, "summary": _summary(project_id)}

    if any(word in normalized for word in ["compris", "resume", "résume", "analyse", "contexte"]):
        reply = _project_brief(state)
    elif any(word in normalized for word in ["pourquoi", "question", "questions", "repondre", "répondre", "exemple"]):
        reply = _question_help(project)
    elif any(word in normalized for word in ["lance", "gener", "génèr", "continue", "agent 2", "agent2"]):
        if state.get("ready_for_agent2"):
            _run_agent2_and_maybe_agent3(project_id)
            reply = "J'ai lance Agent 2 puis Agent 3 quand c'etait possible. Regarde l'onglet Resultat."
        else:
            reply = (
                "Je ne peux pas encore lancer Agent 2 : Agent 1 attend des reponses plus completes. "
                "Tu peux me les donner ici avec 1) ... 2) ..."
            )
    elif any(word in normalized for word in ["export", "pdf", "cahier", "markdown"]):
        reply = _result_brief(state, exports)
    elif any(word in normalized for word in ["aide", "help", "comment"]):
        reply = (
            "Tu peux me parler naturellement. Exemples :\n"
            "- qu'est-ce que tu as compris ?\n"
            "- pourquoi tu poses ces questions ?\n"
            "- le domaine est e-commerce\n"
            "- les acteurs sont client, artisan, admin\n"
            "- 1) ... 2) ... 3) ... pour repondre aux questions"
        )
    elif questions:
        reply = (
            "Je suis en attente de clarifications. Tu peux soit remplir les champs, soit repondre ici "
            "avec des reponses numerotees :\n"
            + "\n".join(f"{index}. {question}" for index, question in enumerate(questions, 1))
        )
    else:
        reply = (
            "Je suis le chatbot contextuel de ReqBot. Je peux expliquer ce que les agents ont compris, "
            "corriger le contexte, guider tes reponses, lancer la generation ou commenter le backlog."
        )

    project.setdefault("chat_history", []).append({"role": "assistant", "content": reply})
    return {"reply": reply, "summary": _summary(project_id)}


def _run_agent2_and_maybe_agent3(project_id: str) -> None:
    from agents.agent2_validation import agent2_validation
    from agents.agent3_agile import agent3_agile
    from exporters.cahier_des_charges_exporter import export_cahier_des_charges

    project = PROJECTS[project_id]
    state = project["state"]
    project["pending_a2a_questions"] = []
    project["exports"] = {}

    state = add_trace(
        state,
        agent="Interface Web",
        step="Lancement Agent 2",
        observation="L'utilisateur a valide la collecte depuis l'interface.",
        decision="Executer Agent 2 depuis l'API web.",
        rationale="Le SharedState contient la demande et les reponses humaines.",
    )

    state = agent2_validation(state, verbose=False)
    a2a_questions = _fallback_a2a_questions(state)
    if a2a_questions:
        project["state"] = state
        project["pending_a2a_questions"] = a2a_questions
        return

    if state.get("requirements"):
        state = agent3_agile(state, verbose=False)
        if state.get("requirements"):
            project["exports"] = export_cahier_des_charges(state, output_dir=OUTPUT_DIR)

    project["state"] = state


def _append_human_answers_for_questions(
    state: SharedState,
    questions: list[str],
    answers: list[str],
) -> SharedState:
    from agents.agent1_intake import submit_stakeholder_answers

    state["clarification_questions"].extend(questions)
    combined_answers = state.get("stakeholder_answers", []) + answers
    state = submit_stakeholder_answers(state, combined_answers)
    _clear_generated_state(state)
    return state


class ReqBotHandler(BaseHTTPRequestHandler):
    server_version = "ReqBotWeb/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[ReqBot] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._serve_file(INDEX_PATH, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/project":
            found = _get_project(self)
            if found:
                project_id, _ = found
                _write_json(self, _summary(project_id))
            return
        if parsed.path == "/api/download":
            self._download()
            return
        _write_error(self, "Route introuvable.", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/start":
                self._start_project()
            elif parsed.path == "/api/answers":
                self._submit_answers()
            elif parsed.path == "/api/generate":
                self._generate()
            elif parsed.path == "/api/a2a":
                self._submit_a2a()
            elif parsed.path == "/api/chat":
                self._chat()
            else:
                _write_error(self, "Route introuvable.", status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            _write_error(self, f"Erreur serveur : {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists():
            _write_error(self, f"Fichier introuvable : {path}", status=HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        mime = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _start_project(self) -> None:
        raw_input, upload_path = _read_start_payload(self)
        if not raw_input and upload_path is None:
            _write_error(self, "La demande client est obligatoire.")
            return
        if upload_path is None and not _looks_like_project_request(raw_input):
            _write_error(
                self,
                "Ce message ressemble a une conversation, pas a une demande projet. "
                "Decris le projet avec son objectif, ses utilisateurs et ses fonctionnalites.",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
            return

        from agents.agent1_intake import agent1_intake

        state = _initial_state_from_input(raw_input, upload_path)
        state = agent1_intake(state, file_path=None, verbose=False)
        project_id = uuid.uuid4().hex
        PROJECTS[project_id] = {
            "state": state,
            "exports": {},
            "pending_a2a_questions": [],
            "upload_path": str(upload_path) if upload_path else None,
            "chat_history": [],
        }
        if state.get("ready_for_agent2"):
            _run_agent2_and_maybe_agent3(project_id)
        _write_json(self, _summary(project_id))

    def _chat(self) -> None:
        payload = _read_json(self)
        found = _get_project(self, payload)
        if not found:
            return
        project_id, _ = found
        message = str(payload.get("message", "")).strip()
        if not message:
            _write_error(self, "Message vide.")
            return
        response = _chat_response(project_id, message)
        _write_json(self, {"ok": True, **response})

    def _submit_answers(self) -> None:
        from agents.agent1_intake import submit_stakeholder_answers

        payload = _read_json(self)
        found = _get_project(self, payload)
        if not found:
            return
        project_id, project = found
        answers = payload.get("answers", [])
        if not isinstance(answers, list):
            _write_error(self, "Le champ answers doit etre une liste.")
            return

        state = submit_stakeholder_answers(project["state"], [str(answer) for answer in answers])
        project["state"] = state
        project["exports"] = {}
        project["pending_a2a_questions"] = []
        if state.get("ready_for_agent2"):
            _run_agent2_and_maybe_agent3(project_id)
        _write_json(self, _summary(project_id))

    def _generate(self) -> None:
        payload = _read_json(self)
        found = _get_project(self, payload)
        if not found:
            return
        project_id, project = found
        if not project["state"].get("ready_for_agent2"):
            _write_error(self, "Agent 1 n'a pas encore valide la collecte.")
            return

        _run_agent2_and_maybe_agent3(project_id)
        _write_json(self, _summary(project_id))

    def _submit_a2a(self) -> None:
        payload = _read_json(self)
        found = _get_project(self, payload)
        if not found:
            return
        project_id, project = found
        questions = project.get("pending_a2a_questions", [])
        if not questions:
            _write_error(self, "Aucune question A2A en attente.")
            return
        answers = payload.get("answers", [])
        if not isinstance(answers, list):
            _write_error(self, "Le champ answers doit etre une liste.")
            return

        state = _append_human_answers_for_questions(
            project["state"],
            questions,
            [str(answer) for answer in answers],
        )
        project["state"] = state
        project["pending_a2a_questions"] = []

        if state.get("ready_for_agent2"):
            _run_agent2_and_maybe_agent3(project_id)

        _write_json(self, _summary(project_id))

    def _download(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        project_id = (query.get("id") or [""])[0]
        kind = (query.get("kind") or [""])[0]
        if not project_id or project_id not in PROJECTS:
            _write_error(self, "Projet introuvable.", status=HTTPStatus.NOT_FOUND)
            return

        project = PROJECTS[project_id]
        if kind == "json":
            data = json.dumps(project["state"], ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="reqbot_state.json"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        path_value = project.get("exports", {}).get(kind)
        if kind not in {"pdf", "markdown"} or not path_value:
            _write_error(self, "Export indisponible.", status=HTTPStatus.NOT_FOUND)
            return

        path = Path(path_value).resolve()
        if not path.exists() or OUTPUT_DIR.resolve() not in path.parents:
            _write_error(self, "Fichier export introuvable.", status=HTTPStatus.NOT_FOUND)
            return

        content_type = "application/pdf" if kind == "pdf" else "text/markdown; charset=utf-8"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), ReqBotHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"ReqBot plateforme demarree : {url}", flush=True)
    print("Ctrl+C pour arreter.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArret de ReqBot.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
