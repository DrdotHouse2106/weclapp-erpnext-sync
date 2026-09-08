#!/usr/bin/env python3
"""READ-ONLY Probe: prüft, ob WeClapps REST-API serverseitig nach lastModifiedDate filtert.

Jeder HTTP-Aufruf geht durch _get() und ist damit garantiert ein GET - es gibt keinen
Schreibpfad. Nichts wird in WeClapp verändert.

Nutzung:
    WECLAPP_BASE_URL="https://tenant.weclapp.com/webapp/api/v1/" \\
    WECLAPP_API_TOKEN="..." \\
    python3 scripts/weclapp_filter_probe.py

Ergebnis 2026-09-07 gegen francetec.weclapp.com: Filter funktioniert vollständig
(lastModifiedDate-gt=<epoch_ms> auf /count und Listen-Endpoint, alle Objekttypen,
kombinierbar mit -lt, sort, properties). Nur Epoch-Millisekunden; ISO-String -> HTTP 500.
"""

import os
import sys
import time
import urllib.parse

import requests

BASE = os.environ.get("WECLAPP_BASE_URL", "").rstrip("/") + "/"
TOKEN = os.environ.get("WECLAPP_API_TOKEN", "")

if not BASE.strip("/") or not TOKEN:
	sys.exit("Bitte WECLAPP_BASE_URL und WECLAPP_API_TOKEN als Umgebungsvariablen setzen.")

S = requests.Session()
S.headers.update({"AuthenticationToken": TOKEN, "Content-Type": "application/json"})
CALLS: list[str] = []


def _get(path, params=None):
	"""Die einzige Netzwerk-Primitive - GET-only."""
	CALLS.append("GET " + BASE + path + ("?" + urllib.parse.urlencode(params) if params else ""))
	r = S.request("GET", BASE + path, params=params, timeout=(10, 120))
	r.raise_for_status()
	return r


def count(entity, params=None):
	return _get(f"{entity}/count", params).json()["result"]


def main():
	now = int(time.time() * 1000)
	cut_365d = now - 365 * 86_400_000

	print("=== /count mit und ohne lastModifiedDate-Filter ===")
	for entity in ["customer", "salesOrder", "article", "party", "quotation", "salesInvoice"]:
		total = count(entity)
		filt = count(entity, {"lastModifiedDate-gt": cut_365d})
		verdict = "FILTER WIRKT" if filt < total else "keine Reduktion"
		print(f"  {entity:15} gesamt={total:6}  geändert<365T={filt:6}  {verdict}")

	print("\n=== Komplement -gt + -lt muss die Gesamtzahl ergeben ===")
	gt = count("salesInvoice", {"lastModifiedDate-gt": cut_365d})
	lt = count("salesInvoice", {"lastModifiedDate-lt": cut_365d})
	print(f"  gt={gt} + lt={lt} = {gt + lt}  vs. gesamt {count('salesInvoice')}")

	print("\n=== Listen-Endpoint: Filter + sort + properties ===")
	rows = _get(
		"salesInvoice",
		{
			"lastModifiedDate-gt": cut_365d,
			"pageSize": 5,
			"sort": "-lastModifiedDate",
			"properties": "id,invoiceNumber,lastModifiedDate",
		},
	).json()["result"]
	for row in rows:
		lm = row.get("lastModifiedDate")
		human = time.strftime("%Y-%m-%d", time.gmtime(lm / 1000)) if lm else "?"
		print(f"  id={row.get('id')} {row.get('invoiceNumber')} lastModified={lm} ({human})")
	violations = [r for r in rows if (r.get("lastModifiedDate") or 0) <= cut_365d]
	print(f"  Verletzungen des -gt-Cutoffs: {len(violations)} (erwartet 0)")

	print("\n--- alle abgesetzten HTTP-Aufrufe (jeder ein GET) ---")
	for c in CALLS:
		print("  " + c)


if __name__ == "__main__":
	main()
