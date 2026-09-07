# WeClapp REST-API
WC_API_BASE                 = "https://your-tenant.weclapp.com/webapp/api/v1/"
WC_API_TOKEN                = "your-api-token"
WC_PAGE_SIZE                = 100       # Amount of entities to fetch per request

# WeClapp Cache DB
WC_CACHE_BASE               = "./weclapp/cache/"
WC_CACHE_DOCUMENTS_BASE     = "./weclapp/cache/documents/"

# ERPNext REST-API
EN_API_BASE                 = "http://erp.localhost:8000/api/"
EN_API_KEY                  = "your-api-key"
EN_API_SECRET               = "your-api-secret"

# ERPNext Country Mapping - WeClapp countryCode (ISO 3166-1 alpha-2, lowercased) -> exact ERPNext Country name.
# Generated from the live ERPNext Country doctype so every code actually resolves to a real record.
EN_COUNTRY_MAP = {
    'ad': 'Andorra',
    'ae': 'United Arab Emirates',
    'af': 'Afghanistan',
    'ag': 'Antigua and Barbuda',
    'ai': 'Anguilla',
    'al': 'Albania',
    'am': 'Armenia',
    'ao': 'Angola',
    'aq': 'Antarctica',
    'ar': 'Argentina',
    'as': 'American Samoa',
    'at': 'Austria',
    'au': 'Australia',
    'aw': 'Aruba',
    'ax': 'Åland Islands',
    'az': 'Azerbaijan',
    'ba': 'Bosnia and Herzegovina',
    'bb': 'Barbados',
    'bd': 'Bangladesh',
    'be': 'Belgium',
    'bf': 'Burkina Faso',
    'bg': 'Bulgaria',
    'bh': 'Bahrain',
    'bi': 'Burundi',
    'bj': 'Benin',
    'bl': 'Saint Barthélemy',
    'bm': 'Bermuda',
    'bn': 'Brunei Darussalam',
    'bo': 'Bolivia, Plurinational State of',
    'bq': 'Bonaire, Sint Eustatius and Saba',
    'br': 'Brazil',
    'bs': 'Bahamas',
    'bt': 'Bhutan',
    'bv': 'Bouvet Island',
    'bw': 'Botswana',
    'by': 'Belarus',
    'bz': 'Belize',
    'ca': 'Canada',
    'cc': 'Cocos (Keeling) Islands',
    'cd': 'Congo, The Democratic Republic of the',
    'cf': 'Central African Republic',
    'cg': 'Congo',
    'ch': 'Switzerland',
    'ci': 'Ivory Coast',
    'ck': 'Cook Islands',
    'cl': 'Chile',
    'cm': 'Cameroon',
    'cn': 'China',
    'co': 'Colombia',
    'cr': 'Costa Rica',
    'cu': 'Cuba',
    'cv': 'Cape Verde',
    'cw': 'Curaçao',
    'cx': 'Christmas Island',
    'cy': 'Cyprus',
    'cz': 'Czech Republic',
    'de': 'Germany',
    'dj': 'Djibouti',
    'dk': 'Denmark',
    'dm': 'Dominica',
    'do': 'Dominican Republic',
    'dz': 'Algeria',
    'ec': 'Ecuador',
    'ee': 'Estonia',
    'eg': 'Egypt',
    'eh': 'Western Sahara',
    'er': 'Eritrea',
    'es': 'Spain',
    'et': 'Ethiopia',
    'fi': 'Finland',
    'fj': 'Fiji',
    'fk': 'Falkland Islands (Malvinas)',
    'fm': 'Micronesia, Federated States of',
    'fo': 'Faroe Islands',
    'fr': 'France',
    'ga': 'Gabon',
    'gb': 'United Kingdom',
    'gd': 'Grenada',
    'ge': 'Georgia',
    'gf': 'French Guiana',
    'gg': 'Guernsey',
    'gh': 'Ghana',
    'gi': 'Gibraltar',
    'gl': 'Greenland',
    'gm': 'Gambia',
    'gn': 'Guinea',
    'gp': 'Guadeloupe',
    'gq': 'Equatorial Guinea',
    'gr': 'Greece',
    'gs': 'South Georgia and the South Sandwich Islands',
    'gt': 'Guatemala',
    'gu': 'Guam',
    'gw': 'Guinea-Bissau',
    'gy': 'Guyana',
    'hk': 'Hong Kong',
    'hm': 'Heard Island and McDonald Islands',
    'hn': 'Honduras',
    'hr': 'Croatia',
    'ht': 'Haiti',
    'hu': 'Hungary',
    'id': 'Indonesia',
    'ie': 'Ireland',
    'il': 'Israel',
    'im': 'Isle of Man',
    'in': 'India',
    'io': 'British Indian Ocean Territory',
    'iq': 'Iraq',
    'ir': 'Iran',
    'is': 'Iceland',
    'it': 'Italy',
    'je': 'Jersey',
    'jm': 'Jamaica',
    'jo': 'Jordan',
    'jp': 'Japan',
    'ke': 'Kenya',
    'kg': 'Kyrgyzstan',
    'kh': 'Cambodia',
    'ki': 'Kiribati',
    'km': 'Comoros',
    'kn': 'Saint Kitts and Nevis',
    'kp': 'Korea, Democratic Peoples Republic of',
    'kr': 'Korea, Republic of',
    'kw': 'Kuwait',
    'ky': 'Cayman Islands',
    'kz': 'Kazakhstan',
    'la': 'Lao Peoples Democratic Republic',
    'lb': 'Lebanon',
    'lc': 'Saint Lucia',
    'li': 'Liechtenstein',
    'lk': 'Sri Lanka',
    'lr': 'Liberia',
    'ls': 'Lesotho',
    'lt': 'Lithuania',
    'lu': 'Luxembourg',
    'lv': 'Latvia',
    'ly': 'Libya',
    'ma': 'Morocco',
    'mc': 'Monaco',
    'md': 'Moldova, Republic of',
    'me': 'Montenegro',
    'mf': 'Saint Martin (French part)',
    'mg': 'Madagascar',
    'mh': 'Marshall Islands',
    'mk': 'Macedonia',
    'ml': 'Mali',
    'mm': 'Myanmar',
    'mn': 'Mongolia',
    'mo': 'Macao',
    'mp': 'Northern Mariana Islands',
    'mq': 'Martinique',
    'mr': 'Mauritania',
    'ms': 'Montserrat',
    'mt': 'Malta',
    'mu': 'Mauritius',
    'mv': 'Maldives',
    'mw': 'Malawi',
    'mx': 'Mexico',
    'my': 'Malaysia',
    'mz': 'Mozambique',
    'na': 'Namibia',
    'nc': 'New Caledonia',
    'ne': 'Niger',
    'nf': 'Norfolk Island',
    'ng': 'Nigeria',
    'ni': 'Nicaragua',
    'nl': 'Netherlands',
    'no': 'Norway',
    'np': 'Nepal',
    'nr': 'Nauru',
    'nu': 'Niue',
    'nz': 'New Zealand',
    'om': 'Oman',
    'pa': 'Panama',
    'pe': 'Peru',
    'pf': 'French Polynesia',
    'pg': 'Papua New Guinea',
    'ph': 'Philippines',
    'pk': 'Pakistan',
    'pl': 'Poland',
    'pm': 'Saint Pierre and Miquelon',
    'pn': 'Pitcairn',
    'pr': 'Puerto Rico',
    'ps': 'Palestinian Territory, Occupied',
    'pt': 'Portugal',
    'pw': 'Palau',
    'py': 'Paraguay',
    'qa': 'Qatar',
    're': 'Réunion',
    'ro': 'Romania',
    'rs': 'Serbia',
    'ru': 'Russian Federation',
    'rw': 'Rwanda',
    'sa': 'Saudi Arabia',
    'sb': 'Solomon Islands',
    'sc': 'Seychelles',
    'sd': 'Sudan',
    'se': 'Sweden',
    'sg': 'Singapore',
    'sh': 'Saint Helena, Ascension and Tristan da Cunha',
    'si': 'Slovenia',
    'sj': 'Svalbard and Jan Mayen',
    'sk': 'Slovakia',
    'sl': 'Sierra Leone',
    'sm': 'San Marino',
    'sn': 'Senegal',
    'so': 'Somalia',
    'sr': 'Suriname',
    'ss': 'South Sudan',
    'st': 'Sao Tome and Principe',
    'sv': 'El Salvador',
    'sx': 'Sint Maarten (Dutch part)',
    'sy': 'Syria',
    'sz': 'Swaziland',
    'tc': 'Turks and Caicos Islands',
    'td': 'Chad',
    'tf': 'French Southern Territories',
    'tg': 'Togo',
    'th': 'Thailand',
    'tj': 'Tajikistan',
    'tk': 'Tokelau',
    'tl': 'Timor-Leste',
    'tm': 'Turkmenistan',
    'tn': 'Tunisia',
    'to': 'Tonga',
    'tr': 'Türkiye',
    'tt': 'Trinidad and Tobago',
    'tv': 'Tuvalu',
    'tw': 'Taiwan',
    'tz': 'Tanzania',
    'ua': 'Ukraine',
    'ug': 'Uganda',
    'um': 'United States Minor Outlying Islands',
    'us': 'United States',
    'uy': 'Uruguay',
    'uz': 'Uzbekistan',
    'va': 'Holy See (Vatican City State)',
    'vc': 'Saint Vincent and the Grenadines',
    've': 'Venezuela, Bolivarian Republic of',
    'vg': 'Virgin Islands, British',
    'vi': 'Virgin Islands, U.S.',
    'vn': 'Vietnam',
    'vu': 'Vanuatu',
    'wf': 'Wallis and Futuna',
    'ws': 'Samoa',
    'xk': 'Kosovo',
    'ye': 'Yemen',
    'yt': 'Mayotte',
    'za': 'South Africa',
    'zm': 'Zambia',
    'zw': 'Zimbabwe',
}

# ERPNext Settings
EN_DEFAULT_INVOICE_STATE        = 1                             # 0 = DRAFT, 1 = SUBMITTED, 2 = CANCELLED
EN_DEFAULT_CURRENCY             = "EUR"                         # Default currency for invoices (must exist in ERPNext)
EN_DEFAULT_PHONE_COUNTRY_CODE   = "49"                          # Default country code for phone numbers without leading +
EN_BANK_ACCOUNT_TYPE            = "Kunden-Bankkonto"            # Bank account type for customers (must exist in ERPNext)
EN_DEFAULT_UOM                  = "Nos"                         # Default UOM for items - verify this exists in your ERPNext UOM master (Frappe's default is "Nos", not "Stk")
EN_DEFAULT_COST_CENTER          = "Haupt - YC"                  # Default cost center for invoices (must exist in ERPNext - verify company abbreviation suffix!)
EN_DEFAULT_WAREHOUSE            = "Stores - YC"                 # Default warehouse for stock items in Sales/Purchase Order lines (must exist in ERPNext - verify company abbreviation suffix!)
EN_INVOICE_MODE_OF_PAYMENT      = "Cash"                        # Default mode of payment for invoices (must exist in ERPNext - "Bargeld" does not exist, ERPNext ships English mode-of-payment names)
EN_INVOICE_PAID_TO_ACCOUNT_TYPE = "Cash"                        # Default account type for paid invoices (must exist in ERPNext)
EN_DEFAULT_TAXES_AND_CHARGES    = "Lieferung oder sonstige Leistung im Inland - YC"          # Default taxes and charges for invoices (must exist in ERPNext)
EN_INVOICE_PAID_FROM_ACCOUNT    = "1410 - Forderungen aus Lieferungen und Leistungen ohne Kontokorrent - YC"  # Receivable account paid from (must be a leaf/postable account, not a group node)
EN_INVOICE_PAID_TO_ACCOUNT      = "1000 - Kasse - YC"                                       # Cash account paid to (must exist in ERPNext)
EN_MODE_OF_PAYMENT_BANK         = "Wire Transfer"                                           # Mode of payment for bank-settled payments (must exist in ERPNext, alongside EN_INVOICE_MODE_OF_PAYMENT)
EN_BANK_ACCOUNT_GROUP              = "Bank - YC"                                            # Parent group for real bank/payment accounts (must exist in ERPNext)
EN_LOAN_ACCOUNT_GROUP              = "II. Verbindlichkeiten gegenüber Kreditinstituten - YC" # Parent group for loan/credit-card accounts (SKR03 "0"-prefixed account numbers)
EN_RECEIVABLE_WRITEOFF_ACCOUNT     = "2400 - Forderungsverluste - YC"                        # Booked against for WeClapp payments with no matching journal entry
EN_RECEIVABLE_WRITEOFF_ACCOUNT_TYPE = "Expense Account"                                     # Account type of EN_RECEIVABLE_WRITEOFF_ACCOUNT
EN_RECEIVABLE_WRITEOFF_ACCOUNT_GROUP = "Aufwendungen 2/4 - YC"                              # Parent group EN_RECEIVABLE_WRITEOFF_ACCOUNT is created under (must exist in ERPNext)
EN_DEBTOR_ACCOUNT_GROUP             = "1400 - Forderungen aus Lieferungen und Leistungen mit Kontokorrent - YC"    # Parent group for per-customer individual sub-ledger accounts (Personenkonten) - verify against your chart of accounts
EN_CREDITOR_ACCOUNT_GROUP           = "1600 - Verbindlichkeiten aus Lieferungen und Leistungen mit Kontokorrent - YC"  # Parent group for per-supplier individual sub-ledger accounts (Personenkonten) - verify against your chart of accounts

EN_FREE_TEXT_ITEM               = "FREITEXT"                    # Placeholder item for free-text document lines without a WeClapp article (created by setup.py)
EN_UPLOAD_IGNORE_PATTERNS       = ["Bestandsbewertung"]         # WeClapp document files whose name contains one of these substrings (case-insensitive) are NOT uploaded to ERPNext
EN_PURCHASE_IMPORT_VAT_ACCOUNT  = "1588 - Entstandene Einfuhrumsatzsteuer - YC"  # Account for WeClapp's importSalesTaxAmount (Einfuhrumsatzsteuer) on purchase invoices
WC_CACHE_IMAGES_BASE            = "weclapp/cache/images/"       # Local cache for article images (filled by cache_article_images.py, read by the article migration)
EN_COMPANY                      = "Your Company"                # ERPNext company name (for item defaults etc.)
EN_COMPANY_ABBR                 = "YC"                          # ERPNext company abbreviation, auto-appended by ERPNext to Warehouse/Cost Center/... names
EN_DEFAULT_BUYING_PRICE_LIST    = "Standard Buying"             # Buying price list for purchase prices from WeClapp supply sources

# WeClapp custom attributes (by attributeKey) that are NOT migrated (e.g. per-shop integration fields)
EN_CUSTOM_ATTRIBUTE_EXCLUDE = set()

# Explicit fieldtype overrides per attributeKey (defaults derive from the WeClapp attributeType)
EN_CUSTOM_ATTRIBUTE_TYPE_OVERRIDES = {}

# WeClapp MULTISELECT_LIST attributes rendered as real multi-select dropdowns in ERPNext
# (fieldtype "Table MultiSelect"). Maps attributeKey -> name of the option DocType that
# setup.py creates and fills with the WeClapp selectableValues.
EN_MULTISELECT_TABLE_FIELDS = {}

# ERPNext UOM Mapping - WeClapp unitName (lowercased) -> ERPNext UOM name.
# Frappe ships English UOM names ("Nos", "Kg", "Gram", "Litre", "Meter", ...) which usually don't
# match WeClapp's German short forms 1:1 - check your ERPNext UOM list and adjust this mapping.
EN_UOM_MAP = {
    'stk.': 'Nos',
    'stk': 'Nos',
    'kg': 'Kg',
    'g': 'Gram',
    'l': 'Litre',
    'h': 'Hour',
    'm': 'Meter',
    'm²': 'Square Meter',
    'cm²': 'Square Centimeter',
    'tag': 'Day',
    'woche': 'Week',
}

# ERPNext Settings - Articles / Items
EN_DEFAULT_ITEM_GROUP           = "All Item Groups"             # Fallback item group for articles without a recordItemGroupName (must exist in ERPNext)
EN_DEFAULT_PRICE_LIST           = "Standard Selling"             # Default price list for article prices (must exist in ERPNext)

# ERPNext Settings - Customers
EN_CUSTOMER_GROUP_COMPANY       = "Commercial"                   # Customer group for company customers (must exist in ERPNext - check your Customer Group list!)
EN_CUSTOMER_GROUP_INDIVIDUAL    = "Individual"                   # Customer group for private customers (must exist in ERPNext)
EN_TERRITORY_GERMANY            = "Germany"                      # Territory name used when the customer's country resolves to Germany
EN_TERRITORY_DEFAULT            = "Rest Of The World"            # Fallback territory for any other country - check what Territory records actually exist in your ERPNext!

# ERPNext Settings - Suppliers
EN_DEFAULT_SUPPLIER_GROUP       = "All Supplier Groups"          # Fallback supplier group (must exist in ERPNext)

# ERPNext Settings - Purchase invoices
EN_DEFAULT_PURCHASE_TAXES_AND_CHARGES = "Lieferung aus dem Inland - YC"                      # Default purchase taxes and charges template (must exist in ERPNext)
EN_PURCHASE_MODE_OF_PAYMENT           = "Cash"                                               # Default mode of payment for purchase invoices (must exist in ERPNext)
EN_PURCHASE_PAID_FROM_ACCOUNT         = "1000 - Kasse - YC"                                  # Cash account paid from when settling a purchase invoice (must exist in ERPNext)
EN_PURCHASE_PAID_FROM_ACCOUNT_TYPE    = "Cash"                                               # Account type of EN_PURCHASE_PAID_FROM_ACCOUNT
EN_PURCHASE_PAID_TO_ACCOUNT           = "1610 - Verbindlichkeiten aus Lieferungen und Leistungen ohne Kontokorrent - YC"  # Payable account paid to (leaf/postable account)
EN_PURCHASE_PAID_TO_ACCOUNT_TYPE      = "Payable"                                            # Account type of EN_PURCHASE_PAID_TO_ACCOUNT

# ERPNext Settings - Bank accounts
EN_MIGRATE_BANK_ACCOUNTS        = True                           # If False, customer/supplier bank accounts are not migrated

# ERPNext Settings - Payment Terms
EN_MIGRATION_PAYMENT_TERMS_TEMPLATE = "Migration - unbegrenzt"   # Dummy template with a very high credit_days, set on every migrated Sales/Purchase Invoice - see config.py comment for why