"""Creates a part that belongs to a REAL session (through the API) and gives it real, gradeable output, so specs that need
a part with a session (the layout audit) actually run instead of skipping.

    python seed_session_part.py <base_url> <final_dir> <part>
"""
import json
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

base, final, part = sys.argv[1], sys.argv[2], sys.argv[3]
sid = json.load(urllib.request.urlopen(urllib.request.Request(base + "/api/session", method="POST")))["session"]
b = uuid.uuid4().hex
CRLF = "\r\n"
body = (f'--{b}{CRLF}Content-Disposition: form-data; name="session"{CRLF}{CRLF}{sid}{CRLF}'
        f'--{b}{CRLF}Content-Disposition: form-data; name="part"{CRLF}{CRLF}{part}{CRLF}'
        f'--{b}{CRLF}Content-Disposition: form-data; name="original"; filename="d.pdf"{CRLF}Content-Type: application/pdf{CRLF}{CRLF}%PDF-1.4 x{CRLF}'
        f'--{b}--{CRLF}').encode()
urllib.request.urlopen(urllib.request.Request(base + "/api/parts", data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={b}"}))
here = Path(__file__).resolve().parent
subprocess.run([sys.executable, str(here / "make_scored_part.py"), final, part, "good"], check=True, capture_output=True)
print("seeded session part", part)
