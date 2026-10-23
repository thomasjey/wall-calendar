"""The away-from-home service on Azure Functions (DESIGN §15, §17).

Plain HTTPS calls with `requests` only: no MSAL and no Azure SDK (ADR-30).
Nothing here imports `azure.functions`; `function_app.py` adapts it.
"""
