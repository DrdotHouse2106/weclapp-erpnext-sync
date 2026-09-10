"""Read-only WeClapp REST-Client für den ERPNext-Sync.

WICHTIG: WeClapp ist das produktive Quellsystem. Dieser Client ist **ausschließlich lesend**.
Jeder HTTP-Aufruf geht durch `_request()`, das alles außer GET hart ablehnt (WeClappWriteRefused).
Es gibt bewusst keine create/update/delete-Methode.

Speicher: Der Client lädt **niemals** eine ganze Entität am Stück. `iter_pages()` /
`iter_all()` sind Generatoren, die Seite für Seite von WeClapp holen und yielden - der Aufrufer
verarbeitet eine Seite und verwirft sie, bevor die nächste geholt wird.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from typing import Any

import requests

from .doctypes import WeClappDocType
from .exceptions import WeClappApiError, WeClappWriteRefused

# (connect timeout, read timeout) in Sekunden. Ohne read-timeout kann ein hängender
# Server/Proxy den Sync-Job stundenlang blockieren (im Vorgängerprojekt real beobachtet).
_TIMEOUT = (10, 180)

_DEFAULT_PAGE_SIZE = 100

# Last-Management (WeClapp API-Update): der Server schickt X-Weclapp-Wait-Ms / -Wait-Reason,
# wenn er die Anfrage wegen Systemlast verzögert hat. Wir warten diese Zeit vor dem nächsten
# Aufruf ab und retryen 429/503 gebremst. Sleeps sind gedeckelt, Retries begrenzt.
_MAX_RETRIES = 4
_MAX_WAIT_S = 30.0

# WeClapp-Filter-Operator-Suffixe (Query-Param-Syntax: "<feld>-<op>=<wert>").
# Live bestätigt 2026-09-07 gegen francetec.weclapp.com.
FILTER_OPS = ("eq", "ne", "gt", "lt", "ge", "le", "null", "notnull", "like", "notlike", "in", "notin")


class WeClappClient:
	"""Lesender Zugriff auf eine WeClapp-Instanz.

	Args:
		base_url: z.B. "https://tenant.weclapp.com/webapp/api/v1/" (mit abschließendem "/").
		api_token: WeClapp API-Token (AuthenticationToken-Header).
		page_size: Seitengröße für die Streaming-Iteratoren.
	"""

	def __init__(self, base_url: str, api_token: str, *, page_size: int = _DEFAULT_PAGE_SIZE):
		if not base_url:
			raise WeClappApiError("WeClapp base_url fehlt")
		if not api_token:
			raise WeClappApiError("WeClapp api_token fehlt")
		self.base_url = base_url if base_url.endswith("/") else base_url + "/"
		self.api_token = api_token
		self.page_size = page_size
		self._session: requests.Session | None = None
		self._pending_wait_s = 0.0  # vom Server per X-Weclapp-Wait-Ms angefordert

	# ------------------------------------------------------------------ lifecycle
	def __enter__(self) -> WeClappClient:
		self.open()
		return self

	def __exit__(self, *exc: object) -> None:
		self.close()

	def open(self) -> None:
		self._session = requests.Session()
		self._session.headers.update(
			{
				"Content-Type": "application/json",
				"AuthenticationToken": self.api_token,
			}
		)

	def close(self) -> None:
		if self._session is not None:
			self._session.close()
			self._session = None

	@property
	def session(self) -> requests.Session:
		if self._session is None:
			self.open()
		assert self._session is not None
		return self._session

	# ------------------------------------------------------------------ core request
	def _request(self, path: str, *, method: str = "GET", params: Mapping[str, Any] | None = None) -> requests.Response:
		"""Die einzige Netzwerk-Primitive. GET-only, hart erzwungen.

		`path` ist relativ zur base_url (ohne führenden "/").
		"""
		if method != "GET":
			raise WeClappWriteRefused(
				f"Abgelehnt: {method} {path} - der WeClapp-Client ist ausschließlich lesend",
				method=method,
				url=self.base_url + path,
			)

		url = self.base_url + path

		# Vom Server zuvor angeforderte Wartezeit abwarten (Last-Management).
		if self._pending_wait_s:
			time.sleep(min(self._pending_wait_s, _MAX_WAIT_S))
			self._pending_wait_s = 0.0

		last_exc: Exception | None = None
		for attempt in range(_MAX_RETRIES):
			response: requests.Response | None = None
			try:
				response = self.session.request(method="GET", url=url, params=params, timeout=_TIMEOUT)
			except requests.RequestException as e:
				last_exc = WeClappApiError(f"Verbindungsfehler bei GET {url}: {e}", method="GET", url=url)
				time.sleep(min(2**attempt, _MAX_WAIT_S))
				continue

			# Server bittet um Wartezeit für den nächsten Aufruf (auch bei 200).
			wait_ms = response.headers.get("X-Weclapp-Wait-Ms")
			if wait_ms and wait_ms.isdigit():
				self._pending_wait_s = min(int(wait_ms) / 1000.0, _MAX_WAIT_S)

			if response.status_code in (429, 503) and attempt < _MAX_RETRIES - 1:
				retry_after = response.headers.get("Retry-After")
				sleep_s = self._pending_wait_s or (
					float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit()
					else min(2**attempt, _MAX_WAIT_S)
				)
				self._pending_wait_s = 0.0
				time.sleep(min(sleep_s, _MAX_WAIT_S))
				continue

			try:
				response.raise_for_status()
			except requests.RequestException as e:
				raise WeClappApiError(
					f"HTTP {response.status_code} bei GET {url}: {response.text[:500]}",
					method="GET",
					url=url,
					status_code=response.status_code,
					response_text=response.text,
				) from e
			return response

		assert last_exc is not None
		raise last_exc

	@staticmethod
	def _merge_params(
		params: Mapping[str, Any] | None, filters: Mapping[str, Any] | None
	) -> dict[str, Any]:
		merged: dict[str, Any] = dict(params or {})
		if filters:
			for key, value in filters.items():
				merged[key] = value
		return merged

	# ------------------------------------------------------------------ read API
	def count(
		self,
		entity: WeClappDocType | str,
		*,
		filters: Mapping[str, Any] | None = None,
	) -> int:
		"""Anzahl Datensätze der Entität (optional gefiltert).

		WeClapps /count-Endpunkt respektiert dieselben `<feld>-<op>`-Filter wie der
		Listen-Endpunkt (live bestätigt)."""
		data = self._request(f"{entity}/count", params=self._merge_params(None, filters)).json()
		result = data.get("result")
		if result is None:
			raise WeClappApiError(f"Kein result im /count für {entity}: {data}")
		return int(result)

	def get(
		self,
		entity: WeClappDocType | str,
		id: str,
		*,
		serialize_nulls: bool = False,
	) -> dict:
		"""Einzelnen Datensatz per WeClapp-ID holen."""
		params = {"serializeNulls": "true"} if serialize_nulls else None
		return self._request(f"{entity}/id/{id}", params=params).json()

	def iter_pages(
		self,
		entity: WeClappDocType | str,
		*,
		filters: Mapping[str, Any] | None = None,
		sort: str | None = None,
		properties: str | None = None,
		serialize_nulls: bool = False,
		page_size: int | None = None,
	) -> Iterator[list[dict]]:
		"""Generator: yieldt Datensätze **seitenweise** (Liste pro Seite).

		Holt Seite N, yieldt sie, holt dann erst Seite N+1. Der Aufrufer verarbeitet und
		verwirft jede Seite - so liegt nie die ganze Entität im Speicher.

		Args:
			filters: dict `{"lastModifiedDate-gt": <epoch_ms>, ...}` (WeClapp-Query-Filter).
			sort: z.B. "-lastModifiedDate" (absteigend) oder "lastModifiedDate".
			properties: Kommaliste zu ladender Felder (Feldreduktion), z.B. "id,invoiceNumber".
			serialize_nulls: WeClapp liefert Null-Felder mit statt sie wegzulassen.
		"""
		size = page_size or self.page_size
		base_params: dict[str, Any] = {"pageSize": size}
		if sort:
			base_params["sort"] = sort
		if properties:
			base_params["properties"] = properties
		if serialize_nulls:
			base_params["serializeNulls"] = "true"

		page = 1
		while True:
			params = self._merge_params({**base_params, "page": page}, filters)
			rows = self._request(str(entity), params=params).json().get("result", [])
			if not rows:
				break
			yield rows
			if len(rows) < size:
				break
			page += 1

	def iter_all(
		self,
		entity: WeClappDocType | str,
		*,
		filters: Mapping[str, Any] | None = None,
		sort: str | None = None,
		properties: str | None = None,
		serialize_nulls: bool = False,
		page_size: int | None = None,
	) -> Iterator[dict]:
		"""Generator: yieldt einzelne Datensätze, intern seitenweise geladen."""
		for rows in self.iter_pages(
			entity,
			filters=filters,
			sort=sort,
			properties=properties,
			serialize_nulls=serialize_nulls,
			page_size=page_size,
		):
			yield from rows

	# ------------------------------------------------------------------ Anhänge / Belege
	def get_documents(self, entity: WeClappDocType | str, id: str) -> list[dict]:
		"""Metadaten aller an einen Datensatz gehängten WeClapp-Dokumente (Dateien)."""
		return self._request(
			"document", params={"entityName": str(entity), "entityId": id}
		).json().get("result", [])

	def iter_document_content(self, document_id: str, *, chunk_size: int = 1 << 16) -> Iterator[bytes]:
		"""Generator über den Binärinhalt eines WeClapp-Dokuments - streamend, damit große
		PDFs nicht komplett in den RAM geladen werden. Der Aufrufer schreibt die Chunks direkt
		in eine Datei / einen Frappe-File und verwirft sie."""
		url = self.base_url + f"document/id/{document_id}/download"
		try:
			with self.session.get(url, stream=True, timeout=_TIMEOUT) as resp:
				resp.raise_for_status()
				yield from resp.iter_content(chunk_size=chunk_size)
		except requests.RequestException as e:
			raise WeClappApiError(f"Download von document/{document_id} fehlgeschlagen: {e}", url=url) from e

	# ------------------------------------------------------------------ Helfer
	@staticmethod
	def modified_since_filter(epoch_ms: int | None) -> dict[str, Any]:
		"""Baut den Delta-Filter. `None`/0 -> leerer Filter (= Vollabruf)."""
		if not epoch_ms:
			return {}
		return {"lastModifiedDate-gt": int(epoch_ms)}

	@staticmethod
	def now_ms() -> int:
		return int(time.time() * 1000)

	# create/update/delete existieren bewusst NICHT. Ein Aufruf über _request mit
	# nicht-GET-Methode wirft WeClappWriteRefused.
	def create(self, *_a: object, **_k: object) -> None:  # pragma: no cover
		raise WeClappWriteRefused("WeClapp-Client ist read-only - create() gibt es nicht")

	def update(self, *_a: object, **_k: object) -> None:  # pragma: no cover
		raise WeClappWriteRefused("WeClapp-Client ist read-only - update() gibt es nicht")

	def delete(self, *_a: object, **_k: object) -> None:  # pragma: no cover
		raise WeClappWriteRefused("WeClapp-Client ist read-only - delete() gibt es nicht")
