import config
from pathlib import Path
from .base_migration import BaseMigration
from .item_price_migration import ItemPriceMigration
from erpnext import ERPNextAPI, ERPNextDocType, ERPNextHelper
from weclapp import WeClappDocType

class ArticleMigration(BaseMigration):
    """Migration wrapper for an article object from WeClapp to ERPNext."""

    def __init__(self, en_api: ERPNextAPI, wc_data: dict, wc_custom_attribute_definitions: dict,
                 wc_article_categories: dict = None, wc_article_supply_sources: dict = None):
        """Initializes the migration wrapper."""
        super().__init__(en_api, wc_data, wc_custom_attribute_definitions)
        self.wc_article_categories = wc_article_categories or {}
        self.wc_article_supply_sources = wc_article_supply_sources or {}

    def get_doctype(self) -> ERPNextDocType:
        return ERPNextDocType.ITEM

    def get_wc_doctype(self) -> WeClappDocType:
        return WeClappDocType.ARTICLE

    def migrate(self) -> dict:
        """Migrates a given WeClapp-Object and creates it in ERPNext."""
        if not self.validate():
            return None

        # Base data
        en_data = self._transform()

        # Upsert: if the item already exists (same article number), update it with the current
        # field mapping (custom fields, manufacturer, ...) instead of failing with a duplicate
        # error. Prices/documents are skipped then to avoid duplicating them.
        # "description"/"item_group" are excluded here on purpose: once an item exists, these two
        # fields may be co-managed by other integrations (e.g. a Shopware sync writing back
        # shop-edited descriptions/categories) that only push their own state, don't track who
        # last touched the field, and would be silently overwritten by a WeClapp re-run - even
        # though this project's own plan is to run the WeClapp import only once, before any such
        # integration starts. Only setting them on initial creation makes that safe regardless of
        # whether that "runs only once" assumption actually holds in practice.
        existing = self._en_api.get(ERPNextDocType.ITEM, en_data.get("item_code"))
        if existing:
            update_data = {k: v for k, v in en_data.items()
                            if k not in ("item_code", "taxes", "barcodes", "description", "item_group")}
            en_item = self._en_api.update(ERPNextDocType.ITEM, en_data.get("item_code"), update_data)["data"]
            # Backfill images on re-runs, but only while none is set yet (avoids duplicates)
            if not existing.get("image"):
                self._upload_article_images(en_item.get("name", str()))
            # Backfill the buying price (duplicate creations are rejected by ERPNext and skipped)
            self._create_purchase_price(en_item)
            return en_item

        # Create item in ERPNext. Some WeClapp articles share the same EAN, but ERPNext
        # enforces barcode uniqueness - in that case retry without the barcode (first
        # article keeps the EAN, duplicates lose only the barcode, not the whole item).
        try:
            en_item = self._en_api.create(ERPNextDocType.ITEM, en_data)
        except Exception as e:
            if "Barcode" in str(e) and en_data.get("barcodes"):
                en_data["barcodes"] = []
                en_item = self._en_api.create(ERPNextDocType.ITEM, en_data)
            else:
                raise

        # Prices: WeClapp keeps several parallel prices per article, one per sales channel
        # (NET1, NET7, GROSS1, ...) rather than a price history - all can be active at once
        # (endDate == null). Since all of them currently map onto the single
        # config.EN_DEFAULT_PRICE_LIST, only the first general (non-customer-specific) price is
        # migrated, or ERPNext rejects the rest as duplicates for that price list/item/currency.
        # Price scales (priceScaleType/priceScaleValue) are not considered either.
        general_prices = [p for p in self.wc_data.get("articlePrices", []) if p.get("customerId") is None]
        if general_prices:
            price_migration = ItemPriceMigration(self._en_api, general_prices[0], en_item)
            if price_migration.validate():
                price_migration.migrate()

        # Purchase price from the primary supply source (Standard Buying price list)
        self._create_purchase_price(en_item)

        # Upload WeClapp documents (data sheets, spreadsheets, etc.)
        self.upload_weclapp_documents(en_item.get("name", str()))

        # Upload article images (if cached locally - see cache_article_images.py)
        self._upload_article_images(en_item.get("name", str()))

        return en_item

    def _create_purchase_price(self, en_item: dict):
        """Creates the ERPNext buying Item Price from the primary WeClapp supply source.
        Safe to call repeatedly - ERPNext rejects a second price for the same
        item/price list/currency as a duplicate, which is caught and ignored.

        Args:
            en_item (dict): Created/updated ERPNext item
        """
        price = self._map_purchase_price()
        if not price or price <= 0:
            return
        try:
            self._en_api.create(ERPNextDocType.ITEM_PRICE, {
                "item_code"       : en_item.get("name"),
                "price_list"      : config.EN_DEFAULT_BUYING_PRICE_LIST,
                "price_list_rate" : price,
                "currency"        : config.EN_DEFAULT_CURRENCY,
                "buying"          : 1
            })
        except Exception as e:
            if "Duplicate" not in str(e) and "already exists" not in str(e):
                raise

    def _upload_article_images(self, name: str):
        """Uploads the locally cached WeClapp article images (see cache_article_images.py).
        The WeClapp main image (cached with "MAIN_" filename prefix) becomes the ERPNext
        item image; all others become plain attachments. Does nothing if no images were
        cached for this article.

        Args:
            name (str): ERPNext item name
        """
        image_dir = Path(config.WC_CACHE_IMAGES_BASE).joinpath(f"article/{self.wc_data.get('id')}")
        if not image_dir.exists():
            return

        # Same failure tolerance as BaseMigration.upload_weclapp_documents(): the item already
        # exists, a re-run would skip the images - so a failed upload must not fail the record
        for file in sorted(image_dir.iterdir()):
            if not file.is_file():
                continue
            try:
                uploaded = self._en_api.upload_file(ERPNextDocType.ITEM, name, str(file))
                print(f"Uploaded image {file.name}")
                if file.name.startswith("MAIN_") and uploaded.get("file_url"):
                    self._en_api.update(ERPNextDocType.ITEM, name, {"image": uploaded["file_url"]})
            except Exception as e:
                print(f"FAILED image upload {file.name} to Item {name}: {type(e).__name__}: {e}")

    def validate(self) -> bool:
        """
        Validates the given data.
        Returns: True if valid, False if not
        """
        return self.wc_data.get("articleNumber") and self.wc_data.get("name")

    def _transform(self) -> dict:
        """Transforms the data from WeClapp to ERPNext."""

        transformed_data = {
            "item_code": self.wc_data.get("articleNumber"),
            "item_name": (self.wc_data.get("name") or "")[:140],
            "item_group": self._map_item_group(),
            "description": self.wc_data.get("description") or self.wc_data.get("name"),
            "stock_uom": ERPNextHelper.get_uom_string(self.wc_data.get("unitName", None)),
            "is_stock_item": 1 if self.wc_data.get("articleType") == "STORABLE" else 0,
            "weight_per_unit": self.wc_data.get("articleGrossWeight") or 0,
            "barcodes": self._map_barcodes(),
            # Always imported enabled - ERPNext refuses documents referencing disabled items, and
            # old documents still reference inactive articles. WeClapp's active flag is applied
            # afterwards by main.py's apply_wc_blocks() final phase.
            "disabled": 0,
            "manufacturer": self.wc_data.get("manufacturerName") or None,
            "manufacturer_part_no": self.wc_data.get("manufacturerPartNumber") or None,
            "country_of_origin": ERPNextHelper.get_country_string(self.wc_data.get("countryOfOriginCode")),
            "taxes": self._map_item_taxes(),
            "supplier_items": self._map_supplier_items(),
            "item_defaults": self._map_item_defaults(),
        }

        # Custom Attributes (Zusatzfelder)
        transformed_data.update(self._map_custom_attributes())

        return transformed_data

    def _map_item_group(self) -> str:
        """Maps the article's category (articleCategoryId) to an ERPNext Item Group name.
        "recordItemGroupName" is always null in the real data - the actual category is
        referenced via articleCategoryId (see weclapp/cache/articleCategory.json).
        """
        category = self.wc_article_categories.get(self.wc_data.get("articleCategoryId"))
        return category.get("name") if category else config.EN_DEFAULT_ITEM_GROUP

    def _get_supply_sources(self) -> list[dict]:
        """Returns the article's resolved WeClapp supply sources (Bezugsquellen), ordered by
        positionNumber (position 1 = primary source).
        """
        refs = sorted(self.wc_data.get("supplySources") or [],
                      key=lambda s: s.get("positionNumber") or 999)
        sources = []
        for ref in refs:
            source = self.wc_article_supply_sources.get(ref.get("articleSupplySourceId"))
            if source and source.get("supplierNumber"):
                sources.append(source)
        return sources

    def _map_supplier_items(self) -> list[dict]:
        """Maps the WeClapp supply sources to ERPNext's Item Supplier child table
        (supplier + the supplier's own article number).
        """
        supplier_items = []
        seen = set()
        for source in self._get_supply_sources():
            supplier = source.get("supplierNumber")
            if supplier in seen:
                continue
            seen.add(supplier)
            supplier_items.append({
                "supplier": supplier,
                "supplier_part_no": source.get("articleNumber") or None
            })
        return supplier_items

    def _map_item_defaults(self) -> list[dict]:
        """Maps the primary supply source (positionNumber 1) to the item's default supplier.
        """
        sources = self._get_supply_sources()
        if not sources:
            return []
        return [{
            "company": config.EN_COMPANY,
            "default_supplier": sources[0].get("supplierNumber")
        }]

    def _map_purchase_price(self) -> float:
        """Returns the purchase price of the primary supply source (first base price,
        scale 'from 1' preferred), or None.
        """
        for source in self._get_supply_sources():
            prices = source.get("articlePrices") or []
            if not prices:
                continue
            base = [p for p in prices if str(p.get("priceScaleValue") or "1") == "1"]
            price = (base or prices)[0].get("price")
            return float(price) if price is not None else None
        return None

    def _map_item_taxes(self) -> list:
        """Deliberately returns no Item Tax Template. An Item's default template is static
        (one rate), but the same article can appear in historical WeClapp documents under
        different tax treatments (domestic standard rate, reduced rate, tax-free export, ...).
        Every migration already books the exact real tax amount per line as an "Actual" row on
        the document itself (see BaseMigration._add_tax/_map_taxes) - a default template here
        would only conflict with that on every historical document where the applied rate
        differs from the item's current default, tripping ERPNext's item-wise tax
        reconciliation ("Artikelbezogene Steuerdetails stimmen nicht ... überein"). Confirmed
        live: this caused ~15-38% of Sales Order/Quotation/Sales Invoice failures in the first
        full migration run against a freshly reset instance, before this fix.
        """
        return []

    def _map_barcodes(self) -> list:
        """Maps the EAN of the article to ERPNext's Item Barcode child table.
        """
        ean = self.wc_data.get("ean", None)
        return [{"barcode": ean}] if ean else []
