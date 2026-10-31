"""A stand-in for Crossref's works service and DataCite's DOI service, for tests only.
It runs on 127.0.0.1 on a free port in a thread and answers GET /works/<doi> in
Crossref's response shape from a given set of records, and GET /dois/<doi> in DataCite's
response shape from a second set, with a 404 for any other DOI and a 500 for DOIs listed
as failing. It records each request's path and User-Agent.

Records are given in the metadata cache's shape ({title, author, issued: year,
container-title, type}) keyed by DOI. DataCite's shape follows its REST API, data with
attributes holding titles, creators (name, givenName, familyName), publicationYear,
publisher, container, and types."""
import http.server
import json
import threading
import urllib.parse


def crossref_shape(record):
    return {"message": {
        "title": [record.get("title", "")],
        "author": [{"family": a.get("family", ""), "given": a.get("given", "")}
                   for a in record.get("author", [])],
        "issued": {"date-parts": [[record.get("issued")]]},
        "container-title": [record.get("container-title", "")],
        "type": record.get("type", ""),
    }}


def datacite_shape(doi, record):
    return {"data": {"id": doi, "type": "dois", "attributes": {
        "doi": doi,
        "titles": [{"title": record.get("title", "")}],
        "creators": [{"name": "%s, %s" % (a.get("family", ""), a.get("given", "")), "nameType": "Personal",
                      "givenName": a.get("given", ""), "familyName": a.get("family", "")}
                     for a in record.get("author", [])],
        "publicationYear": record.get("issued"),
        "publisher": record.get("container-title", ""),
        "container": {},
        "types": {"resourceTypeGeneral": record.get("type", "")},
    }}}


class StandIn(object):
    def __init__(self, records, failing=(), datacite=None):
        self.records = {k.lower(): v for k, v in records.items()}
        self.datacite = {k.lower(): v for k, v in (datacite or {}).items()}
        self.failing = {d.lower() for d in failing}
        self.requests = []
        standin = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                standin.requests.append({"path": self.path, "user_agent": self.headers.get("User-Agent")})
                path = urllib.parse.unquote(self.path)
                for start, held, shape in (("/works/", standin.records, lambda d, r: crossref_shape(r)),
                                           ("/dois/", standin.datacite, datacite_shape)):
                    if path.startswith(start):
                        doi = path[len(start):].lower()
                        break
                else:
                    doi, held, shape = None, {}, None
                if doi in standin.failing:
                    self._send(500, {"status": "error"})
                elif doi in held:
                    self._send(200, shape(doi, held[doi]))
                else:
                    self._send(404, {"status": "not found"})

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:%d/works/" % self.port
        self.datacite_url = "http://127.0.0.1:%d/dois/" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
