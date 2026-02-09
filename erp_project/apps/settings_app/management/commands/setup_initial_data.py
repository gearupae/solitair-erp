"""
Management command to setup initial data for the ERP system.
Creates default roles, permissions, and company settings.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.settings_app.models import (
    Role, Permission, RolePermission, CompanySettings, NumberSeries
)


class Command(BaseCommand):
    help = 'Setup initial data including roles, permissions, and default settings'

    def handle(self, *args, **options):
        self.stdout.write('Setting up initial data...\n')
        
        # Create permissions
        self.create_permissions()
        
        # Create roles
        self.create_roles()
        
        # Create company settings
        self.create_company_settings()
        
        # Create number series
        self.create_number_series()
        
        # Create superuser if not exists
        self.create_superuser()
        
        self.stdout.write(self.style.SUCCESS('\nInitial data setup completed successfully!'))
    
    def create_permissions(self):
        """Create default permissions for all modules."""
        self.stdout.write('Creating permissions...')
        
        modules = [
            ('crm', 'CRM'),
            ('sales', 'Sales'),
            ('purchase', 'Purchase'),
            ('inventory', 'Inventory'),
            ('finance', 'Finance'),
            ('projects', 'Projects'),
            ('hr', 'HR'),
            ('documents', 'Documents'),
            ('settings', 'Settings'),
        ]
        
        permission_types = [
            ('view', 'View'),
            ('create', 'Create'),
            ('edit', 'Edit'),
            ('delete', 'Delete'),
            ('approve', 'Approve'),
        ]
        
        count = 0
        for module_code, module_name in modules:
            for perm_type, perm_name in permission_types:
                code = f'{module_code}_{perm_type}'
                name = f'{perm_name} {module_name}'
                
                perm, created = Permission.objects.get_or_create(
                    code=code,
                    defaults={
                        'module': module_code,
                        'name': name,
                        'permission_type': perm_type,
                    }
                )
                if created:
                    count += 1
        
        self.stdout.write(f'  Created {count} permissions')
    
    def create_roles(self):
        """Create default roles."""
        self.stdout.write('Creating roles...')
        
        roles_data = [
            {
                'name': 'Super Admin',
                'code': 'super_admin',
                'description': 'Full access to all modules and features',
                'is_system_role': True,
                'permissions': 'all'
            },
            {
                'name': 'Admin',
                'code': 'admin',
                'description': 'Administrative access with most permissions',
                'is_system_role': True,
                'permissions': 'all_except_settings'
            },
            {
                'name': 'Manager',
                'code': 'manager',
                'description': 'Department level management access',
                'is_system_role': False,
                'permissions': ['crm', 'sales', 'purchase', 'inventory', 'projects']
            },
            {
                'name': 'Employee',
                'code': 'employee',
                'description': 'Basic employee access',
                'is_system_role': False,
                'permissions': ['crm:view', 'sales:view', 'inventory:view', 'projects:view']
            },
            {
                'name': 'Accountant',
                'code': 'accountant',
                'description': 'Finance and accounting access',
                'is_system_role': False,
                'permissions': ['finance', 'sales:view', 'purchase:view']
            },
            {
                'name': 'Sales',
                'code': 'sales',
                'description': 'Sales team access',
                'is_system_role': False,
                'permissions': ['crm', 'sales', 'inventory:view']
            },
            {
                'name': 'Purchase',
                'code': 'purchase',
                'description': 'Purchase team access',
                'is_system_role': False,
                'permissions': ['purchase', 'inventory:view']
            },
        ]
        
        count = 0
        for role_data in roles_data:
            role, created = Role.objects.get_or_create(
                code=role_data['code'],
                defaults={
                    'name': role_data['name'],
                    'description': role_data['description'],
                    'is_system_role': role_data['is_system_role'],
                }
            )
            
            if created:
                count += 1
                # Assign permissions based on role
                self.assign_role_permissions(role, role_data['permissions'])
        
        self.stdout.write(f'  Created {count} roles')
    
    def assign_role_permissions(self, role, permissions_config):
        """Assign permissions to a role based on configuration."""
        all_permissions = Permission.objects.all()
        
        if permissions_config == 'all':
            # Full access
            for perm in all_permissions:
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=perm,
                    defaults={
                        'can_create': True,
                        'can_read': True,
                        'can_update': True,
                        'can_delete': True,
                        'can_approve': True,
                    }
                )
        elif permissions_config == 'all_except_settings':
            # All except settings
            for perm in all_permissions.exclude(module='settings'):
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=perm,
                    defaults={
                        'can_create': True,
                        'can_read': True,
                        'can_update': True,
                        'can_delete': True,
                        'can_approve': True,
                    }
                )
        elif isinstance(permissions_config, list):
            # Specific modules or permissions
            for perm_cfg in permissions_config:
                if ':' in perm_cfg:
                    # Module:permission_type format (e.g., 'crm:view')
                    module, perm_type = perm_cfg.split(':')
                    perms = all_permissions.filter(module=module)
                    for perm in perms:
                        rp, _ = RolePermission.objects.get_or_create(
                            role=role,
                            permission=perm,
                            defaults={'can_read': False}
                        )
                        if perm_type == 'view':
                            rp.can_read = True
                        elif perm_type == 'create':
                            rp.can_create = True
                        elif perm_type == 'edit':
                            rp.can_update = True
                        elif perm_type == 'delete':
                            rp.can_delete = True
                        elif perm_type == 'approve':
                            rp.can_approve = True
                        rp.save()
                else:
                    # Full module access
                    for perm in all_permissions.filter(module=perm_cfg):
                        RolePermission.objects.get_or_create(
                            role=role,
                            permission=perm,
                            defaults={
                                'can_create': True,
                                'can_read': True,
                                'can_update': True,
                                'can_delete': True,
                                'can_approve': True,
                            }
                        )
    
    def create_company_settings(self):
        """Create default company settings."""
        self.stdout.write('Creating company settings...')
        
        settings, created = CompanySettings.objects.get_or_create(
            pk=1,
            defaults={
                'company_name': 'My Company',
                'currency': 'AED',
                'timezone': 'Asia/Dubai',
                'fiscal_year_start': 1,
                'date_format': '%d/%m/%Y',
            }
        )
        
        if created:
            self.stdout.write('  Created default company settings')
        else:
            self.stdout.write('  Company settings already exist')
    
    def create_number_series(self):
        """Create default number series."""
        self.stdout.write('Creating number series...')
        
        series_data = [
            ('CUSTOMER', 'CUST', 4),
            ('VENDOR', 'VEND', 4),
            ('QUOTATION', 'QUO', 4),
            ('INVOICE', 'INV', 4),
            ('PURCHASE_REQUEST', 'PR', 4),
            ('PURCHASE_ORDER', 'PO', 4),
            ('BILL', 'BILL', 4),
            ('EMPLOYEE', 'EMP', 4),
            ('PROJECT', 'PROJ', 4),
            ('JOURNAL', 'JV', 4),
            ('PAYMENT', 'PAY', 4),
        ]
        
        count = 0
        for doc_type, prefix, padding in series_data:
            series, created = NumberSeries.objects.get_or_create(
                document_type=doc_type,
                defaults={
                    'prefix': prefix,
                    'padding': padding,
                }
            )
            if created:
                count += 1
        
        self.stdout.write(f'  Created {count} number series')
    
    def create_superuser(self):
        """Create default superuser if none exists."""
        self.stdout.write('Checking for superuser...')
        
        if not User.objects.filter(is_superuser=True).exists():
            user = User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='admin123',
                first_name='System',
                last_name='Admin'
            )
            self.stdout.write(self.style.WARNING(
                '  Created superuser: admin / admin123 (CHANGE THIS PASSWORD!)'
            ))
        else:
            self.stdout.write('  Superuser already exists')





