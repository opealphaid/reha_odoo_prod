import logging

from odoo import models

_logger = logging.getLogger(__name__)

_USD_RATE = 6.96


class SalesIvaXlsx(models.AbstractModel):
    _name = 'report.accounting_community.report_sales_iva_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Libro de Ventas IVA (Community)'

    # ------------------------------------------------------------------
    # Punto de entrada del reporte
    # ------------------------------------------------------------------

    def generate_xlsx_report(self, workbook, data, records):
        title_fmt = workbook.add_format({'align': 'left', 'bold': True, 'font_size': 16, 'font_color': 'blue'})
        sub_fmt = workbook.add_format({'font_size': 10})
        head_fmt = workbook.add_format({
            'align': 'center', 'bold': True, 'font_size': 12,
            'font_color': 'white', 'bg_color': '#003399', 'border': 1,
        })
        cell_fmt = workbook.add_format({'font_size': 10, 'border': 1})

        sheet = workbook.add_worksheet('Libro Ventas IVA')
        sheet.set_column('A:Z', 25)

        rows = self._collect_rows(data['start_date'], data['end_date'])
        self._write_sheet(sheet, rows, title_fmt, sub_fmt, head_fmt, cell_fmt)

    # ------------------------------------------------------------------
    # Recolección de datos
    # ------------------------------------------------------------------

    def _collect_rows(self, start_date, end_date):
        invoices = self.env['account.move'].search([
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('journal_id.type', '=', 'sale'),
            ('state', '!=', 'draft'),
        ])
        invoices = invoices.filtered(lambda inv: inv.amount_total_signed > 0)

        rows = {}
        for index, inv in enumerate(invoices):
            rows[index] = self._row_from_invoice(inv)
        return rows

    def _row_from_invoice(self, inv):
        exchange = _USD_RATE if inv.currency_id.name == 'USD' else 1

        descuento = 0.0
        for line in inv.invoice_line_ids:
            name = line.product_id.name
            if name and name.find('DESCUENTO') == 0:
                descuento = round(descuento + (-1 * line.price_total), 2)

        amount_total = inv.amount_total_signed + round(descuento * exchange, 2)

        return {
            'invoice_date': inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else '',
            'invoice_number': getattr(inv, 'siat_numero_factura', '') or '',
            'auth_code': getattr(inv, 'siat_cuf', '') or '',
            'client_vat': inv.partner_id.vat or '',
            'client_name': inv.partner_id.name or '',
            'amount_total': amount_total,
            'base_debito_fiscal': inv.amount_total_signed,
            'debito_fiscal': round(float(inv.amount_tax_signed), 2),
            'state': 'A' if inv.payment_state == 'reversed' else 'V',
            'name': inv.name or '',
            'unique_code': getattr(inv, 'unique_code', '') or '',
        }

    # ------------------------------------------------------------------
    # Escritura del Excel
    # ------------------------------------------------------------------

    def _write_sheet(self, sheet, rows, title_fmt, sub_fmt, head_fmt, cell_fmt):
        sheet.merge_range('A1:D2', 'Registro de Ventas Estandar', title_fmt)
        sheet.merge_range('A3:B3', '(Expresado en Bolivianos)', sub_fmt)

        headers = [
            'N°', 'Especificación', 'Fecha de la Factura', 'N° de la Factura',
            'Código de Autorización', 'NIT/CI Cliente', 'Complemento', 'Nombre o Razón Social',
            'Importe Total de la Venta', 'Importe ICE', 'Importe IEHD', 'Importe IPJ', 'Tasas',
            'Otros No Sujetos al IVA', 'Exportaciones y Operaciones Exentas',
            'Ventas Gravadas a Tasa Cero', 'Subtotal',
            'Descuentos, Bonificaciones y Rebajas Sujetas al IVA', 'Importe Gift Card',
            'Importe Base para Débito Fiscal', 'Debito Fiscal', 'Estado', 'Código de Control',
            'Tipo de Venta', 'Nro Asiento Contable', 'Correlativo',
        ]
        for col, h in enumerate(headers):
            sheet.write(3, col, h, head_fmt)

        for seq, (_, row) in enumerate(rows.items()):
            r = seq + 4
            sheet.write(r, 0, seq + 1, cell_fmt)
            sheet.write(r, 1, '2', cell_fmt)
            sheet.write(r, 2, row['invoice_date'], cell_fmt)
            sheet.write(r, 3, row['invoice_number'], cell_fmt)
            sheet.write(r, 4, row['auth_code'], cell_fmt)
            sheet.write(r, 5, row['client_vat'], cell_fmt)
            sheet.write(r, 6, '', cell_fmt)
            sheet.write(r, 7, row['client_name'], cell_fmt)
            sheet.write(r, 8, row['amount_total'], cell_fmt)
            sheet.write(r, 9, '0.00', cell_fmt)
            sheet.write(r, 10, '0.00', cell_fmt)
            sheet.write(r, 11, '0.00', cell_fmt)
            sheet.write(r, 12, '0.00', cell_fmt)
            sheet.write(r, 13, '0.00', cell_fmt)
            sheet.write(r, 14, '0.00', cell_fmt)
            sheet.write(r, 15, '0.00', cell_fmt)
            sheet.write(r, 16, row['amount_total'], cell_fmt)
            sheet.write(r, 17, '0.00', cell_fmt)
            sheet.write(r, 18, '0.00', cell_fmt)
            sheet.write(r, 19, row['base_debito_fiscal'], cell_fmt)
            sheet.write(r, 20, row['debito_fiscal'], cell_fmt)
            sheet.write(r, 21, row['state'], cell_fmt)
            sheet.write(r, 22, '', cell_fmt)
            sheet.write(r, 23, '0', cell_fmt)
            sheet.write(r, 24, row['name'], cell_fmt)
            sheet.write(r, 25, row['unique_code'], cell_fmt)
