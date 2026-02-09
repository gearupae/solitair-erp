# Gearup ERP System

A minimal, modular ERP system built with Django 5.x, Bootstrap 5, and PostgreSQL.

## Features

- **CRM Module**: Customer and Lead management
- **Role-Based Access Control**: Granular permissions system
- **Audit Trail**: Track all changes with user and timestamp
- **Responsive UI**: Modern Bootstrap 5 interface
- **UAE Compliant**: Built for UAE VAT and Corporate Tax compliance (Finance module)

## Tech Stack

- **Backend**: Django 5.x
- **Frontend**: Bootstrap 5, jQuery, DataTables, Select2
- **Database**: PostgreSQL
- **Authentication**: Django built-in auth

## Installation

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- pip

### Setup

1. **Clone the repository**
   ```bash
   cd /path/to/Gearup\ ERP
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create PostgreSQL database**
   ```sql
   CREATE DATABASE erp_db;
   ```

5. **Configure environment**
   ```bash
   cd erp_project
   cp .env.example .env
   # Edit .env with your database credentials
   ```

6. **Run migrations**
   ```bash
   python manage.py migrate
   ```

7. **Setup initial data**
   ```bash
   python manage.py setup_initial_data
   ```
   This creates:
   - Default permissions for all modules
   - Default roles (Super Admin, Admin, Manager, etc.)
   - Company settings
   - Number series
   - Default superuser: `admin` / `admin123`

8. **Collect static files**
   ```bash
   python manage.py collectstatic --noinput
   ```

9. **Run the development server**
   ```bash
   python manage.py runserver
   ```

10. **Access the application**
    - URL: http://localhost:8000
    - Login: `admin` / `admin123`
    - **Important**: Change the default password after first login!

## Project Structure

```
erp_project/
├── apps/
│   ├── core/           # Common models, mixins, utilities
│   ├── crm/            # Customer/Lead management
│   ├── settings_app/   # Users, Roles, Permissions, Company
│   └── ... (future modules)
├── static/
│   ├── css/style.css
│   └── js/main.js
├── templates/
│   ├── base.html
│   ├── partials/
│   ├── auth/
│   ├── core/
│   ├── crm/
│   └── settings/
├── media/              # User uploads
└── erp_project/        # Django project config
```

## Modules

### Currently Implemented

1. **Core**
   - Base models with audit fields (created_at, updated_at, created_by, updated_by, is_active)
   - Permission mixins for views
   - Utility functions (number generation, audit logging)

2. **CRM**
   - Customer/Lead management
   - Inline form for quick creation
   - Search and filter functionality
   - Lead to Customer conversion

3. **Settings**
   - User management with role assignment
   - Role management with permission matrix
   - Company settings
   - Audit log viewer

### Planned Modules

- Sales (Quotations, Invoices)
- Purchase (Vendors, PO, Bills)
- Inventory (Items, Stock)
- Finance (UAE VAT & Tax Compliant)
- Projects (Tasks, Timesheets)
- HR (Employees, Leave, Payroll)
- Documents (Doc Expiry)

## Default Roles

| Role | Access Level |
|------|--------------|
| Super Admin | Full access to everything |
| Admin | All modules except settings |
| Manager | CRM, Sales, Purchase, Inventory, Projects |
| Employee | View-only access to main modules |
| Accountant | Finance + view Sales/Purchase |
| Sales | CRM, Sales, view Inventory |
| Purchase | Purchase, view Inventory |

## Number Series

Documents are auto-numbered with format: `PREFIX-YEAR-NUMBER`

Example: `INV-2025-0001`

## Security Features

- CSRF protection
- Password hashing
- SQL injection prevention (ORM)
- XSS protection (template escaping)
- Permission checks on all views
- Session timeout (8 hours)
- Audit logging

## License

Proprietary - Gearup ERP

## Support

For support, contact your system administrator.





