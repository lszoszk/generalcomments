"""
UN Human Rights Database · PythonAnywhere redirector
=================================================

Replaces the legacy Flask app that served search results from
lszoszk.pythonanywhere.com. Every old URL now 301-redirects to the
equivalent path on https://lszoszk.github.io/generalcomments/, while
translating the legacy search-form parameters into the new app's
short query keys.

Why 301?
    - Permanent redirect: Google passes link authority over time.
    - Browsers cache the redirect, so repeat visitors don't even hit PA.
    - Keep this running for at least 6–12 months while the new domain
      accumulates indexing and external sites refresh their links.

Why a Flask redirector instead of an .htaccess?
    PythonAnywhere doesn't expose Apache's mod_rewrite for free-tier
    sites, but it serves Flask apps by default — so a tiny redirect
    app is the simplest portable solution.

Deploy:
    1. SSH/Files: upload this file to /home/lszoszk/mysite/app_redirector.py
    2. Edit /home/lszoszk/mysite/flask_app.py — change the import to:
           from app_redirector import app as application
    3. Web tab → Reload web app
    4. Verify with:
           curl -I https://lszoszk.pythonanywhere.com/search?search_query=privacy
       Expect:  HTTP/1.1 301
                Location: https://lszoszk.github.io/generalcomments/?q=privacy
"""

from flask import Flask, redirect, request, Response
from urllib.parse import urlencode

app = Flask(__name__)

NEW_BASE = "https://lszoszk.github.io/generalcomments"

# ─── Old → new path mapping ────────────────────────────────────────────────
# Anything not in this map drops through to the new home.
PATH_MAP = {
    "/":                            "/",
    "/about":                       "/",
    "/cookie-policy":               "/",
    "/corpus_viewer.html":          "/",
    "/documents":                   "/",
    "/enhanced":                    "/",
    "/enhanced_about":              "/",
    "/enhanced_browse":             "/",
    "/enhanced_home":               "/",
    "/enhanced_procedures":         "/?scope=sp",
    "/enhanced_procedures_browse":  "/?scope=sp",
    "/neurorights_search":          "/",   # neurorights dataset isn't on the new app
    "/oneshot":                     "/",
    "/specialprocedures":           "/?scope=sp",
    "/survey":                      "/",
    "/vibecoding":                  "/",
    "/sitemap.xml":                 "/sitemap.xml",
}

# Param-translating routes — handled in make_target().
SEARCH_PATHS = {"/search", "/enhanced/search"}
SP_SEARCH_PATHS = {"/specialprocedures/search"}


def translate_search_args(args, scope=None):
    """Map old query-string keys to the new app's short keys."""
    out = {}
    if scope:
        out["scope"] = scope
    q = args.get("search_query")
    if q:
        out["q"] = q
    tbs = args.getlist("treatyBodies[]")
    if tbs:
        out["tb"] = "|".join(tbs)
    labels = args.getlist("labels[]")
    if labels:
        out["g"] = "|".join(labels)
    if args.get("year_start"):
        out["y1"] = args["year_start"]
    if args.get("year_end"):
        out["y2"] = args["year_end"]
    return out


def make_target(path, args):
    """Build the path-and-query portion of the new URL."""
    if path in SEARCH_PATHS:
        params = translate_search_args(args)
        return "/" + ("?" + urlencode(params) if params else "")
    if path in SP_SEARCH_PATHS:
        params = translate_search_args(args, scope="sp")
        return "/?" + urlencode(params)
    return PATH_MAP.get(path, "/")


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/robots.txt")
def robots():
    """Don't block crawlers — they need to crawl us to discover the 301s."""
    return Response(
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {NEW_BASE}/sitemap.xml\n",
        mimetype="text/plain",
    )


# Old API endpoints have no equivalent on the static site — return 410 Gone
# so search engines drop them rather than chasing soft-404s.
@app.route("/api/<path:_rest>")
@app.route("/get_documents/<path:_rest>")
@app.route("/get_document/<path:_rest>")
@app.route("/export_to_excel", methods=["GET", "POST"])
def gone(_rest=None):
    return Response(
        f"This endpoint has moved. See {NEW_BASE}/ for the static replacement.",
        status=410,
        mimetype="text/plain",
    )


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catchall(path):
    # Normalise — collapse trailing slash, prepend leading slash
    full = "/" + path.rstrip("/") if path else "/"
    target = make_target(full, request.args)
    response = redirect(NEW_BASE + target, code=301)
    # Tell intermediaries this redirect is permanent and cacheable
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


if __name__ == "__main__":
    # Local smoke test:
    #   FLASK_APP=app.py flask run
    #   curl -I http://localhost:5000/search?search_query=privacy\&treatyBodies\[\]=CRC
    app.run(debug=True)
