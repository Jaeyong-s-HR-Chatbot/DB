import http.server, os, urllib.parse
D=os.path.dirname(os.path.abspath(__file__))
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s,*a,**k): super().__init__(*a,directory=D,**k)
    def do_POST(s):
        name=os.path.basename(urllib.parse.parse_qs(urllib.parse.urlparse(s.path).query)['name'][0])
        data=s.rfile.read(int(s.headers['Content-Length'])); open(os.path.join(D,name),'wb').write(data)
        s.send_response(200); s.end_headers(); s.wfile.write(b'ok')
    def log_message(s,*a): pass
http.server.ThreadingHTTPServer(('127.0.0.1',8766),H).serve_forever()
