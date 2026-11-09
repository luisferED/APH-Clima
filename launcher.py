"""Launch the bundled server once and open the requested operator/output view."""
import json
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:9010'
opener = build_opener(ProxyHandler({}))


def ready():
    try:
        with opener.open(BASE + '/api/weather', timeout=1) as response:
            data = json.load(response)
            return len(data.get('cities', [])) == 9
    except Exception:
        return False


def main():
    if not ready():
        with (ROOT / 'server.log').open('ab') as log:
            subprocess.Popen([sys.executable, '-u', str(ROOT / 'server.py')], cwd=ROOT,
                             stdout=log, stderr=log,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(40):
            if ready():
                break
            time.sleep(.25)
        else:
            raise RuntimeError('No se pudo iniciar APH en el puerto 9010. Revisa server.log o si el puerto esta ocupado.')
    mode = sys.argv[1] if len(sys.argv) > 1 else 'panel'
    paths = {'panel': ['/'], 'current': ['/output.html?view=current'],
             'extended': ['/output.html?view=extended'], 'output': ['/output.html'],
             'all': ['/', '/output.html?view=current', '/output.html?view=extended']}
    for path in paths.get(mode, ['/']):
        webbrowser.open(BASE + path)


if __name__ == '__main__':
    main()
