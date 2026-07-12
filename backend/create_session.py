import httpx
import json

with open('fe-audit-dict.xml', 'rb') as f:
    files = {'file': ('dict.xml', f, 'text/xml')}
    r = httpx.post('http://localhost:8000/api/upload/dictionary', files=files, timeout=30)
    print(f'Status: {r.status_code}')
    print(f'Response: {r.text[:500]}')
