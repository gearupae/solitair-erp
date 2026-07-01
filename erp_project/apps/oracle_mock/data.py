"""Sample Oracle Fusion REST payloads for Depa ERP mock."""

from __future__ import annotations

from datetime import date, timedelta

SAMPLE_PRODUCTION_ORDERS = {
    'items': [
        {
            'WorkOrderId': 900001,
            'WorkOrderNumber': 'ORC-2026-0101',
            'WorkOrderDescription': 'Reception desk — walnut veneer',
            'OrganizationCode': 'DEPA_MAIN',
            'Quantity': 2,
            'StatusCode': 'Released',
            'ScheduledStartDate': (date.today() + timedelta(days=7)).isoformat(),
            'ScheduledCompletionDate': (date.today() + timedelta(days=21)).isoformat(),
            'WIPValue': 0.0,
        },
        {
            'WorkOrderId': 900002,
            'WorkOrderNumber': 'ORC-2026-0102',
            'WorkOrderDescription': 'Conference table carcass',
            'OrganizationCode': 'DEPA_MAIN',
            'Quantity': 1,
            'StatusCode': 'Released',
            'ScheduledStartDate': (date.today() + timedelta(days=14)).isoformat(),
            'ScheduledCompletionDate': (date.today() + timedelta(days=35)).isoformat(),
            'WIPValue': 0.0,
        },
        {
            'WorkOrderId': 900003,
            'WorkOrderNumber': 'ORC-2026-0103',
            'WorkOrderDescription': 'Hotel wardrobe modules (batch)',
            'OrganizationCode': 'DEPA_MAIN',
            'Quantity': 8,
            'StatusCode': 'Released',
            'ScheduledStartDate': date.today().isoformat(),
            'ScheduledCompletionDate': (date.today() + timedelta(days=45)).isoformat(),
            'WIPValue': 0.0,
        },
    ],
    'count': 3,
    'hasMore': False,
    'limit': 25,
    'offset': 0,
}

SAMPLE_ITEMS = {
    'items': [
        {
            'ItemId': 10001,
            'ItemNumber': 'MDF-18-WAL',
            'ItemDescription': 'MDF panel 18mm walnut',
            'PrimaryUOMCode': 'SQM',
            'ItemStatus': 'Active',
        },
        {
            'ItemId': 10002,
            'ItemNumber': 'VNR-OAK-A',
            'ItemDescription': 'Oak veneer sheet A-grade',
            'PrimaryUOMCode': 'SQM',
            'ItemStatus': 'Active',
        },
        {
            'ItemId': 10003,
            'ItemNumber': 'HW-SC-RUN',
            'ItemDescription': 'Soft-close drawer runners',
            'PrimaryUOMCode': 'PCS',
            'ItemStatus': 'Active',
        },
        {
            'ItemId': 10004,
            'ItemNumber': 'EDGE-PVC-2-WAL',
            'ItemDescription': 'PVC edge tape 2mm walnut',
            'PrimaryUOMCode': 'M',
            'ItemStatus': 'Active',
        },
    ],
    'count': 4,
    'hasMore': False,
    'limit': 25,
    'offset': 0,
}
