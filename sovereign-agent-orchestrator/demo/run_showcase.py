#!/usr/bin/env python3
"""Uploads the synthetic corpus and measures what the orchestrator does with it.

Three things happen, in order, and each prints a number rather than a claim:

1. Upload. Every document goes in as the role that owns it, with the scope that
   routes it to its tier. The ingest wall time is printed per file, which is the
   text-versus-vision cost difference made visible -- a text PDF lands in about a
   second, a scanned page takes as long as the vision model needs to read it.
2. Retrieval. The planted queries are replayed through
   /api/v1/knowledge/evaluate as an administrator, giving hit rate and MRR over
   documents whose correct answer was fixed before any model saw them.
3. Isolation. A fact from each tier is queried as lower, higher and admin. The
   table that prints is the tier boundary: the same query, the same index, three
   different sets of readable tiers.

    python demo/run_showcase.py --base-url http://localhost:8080/api/v1

Needs DEV_AUTH_ENABLED=true on the API. Passwords come from DEV_ADMIN_PASSWORD /
DEV_HIGHER_PASSWORD / DEV_LOWER_PASSWORD, defaulting to the same values
app/dev_auth.py falls back to.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx

ROLE_PASSWORDS = {
    'admin': ('DEV_ADMIN_PASSWORD', 'admin-test-only'),
    'higher': ('DEV_HIGHER_PASSWORD', 'higher-test-only'),
    'lower': ('DEV_LOWER_PASSWORD', 'lower-test-only'),
}

# Each probe names a fact, the file holding it, and the roles whose readable
# tiers contain that file. `expected` is what the tier rules in app/access.py
# require -- not what we hope to see.
ISOLATION_PROBES = [
    {
        'fact': 'vibration alarm threshold (lower tier)',
        'query': 'What is the vibration alarm threshold for a boiler feed pump?',
        'file': 'sop_pump_changeover.pdf',
        'expected': {'lower', 'higher', 'admin'},
    },
    {
        'fact': 'coupling misalignment root cause (higher tier)',
        'query': 'What was the root cause of the P-204B bearing temperature rise?',
        'file': 'ecn_4471_coupling.docx',
        'expected': {'higher', 'admin'},
    },
    {
        'fact': 'liquidated damages clause (admin tier)',
        'query': 'What are the liquidated damages per affected pump set?',
        'file': 'vendor_addendum_a3.docx',
        'expected': {'admin'},
    },
]


def login(client: httpx.Client, base: str, role: str) -> str:
    env_key, default = ROLE_PASSWORDS[role]
    response = client.post(f'{base}/auth/dev/login', json={'username': role, 'password': os.getenv(env_key, default)})
    if response.status_code == 404:
        raise SystemExit('DEV_AUTH_DISABLED: set DEV_AUTH_ENABLED=true on the API and restart it.')
    if response.status_code == 503:
        raise SystemExit('DEV_AUTH_SECRET_NOT_CONFIGURED: JWT_SECRET must be at least 32 characters.')
    if response.status_code == 401:
        raise SystemExit(f'INVALID_CREDENTIALS for role {role}: set {env_key} to match the API.')
    response.raise_for_status()
    return response.json()['access_token']


def upload(client: httpx.Client, base: str, token: str, path: Path, scope: str) -> tuple[dict, float]:
    """Uploads one document and returns the server's record plus ingest wall time.

    The elapsed time is the point of returning it: ingest is synchronous, so this
    is exactly how long the extraction path for this document took.
    """
    started = time.perf_counter()
    with path.open('rb') as handle:
        response = client.post(
            f'{base}/files',
            headers={'Authorization': f'Bearer {token}'},
            files={'file': (path.name, handle)},
            data={'scope': scope},
            timeout=900.0,
        )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


def search(client: httpx.Client, base: str, token: str, query: str, top_k: int = 5) -> list[dict]:
    response = client.post(
        f'{base}/knowledge/search',
        headers={'Authorization': f'Bearer {token}'},
        json={'query': query, 'top_k': top_k},
        timeout=180.0,
    )
    response.raise_for_status()
    return response.json()['data']


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', default='http://localhost:8080/api/v1')
    parser.add_argument('--corpus', default='demo/corpus')
    parser.add_argument('--skip-upload', action='store_true', help='reuse the ids in corpus/uploaded.json')
    args = parser.parse_args()

    base = args.base_url.rstrip('/')
    corpus = Path(args.corpus)
    manifest = json.loads((corpus / 'manifest.json').read_text())
    documents = manifest['documents']
    uploaded_path = corpus / 'uploaded.json'

    with httpx.Client(timeout=60.0) as client:
        tokens = {role: login(client, base, role) for role in ROLE_PASSWORDS}
        print(f'Authenticated as admin, higher, lower against {base}\n')

        # --- 1. upload -------------------------------------------------------
        if args.skip_upload and uploaded_path.exists():
            ids = json.loads(uploaded_path.read_text())
            print(f'Reusing {len(ids)} file ids from {uploaded_path}\n')
        else:
            ids = {}
            print(f'{"document":34} {"tier":>7} {"ingest":>9} {"chunks":>7}  expected path')
            print('-' * 86)
            for document in documents:
                record, elapsed = upload(
                    client, base, tokens[document['upload_as']],
                    corpus / document['file'], document['scope'],
                )
                ids[document['file']] = record['file_id']
                index = record.get('index') or {}
                # The ingest response carries the tier and chunk count but not the
                # route taken, so the expected route comes from the manifest and the
                # wall time corroborates it: a text document that suddenly takes a
                # minute means configuration sent it to the vision model.
                tier = index.get('tier', document['tier'])
                chunks = index.get('chunks', 0)
                print(f'{document["file"]:34} {tier:>7} {elapsed:8.1f}s {chunks:>7}  {document["extraction_path"]}')
            uploaded_path.write_text(json.dumps(ids, indent=2) + '\n')
            print(f'\nWrote {len(ids)} file ids to {uploaded_path}\n')

        # --- 2. retrieval ----------------------------------------------------
        cases = json.loads((corpus / 'eval_cases.json').read_text())
        payload = {'cases': [
            {'query': case['query'],
             'expected_file_ids': [ids[name] for name in case['expected_files'] if name in ids]}
            for case in cases
        ]}
        response = client.post(
            f'{base}/knowledge/evaluate',
            headers={'Authorization': f'Bearer {tokens["admin"]}'},
            json=payload, timeout=600.0,
        )
        response.raise_for_status()
        data = response.json()['data']
        metrics = data['metrics']
        print('Retrieval over the planted queries, as admin (all three tiers readable)')
        print(f'  cases     {metrics["count"]}')
        print(f'  hit rate  {metrics["hit_rate"]:.3f}')
        print(f'  MRR       {metrics["mrr"]:.3f}')
        misses = [case['query'] for case in data['cases'] if not case['hit']]
        for miss in misses:
            print(f'  MISS      {miss}')
        print()

        # --- 3. isolation ----------------------------------------------------
        print('Tier isolation: can this role retrieve the file holding the fact?')
        print(f'{"fact":46} {"lower":>7} {"higher":>7} {"admin":>7}  verdict')
        print('-' * 82)
        failures = 0
        for probe in ISOLATION_PROBES:
            target = ids.get(probe['file'])
            seen = {}
            for role in ('lower', 'higher', 'admin'):
                hits = search(client, base, tokens[role], probe['query'])
                # A hit carries the upload's file_id inside its metadata, and its
                # `source` is the original filename -- match on either.
                seen[role] = any(
                    (hit.get('metadata') or {}).get('file_id') == target
                    or hit.get('source') == probe['file']
                    for hit in hits
                )
            actual = {role for role, found in seen.items() if found}
            ok = actual == probe['expected']
            failures += 0 if ok else 1
            cells = ''.join(f'{("yes" if seen[r] else "no"):>8}' for r in ('lower', 'higher', 'admin'))
            print(f'{probe["fact"]:46}{cells}  {"as designed" if ok else "UNEXPECTED"}')
        print()
        if failures:
            print(f'{failures} isolation probe(s) did not match app/access.py. Investigate before demonstrating.')
        else:
            print('All isolation probes match the tier rules in app/access.py.')


if __name__ == '__main__':
    main()
