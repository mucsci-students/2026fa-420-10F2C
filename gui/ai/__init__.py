"""
AI assistant (Sprint 3): type a request in everyday language and the AI
carries it out with a fixed set of tools.

    prompt.py    the base prompt (the AI's role and rules) and the capability list
    tools.py     the tools; each one validates its arguments and calls a controller
    runner.py    the LangChain + OpenAI agent that picks which tools to call
    service.py   one request from start to finish: guard, run, plain-language reply

The AI never edits the configuration itself. It can only call the tools in
tools.py, and every tool goes through the same gui/controllers/ functions the
normal pages use, so the same validation and safeguards apply.
"""
