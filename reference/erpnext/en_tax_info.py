import config

class TaxInfo:
    """Tax class for ERPNext
    """
    def __init__(self, income_account: str, tax_account: str, description: str, tax_rate: float):
        """Initializes the tax.

        Args:
            account_head (str): Account head (must exist in ERPNext)
            description (str): Description
            rate (float): Tax rate
        """
        self.income_account = income_account
        self.tax_account    = tax_account
        self.description    = description
        self.tax_rate       = tax_rate

    def __str__(self) -> str:
        """Returns a string representation of the tax.

        Returns:
            str: String representation
        """
        return f"{self.income_account} ({self.tax_rate}%)"

class PurchaseTaxInfo:
    """Tax class for ERPNext purchase invoices (uses an expense account instead of an income account)
    """
    def __init__(self, expense_account: str, tax_account: str, description: str, tax_rate: float):
        """Initializes the tax.

        Args:
            expense_account (str): Expense account head (must exist in ERPNext)
            tax_account (str): Input tax account head (must exist in ERPNext)
            description (str): Description
            tax_rate (float): Tax rate
        """
        self.expense_account = expense_account
        self.tax_account     = tax_account
        self.description     = description
        self.tax_rate        = tax_rate

    def __str__(self) -> str:
        """Returns a string representation of the tax.

        Returns:
            str: String representation
        """
        return f"{self.expense_account} ({self.tax_rate}%)"