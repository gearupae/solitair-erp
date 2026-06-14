"""
Comprehensive Test Data Seeding for UAE ERP Finance Testing
Creates 50+ rows for each module to enable full finance validation.

Run: python manage.py seed_test_data
"""
import random
from datetime import date, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed comprehensive test data for UAE ERP finance testing (50+ rows per module)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview without saving'
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.admin_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
        
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('UAE ERP COMPREHENSIVE TEST DATA SEEDER'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        try:
            with transaction.atomic():
                # 1. Setup Chart of Accounts
                self.setup_chart_of_accounts()
                
                # 2. Seed Vendors
                self.seed_vendors()
                
                # 3. Seed Customers
                self.seed_customers()
                
                # 4. Seed Employees
                self.seed_employees()
                
                # 5. Seed Inventory Items
                self.seed_inventory_items()
                
                # 6. Seed Asset Categories & Fixed Assets
                self.seed_fixed_assets()
                
                # 7. Seed Projects
                self.seed_projects()
                
                # 8. Seed Properties, Tenants, Leases
                self.seed_property_management()
                
                # 9. Seed PDC Cheques
                self.seed_pdc_cheques()
                
                # 10. Seed Recurring Expenses
                self.seed_recurring_expenses()
                
                # 11. Seed Stock Movements
                self.seed_stock_movements()
                
                # 12. Seed Sales Invoices
                self.seed_sales_invoices()
                
                # 13. Seed Purchase Bills
                self.seed_purchase_bills()
                
                # 14. Seed Expense Claims
                self.seed_expense_claims()
                
                # 15. Seed Payroll
                self.seed_payroll()
                
                # 16. Run Depreciation
                self.run_depreciation()
                
                # 17. Final Validation
                self.validate_data()
                
                if self.dry_run:
                    self.stdout.write(self.style.WARNING('\nDRY RUN - Rolling back'))
                    raise Exception('Dry run - rollback')
                    
        except Exception as e:
            if 'Dry run' not in str(e):
                self.stderr.write(self.style.ERROR(f'Error: {e}'))
                raise
        
        self.stdout.write(self.style.SUCCESS('\n' + '=' * 60))
        self.stdout.write(self.style.SUCCESS('TEST DATA SEEDING COMPLETED SUCCESSFULLY'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

    def setup_chart_of_accounts(self):
        """Ensure required GL accounts exist."""
        self.stdout.write('\n📊 Setting up Chart of Accounts...')
        from apps.finance.models import Account, AccountType
        
        accounts_data = [
            # Assets
            ('1000', 'Cash', AccountType.ASSET),
            ('1100', 'Bank - ADCB', AccountType.ASSET),
            ('1101', 'Bank - Emirates NBD', AccountType.ASSET),
            ('1102', 'Bank - Mashreq', AccountType.ASSET),
            ('1200', 'Accounts Receivable', AccountType.ASSET),
            ('1201', 'Trade Debtors - Local', AccountType.ASSET),
            ('1202', 'Trade Debtors - Export', AccountType.ASSET),
            ('1210', 'Trade Debtors - Property', AccountType.ASSET),
            ('1300', 'VAT Recoverable', AccountType.ASSET),
            ('1400', 'Fixed Assets - Furniture', AccountType.ASSET),
            ('1401', 'Accumulated Depreciation - Furniture', AccountType.ASSET),
            ('1410', 'Fixed Assets - IT Equipment', AccountType.ASSET),
            ('1411', 'Accumulated Depreciation - IT Equipment', AccountType.ASSET),
            ('1420', 'Fixed Assets - Vehicles', AccountType.ASSET),
            ('1421', 'Accumulated Depreciation - Vehicles', AccountType.ASSET),
            ('1500', 'Inventory', AccountType.ASSET),
            ('1600', 'PDC Receivable', AccountType.ASSET),
            ('1700', 'Prepaid Expenses', AccountType.ASSET),
            # Liabilities
            ('2000', 'Accounts Payable', AccountType.LIABILITY),
            ('2010', 'GRN Clearing', AccountType.LIABILITY),
            ('2100', 'VAT Payable', AccountType.LIABILITY),
            ('2200', 'Salary Payable', AccountType.LIABILITY),
            ('2210', 'Employee Payable', AccountType.LIABILITY),
            ('2300', 'Security Deposit Liability', AccountType.LIABILITY),
            ('2400', 'Corporate Tax Payable', AccountType.LIABILITY),
            ('2500', 'Gratuity Payable', AccountType.LIABILITY),
            # Equity
            ('3000', 'Share Capital', AccountType.EQUITY),
            ('3100', 'Retained Earnings', AccountType.EQUITY),
            ('3200', 'Current Year P&L', AccountType.EQUITY),
            # Income
            ('4000', 'Sales Revenue', AccountType.INCOME),
            ('4001', 'Sales - Products', AccountType.INCOME),
            ('4002', 'Sales - Services', AccountType.INCOME),
            ('4100', 'Rental Income', AccountType.INCOME),
            ('4200', 'Project Revenue', AccountType.INCOME),
            ('4300', 'Other Income', AccountType.INCOME),
            ('4400', 'Interest Income', AccountType.INCOME),
            ('4500', 'Gain on Asset Disposal', AccountType.INCOME),
            # Expenses
            ('5000', 'Cost of Goods Sold', AccountType.EXPENSE),
            ('5100', 'COGS - Products', AccountType.EXPENSE),
            ('5200', 'Stock Variance', AccountType.EXPENSE),
            ('5300', 'Salary Expense', AccountType.EXPENSE),
            ('5310', 'Gratuity Expense', AccountType.EXPENSE),
            ('5400', 'Rent Expense', AccountType.EXPENSE),
            ('5410', 'Utilities - Electricity', AccountType.EXPENSE),
            ('5420', 'Utilities - Water', AccountType.EXPENSE),
            ('5430', 'Internet & Telecom', AccountType.EXPENSE),
            ('5500', 'Depreciation Expense', AccountType.EXPENSE),
            ('5600', 'Office Supplies', AccountType.EXPENSE),
            ('5700', 'Travel & Entertainment', AccountType.EXPENSE),
            ('5800', 'Professional Fees', AccountType.EXPENSE),
            ('5900', 'Bank Charges', AccountType.EXPENSE),
            ('5910', 'Corporate Tax Expense', AccountType.EXPENSE),
            ('6000', 'Project Expenses', AccountType.EXPENSE),
            ('6100', 'Marketing Expense', AccountType.EXPENSE),
            ('6200', 'Insurance Expense', AccountType.EXPENSE),
            ('6300', 'Maintenance Expense', AccountType.EXPENSE),
            ('6400', 'Software Subscriptions', AccountType.EXPENSE),
            ('6500', 'Loss on Asset Disposal', AccountType.EXPENSE),
        ]
        
        created = 0
        for code, name, acc_type in accounts_data:
            account, was_created = Account.objects.get_or_create(
                code=code,
                defaults={'name': name, 'account_type': acc_type}
            )
            if was_created:
                created += 1
        
        self.stdout.write(f'  Created {created} accounts, Total: {Account.objects.count()}')

    def seed_vendors(self):
        """Seed 60 vendors."""
        self.stdout.write('\n🏢 Seeding Vendors (60 rows)...')
        from apps.purchase.models import Vendor
        
        vendors_data = [
            # Utilities
            ('Etisalat', 'Telecom', '100234567890123'),
            ('Du', 'Telecom', '100234567890124'),
            ('DEWA', 'Utilities', '100234567890125'),
            ('SEWA', 'Utilities', '100234567890126'),
            ('ADDC', 'Utilities', '100234567890127'),
            # Real Estate
            ('Office Landlord LLC', 'Real Estate', '100234567890128'),
            ('Dubai Properties Corp', 'Real Estate', '100234567890129'),
            ('Emirates REIT', 'Real Estate', '100234567890130'),
            ('DAMAC Properties', 'Real Estate', '100234567890131'),
            ('Emaar Properties', 'Real Estate', '100234567890132'),
            # IT & Technology
            ('Amazon Web Services', 'Cloud Services', '100234567890133'),
            ('Microsoft UAE', 'Software', '100234567890134'),
            ('Dell Technologies', 'IT Hardware', '100234567890135'),
            ('HP Enterprise', 'IT Hardware', '100234567890136'),
            ('Cisco Systems', 'Networking', '100234567890137'),
            ('Lenovo UAE', 'IT Hardware', '100234567890138'),
            ('Oracle ME', 'Software', '100234567890139'),
            ('SAP MENA', 'Software', '100234567890140'),
            # Office Supplies
            ('Office Depot UAE', 'Office Supplies', '100234567890141'),
            ('Staples Dubai', 'Office Supplies', '100234567890142'),
            ('Al Futtaim Office', 'Office Supplies', '100234567890143'),
            ('IKEA UAE', 'Furniture', '100234567890144'),
            ('Home Centre', 'Furniture', '100234567890145'),
            # Professional Services
            ('PwC UAE', 'Audit', '100234567890146'),
            ('Deloitte ME', 'Consulting', '100234567890147'),
            ('KPMG UAE', 'Tax Advisory', '100234567890148'),
            ('EY Middle East', 'Advisory', '100234567890149'),
            ('Baker McKenzie', 'Legal', '100234567890150'),
            ('Al Tamimi & Co', 'Legal', '100234567890151'),
            # Insurance
            ('AXA Insurance', 'Insurance', '100234567890152'),
            ('Oman Insurance', 'Insurance', '100234567890153'),
            ('Dubai Insurance', 'Insurance', '100234567890154'),
            ('SALAMA Insurance', 'Insurance', '100234567890155'),
            # Logistics
            ('Aramex', 'Logistics', '100234567890156'),
            ('DHL Express', 'Logistics', '100234567890157'),
            ('FedEx UAE', 'Logistics', '100234567890158'),
            ('Emirates Post', 'Logistics', '100234567890159'),
            # Maintenance
            ('Emrill Services', 'Facility Mgmt', '100234567890160'),
            ('Farnek Services', 'Facility Mgmt', '100234567890161'),
            ('Imdaad LLC', 'Facility Mgmt', '100234567890162'),
            # Marketing
            ('Google UAE', 'Digital Marketing', '100234567890163'),
            ('Facebook ME', 'Social Media', '100234567890164'),
            ('Leo Burnett', 'Advertising', '100234567890165'),
            # Travel
            ('Emirates Airlines', 'Travel', '100234567890166'),
            ('Etihad Airways', 'Travel', '100234567890167'),
            ('DNATA Travel', 'Travel Agency', '100234567890168'),
            # Banking
            ('Emirates NBD', 'Banking', '100234567890169'),
            ('ADCB', 'Banking', '100234567890170'),
            ('Mashreq Bank', 'Banking', '100234567890171'),
            # Others
            ('Carrefour UAE', 'Retail', '100234567890172'),
            ('Lulu Hypermarket', 'Retail', '100234567890173'),
            ('Petrol Station Co', 'Fuel', '100234567890174'),
            ('ENOC', 'Fuel', '100234567890175'),
            ('Al Ain Water', 'Beverages', '100234567890176'),
            ('Masafi Water', 'Beverages', '100234567890177'),
            ('Nespresso UAE', 'Beverages', '100234567890178'),
            ('Catering Company', 'Food Services', '100234567890179'),
            ('Security Services LLC', 'Security', '100234567890180'),
            ('Cleaning Services Co', 'Cleaning', '100234567890181'),
        ]
        
        created = 0
        for name, notes, trn in vendors_data:
            vendor, was_created = Vendor.objects.get_or_create(
                name=name,
                defaults={
                    'trn': trn,
                    'notes': notes,
                    'address': f'{name}, Dubai, UAE',
                    'city': 'Dubai',
                    'payment_terms': 'Net 30',
                    'credit_limit': Decimal(random.choice(['50000', '100000', '200000', '500000'])),
                    'status': 'active',
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} vendors, Total: {Vendor.objects.count()}'))

    def seed_customers(self):
        """Seed 60 customers."""
        self.stdout.write('\n👥 Seeding Customers (60 rows)...')
        from apps.crm.models import Customer
        
        customers_data = [
            # Trading Companies
            ('ABC Trading LLC', '100111222333444'),
            ('XYZ Import Export', '100111222333445'),
            ('Gulf Trading Co', '100111222333446'),
            ('Al Futtaim Trading', '100111222333447'),
            ('Majid Al Futtaim', '100111222333448'),
            ('Juma Al Majid Group', '100111222333449'),
            ('Al Tayer Group', '100111222333450'),
            ('Al Habtoor Group', '100111222333451'),
            ('Easa Saleh Al Gurg', '100111222333452'),
            ('Galadari Brothers', '100111222333453'),
            # Tech Companies
            ('Tech Solutions DMCC', '100111222333454'),
            ('Digital Innovations', '100111222333455'),
            ('Smart Systems LLC', '100111222333456'),
            ('Cloud Nine Tech', '100111222333457'),
            ('Data Analytics Co', '100111222333458'),
            ('AI Solutions UAE', '100111222333459'),
            ('Cyber Security ME', '100111222333460'),
            ('Mobile Apps Dubai', '100111222333461'),
            ('Web Developers LLC', '100111222333462'),
            ('IT Consulting FZE', '100111222333463'),
            # Construction
            ('Build Right LLC', '100111222333464'),
            ('Construction Plus', '100111222333465'),
            ('Al Naboodah Const', '100111222333466'),
            ('Arabtec Holdings', '100111222333467'),
            ('Drake & Scull', '100111222333468'),
            # Healthcare
            ('Medical Center LLC', '100111222333469'),
            ('Health Plus Clinic', '100111222333470'),
            ('Pharma Distributors', '100111222333471'),
            ('Dental Care UAE', '100111222333472'),
            ('Wellness Hub', '100111222333473'),
            # Hospitality
            ('Hotel Management Co', '100111222333474'),
            ('Restaurant Group', '100111222333475'),
            ('Catering Services', '100111222333476'),
            ('Event Planners LLC', '100111222333477'),
            ('Travel & Tourism', '100111222333478'),
            # Manufacturing
            ('Steel Industries', '100111222333479'),
            ('Plastic Factory LLC', '100111222333480'),
            ('Food Processing Co', '100111222333481'),
            ('Packaging Solutions', '100111222333482'),
            ('Textile Mills UAE', '100111222333483'),
            # Retail
            ('Fashion Retail LLC', '100111222333484'),
            ('Electronics Store', '100111222333485'),
            ('Furniture Gallery', '100111222333486'),
            ('Sports Equipment', '100111222333487'),
            ('Jewelry Trading', '100111222333488'),
            # Services
            ('Legal Services LLC', '100111222333489'),
            ('Accounting Firm', '100111222333490'),
            ('Marketing Agency', '100111222333491'),
            ('HR Consultants', '100111222333492'),
            ('Training Institute', '100111222333493'),
            # Real Estate
            ('Property Developers', '100111222333494'),
            ('Real Estate Brokers', '100111222333495'),
            ('Facility Managers', '100111222333496'),
            ('Interior Designers', '100111222333497'),
            ('Architecture Firm', '100111222333498'),
            # Education
            ('Private School LLC', '100111222333499'),
            ('Language Institute', '100111222333500'),
            ('University Dubai', '100111222333501'),
            ('Online Learning Co', '100111222333502'),
            ('Research Center', '100111222333503'),
        ]
        
        created = 0
        for name, trn in customers_data:
            customer, was_created = Customer.objects.get_or_create(
                name=name,
                defaults={
                    'trn': trn,
                    'address': f'{name}, Dubai, UAE',
                    'city': 'Dubai',
                    'country': 'United Arab Emirates',
                    'payment_terms': 'Net 30',
                    'credit_limit': Decimal(random.choice(['100000', '200000', '500000', '1000000'])),
                    'customer_type': 'customer',
                    'status': 'active',
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} customers, Total: {Customer.objects.count()}'))

    def seed_employees(self):
        """Seed 60 employees."""
        self.stdout.write('\n👨‍💼 Seeding Employees (60 rows)...')
        from apps.hr.models import Employee, Department, Designation
        
        # Create departments
        departments = [
            ('MGMT', 'Management'),
            ('FIN', 'Finance'),
            ('HR', 'Human Resources'),
            ('IT', 'Information Technology'),
            ('SALES', 'Sales'),
            ('MKT', 'Marketing'),
            ('OPS', 'Operations'),
            ('ADMIN', 'Administration'),
            ('PROJ', 'Projects'),
            ('SUPP', 'Support'),
        ]
        
        dept_objs = {}
        for code, name in departments:
            dept, _ = Department.objects.get_or_create(code=code, defaults={'name': name})
            dept_objs[code] = dept
        
        # Create designations
        designations_data = [
            ('CEO', 'MGMT'), ('CFO', 'FIN'), ('CTO', 'IT'), ('COO', 'OPS'),
            ('Manager', 'MGMT'), ('Senior Accountant', 'FIN'), ('Accountant', 'FIN'),
            ('HR Manager', 'HR'), ('HR Executive', 'HR'), ('IT Manager', 'IT'),
            ('Developer', 'IT'), ('Sales Manager', 'SALES'), ('Sales Executive', 'SALES'),
            ('Marketing Manager', 'MKT'), ('Project Manager', 'PROJ'), ('Admin Officer', 'ADMIN'),
        ]
        
        desig_objs = {}
        for title, dept_code in designations_data:
            desig, _ = Designation.objects.get_or_create(
                name=title,
                department=dept_objs[dept_code]
            )
            desig_objs[title] = desig
        
        # Employee data
        employees_data = [
            ('Ahmed', 'Al Maktoum', 'MGMT', 'CEO', 50000),
            ('Mohammed', 'Al Nahyan', 'FIN', 'CFO', 45000),
            ('Khalid', 'Al Qasimi', 'IT', 'CTO', 42000),
            ('Omar', 'Al Falasi', 'OPS', 'COO', 40000),
            ('Saeed', 'Al Mansoori', 'FIN', 'Manager', 25000),
            ('Rashid', 'Al Suwaidi', 'FIN', 'Senior Accountant', 18000),
            ('Hassan', 'Al Mazrouei', 'FIN', 'Accountant', 12000),
            ('Abdullah', 'Al Ketbi', 'FIN', 'Accountant', 11000),
            ('Youssef', 'Al Dhaheri', 'FIN', 'Accountant', 10000),
            ('Hamad', 'Al Shamsi', 'HR', 'HR Manager', 22000),
            ('Sultan', 'Al Kaabi', 'HR', 'HR Executive', 12000),
            ('Majid', 'Al Nuaimi', 'HR', 'HR Executive', 11000),
            ('Fahad', 'Al Zaabi', 'IT', 'IT Manager', 28000),
            ('Tariq', 'Al Muhairbi', 'IT', 'Developer', 15000),
            ('Walid', 'Al Hashemi', 'IT', 'Developer', 14000),
            ('Nasser', 'Al Shehhi', 'IT', 'Developer', 13000),
            ('Khaled', 'Al Balushi', 'IT', 'Developer', 12000),
            ('Faisal', 'Al Marzooqi', 'SALES', 'Sales Manager', 25000),
            ('Saleh', 'Al Mehairi', 'SALES', 'Sales Executive', 12000),
            ('Bader', 'Al Qubaisi', 'SALES', 'Sales Executive', 11000),
            ('Mansour', 'Al Romaithi', 'SALES', 'Sales Executive', 10000),
            ('Jassim', 'Al Blooshi', 'SALES', 'Sales Executive', 10000),
            ('Adel', 'Al Hajri', 'MKT', 'Marketing Manager', 22000),
            ('Rami', 'Al Khoori', 'MKT', 'Sales Executive', 11000),
            ('Zayed', 'Al Awadhi', 'PROJ', 'Project Manager', 28000),
            ('Hamed', 'Al Tenaiji', 'PROJ', 'Project Manager', 26000),
            ('Ali', 'Khan', 'IT', 'Developer', 12000),
            ('Imran', 'Ahmed', 'IT', 'Developer', 11000),
            ('Amir', 'Hassan', 'FIN', 'Accountant', 9000),
            ('Bilal', 'Malik', 'OPS', 'Admin Officer', 8000),
            ('Danish', 'Sheikh', 'SALES', 'Sales Executive', 9000),
            ('Ehsan', 'Qureshi', 'IT', 'Developer', 10000),
            ('Farhan', 'Ali', 'SUPP', 'Admin Officer', 7000),
            ('Ghulam', 'Hussain', 'OPS', 'Admin Officer', 7500),
            ('Haider', 'Abbas', 'HR', 'HR Executive', 8000),
            ('Irfan', 'Syed', 'IT', 'Developer', 11000),
            ('Junaid', 'Raza', 'SALES', 'Sales Executive', 8500),
            ('Kamran', 'Akhtar', 'FIN', 'Accountant', 9500),
            ('Liaqat', 'Mehmood', 'OPS', 'Admin Officer', 7000),
            ('Mubarak', 'Saif', 'ADMIN', 'Admin Officer', 6500),
            ('Naveed', 'Iqbal', 'IT', 'Developer', 10500),
            ('Owais', 'Tariq', 'MKT', 'Sales Executive', 8000),
            ('Pervaiz', 'Javed', 'FIN', 'Accountant', 8500),
            ('Qamar', 'Zaman', 'OPS', 'Admin Officer', 7500),
            ('Rizwan', 'Anwar', 'SALES', 'Sales Executive', 9000),
            ('Shahid', 'Afridi', 'PROJ', 'Project Manager', 20000),
            ('Talha', 'Baig', 'IT', 'Developer', 12500),
            ('Umair', 'Aziz', 'HR', 'HR Executive', 8500),
            ('Waqas', 'Younas', 'FIN', 'Accountant', 9000),
            ('Yasir', 'Hameed', 'SALES', 'Sales Executive', 8500),
            ('Zahid', 'Bashir', 'OPS', 'Admin Officer', 7000),
            ('Aamir', 'Riaz', 'IT', 'Developer', 11500),
            ('Basit', 'Nawaz', 'MKT', 'Sales Executive', 8000),
            ('Chand', 'Bibi', 'ADMIN', 'Admin Officer', 6000),
            ('Daud', 'Ibrahim', 'FIN', 'Accountant', 8000),
            ('Ehtisham', 'Latif', 'PROJ', 'Project Manager', 18000),
            ('Faheem', 'Ashraf', 'IT', 'Developer', 10000),
            ('Gohar', 'Mustafa', 'SALES', 'Sales Executive', 8000),
            ('Habib', 'Ur Rehman', 'OPS', 'Admin Officer', 7000),
            ('Ismail', 'Yaqoob', 'HR', 'HR Executive', 7500),
        ]
        
        created = 0
        for first, last, dept_code, desig, salary in employees_data:
            emp, was_created = Employee.objects.get_or_create(
                first_name=first,
                last_name=last,
                defaults={
                    'department': dept_objs[dept_code],
                    'designation': desig_objs.get(desig, list(desig_objs.values())[0]),
                    'basic_salary': Decimal(str(salary)),
                    'email': f'{first.lower()}.{last.lower()}@company.ae',
                    'date_of_joining': date(2023, random.randint(1, 12), random.randint(1, 28)),
                    'status': 'active',
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} employees, Total: {Employee.objects.count()}'))

    def seed_inventory_items(self):
        """Seed 60 inventory items."""
        self.stdout.write('\n📦 Seeding Inventory Items (60 rows)...')
        from apps.inventory.models import Item, Warehouse
        
        # Create warehouses
        warehouses_data = [
            ('MAIN', 'Main Warehouse', 'Dubai'),
            ('JLT', 'JLT Warehouse', 'Dubai'),
            ('AUH', 'Abu Dhabi Warehouse', 'Abu Dhabi'),
            ('SHJ', 'Sharjah Warehouse', 'Sharjah'),
        ]
        
        wh_objs = {}
        for code, name, city in warehouses_data:
            wh, _ = Warehouse.objects.get_or_create(
                code=code,
                defaults={'name': name, 'address': f'{name}, {city}, UAE'}
            )
            wh_objs[code] = wh
        
        # Items data
        items_data = [
            # IT Equipment
            ('Laptop Dell XPS 15', 'IT', 3500, 4500, 'piece'),
            ('Laptop HP ProBook', 'IT', 2800, 3600, 'piece'),
            ('Laptop Lenovo ThinkPad', 'IT', 3200, 4100, 'piece'),
            ('Desktop PC Dell', 'IT', 2500, 3200, 'piece'),
            ('Desktop PC HP', 'IT', 2300, 3000, 'piece'),
            ('Monitor 27" Dell', 'IT', 800, 1100, 'piece'),
            ('Monitor 24" HP', 'IT', 600, 850, 'piece'),
            ('Keyboard Logitech', 'IT', 150, 220, 'piece'),
            ('Mouse Wireless', 'IT', 80, 130, 'piece'),
            ('Webcam HD', 'IT', 200, 320, 'piece'),
            ('Headset Jabra', 'IT', 350, 500, 'piece'),
            ('Docking Station', 'IT', 400, 580, 'piece'),
            ('Network Switch', 'IT', 1200, 1600, 'piece'),
            ('WiFi Router', 'IT', 450, 650, 'piece'),
            ('UPS 1500VA', 'IT', 600, 850, 'piece'),
            ('External HDD 1TB', 'IT', 180, 280, 'piece'),
            ('USB Flash 64GB', 'IT', 40, 70, 'piece'),
            ('Printer HP LaserJet', 'IT', 1200, 1650, 'piece'),
            ('Scanner Epson', 'IT', 800, 1100, 'piece'),
            ('Projector Epson', 'IT', 2500, 3300, 'piece'),
            # Furniture
            ('Executive Desk', 'FUR', 1500, 2100, 'piece'),
            ('Manager Desk', 'FUR', 1200, 1700, 'piece'),
            ('Staff Desk', 'FUR', 800, 1150, 'piece'),
            ('Executive Chair', 'FUR', 900, 1300, 'piece'),
            ('Manager Chair', 'FUR', 600, 900, 'piece'),
            ('Staff Chair', 'FUR', 350, 520, 'piece'),
            ('Meeting Table 8P', 'FUR', 2000, 2800, 'piece'),
            ('Meeting Table 4P', 'FUR', 1200, 1700, 'piece'),
            ('Cabinet 4 Drawer', 'FUR', 450, 680, 'piece'),
            ('Bookshelf', 'FUR', 350, 520, 'piece'),
            ('Reception Desk', 'FUR', 2500, 3500, 'piece'),
            ('Sofa 3 Seater', 'FUR', 1800, 2600, 'piece'),
            ('Coffee Table', 'FUR', 400, 600, 'piece'),
            ('Whiteboard', 'FUR', 200, 320, 'piece'),
            ('Notice Board', 'FUR', 150, 250, 'piece'),
            # Office Supplies
            ('A4 Paper Box', 'SUP', 80, 120, 'box'),
            ('Printer Toner HP', 'SUP', 250, 380, 'piece'),
            ('Ink Cartridge', 'SUP', 120, 180, 'piece'),
            ('Stapler', 'SUP', 25, 45, 'piece'),
            ('Staples Box', 'SUP', 8, 15, 'box'),
            ('Paper Clips', 'SUP', 5, 12, 'box'),
            ('Binder Clips', 'SUP', 10, 18, 'box'),
            ('Sticky Notes', 'SUP', 15, 28, 'pack'),
            ('Highlighters Set', 'SUP', 20, 35, 'pack'),
            ('Pens Box', 'SUP', 30, 50, 'box'),
            ('Pencils Box', 'SUP', 15, 28, 'box'),
            ('Folders Pack', 'SUP', 25, 42, 'pack'),
            ('Envelopes Box', 'SUP', 35, 55, 'box'),
            ('Tape Dispenser', 'SUP', 20, 35, 'piece'),
            ('Scissors', 'SUP', 12, 22, 'piece'),
            # Electronics
            ('iPad Pro 12.9', 'ELEC', 3200, 4200, 'piece'),
            ('iPad Air', 'ELEC', 2200, 2900, 'piece'),
            ('Samsung Tab S8', 'ELEC', 2500, 3300, 'piece'),
            ('iPhone 15 Pro', 'ELEC', 4500, 5500, 'piece'),
            ('Samsung S24 Ultra', 'ELEC', 4200, 5200, 'piece'),
            ('Apple Watch', 'ELEC', 1500, 2000, 'piece'),
            ('AirPods Pro', 'ELEC', 800, 1100, 'piece'),
            ('Power Bank 20000', 'ELEC', 150, 250, 'piece'),
            ('HDMI Cable', 'ELEC', 30, 55, 'piece'),
            ('USB-C Cable', 'ELEC', 25, 45, 'piece'),
        ]
        
        created = 0
        for name, category, cost, price, unit in items_data:
            item, was_created = Item.objects.get_or_create(
                name=name,
                defaults={
                    'description': f'{name} - {category}',
                    'unit': unit,
                    'purchase_price': Decimal(str(cost)),
                    'selling_price': Decimal(str(price)),
                    'vat_rate': Decimal('5.00'),
                    'minimum_stock': Decimal(str(random.randint(5, 20))),
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} items, Total: {Item.objects.count()}'))

    def seed_fixed_assets(self):
        """Seed 60 fixed assets."""
        self.stdout.write('\n🏭 Seeding Fixed Assets (60 rows)...')
        from apps.assets.models import AssetCategory, FixedAsset
        from apps.finance.models import Account
        
        # Create asset categories
        categories_data = [
            ('FUR', 'Furniture & Fixtures', 5, 'straight_line', '1400', '5500', '1401'),
            ('IT', 'IT Equipment', 3, 'straight_line', '1410', '5500', '1411'),
            ('VEH', 'Vehicles', 5, 'straight_line', '1420', '5500', '1421'),
            ('ELEC', 'Electronics', 3, 'straight_line', '1410', '5500', '1411'),
            ('MACH', 'Machinery', 7, 'straight_line', '1400', '5500', '1401'),
        ]
        
        cat_objs = {}
        for code, name, life, method, asset_acc, dep_acc, accum_acc in categories_data:
            asset_account = Account.objects.filter(code=asset_acc).first()
            dep_account = Account.objects.filter(code=dep_acc).first()
            accum_account = Account.objects.filter(code=accum_acc).first()
            
            cat, _ = AssetCategory.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'useful_life_years': life,
                    'depreciation_method': method,
                    'asset_account': asset_account,
                    'depreciation_expense_account': dep_account,
                    'accumulated_depreciation_account': accum_account,
                }
            )
            cat_objs[code] = cat
        
        # Assets data
        assets_data = [
            # Furniture
            ('Executive Desks Set', 'FUR', 35000, date(2024, 1, 1)),
            ('Manager Desks Set', 'FUR', 25000, date(2024, 1, 1)),
            ('Staff Desks - Floor 1', 'FUR', 40000, date(2024, 1, 1)),
            ('Staff Desks - Floor 2', 'FUR', 40000, date(2024, 1, 1)),
            ('Executive Chairs Set', 'FUR', 18000, date(2024, 1, 1)),
            ('Manager Chairs Set', 'FUR', 12000, date(2024, 1, 1)),
            ('Staff Chairs - All', 'FUR', 35000, date(2024, 1, 1)),
            ('Meeting Room Furniture A', 'FUR', 25000, date(2024, 1, 1)),
            ('Meeting Room Furniture B', 'FUR', 20000, date(2024, 1, 1)),
            ('Reception Area Furniture', 'FUR', 30000, date(2024, 1, 1)),
            ('Cabinets & Storage', 'FUR', 22000, date(2024, 1, 1)),
            ('Pantry Furniture', 'FUR', 15000, date(2024, 1, 1)),
            # IT Equipment
            ('Laptops - Management', 'IT', 70000, date(2024, 1, 1)),
            ('Laptops - Finance', 'IT', 42000, date(2024, 1, 1)),
            ('Laptops - IT Team', 'IT', 56000, date(2024, 1, 1)),
            ('Laptops - Sales', 'IT', 49000, date(2024, 1, 1)),
            ('Laptops - Others', 'IT', 63000, date(2024, 1, 1)),
            ('Desktops - All', 'IT', 50000, date(2024, 1, 1)),
            ('Monitors - All', 'IT', 40000, date(2024, 1, 1)),
            ('Servers - Main', 'IT', 120000, date(2024, 1, 1)),
            ('Servers - Backup', 'IT', 80000, date(2024, 1, 1)),
            ('Network Equipment', 'IT', 45000, date(2024, 1, 1)),
            ('Printers & Scanners', 'IT', 25000, date(2024, 1, 1)),
            ('Projectors', 'IT', 30000, date(2024, 1, 1)),
            ('CCTV System', 'IT', 35000, date(2024, 1, 1)),
            ('Access Control System', 'IT', 28000, date(2024, 1, 1)),
            ('Phone System', 'IT', 40000, date(2024, 1, 1)),
            ('UPS Systems', 'IT', 32000, date(2024, 1, 1)),
            # Vehicles
            ('Company Car - CEO', 'VEH', 250000, date(2024, 1, 1)),
            ('Company Car - CFO', 'VEH', 180000, date(2024, 1, 1)),
            ('Company Car - Sales 1', 'VEH', 120000, date(2024, 1, 1)),
            ('Company Car - Sales 2', 'VEH', 120000, date(2024, 1, 1)),
            ('Company Van - Delivery', 'VEH', 85000, date(2024, 1, 1)),
            ('Company Pickup', 'VEH', 95000, date(2024, 1, 1)),
            # Electronics
            ('iPads - Management', 'ELEC', 32000, date(2024, 1, 1)),
            ('iPads - Sales', 'ELEC', 44000, date(2024, 1, 1)),
            ('Mobile Phones - Staff', 'ELEC', 90000, date(2024, 1, 1)),
            ('Smartwatches - Mgmt', 'ELEC', 15000, date(2024, 1, 1)),
            ('Audio/Video Equipment', 'ELEC', 45000, date(2024, 1, 1)),
            ('TV Screens - Office', 'ELEC', 25000, date(2024, 1, 1)),
            ('Coffee Machines', 'ELEC', 18000, date(2024, 1, 1)),
            ('Water Dispensers', 'ELEC', 8000, date(2024, 1, 1)),
            ('Air Purifiers', 'ELEC', 12000, date(2024, 1, 1)),
            ('Microwave Ovens', 'ELEC', 5000, date(2024, 1, 1)),
            ('Refrigerators', 'ELEC', 15000, date(2024, 1, 1)),
            # More Furniture
            ('Lounge Sofas', 'FUR', 28000, date(2024, 1, 1)),
            ('Outdoor Furniture', 'FUR', 15000, date(2024, 1, 1)),
            ('Partition Walls', 'FUR', 35000, date(2024, 1, 1)),
            ('Blinds & Curtains', 'FUR', 20000, date(2024, 1, 1)),
            ('Carpets', 'FUR', 40000, date(2024, 1, 1)),
            ('Lighting Fixtures', 'FUR', 25000, date(2024, 1, 1)),
            ('Art & Decor', 'FUR', 15000, date(2024, 1, 1)),
            ('Plants & Planters', 'FUR', 8000, date(2024, 1, 1)),
            # More IT
            ('Backup Drives', 'IT', 15000, date(2024, 1, 1)),
            ('Firewall Equipment', 'IT', 25000, date(2024, 1, 1)),
            ('Video Conf Equipment', 'IT', 50000, date(2024, 1, 1)),
            ('Headsets & Accessories', 'IT', 12000, date(2024, 1, 1)),
            ('Software Licenses (Cap)', 'IT', 80000, date(2024, 1, 1)),
            ('Docking Stations', 'IT', 18000, date(2024, 1, 1)),
        ]
        
        created = 0
        for name, cat_code, cost, acq_date in assets_data:
            asset, was_created = FixedAsset.objects.get_or_create(
                name=name,
                defaults={
                    'category': cat_objs[cat_code],
                    'acquisition_date': acq_date,
                    'acquisition_cost': Decimal(str(cost)),
                    'depreciation_method': cat_objs[cat_code].depreciation_method,
                    'useful_life_years': cat_objs[cat_code].useful_life_years,
                    'salvage_value': Decimal(str(int(cost * 0.05))),  # 5% salvage
                    'status': 'draft',
                    'location': 'Dubai Office',
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} fixed assets, Total: {FixedAsset.objects.count()}'))

    def seed_projects(self):
        """Seed 50 projects."""
        self.stdout.write('\n📋 Seeding Projects (50 rows)...')
        from apps.projects.models import Project
        from apps.crm.models import Customer
        
        customers = list(Customer.objects.all()[:30])
        
        projects_data = [
            ('ERP Implementation Phase 1', 'fixed', 500000),
            ('ERP Implementation Phase 2', 'fixed', 400000),
            ('Mobile App Development', 'fixed', 300000),
            ('Website Redesign', 'fixed', 150000),
            ('Cloud Migration', 'time_material', 250000),
            ('Network Infrastructure', 'fixed', 180000),
            ('Security Audit', 'time_material', 80000),
            ('Process Automation', 'fixed', 200000),
            ('Data Analytics Platform', 'fixed', 350000),
            ('CRM Integration', 'fixed', 120000),
            ('E-commerce Platform', 'fixed', 280000),
            ('HR System Implementation', 'milestone', 160000),
            ('Finance System Upgrade', 'milestone', 190000),
            ('Inventory Management', 'fixed', 140000),
            ('Supply Chain Optimization', 'time_material', 220000),
            ('Quality Management System', 'milestone', 110000),
            ('Training Program', 'time_material', 90000),
            ('Change Management', 'time_material', 130000),
            ('Digital Transformation', 'milestone', 450000),
            ('IoT Implementation', 'fixed', 320000),
            ('AI/ML Development', 'fixed', 380000),
            ('Blockchain Solution', 'fixed', 270000),
            ('API Integration', 'fixed', 95000),
            ('Database Optimization', 'time_material', 75000),
            ('Server Migration', 'fixed', 110000),
            ('Disaster Recovery Setup', 'fixed', 145000),
            ('Compliance Audit', 'time_material', 85000),
            ('Performance Optimization', 'time_material', 70000),
            ('User Training', 'time_material', 60000),
            ('Documentation Project', 'time_material', 45000),
            ('System Integration', 'milestone', 185000),
            ('Legacy Modernization', 'fixed', 290000),
            ('DevOps Implementation', 'time_material', 170000),
            ('Agile Transformation', 'time_material', 120000),
            ('Customer Portal', 'fixed', 195000),
            ('Vendor Portal', 'fixed', 165000),
            ('Employee Portal', 'fixed', 145000),
            ('Business Intelligence', 'milestone', 230000),
            ('Reporting System', 'fixed', 95000),
            ('Dashboard Development', 'fixed', 85000),
            ('Mobile Optimization', 'fixed', 75000),
            ('SEO Implementation', 'time_material', 55000),
            ('Content Management', 'fixed', 105000),
            ('Knowledge Base', 'fixed', 65000),
            ('Help Desk System', 'fixed', 115000),
            ('Ticketing System', 'fixed', 90000),
            ('Asset Management', 'milestone', 130000),
            ('Facility Management', 'fixed', 155000),
            ('Project Management Tool', 'fixed', 140000),
            ('Collaboration Platform', 'fixed', 175000),
        ]
        
        created = 0
        for i, (name, billing_type, value) in enumerate(projects_data):
            customer = customers[i % len(customers)] if customers else None
            proj, was_created = Project.objects.get_or_create(
                name=name,
                defaults={
                    'customer': customer,
                    'billing_type': billing_type,
                    'contract_value': Decimal(str(value)),
                    'budget': Decimal(str(int(value * 0.85))),
                    'start_date': date(2024, random.randint(1, 6), 1),
                    'end_date': date(2024, random.randint(7, 12), 28),
                    'status': random.choice(['planning', 'ongoing']),
                    'description': f'{name} for {customer.name if customer else "Internal"}',
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} projects, Total: {Project.objects.count()}'))

    def seed_property_management(self):
        """Seed properties, tenants, leases."""
        self.stdout.write('\n🏢 Seeding Property Management (50+ rows each)...')
        from apps.property.models import Property, Unit, Tenant, Lease
        from apps.finance.models import Account
        
        # Properties
        properties_data = [
            ('Business Bay Tower', 'Dubai', 'commercial', 50),
            ('Marina Heights', 'Dubai', 'residential', 80),
            ('JLT Office Park', 'Dubai', 'commercial', 40),
            ('Downtown Plaza', 'Dubai', 'mixed', 60),
            ('DIFC Center', 'Dubai', 'commercial', 35),
            ('Palm Residences', 'Dubai', 'residential', 100),
            ('Deira Commercial', 'Dubai', 'commercial', 45),
            ('Sharjah Business', 'Sharjah', 'commercial', 30),
            ('Abu Dhabi Tower', 'Abu Dhabi', 'commercial', 55),
            ('Ajman Plaza', 'Ajman', 'mixed', 25),
        ]
        
        prop_objs = {}
        for name, city, prop_type, units in properties_data:
            prop, _ = Property.objects.get_or_create(
                name=name,
                defaults={
                    'address': f'{name}, {city}, UAE',
                    'city': city,
                    'emirate': city if city in ['Dubai', 'Sharjah', 'Ajman'] else city.split()[0],
                    'property_type': prop_type,
                    'total_units': units,
                }
            )
            prop_objs[name] = prop
        
        # Units - create 60 units across properties
        unit_count = 0
        for prop_name, prop in prop_objs.items():
            for i in range(6):  # 6 units per property
                unit_type = random.choice(['apartment', 'office', 'shop', 'villa'])
                rent = random.choice([5000, 8000, 10000, 15000, 20000, 25000, 30000])
                Unit.objects.get_or_create(
                    property=prop,
                    unit_number=f'{i+1:03d}',
                    defaults={
                        'unit_type': unit_type,
                        'floor': str((i // 10) + 1),
                        'area_sqft': random.randint(500, 2000),
                        'bedrooms': random.randint(0, 3) if unit_type in ['apartment', 'villa'] else 0,
                        'status': 'available',
                        'monthly_rent': Decimal(str(rent)),
                    }
                )
                unit_count += 1
        
        self.stdout.write(f'  Created {unit_count} units')
        
        # Tenants - 60 tenants
        ar_property = Account.objects.filter(code='1210').first()
        
        tenant_names = [
            'Alpha Trading LLC', 'Beta Services FZE', 'Gamma Tech DMCC', 'Delta Logistics',
            'Epsilon Consulting', 'Zeta Holdings', 'Eta Investments', 'Theta Properties',
            'Iota Solutions', 'Kappa Enterprises', 'Lambda Corp', 'Mu Trading',
            'Nu Services', 'Xi Industries', 'Omicron LLC', 'Pi Technologies',
            'Rho Consulting', 'Sigma Holdings', 'Tau Investments', 'Upsilon Group',
            'Phi Trading', 'Chi Services', 'Psi Solutions', 'Omega Corp',
            'First Gulf Trading', 'Second Wave Tech', 'Third Eye Consulting', 'Fourth Dimension',
            'Fifth Avenue', 'Sixth Sense', 'Seventh Heaven', 'Eight Mile',
            'Ninth Gate', 'Tenth Floor', 'Rising Star', 'Golden Eagle',
            'Silver Line', 'Bronze Age', 'Platinum Plus', 'Diamond Edge',
            'Pearl Gulf', 'Ruby Stone', 'Emerald City', 'Sapphire Blue',
            'Crystal Clear', 'Amber Light', 'Jade Garden', 'Opal Trade',
            'Topaz Tech', 'Coral Reef', 'Marble Hall', 'Granite Rock',
            'Cedar Wood', 'Pine Tree', 'Oak Ridge', 'Maple Leaf',
            'Palm Bay', 'Olive Branch', 'Fig Tree', 'Apple Core',
        ]
        
        tenant_objs = []
        for name in tenant_names:
            tenant, _ = Tenant.objects.get_or_create(
                name=name,
                defaults={
                    'email': f'{name.lower().replace(" ", ".")}@email.com',
                    'phone': f'+9715{random.randint(1000000, 9999999)}',
                    'trn': f'100{random.randint(100000000000, 999999999999)}',
                    'address': f'{name}, Dubai, UAE',
                    'status': 'active',
                    'ar_account': ar_property,
                }
            )
            tenant_objs.append(tenant)
        
        self.stdout.write(f'  Created {len(tenant_names)} tenants')
        
        # Leases - 50 leases
        units = list(Unit.objects.all())
        lease_count = 0
        for i, tenant in enumerate(tenant_objs[:50]):
            unit = units[i % len(units)] if units else None
            annual_rent = random.choice([60000, 80000, 100000, 120000, 150000, 180000, 200000])
            
            Lease.objects.get_or_create(
                tenant=tenant,
                unit=unit,
                start_date=date(2024, 1, 1),
                defaults={
                    'end_date': date(2024, 12, 31),
                    'annual_rent': Decimal(str(annual_rent)),
                    'payment_frequency': random.choice(['monthly', 'quarterly']),
                    'number_of_cheques': 12 if random.random() > 0.5 else 4,
                    'security_deposit': Decimal(str(annual_rent // 12)),
                    'status': 'active',
                }
            )
            lease_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {lease_count} leases'))

    def seed_pdc_cheques(self):
        """Seed 60 PDC cheques."""
        self.stdout.write('\n💳 Seeding PDC Cheques (60 rows)...')
        from apps.property.models import PDCCheque, Tenant, Lease
        from apps.finance.models import BankAccount
        
        tenants = list(Tenant.objects.all())
        leases = list(Lease.objects.all())
        banks = ['ADCB', 'Emirates NBD', 'Mashreq', 'FAB', 'DIB', 'RAKBank', 'CBD', 'NBAD']
        bank_account = BankAccount.objects.first()
        
        pdc_count = 0
        for i in range(60):
            tenant = tenants[i % len(tenants)]
            lease = leases[i % len(leases)] if leases else None
            amount = random.choice([10500, 15750, 21000, 26250, 31500, 42000, 52500])
            month = (i % 12) + 1
            # Use safe day values that work for all months (including Feb)
            day = random.choice([10, 15, 20, 25])
            cheque_date = date(2024, month, day)
            bank = random.choice(banks)
            
            # Determine status
            if i < 20:
                status = 'cleared'
                deposit_status = 'cleared'
            elif i < 40:
                status = 'deposited'
                deposit_status = 'in_clearing'
            else:
                status = 'received'
                deposit_status = 'pending'
            
            pdc, created = PDCCheque.objects.get_or_create(
                cheque_number=f'CHQ{100000 + i}',
                bank_name=bank,
                cheque_date=cheque_date,
                amount=Decimal(str(amount)),
                tenant=tenant,
                defaults={
                    'lease': lease,
                    'purpose': 'rent',
                    'status': status,
                    'deposit_status': deposit_status,
                    'received_date': date(2024, 1, random.randint(1, 28)),
                    'deposited_to_bank': bank_account if status != 'received' else None,
                    'deposited_date': cheque_date - timedelta(days=5) if status != 'received' else None,
                    'cleared_date': cheque_date if status == 'cleared' else None,
                }
            )
            if created:
                pdc_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {pdc_count} PDC cheques'))

    def seed_recurring_expenses(self):
        """Seed 50 recurring expenses."""
        self.stdout.write('\n🔄 Seeding Recurring Expenses (50 rows)...')
        from apps.purchase.models import Vendor, RecurringExpense
        from apps.finance.models import Account, TaxCode
        
        vendors = {v.name: v for v in Vendor.objects.all()}
        vat_code = TaxCode.objects.filter(rate=5).first()
        zero_code = TaxCode.objects.filter(rate=0).first()
        
        # Get expense accounts
        accounts = {
            'Rent': Account.objects.filter(code='5400').first(),
            'Electricity': Account.objects.filter(code='5410').first(),
            'Internet': Account.objects.filter(code='5430').first(),
            'Software': Account.objects.filter(code='6400').first(),
            'Insurance': Account.objects.filter(code='6200').first(),
            'Maintenance': Account.objects.filter(code='6300').first(),
            'Marketing': Account.objects.filter(code='6100').first(),
            'Default': Account.objects.filter(account_type='expense').first(),
        }
        
        recurring_data = [
            # Rent
            ('Office Rent - Floor 1', 'Office Landlord LLC', 50000, 'Rent', False, 'monthly'),
            ('Office Rent - Floor 2', 'Office Landlord LLC', 45000, 'Rent', False, 'monthly'),
            ('Warehouse Rent', 'Dubai Properties Corp', 25000, 'Rent', False, 'monthly'),
            ('Parking Rent', 'DAMAC Properties', 5000, 'Rent', False, 'monthly'),
            # Utilities
            ('Electricity - Main Office', 'DEWA', 8000, 'Electricity', True, 'monthly'),
            ('Electricity - Warehouse', 'DEWA', 3000, 'Electricity', True, 'monthly'),
            ('Water Supply', 'DEWA', 1500, 'Electricity', True, 'monthly'),
            ('Internet - Main', 'Etisalat', 2000, 'Internet', True, 'monthly'),
            ('Internet - Backup', 'Du', 1500, 'Internet', True, 'monthly'),
            ('Telephone Lines', 'Etisalat', 1000, 'Internet', True, 'monthly'),
            # Software
            ('Microsoft 365', 'Microsoft UAE', 3000, 'Software', True, 'monthly'),
            ('AWS Cloud', 'Amazon Web Services', 5000, 'Software', True, 'monthly'),
            ('Salesforce CRM', 'Oracle ME', 2500, 'Software', True, 'monthly'),
            ('Zoom Subscription', 'Microsoft UAE', 500, 'Software', True, 'monthly'),
            ('Slack Enterprise', 'Amazon Web Services', 800, 'Software', True, 'monthly'),
            ('GitHub Enterprise', 'Microsoft UAE', 1200, 'Software', True, 'monthly'),
            ('Adobe Creative', 'Amazon Web Services', 1500, 'Software', True, 'monthly'),
            ('Accounting Software', 'SAP MENA', 2000, 'Software', True, 'monthly'),
            ('HR Software', 'Oracle ME', 1800, 'Software', True, 'monthly'),
            ('Project Management', 'Microsoft UAE', 900, 'Software', True, 'monthly'),
            # Insurance
            ('Office Insurance', 'AXA Insurance', 15000, 'Insurance', False, 'yearly'),
            ('Vehicle Insurance', 'Oman Insurance', 25000, 'Insurance', False, 'yearly'),
            ('Health Insurance', 'Dubai Insurance', 180000, 'Insurance', False, 'yearly'),
            ('Professional Indemnity', 'SALAMA Insurance', 20000, 'Insurance', False, 'yearly'),
            ('Asset Insurance', 'AXA Insurance', 12000, 'Insurance', False, 'yearly'),
            # Maintenance
            ('AC Maintenance', 'Emrill Services', 2500, 'Maintenance', True, 'quarterly'),
            ('Elevator Maintenance', 'Farnek Services', 3000, 'Maintenance', True, 'quarterly'),
            ('Fire System Maintenance', 'Imdaad LLC', 2000, 'Maintenance', True, 'quarterly'),
            ('Cleaning Services', 'Cleaning Services Co', 8000, 'Maintenance', True, 'monthly'),
            ('Pest Control', 'Farnek Services', 1000, 'Maintenance', True, 'quarterly'),
            ('Security Services', 'Security Services LLC', 15000, 'Maintenance', True, 'monthly'),
            ('Landscaping', 'Emrill Services', 2000, 'Maintenance', True, 'monthly'),
            ('IT Support', 'Dell Technologies', 5000, 'Maintenance', True, 'monthly'),
            ('Printer Maintenance', 'HP Enterprise', 1500, 'Maintenance', True, 'quarterly'),
            ('CCTV Maintenance', 'Cisco Systems', 1200, 'Maintenance', True, 'quarterly'),
            # Marketing
            ('Google Ads', 'Google UAE', 10000, 'Marketing', True, 'monthly'),
            ('Facebook Ads', 'Facebook ME', 5000, 'Marketing', True, 'monthly'),
            ('LinkedIn Premium', 'Microsoft UAE', 2000, 'Marketing', True, 'monthly'),
            ('PR Agency', 'Leo Burnett', 15000, 'Marketing', True, 'monthly'),
            ('SEO Services', 'Google UAE', 3000, 'Marketing', True, 'monthly'),
            # Others
            ('Courier Services', 'Aramex', 2000, 'Default', True, 'monthly'),
            ('Stationery Supply', 'Office Depot UAE', 1500, 'Default', True, 'monthly'),
            ('Coffee & Pantry', 'Nespresso UAE', 1000, 'Default', True, 'monthly'),
            ('Water Delivery', 'Al Ain Water', 500, 'Default', True, 'monthly'),
            ('Fuel Card', 'ENOC', 5000, 'Default', True, 'monthly'),
            ('Bank Charges', 'Emirates NBD', 500, 'Default', True, 'monthly'),
            ('Audit Fees', 'PwC UAE', 50000, 'Default', True, 'yearly'),
            ('Legal Retainer', 'Al Tamimi & Co', 20000, 'Default', True, 'quarterly'),
            ('Training Budget', 'Training Institute', 10000, 'Default', True, 'quarterly'),
            ('Travel Budget', 'DNATA Travel', 15000, 'Default', True, 'monthly'),
        ]
        
        created = 0
        for name, vendor_name, amount, acc_key, has_vat, freq in recurring_data:
            vendor = vendors.get(vendor_name)
            if not vendor:
                continue
            
            expense_account = accounts.get(acc_key) or accounts['Default']
            tax_code = vat_code if has_vat else zero_code
            
            rec, was_created = RecurringExpense.objects.get_or_create(
                name=name,
                vendor=vendor,
                defaults={
                    'expense_account': expense_account,
                    'tax_code': tax_code,
                    'amount': Decimal(str(amount)),
                    'frequency': freq,
                    'start_date': date(2024, 1, 1),
                    'next_run_date': date(2024, 2, 1),
                    'auto_post': True,
                    'status': 'active',
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {created} recurring expenses'))

    def seed_stock_movements(self):
        """Seed 60 stock movements."""
        self.stdout.write('\n📈 Seeding Stock Movements (60 rows)...')
        from apps.inventory.models import Item, Warehouse, StockMovement
        
        items = list(Item.objects.all())
        warehouses = list(Warehouse.objects.all())
        
        if not items or not warehouses:
            self.stdout.write(self.style.WARNING('  No items or warehouses found'))
            return
        
        main_warehouse = warehouses[0]
        
        movement_count = 0
        for i in range(60):
            item = items[i % len(items)]
            
            if i < 30:
                # Stock In (purchases)
                movement_type = 'in'
                qty = random.randint(10, 50)
                cost = item.purchase_price
            elif i < 50:
                # Stock Out (sales)
                movement_type = 'out'
                qty = random.randint(1, 10)
                cost = item.purchase_price
            else:
                # Adjustments
                movement_type = random.choice(['adjustment_plus', 'adjustment_minus'])
                qty = random.randint(1, 5)
                cost = item.purchase_price
            
            movement, created = StockMovement.objects.get_or_create(
                item=item,
                warehouse=main_warehouse,
                movement_type=movement_type,
                movement_date=date(2024, random.randint(1, 3), random.randint(1, 28)),
                quantity=Decimal(str(qty)),
                defaults={
                    'unit_cost': cost,
                    'total_cost': cost * qty,
                    'reference': f'REF-{i+1000}',
                    'notes': f'Test movement {i+1}',
                    'posted': False,
                }
            )
            if created:
                movement_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {movement_count} stock movements'))

    def seed_sales_invoices(self):
        """Seed 60 sales invoices."""
        self.stdout.write('\n💰 Seeding Sales Invoices (60 rows)...')
        from apps.sales.models import Invoice, InvoiceItem
        from apps.crm.models import Customer
        
        customers = list(Customer.objects.all())
        
        if not customers:
            self.stdout.write(self.style.WARNING('  No customers found'))
            return
        
        products = [
            ('Software Development Services', 15000),
            ('IT Consulting', 8000),
            ('Cloud Infrastructure Setup', 25000),
            ('Network Installation', 12000),
            ('Security Assessment', 10000),
            ('Mobile App Development', 35000),
            ('Website Development', 20000),
            ('ERP Implementation', 80000),
            ('Data Migration', 15000),
            ('Training Services', 5000),
            ('Support Contract', 3000),
            ('Hardware Supply', 25000),
            ('License Renewal', 8000),
            ('API Integration', 12000),
            ('Database Optimization', 10000),
        ]
        
        invoice_count = 0
        for i in range(60):
            customer = customers[i % len(customers)]
            inv_date = date(2024, (i % 3) + 1, random.randint(1, 28))
            
            invoice = Invoice.objects.create(
                customer=customer,
                invoice_date=inv_date,
                due_date=inv_date + timedelta(days=30),
                status='draft',
                notes=f'Invoice for {customer.name}',
            )
            
            # Add 1-3 items per invoice
            num_items = random.randint(1, 3)
            for j in range(num_items):
                product, base_price = random.choice(products)
                qty = random.randint(1, 5)
                price = Decimal(str(base_price)) * Decimal(str(random.uniform(0.8, 1.2)))
                
                InvoiceItem.objects.create(
                    invoice=invoice,
                    description=product,
                    quantity=Decimal(str(qty)),
                    unit_price=price.quantize(Decimal('0.01')),
                    vat_rate=Decimal('5.00'),
                )
            
            invoice.calculate_totals()
            invoice_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {invoice_count} sales invoices'))

    def seed_purchase_bills(self):
        """Seed 60 purchase bills."""
        self.stdout.write('\n🧾 Seeding Purchase Bills (60 rows)...')
        from apps.purchase.models import Vendor, VendorBill, VendorBillItem
        
        vendors = list(Vendor.objects.all())
        
        if not vendors:
            self.stdout.write(self.style.WARNING('  No vendors found'))
            return
        
        items = [
            ('Office Supplies', 1500),
            ('IT Equipment', 8000),
            ('Furniture', 5000),
            ('Professional Services', 10000),
            ('Maintenance Work', 3000),
            ('Software License', 2500),
            ('Consulting Fees', 15000),
            ('Travel Expenses', 4000),
            ('Marketing Materials', 2000),
            ('Telecommunications', 1000),
            ('Insurance Premium', 5000),
            ('Rent Payment', 25000),
            ('Utility Bills', 3000),
            ('Security Services', 4000),
            ('Cleaning Services', 2000),
        ]
        
        bill_count = 0
        for i in range(60):
            vendor = vendors[i % len(vendors)]
            bill_date = date(2024, (i % 3) + 1, random.randint(1, 28))
            
            bill = VendorBill.objects.create(
                vendor=vendor,
                vendor_invoice_number=f'VINV-{vendor.vendor_number}-{i+1000}',
                bill_date=bill_date,
                due_date=bill_date + timedelta(days=30),
                status='draft',
                notes=f'Bill from {vendor.name}',
            )
            
            # Add 1-3 items per bill
            num_items = random.randint(1, 3)
            for j in range(num_items):
                item_desc, base_price = random.choice(items)
                qty = random.randint(1, 10)
                price = Decimal(str(base_price)) * Decimal(str(random.uniform(0.8, 1.2)))
                
                VendorBillItem.objects.create(
                    bill=bill,
                    description=item_desc,
                    quantity=Decimal(str(qty)),
                    unit_price=price.quantize(Decimal('0.01')),
                    vat_rate=Decimal('5.00'),
                )
            
            bill.calculate_totals()
            bill_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {bill_count} purchase bills'))

    def seed_expense_claims(self):
        """Seed 60 expense claims."""
        self.stdout.write('\n💳 Seeding Expense Claims (60 rows)...')
        from apps.purchase.models import ExpenseClaim, ExpenseClaimItem
        
        users = list(User.objects.filter(is_active=True))
        
        if not users:
            users = [self.admin_user]
        
        expenses = [
            ('Travel - Client Meeting', 'travel', 500),
            ('Travel - Conference', 'travel', 2000),
            ('Travel - Training', 'travel', 1500),
            ('Meals - Client Entertainment', 'meals', 300),
            ('Meals - Team Lunch', 'meals', 200),
            ('Accommodation - Business Trip', 'accommodation', 800),
            ('Transport - Taxi', 'transport', 150),
            ('Transport - Fuel', 'transport', 200),
            ('Office Supplies', 'office', 250),
            ('Communication - Phone', 'communication', 100),
            ('Software Purchase', 'office', 500),
            ('Training Materials', 'other', 300),
            ('Parking Fees', 'transport', 50),
            ('Courier Services', 'other', 100),
            ('Printing Services', 'office', 150),
        ]
        
        claim_count = 0
        for i in range(60):
            user = users[i % len(users)]
            claim_date = date(2024, (i % 3) + 1, random.randint(1, 28))
            
            claim = ExpenseClaim.objects.create(
                employee=user,
                claim_date=claim_date,
                description=f'Expense claim for {claim_date.strftime("%B %Y")}',
                status='draft',
            )
            
            # Add 1-4 items per claim
            num_items = random.randint(1, 4)
            for j in range(num_items):
                desc, category, base_amt = random.choice(expenses)
                amt = Decimal(str(base_amt)) * Decimal(str(random.uniform(0.8, 1.5)))
                
                ExpenseClaimItem.objects.create(
                    expense_claim=claim,
                    date=claim_date - timedelta(days=random.randint(1, 15)),
                    category=category,
                    description=desc,
                    amount=amt.quantize(Decimal('0.01')),
                    vat_amount=(amt * Decimal('0.05')).quantize(Decimal('0.01')),
                    has_receipt=random.random() > 0.2,
                )
            
            claim.calculate_totals()
            claim_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {claim_count} expense claims'))

    def seed_payroll(self):
        """Seed 60 payroll records."""
        self.stdout.write('\n💵 Seeding Payroll (60 rows)...')
        from apps.hr.models import Payroll, Employee
        
        employees = list(Employee.objects.filter(status='active'))
        
        if not employees:
            self.stdout.write(self.style.WARNING('  No active employees found'))
            return
        
        payroll_count = 0
        for month_num in [1, 2, 3]:  # Jan, Feb, Mar 2024
            # Create date for first day of month
            month_date = date(2024, month_num, 1)
            
            for emp in employees[:20]:  # 20 employees per month = 60 total
                allowances = emp.basic_salary * Decimal('0.25') + Decimal('500')
                net_salary = emp.basic_salary + allowances
                
                payroll, created = Payroll.objects.get_or_create(
                    employee=emp,
                    month=month_date,
                    defaults={
                        'basic_salary': emp.basic_salary,
                        'allowances': allowances,
                        'deductions': Decimal('0'),
                        'net_salary': net_salary,
                        'status': 'draft',
                    }
                )
                if created:
                    payroll_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'  Created {payroll_count} payroll records'))

    def run_depreciation(self):
        """Run depreciation for Jan, Feb, Mar 2024."""
        self.stdout.write('\n📉 Running Asset Depreciation...')
        from apps.assets.models import FixedAsset
        
        assets = FixedAsset.objects.filter(status='draft')
        
        # First activate all draft assets
        activated = 0
        for asset in assets:
            try:
                asset.activate(self.admin_user)
                activated += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  Could not activate {asset.name}: {e}'))
        
        self.stdout.write(f'  Activated {activated} assets')
        
        # Run depreciation for 3 months
        active_assets = FixedAsset.objects.filter(status='active')
        dep_count = 0
        
        for month in [1, 2, 3]:
            dep_date = date(2024, month, 28)
            for asset in active_assets:
                try:
                    asset.run_depreciation(dep_date, self.admin_user)
                    dep_count += 1
                except Exception as e:
                    pass  # Skip if already depreciated
        
        self.stdout.write(self.style.SUCCESS(f'  Ran {dep_count} depreciation entries'))

    def validate_data(self):
        """Validate seeded data."""
        self.stdout.write('\n✅ Validating Data...')
        from apps.finance.models import Account, JournalEntry
        from apps.purchase.models import Vendor, VendorBill
        from apps.sales.models import Invoice
        from apps.crm.models import Customer
        from apps.hr.models import Employee, Payroll
        from apps.inventory.models import Item, StockMovement
        from apps.assets.models import FixedAsset
        from apps.projects.models import Project
        from apps.property.models import Property, Tenant, Lease, PDCCheque
        from apps.purchase.models import RecurringExpense, ExpenseClaim
        
        self.stdout.write(f'  Accounts: {Account.objects.count()}')
        self.stdout.write(f'  Vendors: {Vendor.objects.count()}')
        self.stdout.write(f'  Customers: {Customer.objects.count()}')
        self.stdout.write(f'  Employees: {Employee.objects.count()}')
        self.stdout.write(f'  Items: {Item.objects.count()}')
        self.stdout.write(f'  Stock Movements: {StockMovement.objects.count()}')
        self.stdout.write(f'  Fixed Assets: {FixedAsset.objects.count()}')
        self.stdout.write(f'  Projects: {Project.objects.count()}')
        self.stdout.write(f'  Properties: {Property.objects.count()}')
        self.stdout.write(f'  Tenants: {Tenant.objects.count()}')
        self.stdout.write(f'  Leases: {Lease.objects.count()}')
        self.stdout.write(f'  PDC Cheques: {PDCCheque.objects.count()}')
        self.stdout.write(f'  Recurring Expenses: {RecurringExpense.objects.count()}')
        self.stdout.write(f'  Sales Invoices: {Invoice.objects.count()}')
        self.stdout.write(f'  Vendor Bills: {VendorBill.objects.count()}')
        self.stdout.write(f'  Expense Claims: {ExpenseClaim.objects.count()}')
        self.stdout.write(f'  Payroll Records: {Payroll.objects.count()}')
        self.stdout.write(f'  Journal Entries: {JournalEntry.objects.count()}')

