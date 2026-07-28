import datetime
import logging
from odoo import fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class BankbookXlsx(models.AbstractModel):
    _name = 'report.accounting_community.report_bankbook_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    HEADERS = [
        "Cuenta Bancaria", "Fecha Documento", "Tipo Transaccion",
        "Numero de Doc", "Datos", "Destinatario",
        "Ingreso M/N", "Egreso M/N", "Saldo M/N",
        "Ingreso M/E", "Egreso M/E", "Saldo M/E",
    ]

    # -------------------------------------------------------------------------
    # Entry point
    # -------------------------------------------------------------------------

    def generate_xlsx_report(self, workbook, data, records):
        date_from = self._parse_date(data['start_date'])
        date_to = self._parse_date(data['end_date'])
        account = self.env['account.account'].browse(data['account_id'])

        sheet = workbook.add_worksheet('Libreta Bancaria')
        self._apply_styles(workbook, sheet, date_from, date_to)

        row = 7
        row = self._write_headers(sheet, row)

        lines = self._fetch_movements(account.id, date_from, date_to)
        if not lines:
            raise ValidationError('No hay datos que mostrar para el rango de fechas seleccionado.')

        self._write_body(sheet, row, lines, date_from, account.id)

    # -------------------------------------------------------------------------
    # Sheet setup
    # -------------------------------------------------------------------------

    def _apply_styles(self, workbook, sheet, date_from, date_to):
        head_fmt = workbook.add_format({'font_size': 20, 'align': 'center', 'bold': True})
        label_fmt = workbook.add_format({'font_size': 12, 'bold': True})
        date_fmt = workbook.add_format({'font_size': 10})
        border_fmt = workbook.add_format({'border': 1})

        sheet.set_column('A:L', 21, border_fmt)
        sheet.set_row(2, 50)
        sheet.merge_range('A2:L3', 'Reporte de Movimientos de Cuentas', head_fmt)
        sheet.write('B6', 'From:', label_fmt)
        sheet.merge_range('C6:D6', str(date_from), date_fmt)
        sheet.write('F6', 'To:', label_fmt)
        sheet.merge_range('G6:H6', str(date_to), date_fmt)

    # -------------------------------------------------------------------------
    # Header row
    # -------------------------------------------------------------------------

    def _write_headers(self, sheet, row):
        for col, header in enumerate(self.HEADERS):
            sheet.write(row, col, header)
        return row + 1

    # -------------------------------------------------------------------------
    # Body rows
    # -------------------------------------------------------------------------

    def _write_body(self, sheet, row, lines, date_from, account_id):
        USD, BOB, company, rate_date = self._get_currencies()

        balance_mn = self._get_opening_balance(account_id, date_from)
        balance_me = BOB._convert(balance_mn, USD, company, rate_date)

        sheet.write(row, 5, "Saldo Anterior")
        sheet.write(row, 8, balance_mn)
        sheet.write(row, 11, balance_me)
        row += 1

        for line in lines:
            debit = line.debit
            credit = line.credit
            balance_mn = balance_mn + debit - credit

            debit_me = BOB._convert(debit, USD, company, rate_date)
            credit_me = BOB._convert(credit, USD, company, rate_date)
            balance_me = BOB._convert(balance_mn, USD, company, rate_date)

            row_data = [
                line.account_id.name,
                str(line.date) if line.date else '',
                line.move_id.move_type,
                line.move_name or '',
                line.name or '',
                line.partner_id.name or '',
                debit,
                credit,
            ]
            sheet.write_row(row, 0, row_data)
            sheet.write(row, 8, balance_mn)
            sheet.write(row, 9, debit_me)
            sheet.write(row, 10, credit_me)
            sheet.write(row, 11, balance_me)
            row += 1

        sheet.write(row, 5, "Saldo a Fecha MN")
        sheet.write(row, 8, balance_mn)
        sheet.write(row, 10, "Saldo a Fecha ME")
        sheet.write(row, 11, balance_me)

    # -------------------------------------------------------------------------
    # ORM queries
    # -------------------------------------------------------------------------

    def _fetch_movements(self, account_id, date_from, date_to):
        return self.env['account.move.line'].search([
            ('account_id', '=', account_id),
            ('account_id.account_type', '=', 'asset_cash'),
            ('parent_state', '=', 'posted'),
            '|', ('debit', '!=', 0), ('credit', '!=', 0),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ], order='date asc, id asc')

    def _get_opening_balance(self, account_id, date_from):
        """Suma acumulada de débitos menos créditos anteriores a date_from."""
        groups = self.env['account.move.line'].read_group(
            domain=[
                ('account_id', '=', account_id),
                ('account_id.account_type', '=', 'asset_cash'),
                ('parent_state', '=', 'posted'),
                ('date', '<', date_from),
            ],
            fields=['debit:sum', 'credit:sum'],
            groupby=[],
        )
        if groups:
            return (groups[0].get('debit') or 0.0) - (groups[0].get('credit') or 0.0)
        return 0.0

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_date(self, value):
        if isinstance(value, datetime.date):
            return value
        return datetime.datetime.strptime(value, '%Y-%m-%d').date()

    def _get_currencies(self):
        USD = self.env['res.currency'].search([('name', '=', 'USD')], limit=1)
        BOB = self.env['res.currency'].search([('name', '=', 'BOB')], limit=1)
        rate_date = self._context.get('date') or fields.Date.today()
        company = (
            self.env['res.company'].browse(self._context.get('company_id'))
            if self._context.get('company_id')
            else self.env.company
        )
        return USD, BOB, company, rate_date
