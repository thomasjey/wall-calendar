"""Azure Functions entry point (DESIGN §15.3, §17.3). The only file that
imports azure.functions; everything else is in fwcal.cloud and is tested
without it.

Every request has already passed the platform's sign-in and allowlist (layers 1
and 2); fwcal.cloud.web checks again (layer 3).

The functions are plain (not async): the Python runtime runs them on its own
thread pool, so blocking calls never hold up its event loop, and it ties each
thread to its invocation, which is what lets their log lines through.
"""

import azure.functions as func

from fwcal.cloud import app as cloud
from fwcal.cloud.web import Request

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
MAX_QUERY_FIELDS = 10


# One catch-all route (it also matches "/"); the host's default home page is
# switched off with AzureWebJobsDisableHomepage. Other methods never reach the code.
@app.route(route="{*path}", methods=["GET", "HEAD"])
def web(req: func.HttpRequest) -> func.HttpResponse:
    path = "/" + (req.route_params.get("path") or "")
    query = {k: v for k, v in list(req.params.items())[:MAX_QUERY_FIELDS]}
    headers = {k.lower(): v for k, v in req.headers.items()}
    resp = cloud.handle(Request(req.method.upper(), path, headers, query))
    return func.HttpResponse(body=resp.body, status_code=resp.status, headers=resp.headers,
                             mimetype=(resp.content_type or "").split(";")[0] or None,
                             charset="utf-8")


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def sync(timer: func.TimerRequest) -> None:
    cloud.run_sync()
