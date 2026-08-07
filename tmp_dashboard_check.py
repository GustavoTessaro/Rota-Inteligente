import json
import urllib.request

token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicGVyZmlsIjoiQURNSU4iLCJleHAiOjE3ODYxNDQyMjF9.JQHOOsxgkFKIkkWj6i4UYuko9xlXub2FnaRvU4O-myE'
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/relatorios/dashboard',
    headers={'Authorization': f'Bearer {token}'},
)
with urllib.request.urlopen(req, timeout=10) as r:
    print(r.read().decode())
