"""
Inter-entity transfer posting — issue at source, receive at destination, intercompany GL.
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.finance.models import Account, AccountMapping, JournalEntry, JournalEntryLine
from apps.inventory.models import Stock, StockMovement
from apps.inventory.models_inter_entity import InterEntityTransfer, InterEntityTransferLine


def _transfer_unit_price(line: InterEntityTransferLine, transfer: InterEntityTransfer) -> Decimal:
    if transfer.pricing_basis == InterEntityTransfer.PRICING_AGREED and line.unit_price > 0:
        return line.unit_price
    item = line.item
    cost = item.get_issue_unit_cost(transfer.source_warehouse)
    if transfer.pricing_basis == InterEntityTransfer.PRICING_MARKUP:
        markup = transfer.markup_percent or Decimal('0')
        return (cost * (Decimal('1') + markup / Decimal('100'))).quantize(Decimal('0.01'))
    return cost


@transaction.atomic
def approve_transfer(transfer: InterEntityTransfer, user, side: str):
    if side == 'source':
        if transfer.status != InterEntityTransfer.STATUS_DRAFT:
            raise ValidationError('Transfer must be draft to approve at source.')
        transfer.approved_by_source = user
        transfer.status = InterEntityTransfer.STATUS_APPROVED
        transfer.save(update_fields=['approved_by_source', 'status', 'updated_at'])
    elif side == 'dest':
        if transfer.status not in (
            InterEntityTransfer.STATUS_APPROVED,
            InterEntityTransfer.STATUS_IN_TRANSIT,
        ):
            raise ValidationError('Transfer must be approved or in transit for destination approval.')
        transfer.approved_by_dest = user
        transfer.save(update_fields=['approved_by_dest', 'updated_at'])
    else:
        raise ValidationError('side must be source or dest')


@transaction.atomic
def issue_transfer(transfer: InterEntityTransfer, user):
    if transfer.status != InterEntityTransfer.STATUS_APPROVED:
        raise ValidationError('Transfer must be approved before issue.')
    if transfer.source_entity_id == transfer.destination_entity_id:
        raise ValidationError('Source and destination entities must differ.')

    total_value = Decimal('0')
    for line in transfer.lines.select_for_update().select_related('item'):
        unit_price = _transfer_unit_price(line, transfer)
        line.unit_price = unit_price
        line.save(update_fields=['unit_price'])

        stock = Stock.objects.filter(
            item=line.item, warehouse=transfer.source_warehouse
        ).first()
        if not stock or stock.quantity < line.quantity:
            avail = stock.quantity if stock else Decimal('0')
            raise ValidationError(
                f'Insufficient stock for {line.item.name}. Available: {avail}'
            )

        movement = StockMovement.objects.create(
            item=line.item,
            warehouse=transfer.source_warehouse,
            movement_type='out',
            source='manual',
            quantity=line.quantity,
            unit_cost=unit_price,
            reference=f'Inter-entity transfer {transfer.transfer_number}',
            notes=f'To {transfer.destination_entity.name}',
            movement_date=transfer.transfer_date,
            created_by=user,
        )
        movement.execute(user=user, allow_zero_cost=unit_price <= 0)
        line.source_movement = movement
        line.save(update_fields=['source_movement'])
        total_value += line.line_total

    journal = _post_source_interco_gl(transfer, total_value, user)
    transfer.source_journal = journal
    transfer.status = InterEntityTransfer.STATUS_IN_TRANSIT
    transfer.issued_at = timezone.now()
    transfer.save(update_fields=['source_journal', 'status', 'issued_at', 'updated_at'])
    return transfer


@transaction.atomic
def receive_transfer(transfer: InterEntityTransfer, user):
    if transfer.status != InterEntityTransfer.STATUS_IN_TRANSIT:
        raise ValidationError('Transfer must be in transit to receive.')

    total_value = Decimal('0')
    for line in transfer.lines.select_for_update().select_related('item'):
        unit_price = line.unit_price
        movement = StockMovement.objects.create(
            item=line.item,
            warehouse=transfer.destination_warehouse,
            movement_type='in',
            source='manual',
            quantity=line.quantity,
            unit_cost=unit_price,
            reference=f'Inter-entity receipt {transfer.transfer_number}',
            notes=f'From {transfer.source_entity.name}',
            movement_date=date.today(),
            created_by=user,
        )
        movement.execute(user=user, allow_zero_cost=unit_price <= 0)
        line.destination_movement = movement
        line.save(update_fields=['destination_movement'])
        total_value += line.line_total

    journal = _post_destination_interco_gl(transfer, total_value, user)
    transfer.destination_journal = journal
    transfer.status = InterEntityTransfer.STATUS_RECEIVED
    transfer.received_at = timezone.now()
    transfer.save(update_fields=['destination_journal', 'status', 'received_at', 'updated_at'])
    return transfer


def _post_source_interco_gl(transfer: InterEntityTransfer, total: Decimal, user):
    inventory = AccountMapping.get_account_or_default('inventory_asset', '1500')
    interco_recv = _interco_account(transfer.source_entity, 'receivable')
    if not inventory or not interco_recv:
        raise ValidationError('Configure inventory asset and intercompany receivable accounts.')

    journal = JournalEntry.objects.create(
        date=transfer.transfer_date,
        reference=transfer.transfer_number,
        description=f'Inter-entity issue {transfer.transfer_number}',
        entry_type='standard',
        source_module='inventory',
        created_by=user,
    )
    JournalEntryLine.objects.create(
        journal_entry=journal, account=interco_recv,
        description='Intercompany receivable', debit=total, credit=Decimal('0'),
    )
    JournalEntryLine.objects.create(
        journal_entry=journal, account=inventory,
        description='Inventory credit', debit=Decimal('0'), credit=total,
    )
    journal.calculate_totals()
    journal.post(user)
    return journal


def _post_destination_interco_gl(transfer: InterEntityTransfer, total: Decimal, user):
    inventory = AccountMapping.get_account_or_default('inventory_asset', '1500')
    interco_pay = _interco_account(transfer.destination_entity, 'payable')
    if not inventory or not interco_pay:
        raise ValidationError('Configure inventory asset and intercompany payable accounts.')

    journal = JournalEntry.objects.create(
        date=date.today(),
        reference=f'{transfer.transfer_number}-RCV',
        description=f'Inter-entity receipt {transfer.transfer_number}',
        entry_type='standard',
        source_module='inventory',
        created_by=user,
    )
    JournalEntryLine.objects.create(
        journal_entry=journal, account=inventory,
        description='Inventory debit', debit=total, credit=Decimal('0'),
    )
    JournalEntryLine.objects.create(
        journal_entry=journal, account=interco_pay,
        description='Intercompany payable', debit=Decimal('0'), credit=total,
    )
    journal.calculate_totals()
    journal.post(user)
    return journal


def _interco_account(entity, kind: str) -> Account | None:
    if kind == 'receivable' and entity.intercompany_receivable_account_id:
        return entity.intercompany_receivable_account
    if kind == 'payable' and entity.intercompany_payable_account_id:
        return entity.intercompany_payable_account
    code = '1350' if kind == 'receivable' else '2350'
    return AccountMapping.get_account_or_default(
        f'intercompany_{kind}', code
    )


def reconciliation_report():
    """Placeholder reconciliation — extend with GL balance queries per entity."""
    from apps.settings_app.models import Company

    rows = []
    for entity in Company.objects.filter(is_active=True):
        rows.append({
            'entity': entity.name,
            'intercompany_receivable': entity.intercompany_receivable_account_id,
            'intercompany_payable': entity.intercompany_payable_account_id,
            'net': 'Configure interco accounts per entity',
        })
    return rows
