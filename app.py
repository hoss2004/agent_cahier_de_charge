"""Production entrypoints for ReqBot.

Local execution uses ``main()``.
Vercel's Python runtime imports the top-level ``handler`` variable.
"""

from interface.web_app import ReqBotHandler, main


handler = ReqBotHandler


if __name__ == "__main__":
    main()
