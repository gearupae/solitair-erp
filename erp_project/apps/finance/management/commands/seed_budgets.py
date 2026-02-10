"""
Management command to seed Budget data for FY 2025.

Creates 6 budgets with detailed monthly line items:
- BUD-2025-001: Annual Operating Budget (2,500,000 AED)  - Approved
- BUD-2025-002: Marketing Budget Q1-Q2 (450,000 AED)      - Approved
- BUD-2025-003: IT Infrastructure Capital Budget (800,000) - Draft/Pending
- BUD-2025-004: HR Recruitment & Training (320,000 AED)    - Approved
- BUD-2025-005: Operations & Maintenance (1,200,000 AED)   - Draft
- BUD-2025-006: Emergency Contingency Fund (200,000 AED)   - Approved

Grand Total: 5,470,000 AED

Usage:
    python manage.py seed_budgets
    python manage.py seed_budgets --dry-run
    python manage.py seed_budgets --force
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from datetime import date

from apps.finance.models import (
    Account, FiscalYear, Budget, BudgetLine
)

D = Decimal


class Command(BaseCommand):
    help = 'Seed 6 comprehensive budgets for FY 2025 (Total: 5,470,000 AED)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be created')
        parser.add_argument('--force', action='store_true', help='Delete existing budgets and recreate')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        force = options.get('force', False)

        self.stdout.write(self.style.WARNING('\n' + '=' * 60))
        self.stdout.write(self.style.WARNING('  BUDGET DATA SEEDING - FY 2025'))
        self.stdout.write(self.style.WARNING('=' * 60 + '\n'))

        if dry_run:
            self.stdout.write(self.style.WARNING('** DRY RUN MODE **\n'))

        try:
            with transaction.atomic():
                # Step 1: Get FY 2025
                fy = self._get_fiscal_year()

                # Step 2: Check existing
                if Budget.objects.filter(fiscal_year=fy).exists():
                    if force:
                        count = Budget.objects.filter(fiscal_year=fy).count()
                        if not dry_run:
                            Budget.objects.filter(fiscal_year=fy).delete()
                        self.stdout.write(self.style.WARNING(
                            f'   Deleted {count} existing budget(s) for FY 2025'
                        ))
                    else:
                        existing = Budget.objects.filter(fiscal_year=fy)
                        self.stdout.write(self.style.ERROR(
                            f'Budgets already exist for FY 2025 ({existing.count()} found). '
                            f'Use --force to recreate.'
                        ))
                        return

                # Step 3: Ensure accounts exist
                accounts = self._ensure_accounts(dry_run)

                # Step 4: Get admin user
                from django.contrib.auth import get_user_model
                User = get_user_model()
                admin = User.objects.filter(is_superuser=True, is_active=True).first()

                # Step 5: Create budgets
                budgets_data = self._get_budget_definitions()
                grand_total = D('0.00')

                for bdata in budgets_data:
                    total = self._create_budget(fy, bdata, accounts, admin, dry_run)
                    grand_total += total

                if dry_run:
                    self.stdout.write(self.style.WARNING('\n[DRY RUN] Rolling back...'))
                    raise _DryRunRollback()

        except _DryRunRollback:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Dry run completed. Grand Total: AED {grand_total:,.2f}'
            ))
            return

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 60))
        self.stdout.write(self.style.SUCCESS('  ✓ BUDGET DATA SEEDED SUCCESSFULLY'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(f'\n  Budgets Created: 6')
        self.stdout.write(f'  Grand Total:     AED {grand_total:,.2f}')
        self.stdout.write(f'  Fiscal Year:     {fy.name}')
        self.stdout.write(f'\n  → View at: /finance/budgets/\n')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_fiscal_year(self):
        self.stdout.write(self.style.HTTP_INFO('1. Fiscal Year 2025...'))
        fy = FiscalYear.objects.filter(start_date__year=2025, is_active=True).first()
        if not fy:
            fy = FiscalYear.objects.create(
                name='FY 2025', start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31), is_active=True
            )
            self.stdout.write(self.style.SUCCESS(f'   ✓ Created: {fy.name}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'   ✓ Found: {fy.name}'))
        return fy

    def _ensure_accounts(self, dry_run):
        """Ensure all required accounts exist."""
        self.stdout.write(self.style.HTTP_INFO('\n2. Verifying accounts...'))
        accounts = {}
        required = {
            # Expense accounts used in budgets
            '500001': ('Office Expense - Stationery', 'expense'),
            '500002': ('Office Expense - Printing', 'expense'),
            '500003': ('Office Expense - Pantry Supplies', 'expense'),
            '500004': ('Office Expense - Cleaning Services', 'expense'),
            '500005': ('Office Expense - Security Services', 'expense'),
            '500006': ('Rent Expense - Office Space', 'expense'),
            '500007': ('Rent Expense - Warehouse', 'expense'),
            '500008': ('Rent Expense - Staff Accommodation', 'expense'),
            '500009': ('Salary Expense - Management', 'expense'),
            '500010': ('Salary Expense - Technical Staff', 'expense'),
            '500011': ('Salary Expense - Administrative', 'expense'),
            '500013': ('Bank Charges - Transaction Fees', 'expense'),
            '500023': ('Utilities - Electricity', 'expense'),
            '500024': ('Utilities - Water', 'expense'),
            '500025': ('Utilities - Internet', 'expense'),
            '500026': ('Utilities - Telephone', 'expense'),
            '500027': ('Marketing Expense - Digital', 'expense'),
            '500028': ('Marketing Expense - Print Media', 'expense'),
            '500029': ('Marketing Expense - Events', 'expense'),
            '500030': ('Travel Expense - Local', 'expense'),
            '500031': ('Travel Expense - International', 'expense'),
            '500033': ('Professional Fees - Audit', 'expense'),
            '500034': ('Professional Fees - Legal', 'expense'),
            '500035': ('Professional Fees - Consulting', 'expense'),
            '500036': ('Insurance Expense - Medical', 'expense'),
            '500037': ('Insurance Expense - Vehicle', 'expense'),
            '500038': ('Insurance Expense - Property', 'expense'),
            '500039': ('Repair & Maintenance - AC', 'expense'),
            '500040': ('Repair & Maintenance - Electrical', 'expense'),
            '500041': ('Repair & Maintenance - Plumbing', 'expense'),
            '500042': ('Repair & Maintenance - General', 'expense'),
            '500043': ('IT Expense - Software Licenses', 'expense'),
            '500044': ('IT Expense - Cloud Services', 'expense'),
            '500045': ('IT Expense - Hardware Purchase', 'expense'),
            '500046': ('Freight & Shipping - Local', 'expense'),
            '500047': ('Freight & Shipping - International', 'expense'),
            '500048': ('Entertainment Expense - Business', 'expense'),
            '500049': ('Training Expense - Staff', 'expense'),
            '6100':   ('Marketing Expense', 'expense'),
        }

        found = created = 0
        for code, (name, acc_type) in sorted(required.items()):
            acc = Account.objects.filter(code=code, is_active=True).first()
            if acc:
                accounts[code] = acc
                found += 1
            else:
                if not dry_run:
                    acc = Account.objects.create(
                        code=code, name=name, account_type=acc_type, is_system=True
                    )
                    accounts[code] = acc
                created += 1

        self.stdout.write(f'   ✓ {found} found, {created} created')
        return accounts

    def _create_budget(self, fy, bdata, accounts, admin, dry_run):
        """Create a single budget with its line items. Returns total."""
        self.stdout.write(self.style.HTTP_INFO(
            f'\n   📊 {bdata["name"]}'
        ))
        self.stdout.write(
            f'      Dept: {bdata["department"]} | '
            f'Type: {bdata["period_type"]} | '
            f'Status: {bdata["status"]}'
        )

        total = D('0.00')

        if not dry_run:
            budget = Budget.objects.create(
                name=bdata['name'],
                fiscal_year=fy,
                period_type=bdata['period_type'],
                status=bdata['status'],
                department=bdata['department'],
                notes=bdata['notes'],
                created_by=admin,
                approved_by=admin if bdata['status'] == 'approved' else None,
                approved_date=timezone.now() if bdata['status'] == 'approved' else None,
            )

            for ld in bdata['lines']:
                acc = accounts.get(ld['code']) or Account.objects.filter(
                    code=ld['code'], is_active=True
                ).first()
                if not acc:
                    self.stdout.write(self.style.WARNING(
                        f'      ⚠ Account {ld["code"]} not found, skipping'
                    ))
                    continue

                bl = BudgetLine.objects.create(
                    budget=budget, account=acc,
                    jan=ld['jan'], feb=ld['feb'], mar=ld['mar'],
                    apr=ld['apr'], may=ld['may'], jun=ld['jun'],
                    jul=ld['jul'], aug=ld['aug'], sep=ld['sep'],
                    oct=ld['oct'], nov=ld['nov'], dec=ld['dec'],
                    notes=ld.get('notes', ''),
                )
                total += bl.amount
                self.stdout.write(
                    f'      ✓ {acc.code} {acc.name}: AED {bl.amount:,.2f}'
                )

            self.stdout.write(self.style.SUCCESS(
                f'      ── Budget Total: AED {total:,.2f} '
                f'({budget.lines.count()} lines)'
            ))
        else:
            for ld in bdata['lines']:
                months = ['jan','feb','mar','apr','may','jun',
                          'jul','aug','sep','oct','nov','dec']
                line_total = sum(ld[m] for m in months)
                total += line_total
                self.stdout.write(f'      {ld["code"]}: AED {line_total:,.2f}')
            self.stdout.write(f'      ── Budget Total: AED {total:,.2f}')

        return total

    # ------------------------------------------------------------------
    # Budget Definitions  (Grand Total: 5,470,000 AED)
    # ------------------------------------------------------------------

    def _get_budget_definitions(self):
        return [
            self._budget_001_annual_operating(),
            self._budget_002_marketing(),
            self._budget_003_it_infrastructure(),
            self._budget_004_hr_recruitment(),
            self._budget_005_operations(),
            self._budget_006_contingency(),
        ]

    # ── BUD-2025-001  Annual Operating Budget  2,500,000 AED ─────────
    def _budget_001_annual_operating(self):
        return {
            'name': 'Annual Operating Budget 2025',
            'department': 'Company Wide',
            'period_type': 'annual',
            'status': 'approved',
            'notes': (
                'Master operating budget for fiscal year 2025. '
                'Covers salaries, rent, utilities, travel, professional '
                'services, insurance, maintenance, marketing, and misc.'
            ),
            'lines': [
                # ── Salaries & Wages: 1,538,000 ──
                # Management: 640,000
                {'code': '500009',
                 'jan': D('53000'), 'feb': D('53000'), 'mar': D('53000'),
                 'apr': D('53000'), 'may': D('53000'), 'jun': D('53000'),
                 'jul': D('53000'), 'aug': D('53000'), 'sep': D('53000'),
                 'oct': D('53000'), 'nov': D('55000'), 'dec': D('55000'),
                 'notes': 'Management salaries – annual increment Nov-Dec'},
                # Technical: 510,000
                {'code': '500010',
                 'jan': D('42000'), 'feb': D('42000'), 'mar': D('42000'),
                 'apr': D('42000'), 'may': D('42000'), 'jun': D('42000'),
                 'jul': D('43000'), 'aug': D('43000'), 'sep': D('43000'),
                 'oct': D('43000'), 'nov': D('43000'), 'dec': D('43000'),
                 'notes': 'Technical staff salaries – mid-year increment'},
                # Administrative: 388,000
                {'code': '500011',
                 'jan': D('32000'), 'feb': D('32000'), 'mar': D('32000'),
                 'apr': D('32000'), 'may': D('32000'), 'jun': D('32000'),
                 'jul': D('32000'), 'aug': D('32000'), 'sep': D('33000'),
                 'oct': D('33000'), 'nov': D('33000'), 'dec': D('33000'),
                 'notes': 'Administrative staff salaries'},

                # ── Rent & Utilities: 277,000 ──
                # Office rent: 240,000
                {'code': '500006',
                 'jan': D('20000'), 'feb': D('20000'), 'mar': D('20000'),
                 'apr': D('20000'), 'may': D('20000'), 'jun': D('20000'),
                 'jul': D('20000'), 'aug': D('20000'), 'sep': D('20000'),
                 'oct': D('20000'), 'nov': D('20000'), 'dec': D('20000'),
                 'notes': 'Office space rent – Deira'},
                # Electricity: 37,000
                {'code': '500023',
                 'jan': D('2500'), 'feb': D('2500'), 'mar': D('2500'),
                 'apr': D('3000'), 'may': D('3500'), 'jun': D('4000'),
                 'jul': D('4500'), 'aug': D('4500'), 'sep': D('3500'),
                 'oct': D('3000'), 'nov': D('2000'), 'dec': D('1500'),
                 'notes': 'Electricity – higher in summer months'},

                # ── Office Supplies: 50,000 ──
                {'code': '500001',
                 'jan': D('4000'), 'feb': D('4000'), 'mar': D('4000'),
                 'apr': D('4000'), 'may': D('4000'), 'jun': D('4000'),
                 'jul': D('4000'), 'aug': D('4000'), 'sep': D('5000'),
                 'oct': D('5000'), 'nov': D('4000'), 'dec': D('4000'),
                 'notes': 'Stationery and office supplies'},

                # ── Travel & Entertainment: 91,000 ──
                # Local travel: 60,000
                {'code': '500030',
                 'jan': D('5000'), 'feb': D('5000'), 'mar': D('5000'),
                 'apr': D('5000'), 'may': D('5000'), 'jun': D('5000'),
                 'jul': D('5000'), 'aug': D('5000'), 'sep': D('5000'),
                 'oct': D('5000'), 'nov': D('5000'), 'dec': D('5000'),
                 'notes': 'Local travel and transportation'},
                # Entertainment: 31,000
                {'code': '500048',
                 'jan': D('2500'), 'feb': D('2500'), 'mar': D('2500'),
                 'apr': D('2500'), 'may': D('2500'), 'jun': D('2500'),
                 'jul': D('2500'), 'aug': D('2500'), 'sep': D('2500'),
                 'oct': D('2500'), 'nov': D('3000'), 'dec': D('3000'),
                 'notes': 'Business entertainment'},

                # ── Professional Services: 132,000 ──
                # Audit: 72,000
                {'code': '500033',
                 'jan': D('6000'), 'feb': D('6000'), 'mar': D('6000'),
                 'apr': D('6000'), 'may': D('6000'), 'jun': D('6000'),
                 'jul': D('6000'), 'aug': D('6000'), 'sep': D('6000'),
                 'oct': D('6000'), 'nov': D('6000'), 'dec': D('6000'),
                 'notes': 'Annual audit fees'},
                # Consulting: 60,000
                {'code': '500035',
                 'jan': D('5000'), 'feb': D('5000'), 'mar': D('5000'),
                 'apr': D('5000'), 'may': D('5000'), 'jun': D('5000'),
                 'jul': D('5000'), 'aug': D('5000'), 'sep': D('5000'),
                 'oct': D('5000'), 'nov': D('5000'), 'dec': D('5000'),
                 'notes': 'Consulting and advisory services'},

                # ── Insurance: 83,000 ──
                # Medical: 48,000
                {'code': '500036',
                 'jan': D('4000'), 'feb': D('4000'), 'mar': D('4000'),
                 'apr': D('4000'), 'may': D('4000'), 'jun': D('4000'),
                 'jul': D('4000'), 'aug': D('4000'), 'sep': D('4000'),
                 'oct': D('4000'), 'nov': D('4000'), 'dec': D('4000'),
                 'notes': 'Staff medical insurance'},
                # Vehicle: 35,000
                {'code': '500037',
                 'jan': D('3000'), 'feb': D('3000'), 'mar': D('3000'),
                 'apr': D('3000'), 'may': D('3000'), 'jun': D('3000'),
                 'jul': D('3000'), 'aug': D('3000'), 'sep': D('3000'),
                 'oct': D('3000'), 'nov': D('2500'), 'dec': D('2500'),
                 'notes': 'Vehicle insurance premiums'},

                # ── Maintenance & Repairs: 79,000 ──
                {'code': '500042',
                 'jan': D('6500'), 'feb': D('6500'), 'mar': D('6500'),
                 'apr': D('6500'), 'may': D('6500'), 'jun': D('6500'),
                 'jul': D('6500'), 'aug': D('6500'), 'sep': D('6500'),
                 'oct': D('6500'), 'nov': D('7000'), 'dec': D('7000'),
                 'notes': 'General maintenance and repairs'},

                # ── Marketing & Advertising: 219,000 ──
                {'code': '6100',
                 'jan': D('18000'), 'feb': D('18000'), 'mar': D('18000'),
                 'apr': D('18000'), 'may': D('18000'), 'jun': D('18000'),
                 'jul': D('18000'), 'aug': D('18000'), 'sep': D('18000'),
                 'oct': D('19000'), 'nov': D('19000'), 'dec': D('19000'),
                 'notes': 'Marketing and advertising campaigns'},

                # ── Miscellaneous: 31,000 ──
                {'code': '500013',
                 'jan': D('2500'), 'feb': D('2500'), 'mar': D('2500'),
                 'apr': D('2500'), 'may': D('2500'), 'jun': D('2500'),
                 'jul': D('3000'), 'aug': D('3000'), 'sep': D('2500'),
                 'oct': D('2500'), 'nov': D('2500'), 'dec': D('2500'),
                 'notes': 'Bank charges and transaction fees'},
            ],
        }

    # ── BUD-2025-002  Marketing Budget Q1-Q2  450,000 AED ────────────
    def _budget_002_marketing(self):
        return {
            'name': 'Marketing Budget Q1-Q2 2025',
            'department': 'Marketing',
            'period_type': 'quarterly',
            'status': 'approved',
            'notes': (
                'Marketing campaigns and promotional activities for H1 2025. '
                'Focus on digital advertising, print media, exhibitions, '
                'and marketing collateral.'
            ),
            'lines': [
                # Digital Marketing: 225,000
                {'code': '500027',
                 'jan': D('35000'), 'feb': D('35000'), 'mar': D('40000'),
                 'apr': D('35000'), 'may': D('40000'), 'jun': D('40000'),
                 'jul': D('0'), 'aug': D('0'), 'sep': D('0'),
                 'oct': D('0'), 'nov': D('0'), 'dec': D('0'),
                 'notes': 'Google Ads, Meta, LinkedIn campaigns'},
                # Print Media: 63,000
                {'code': '500028',
                 'jan': D('10000'), 'feb': D('10000'), 'mar': D('11000'),
                 'apr': D('10000'), 'may': D('11000'), 'jun': D('11000'),
                 'jul': D('0'), 'aug': D('0'), 'sep': D('0'),
                 'oct': D('0'), 'nov': D('0'), 'dec': D('0'),
                 'notes': 'Newspapers, magazines, brochures'},
                # Events & Exhibitions: 120,000
                {'code': '500029',
                 'jan': D('15000'), 'feb': D('15000'), 'mar': D('25000'),
                 'apr': D('15000'), 'may': D('25000'), 'jun': D('25000'),
                 'jul': D('0'), 'aug': D('0'), 'sep': D('0'),
                 'oct': D('0'), 'nov': D('0'), 'dec': D('0'),
                 'notes': 'Trade shows, GITEX, industry expos'},
                # Marketing Collateral: 42,000
                {'code': '500002',
                 'jan': D('7000'), 'feb': D('7000'), 'mar': D('7000'),
                 'apr': D('7000'), 'may': D('7000'), 'jun': D('7000'),
                 'jul': D('0'), 'aug': D('0'), 'sep': D('0'),
                 'oct': D('0'), 'nov': D('0'), 'dec': D('0'),
                 'notes': 'Flyers, banners, promotional materials printing'},
            ],
        }

    # ── BUD-2025-003  IT Infrastructure Capital  800,000 AED ─────────
    def _budget_003_it_infrastructure(self):
        return {
            'name': 'IT Infrastructure Capital Budget 2025',
            'department': 'IT Department',
            'period_type': 'annual',
            'status': 'draft',
            'notes': (
                'Capital expenditure for servers, software licenses, '
                'cloud services, and hardware upgrades. '
                'Pending CFO approval.'
            ),
            'lines': [
                # Software Licenses: 325,000
                {'code': '500043',
                 'jan': D('25000'), 'feb': D('25000'), 'mar': D('25000'),
                 'apr': D('25000'), 'may': D('25000'), 'jun': D('25000'),
                 'jul': D('30000'), 'aug': D('30000'), 'sep': D('30000'),
                 'oct': D('30000'), 'nov': D('30000'), 'dec': D('25000'),
                 'notes': 'ERP, Office 365, Adobe, antivirus licenses'},
                # Cloud Services: 199,000
                {'code': '500044',
                 'jan': D('15000'), 'feb': D('15000'), 'mar': D('15000'),
                 'apr': D('16000'), 'may': D('16000'), 'jun': D('16000'),
                 'jul': D('18000'), 'aug': D('18000'), 'sep': D('18000'),
                 'oct': D('18000'), 'nov': D('18000'), 'dec': D('16000'),
                 'notes': 'AWS/Azure cloud hosting and managed services'},
                # Hardware Purchase: 200,000
                {'code': '500045',
                 'jan': D('15000'), 'feb': D('12000'), 'mar': D('18000'),
                 'apr': D('15000'), 'may': D('12000'), 'jun': D('22000'),
                 'jul': D('15000'), 'aug': D('15000'), 'sep': D('18000'),
                 'oct': D('15000'), 'nov': D('15000'), 'dec': D('28000'),
                 'notes': 'Laptops, monitors, servers, networking equipment'},
                # Dedicated Internet: 76,000
                {'code': '500025',
                 'jan': D('6000'), 'feb': D('6000'), 'mar': D('6000'),
                 'apr': D('6000'), 'may': D('6000'), 'jun': D('6000'),
                 'jul': D('7000'), 'aug': D('7000'), 'sep': D('7000'),
                 'oct': D('7000'), 'nov': D('7000'), 'dec': D('5000'),
                 'notes': 'Dedicated internet lines – bandwidth upgrade Jul'},
            ],
        }

    # ── BUD-2025-004  HR Recruitment & Training  320,000 AED ─────────
    def _budget_004_hr_recruitment(self):
        return {
            'name': 'HR Recruitment & Training Budget 2025',
            'department': 'Human Resources',
            'period_type': 'annual',
            'status': 'approved',
            'notes': (
                'New hires, staff training programs, medical insurance, '
                'and international recruitment trips for 2025.'
            ),
            'lines': [
                # Staff Training: 115,000
                {'code': '500049',
                 'jan': D('8000'), 'feb': D('10000'), 'mar': D('12000'),
                 'apr': D('8000'), 'may': D('10000'), 'jun': D('15000'),
                 'jul': D('8000'), 'aug': D('8000'), 'sep': D('12000'),
                 'oct': D('10000'), 'nov': D('8000'), 'dec': D('6000'),
                 'notes': 'Professional development and certifications'},
                # Medical Insurance: 156,000
                {'code': '500036',
                 'jan': D('12000'), 'feb': D('12000'), 'mar': D('12000'),
                 'apr': D('12000'), 'may': D('12000'), 'jun': D('12000'),
                 'jul': D('14000'), 'aug': D('14000'), 'sep': D('14000'),
                 'oct': D('14000'), 'nov': D('14000'), 'dec': D('14000'),
                 'notes': 'Employee medical insurance – renewed Jul'},
                # International Recruitment: 49,000
                {'code': '500031',
                 'jan': D('3000'), 'feb': D('3000'), 'mar': D('5000'),
                 'apr': D('4000'), 'may': D('4000'), 'jun': D('6000'),
                 'jul': D('3000'), 'aug': D('3000'), 'sep': D('5000'),
                 'oct': D('4000'), 'nov': D('4000'), 'dec': D('5000'),
                 'notes': 'Recruitment trips and conferences'},
            ],
        }

    # ── BUD-2025-005  Operations & Maintenance  1,200,000 AED ────────
    def _budget_005_operations(self):
        return {
            'name': 'Operations & Maintenance Budget 2025',
            'department': 'Operations',
            'period_type': 'annual',
            'status': 'draft',
            'notes': (
                'Facility maintenance, utilities, freight, and '
                'operational supplies. Draft – pending Operations Manager review.'
            ),
            'lines': [
                # Warehouse Rent: 228,000
                {'code': '500007',
                 'jan': D('18000'), 'feb': D('18000'), 'mar': D('18000'),
                 'apr': D('18000'), 'may': D('18000'), 'jun': D('18000'),
                 'jul': D('20000'), 'aug': D('20000'), 'sep': D('20000'),
                 'oct': D('20000'), 'nov': D('20000'), 'dec': D('20000'),
                 'notes': 'Warehouse rent – renewed Jul with increase'},
                # Staff Accommodation: 186,000
                {'code': '500008',
                 'jan': D('15000'), 'feb': D('15000'), 'mar': D('15000'),
                 'apr': D('15000'), 'may': D('15000'), 'jun': D('15000'),
                 'jul': D('16000'), 'aug': D('16000'), 'sep': D('16000'),
                 'oct': D('16000'), 'nov': D('16000'), 'dec': D('16000'),
                 'notes': 'Staff accommodation rent'},
                # AC Maintenance: 94,000
                {'code': '500039',
                 'jan': D('5000'), 'feb': D('5000'), 'mar': D('6000'),
                 'apr': D('7000'), 'may': D('8000'), 'jun': D('10000'),
                 'jul': D('12000'), 'aug': D('12000'), 'sep': D('10000'),
                 'oct': D('8000'), 'nov': D('6000'), 'dec': D('5000'),
                 'notes': 'AC maintenance – higher in summer'},
                # Electrical Maintenance: 42,000
                {'code': '500040',
                 'jan': D('3000'), 'feb': D('3000'), 'mar': D('3000'),
                 'apr': D('4000'), 'may': D('4000'), 'jun': D('4000'),
                 'jul': D('4000'), 'aug': D('4000'), 'sep': D('4000'),
                 'oct': D('3000'), 'nov': D('3000'), 'dec': D('3000'),
                 'notes': 'Electrical maintenance'},
                # General Repairs: 72,000
                {'code': '500042',
                 'jan': D('5000'), 'feb': D('5000'), 'mar': D('6000'),
                 'apr': D('6000'), 'may': D('6000'), 'jun': D('6000'),
                 'jul': D('7000'), 'aug': D('7000'), 'sep': D('7000'),
                 'oct': D('6000'), 'nov': D('6000'), 'dec': D('5000'),
                 'notes': 'General repairs and maintenance'},
                # Cleaning Services: 54,000
                {'code': '500004',
                 'jan': D('4000'), 'feb': D('4000'), 'mar': D('4000'),
                 'apr': D('4500'), 'may': D('4500'), 'jun': D('4500'),
                 'jul': D('5000'), 'aug': D('5000'), 'sep': D('5000'),
                 'oct': D('4500'), 'nov': D('4500'), 'dec': D('4500'),
                 'notes': 'Office and warehouse cleaning'},
                # Security Services: 78,000
                {'code': '500005',
                 'jan': D('6000'), 'feb': D('6000'), 'mar': D('6000'),
                 'apr': D('6000'), 'may': D('6000'), 'jun': D('6000'),
                 'jul': D('7000'), 'aug': D('7000'), 'sep': D('7000'),
                 'oct': D('7000'), 'nov': D('7000'), 'dec': D('7000'),
                 'notes': 'Security guard services'},
                # Local Freight: 130,000
                {'code': '500046',
                 'jan': D('9000'), 'feb': D('9000'), 'mar': D('10000'),
                 'apr': D('10000'), 'may': D('10000'), 'jun': D('11000'),
                 'jul': D('12000'), 'aug': D('12000'), 'sep': D('12000'),
                 'oct': D('12000'), 'nov': D('11000'), 'dec': D('12000'),
                 'notes': 'Local delivery and distribution'},
                # Water: 24,000
                {'code': '500024',
                 'jan': D('2000'), 'feb': D('2000'), 'mar': D('2000'),
                 'apr': D('2000'), 'may': D('2000'), 'jun': D('2000'),
                 'jul': D('2000'), 'aug': D('2000'), 'sep': D('2000'),
                 'oct': D('2000'), 'nov': D('2000'), 'dec': D('2000'),
                 'notes': 'Water supply'},
                # Telephone: 24,000
                {'code': '500026',
                 'jan': D('2000'), 'feb': D('2000'), 'mar': D('2000'),
                 'apr': D('2000'), 'may': D('2000'), 'jun': D('2000'),
                 'jul': D('2000'), 'aug': D('2000'), 'sep': D('2000'),
                 'oct': D('2000'), 'nov': D('2000'), 'dec': D('2000'),
                 'notes': 'Telephone and mobile'},
                # Pantry Supplies: 30,000
                {'code': '500003',
                 'jan': D('2500'), 'feb': D('2500'), 'mar': D('2500'),
                 'apr': D('2500'), 'may': D('2500'), 'jun': D('2500'),
                 'jul': D('2500'), 'aug': D('2500'), 'sep': D('2500'),
                 'oct': D('2500'), 'nov': D('2500'), 'dec': D('2500'),
                 'notes': 'Pantry and kitchen supplies'},
                # Plumbing: 24,000
                {'code': '500041',
                 'jan': D('2000'), 'feb': D('2000'), 'mar': D('2000'),
                 'apr': D('2000'), 'may': D('2000'), 'jun': D('2000'),
                 'jul': D('2000'), 'aug': D('2000'), 'sep': D('2000'),
                 'oct': D('2000'), 'nov': D('2000'), 'dec': D('2000'),
                 'notes': 'Plumbing maintenance'},
                # International Freight: 214,000
                {'code': '500047',
                 'jan': D('15000'), 'feb': D('15000'), 'mar': D('18000'),
                 'apr': D('17000'), 'may': D('17000'), 'jun': D('18000'),
                 'jul': D('20000'), 'aug': D('20000'), 'sep': D('20000'),
                 'oct': D('18000'), 'nov': D('18000'), 'dec': D('18000'),
                 'notes': 'International shipping and freight'},
            ],
        }

    # ── BUD-2025-006  Emergency Contingency Fund  200,000 AED ────────
    def _budget_006_contingency(self):
        return {
            'name': 'Emergency Contingency Fund 2025',
            'department': 'Executive',
            'period_type': 'annual',
            'status': 'approved',
            'notes': (
                'Contingency fund for unforeseen expenses and emergencies. '
                'CFO approval required for each drawdown.'
            ),
            'lines': [
                # Emergency Repairs Reserve: 80,000
                {'code': '500042',
                 'jan': D('6500'), 'feb': D('6500'), 'mar': D('6500'),
                 'apr': D('6500'), 'may': D('6500'), 'jun': D('6500'),
                 'jul': D('7000'), 'aug': D('7000'), 'sep': D('7000'),
                 'oct': D('7000'), 'nov': D('6500'), 'dec': D('6500'),
                 'notes': 'Emergency repairs reserve'},
                # Property Insurance: 60,000
                {'code': '500038',
                 'jan': D('5000'), 'feb': D('5000'), 'mar': D('5000'),
                 'apr': D('5000'), 'may': D('5000'), 'jun': D('5000'),
                 'jul': D('5000'), 'aug': D('5000'), 'sep': D('5000'),
                 'oct': D('5000'), 'nov': D('5000'), 'dec': D('5000'),
                 'notes': 'Property insurance contingency'},
                # Legal Contingency: 60,000
                {'code': '500034',
                 'jan': D('5000'), 'feb': D('5000'), 'mar': D('5000'),
                 'apr': D('5000'), 'may': D('5000'), 'jun': D('5000'),
                 'jul': D('5000'), 'aug': D('5000'), 'sep': D('5000'),
                 'oct': D('5000'), 'nov': D('5000'), 'dec': D('5000'),
                 'notes': 'Legal fees contingency reserve'},
            ],
        }


class _DryRunRollback(Exception):
    """Sentinel exception to roll back dry-run transactions."""
    pass
