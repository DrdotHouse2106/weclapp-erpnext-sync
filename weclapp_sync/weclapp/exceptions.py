class WeClappApiError(Exception):
	"""Fehler beim Zugriff auf die WeClapp-REST-API."""

	def __init__(
		self,
		message: str,
		*,
		status_code: int | None = None,
		method: str | None = None,
		url: str | None = None,
		response_text: str | None = None,
	):
		super().__init__(message)
		self.message = message
		self.status_code = status_code
		self.method = method
		self.url = url
		self.response_text = response_text

	def to_dict(self) -> dict:
		return {
			"message": self.message,
			"status_code": self.status_code,
			"method": self.method,
			"url": self.url,
			"response_text": self.response_text,
		}


class WeClappWriteRefused(WeClappApiError):
	"""Wird geworfen, wenn irgendjemand versucht, über diesen Client schreibend auf WeClapp
	zuzugreifen. WeClapp ist das produktive Quellsystem - dieser Client ist ausschließlich
	lesend, und das wird hart erzwungen, nicht nur per Konvention."""
