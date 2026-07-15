"""Shared ISO 4217 currency choices for documents."""

CURRENCY_CHOICES = [
    ('AED', 'AED - UAE Dirham'),
    ('USD', 'USD - US Dollar'),
    ('EUR', 'EUR - Euro'),
    ('GBP', 'GBP - British Pound'),
    ('INR', 'INR - Indian Rupee'),
]

CURRENCY_NAMES = {
    'AED': 'UAE Dirham (AED)',
    'USD': 'US Dollar (USD)',
    'EUR': 'Euro (EUR)',
    'GBP': 'British Pound (GBP)',
    'INR': 'Indian Rupee (INR)',
}

CURRENCY_WORDS = {
    'AED': 'Dirhams',
    'USD': 'US Dollars',
    'EUR': 'Euros',
    'GBP': 'British Pounds',
    'INR': 'Indian Rupees',
}

VALID_CURRENCY_CODES = {code for code, _ in CURRENCY_CHOICES}


def normalize_currency_code(value, default='AED'):
    code = (value or default).strip().upper()
    if code in VALID_CURRENCY_CODES:
        return code
    return default
