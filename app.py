"""Production entrypoints for ReqBot.

Local execution uses ``main()``.
Vercel's Python runtime expects a top-level ``handler`` class.
"""

from http.server import BaseHTTPRequestHandler

from interface.web_app import ReqBotHandler, main


class handler(BaseHTTPRequestHandler):
    """Vercel serverless entrypoint delegated to ReqBotHandler."""

    server_version = ReqBotHandler.server_version
    log_message = ReqBotHandler.log_message
    do_GET = ReqBotHandler.do_GET
    do_POST = ReqBotHandler.do_POST
    _serve_file = ReqBotHandler._serve_file
    _start_project = ReqBotHandler._start_project
    _chat = ReqBotHandler._chat
    _submit_answers = ReqBotHandler._submit_answers
    _generate = ReqBotHandler._generate
    _submit_a2a = ReqBotHandler._submit_a2a
    _download = ReqBotHandler._download


if __name__ == "__main__":
    main()
