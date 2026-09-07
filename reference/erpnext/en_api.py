import requests
import json
from enum import Enum
from requests.auth import HTTPBasicAuth
from requests import RequestException
from .en_api_data import ERPNextAPIChild
from .en_doctypes import ERPNextDocType
from base import ApiBase, ApiException
from pathlib import Path

class FilterOperator(Enum):
    EQUALS                  = "="
    NOT_EQUALS              = "!="
    LESS_THAN               = "<"
    GREATER_THAN            = ">"
    LESS_THAN_OR_EQUALS     = "<="
    GREATER_THAN_OR_EQUALS  = ">="

class ERPNextFilter:
    def __init__(self, field: str, operator: FilterOperator, value: str):
        self.field = field
        self.operator = operator
        self.value = value

    def get_erpnext_filter(self) -> list:
        return [self.field, self.operator.value, self.value]

class ERPNextAPI(ApiBase):
    def __init__(self, api_key : str, api_secret : str, base_url : str):
        """Class for accessing ERPNext API.

        Args:
            api_key (str): ERPNext API key
            api_secret (str): ERPNext API secret
            base_url (str): ERPNext API base URL with trailing slash
            doctype (str): ERPNext DocType (e.g. Customer, Address, ...)
        """
        super().__init__(base_url)
        self.api_key = api_key
        self.api_secret = api_secret

    def open(self):
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(self.api_key, self.api_secret)
        self.session.headers = {"Content-Type": "application/json"}

    def close(self):
        self.session.close()
    
    def _request(self, url: str, method: str, data: dict = None, params: dict = None) -> dict:
        """Makes a request to ERPNext API

        Args:
            url (str): URL to make request to
            method (str): HTTP method (e.g. GET, POST, PUT, DELETE)
            data (ERPNextAPIData, optional): Data to send with request. Defaults to None.

        Returns:
            dict: Response JSON
        Raises:
            Exception: If request fails
        """
        response = None
        try:
            try:
                # (connect timeout, read timeout) - without this, a stalled server/proxy connection
                # blocks the whole migration run indefinitely with no error/output (observed in
                # practice: a run stuck for 22+ hours with zero log activity after the laptop slept).
                response = self.session.request(method=method, url=url, json=data, params=params,
                                                  timeout=(10, 180))
            except RequestException:
                # Transient connection-level failure (no response object) - retry once
                response = self.session.request(method=method, url=url, json=data, params=params,
                                                  timeout=(10, 180))
            response.raise_for_status()
        except RequestException as e:
            if response is None:
                # Connection-level failure even after retry: no HTTP response to report
                raise ApiException(
                    message=f"Connection error in {method} request to {url}: {e}",
                    method=method,
                    url=url
                ) from e
            if response.status_code == 404:
                raise ApiException(
                    message=f"Not found: {response.text}",
                    method=method,
                    url=url,
                    response_text=response.text,
                    status_code=response.status_code
                ) from e
            else:
                raise ApiException(
                    f"Error in {method} request to {url}: {response.text}",
                    method=method,
                    url=url,
                    response_text=response.text,
                    status_code=response.status_code
                ) from e

        return response.json()

    def _get_resource_url(self, doctype: ERPNextDocType|str) -> str:
        """Returns base URL for current API-connection and given DocType.

        Args:
            doctype (ERPNextDocType|str): Desired DocType (enum member or raw doctype name,
                e.g. for custom DocTypes that have no enum entry)

        Returns:
            str: Url built of Base-URL & DocType
        """
        doctype_str = doctype.value if isinstance(doctype, ERPNextDocType) else doctype
        return f"{self.base_url}resource/{doctype_str}"

    def _get_method_url(self, method: str) -> str:
        """Returns base URL for current API-connection and given DocType.

        Args:
            method (str): Desired method

        Returns:
            str: Url built of Base-URL & API-method
        """
        return f"{self.base_url}method/{method}"

    def create_link(self, parent_doctype : ERPNextDocType|str, parent_name : str,
                     child_doctype : ERPNextDocType|str, child_name : str) -> dict:
        """Create a link between two entities

        Args:
            parent_doctype (ERPNextDocType|str): Parent DocType
            parent_name (str): Parent name
            child_doctype (ERPNextDocType|str): Child DocType
            child_name (str): Child name

        Returns:
            dict: Response JSON
        """
        parent_doctype_str = parent_doctype.value if isinstance(parent_doctype, ERPNextDocType) else parent_doctype
        child_doctype_str = child_doctype.value if isinstance(child_doctype, ERPNextDocType) else child_doctype

        url = f"{self.base_url}resource/{child_doctype_str}/{child_name}"
        data = {
            "links": [{
                "link_doctype": parent_doctype_str,
                "link_name": parent_name
            }]
        }
        return self._request(url, "PUT", data)
        
    def get_all(self, doctype: ERPNextDocType) -> dict:
        """Get all entities of the DocType

        Returns:
            dict: JSON-response from ERPNext API
        """
        return self._request(self._get_resource_url(doctype), "GET")
    
    def get(self, doctype: ERPNextDocType, id : str) -> dict:
        """Get an entity of the DocType

        Args:
            name (str): Name of the entity to get

        Returns:
            dict: JSON-response from ERPNext API
        """
        try:
            return self._request(f"{self._get_resource_url(doctype)}/{id}", "GET")["data"]
        except ApiException as e:
            # Only a real 404 means "doesn't exist" - anything else (500, 403, timeout) must
            # propagate, or every exists-check built on get() would mistake a transient server
            # error for a missing document and create a duplicate
            if e.status_code == 404:
                return None
            raise

    def create(self, doctype: ERPNextDocType, data : dict) -> dict:
        """Creates a new entity of the DocType

        Args:
            data (dict): Data to fill the entity with

        Returns:
            dict: JSON-response from ERPNext API
        """
        return self._request(self._get_resource_url(doctype), "POST", data)["data"]

    def update(self, doctype: ERPNextDocType, id : str, data : dict) -> dict:
        """Updates an entity of the DocType

        Args:
            name (str): Name of the entity to update
            data (dict): Data to update the entity with

        Returns:
            dict: JSON-response from ERPNext API
        """
        return self._request(f"{self._get_resource_url(doctype)}/{id}", "PUT", data)

    def delete(self, doctype: ERPNextDocType, id : str) -> dict:
        """Deletes an entity of the DocType

        Args:
            name (str): Name of the entity to delete

        Returns:
            dict: JSON-response from ERPNext API
        """
        return self._request(f"{self._get_resource_url(doctype)}/{id}", "DELETE")

    def search(self, doctype: ERPNextDocType, filters: list) -> dict:
        """Search for entities of the DocType

        Args:
            filters (list): Filters to search for (must contain ERPNextFilter-objects)

        Returns:
            dict: JSON-response from ERPNext API
        """
        filters_converted = []
        for filter in filters:
            filters_converted.append(filter.get_erpnext_filter())

        return self._request(self._get_resource_url(doctype), "GET",
                             params={"filters": json.dumps(filters_converted)})["data"]
    
    def get_count(self, doctype: ERPNextDocType) -> int:
        raise NotImplementedError("Not implemented yet")

    def get_all_names(self, doctype: ERPNextDocType) -> set:
        """Fetches the "name" field of every existing document of the given DocType in a single
        request (limit_page_length=0 - confirmed live to return the full result set, not just
        the default page). Cached per (doctype, ERPNextAPI instance) - one bulk fetch per
        migrate_all() run instead of one GET-by-name request per record. On a re-run over an
        already largely migrated doctype (e.g. 4000+ already-existing Sales Invoices), that
        one-by-one pattern alone can eat 10+ minutes per main.py restart before ever reaching a
        genuinely new record.

        Returns:
            set: All existing document names for the DocType
        """
        if not hasattr(self, "_all_names_cache"):
            self._all_names_cache = {}
        doctype_key = doctype.value if isinstance(doctype, ERPNextDocType) else doctype
        if doctype_key not in self._all_names_cache:
            response = self._request(self._get_resource_url(doctype), "GET",
                                     params={"fields": json.dumps(["name"]), "limit_page_length": 0})
            self._all_names_cache[doctype_key] = {row["name"] for row in response["data"]}
        return self._all_names_cache[doctype_key]
    
    def upload_file(self, doctype: ERPNextDocType, id: str, file_path: str) -> dict:
        """Uploads a file to the given DocType

        Args:
            doctype (ERPNextDocType): DocType to upload file to
            id (str): ID of the entity to upload file to
            file_path (str): Path to file to upload
            file_name (str, optional): Name of the file to upload. Defaults to original file name.

        Returns:
            dict: JSON-response from ERPNext API
        """
        # Upload file
        headers = {
            'Authorization': f"token {self.api_key}:{self.api_secret}",
        }
        with open(file_path, "rb") as file:
            response = requests.post(
                url     = self._get_method_url("upload_file"),
                headers = headers,
                files   = {"file": file},
                data    = {"doctype": doctype.value, "docname": id},
                timeout = (10, 180)
            )
            response.raise_for_status()
            # "message" contains the created File document (file_url etc.)
            return response.json().get("message", {})