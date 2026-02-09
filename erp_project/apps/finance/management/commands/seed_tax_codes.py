"""
Seed Default Tax Codes (UAE VAT Compliance)

This command creates the required Tax Codes for proper VAT handling:
- Standard Rated (5%) - Default for most transactions
- Zero Rated (0%) - Exports, international services
- Exempt - Financial services, residential rent
- Out of Scope - Outside VAT scope

NO hard-coded VAT percentages anywhere else in the system.
All VAT must be derived from these Tax Codes.
"""
from django.core.management.base import BaseCommand
from apps.finance.models import TaxCode, Account, AccountType
from decimal import Decimal


class Command(BaseCommand):
    help = 'Seed default Tax Codes for UAE VAT compliance'

    def handle(self, *args, **options):
        self.stdout.write('Seeding default Tax Codes...')
        
        # Get or create VAT accounts
        vat_payable = Account.objects.filter(
            is_active=True,
            account_type=AccountType.LIABILITY,
            name__icontains='vat'
        ).first()
        
        if not vat_payable:
            vat_payable = Account.objects.filter(
                is_active=True,
                account_type=AccountType.LIABILITY,
                code__startswith='21'
            ).first()
        
        vat_recoverable = Account.objects.filter(
            is_active=True,
            account_type=AccountType.ASSET,
            name__icontains='vat'
        ).first()
        
        if not vat_recoverable:
            vat_recoverable = Account.objects.filter(
                is_active=True,
                account_type=AccountType.ASSET,
                code__startswith='13'
            ).first()
        
        # Define default Tax Codes (UAE Standard)
        tax_codes = [
            {
                'code': 'VAT5',
                'name': 'VAT 5% - Standard Rated',
                'tax_type': 'standard',
                'rate': Decimal('5.00'),
                'description': 'Standard VAT rate for UAE (5%). Applies to most goods and services.',
                'is_default': True,  # Default for new transactions
                'sales_account': vat_payable,
                'purchase_account': vat_recoverable,
            },
            {
                'code': 'VAT0',
                'name': 'VAT 0% - Zero Rated',
                'tax_type': 'zero',
                'rate': Decimal('0.00'),
                'description': 'Zero-rated supplies. Includes: Exports of goods/services, International transportation, First sale of new residential buildings, Designated zones.',
                'is_default': False,
                'sales_account': vat_payable,
                'purchase_account': vat_recoverable,
            },
            {
                'code': 'VATEX',
                'name': 'VAT Exempt',
                'tax_type': 'exempt',
                'rate': Decimal('0.00'),
                'description': 'Exempt supplies. Includes: Financial services (specified), Residential rent, Bare land, Local passenger transport.',
                'is_default': False,
                'sales_account': None,  # No VAT account for exempt
                'purchase_account': None,
            },
            {
                'code': 'VATOOS',
                'name': 'Out of Scope',
                'tax_type': 'out_of_scope',
                'rate': Decimal('0.00'),
                'description': 'Outside the scope of UAE VAT. Includes: Government entities (specified activities), Owner-managed property, Non-business activities.',
                'is_default': False,
                'sales_account': None,
                'purchase_account': None,
            },
        ]
        
        created_count = 0
        updated_count = 0
        
        for tax_data in tax_codes:
            tax_code, created = TaxCode.objects.update_or_create(
                code=tax_data['code'],
                defaults={
                    'name': tax_data['name'],
                    'tax_type': tax_data['tax_type'],
                    'rate': tax_data['rate'],
                    'description': tax_data['description'],
                    'is_default': tax_data['is_default'],
                    'sales_account': tax_data['sales_account'],
                    'purchase_account': tax_data['purchase_account'],
                    'is_active': True,
                }
            )
            
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Created: {tax_data["code"]} - {tax_data["name"]} ({tax_data["rate"]}%)'
                ))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(
                    f'  ↻ Updated: {tax_data["code"]} - {tax_data["name"]} ({tax_data["rate"]}%)'
                ))
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Tax Code seeding complete: {created_count} created, {updated_count} updated'
        ))
        
        # Validation check
        default_count = TaxCode.objects.filter(is_active=True, is_default=True).count()
        if default_count != 1:
            self.stdout.write(self.style.WARNING(
                f'⚠ Warning: {default_count} default Tax Codes found (should be exactly 1)'
            ))
        
        self.stdout.write('')
        self.stdout.write('TAX CODE USAGE RULES:')
        self.stdout.write('  1. All VAT must be derived from Tax Codes')
        self.stdout.write('  2. No Tax Code = Out of Scope (0% VAT)')
        self.stdout.write('  3. VAT rate is READ-ONLY (computed from Tax Code)')
        self.stdout.write('  4. VAT reports differentiate: Standard, Zero, Exempt, Out of Scope')



