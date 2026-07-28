import logging

from odoo import models

_logger = logging.getLogger(__name__)

_USD_RATE = 6.96


class PurchaseIvaXlsx(models.AbstractModel):
    _name = 'report.accounting_community.report_purchase_iva_xlsx'
    _inherit = 'report.report_xlsx.abstract'
    _description = 'Libro de Compras IVA (Community)'

    # ------------------------------------------------------------------
    # Clasificación de líneas de factura
    # ------------------------------------------------------------------

    def _line_has_tax_named(self, tax_ids, needle):
        return any(tax.name and needle in tax.name for tax in tax_ids)

    def _has_gross(self, tax_ids):
        return self._line_has_tax_named(tax_ids, 'Gross')

    def _has_dim_tax(self, tax_ids):
        return self._line_has_tax_named(tax_ids, 'DIM') or self._line_has_tax_named(tax_ids, 'DUI')

    def _is_valid_purchase_bill(self, bill):
        """Determina si una factura de compra debe entrar al libro de IVA.

        No depende de campos custom booleanos: se basa directamente en si
        las líneas tienen impuestos y en los identificadores de SIAT/DUI.
        """
        if not bill.invoice_line_ids.tax_ids:
            return False

        tiene_cuf = bool(getattr(bill, 'siat_cuf', '') or '')
        tiene_dui = len(str(getattr(bill, 'dui', '') or '')) > 1

        if not (tiene_cuf or tiene_dui):
            return False

        numero_factura = getattr(bill, 'siat_numero_factura', 0) or 0
        if str(numero_factura) == '0' and not tiene_dui:
            return False

        if self._has_gross(bill.invoice_line_ids.tax_ids):
            return False

        return True

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

        sheet = workbook.add_worksheet('Libro Compras IVA')
        sheet.set_column('A:Y', 25)

        start_date = data['start_date']
        end_date = data['end_date']

        rows = {}
        rows.update(self._collect_bill_rows(start_date, end_date))
        rows.update(self._collect_expense_rows(start_date, end_date, offset=len(rows)))

        sorted_rows = dict(sorted(rows.items(), key=lambda item: item[1]['invoice_date']))
        self._write_sheet(sheet, sorted_rows, title_fmt, sub_fmt, head_fmt, cell_fmt)

    # ------------------------------------------------------------------
    # Facturas de compra (account.move)
    # ------------------------------------------------------------------

    def _collect_bill_rows(self, start_date, end_date):
        bills = self.env['account.move'].search([
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('journal_id.type', '=', 'purchase'),
            ('state', '=', 'posted'),
        ])

        rows = {}
        for index, bill in enumerate(bills):
            po = self.env['purchase.order'].search([('name', '=', bill.invoice_origin)], limit=1)
            porder_type = getattr(po, 'requested_type_ncr', 'local') or 'local'

            if 'local' not in porder_type and 'interna' not in porder_type:
                continue
            if not self._is_valid_purchase_bill(bill):
                continue

            rows[index] = self._row_from_bill(bill)
        return rows

    def _row_from_bill(self, bill):
        ice = 0.0
        gas = 0.0
        tasas = 0.0
        v_tasas_scf = 0.0
        descuento = 0.0
        pasaje = 0.0

        factura_dim = False
        factura_gasto = False
        factura_pasaje = False
        factura_tasa_0 = False
        tasa_scf = False
        dim_importe_total_compra = 0.0

        for line in bill.invoice_line_ids:
            name = line.product_id.name
            if not name:
                continue
            if name.find('TASAS AFCOOP DS 2762 S/C.FISCAL') == 0:
                tasa_scf = True
                v_tasas_scf += line.price_total
            elif name.find('TASA') == 0:
                tasas += line.price_total
            elif name.find('ICE') == 0 or name.find('ICE - REPRESENTACION Y CORTESIA') == 0:
                ice += line.price_total
            elif name.find('GASTOS BANCARIOS SIN/CF') == 0:
                factura_gasto = True
            elif name.find('PASAJES AEREOS S/CF (Ex.)') == 0:
                factura_pasaje = True
                pasaje += line.price_total
            elif name.find('GI. FLETE TERRESTE/TASA 0') == 0:
                factura_tasa_0 = True
            elif name.find('GASOLINA SIN CF') == 0:
                gas += line.price_total * 0.30
            elif name.find('GI. DIM') == 0 and self._has_dim_tax(line.tax_ids):
                factura_dim = True
                dim_importe_total_compra = line.price_total / 0.13
            elif name.find('DESCUENTO') == 0:
                descuento = round(descuento + abs(line.price_total), 2)

        if factura_dim:
            amount_total = dim_importe_total_compra
        else:
            amount_total = bill.amount_total + descuento

        if factura_gasto:
            no_credit = bill.amount_total + descuento
        elif tasa_scf:
            no_credit = v_tasas_scf
        elif factura_pasaje:
            no_credit = pasaje
        else:
            no_credit = gas

        tasa_cero = amount_total if factura_tasa_0 else 0.0

        base_amount = dim_importe_total_compra if factura_dim else amount_total
        if factura_gasto:
            price_subtotal = 0.0
        else:
            price_subtotal = base_amount - ice - tasas - no_credit - tasa_cero

        bon_al_iva = descuento
        if factura_gasto:
            base_cf = 0.0
        else:
            base_cf = price_subtotal - bon_al_iva

        partner = bill.partner_id

        return {
            'partner_id': partner.vat or ' ',
            'partner': partner.name or '',
            'auth_number': getattr(bill, 'siat_cuf', '') or '',
            'bill_number': getattr(bill, 'siat_numero_factura', 0) or 0,
            'dui': getattr(bill, 'dui', 0) or 0,
            'control_code': '',
            'invoice_date': bill.invoice_date.strftime('%d/%m/%Y') if bill.invoice_date else '',
            'amount_total': amount_total,
            'amount_ICE': ice,
            'tasas': tasas,
            'no_credit': no_credit,
            'tasa_cero': tasa_cero,
            'price_subtotal': price_subtotal,
            'bon_al_iva': bon_al_iva,
            'base_cf': base_cf,
            'credit': bill.amount_tax,
            'currency': bill.currency_id.name,
            'name': bill.name or '',
            'unique_code': getattr(bill, 'unique_code', '') or '',
        }

    # ------------------------------------------------------------------
    # Gastos (hr.expense) — sólo si el modelo tiene los campos de control
    # ------------------------------------------------------------------

    def _expense_model_supports_iva_fields(self):
        expense_fields = self.env['hr.expense']._fields
        required = {'control_code', 'authorization_code', 'rate', 'discount'}
        return required.issubset(expense_fields.keys())

    def _collect_expense_rows(self, start_date, end_date, offset):
        if not self._expense_model_supports_iva_fields():
            _logger.info(
                "hr.expense no tiene los campos de control de IVA Bolivia "
                "(control_code/authorization_code/rate/discount); se omite la sección de gastos."
            )
            return {}

        expenses = self.env['hr.expense'].search([
            ('accounting_date', '>=', start_date),
            ('accounting_date', '<=', end_date),
            ('state', 'in', ['done', 'approved']),
        ])

        rows = {}
        for index, expense in enumerate(expenses):
            if not (expense.control_code or expense.authorization_code):
                continue
            rows[offset + index] = self._row_from_expense(expense)
        return rows

    def _row_from_expense(self, expense):
        product_name = expense.product_id.name or ''
        total_amount = round(expense.total_amount, 2)

        control_tasa = self._line_has_tax_named(expense.tax_ids, 'Tasas')
        factura_gasto = 'SIN/CF' in product_name

        tasas = abs(expense.rate)
        no_credit = total_amount * 0.3 if 'COMBUSTIBLES Y LUBRICANTES' in product_name else 0.0
        tasa_cero = total_amount if 'IMP. FLETE TERRESTE (TASA 0)' in product_name else 0.0

        if control_tasa:
            price_subtotal = 0.0
        else:
            price_subtotal = total_amount - no_credit - tasa_cero

        bon_al_iva = expense.discount or 0.0

        if control_tasa:
            base_cf = 0.0
            credit = 0.0
        else:
            base_cf = price_subtotal - bon_al_iva
            credit = base_cf * 0.13

        if factura_gasto:
            no_credit = total_amount
            price_subtotal = 0.0
            base_cf = 0.0
            credit = 0.0

        expense_sheet = expense.sheet_id if expense.sheet_id else None
        expense_move = None
        if expense_sheet:
            moves = getattr(expense_sheet, 'account_move_ids', None) or getattr(expense_sheet, 'account_move_id', None)
            if moves:
                expense_move = moves[0] if len(moves) else moves

        partner = expense.partner_id

        return {
            'partner_id': partner.vat or ' ',
            'partner': partner.name or 'NONE',
            'auth_number': getattr(expense_move, 'siat_cuf', '') or '' if expense_move else '',
            'bill_number': expense.invoice_number or 0,
            'dui': 0,
            'control_code': '',
            'invoice_date': expense.date.strftime('%d/%m/%Y') if expense.date else '',
            'amount_total': total_amount + tasas,
            'amount_ICE': 0.0,
            'tasas': tasas,
            'no_credit': no_credit,
            'tasa_cero': tasa_cero,
            'price_subtotal': price_subtotal,
            'bon_al_iva': bon_al_iva,
            'base_cf': base_cf,
            'credit': credit,
            'currency': expense.currency_id.name,
            'name': getattr(expense_move, 'name', '') or '' if expense_move else '',
            'unique_code': getattr(expense_move, 'unique_code', '') or '' if expense_move else '',
        }

    # ------------------------------------------------------------------
    # Escritura del Excel
    # ------------------------------------------------------------------

    def _write_sheet(self, sheet, rows, title_fmt, sub_fmt, head_fmt, cell_fmt):
        sheet.merge_range('B2:I3', 'LIBRO DE COMPRAS', title_fmt)
        sheet.merge_range('B4:C4', '(Expresado en Bolivianos)', sub_fmt)

        headers = [
            'N°', 'Especificación', 'NIT Proveedor', 'Razon Social Proveedor',
            'Código de Autorización', 'Número de Factura', 'Numero DUI/DIM', 'Fecha de Factura',
            'Importe Total Compra', 'Importe ICE', 'Importe IEHD', 'Importe IPJ', 'Tasas',
            'Otro NO Sujeto a credito Fiscal', 'Importes Excentos',
            'Importe Compras Grabadas a Tasa Cero', 'Subtotal',
            'Descuentos Bonificaciones Rebajas Sujetas al IVA', 'Importe GIFT CARD',
            'Importe Base CF', 'Credito Fiscal', 'Tipo Compra', 'Código de Control',
            'Nro Asiento Contable', 'Correlativo',
        ]
        for col, h in enumerate(headers):
            sheet.write(6, col, h, head_fmt)

        row_index = 7
        seq = 1
        for _, row in rows.items():
            if row['dui'] == 0 and row['bill_number'] == 0:
                continue

            factor = _USD_RATE if row['currency'] == 'USD' else 1

            sheet.write(row_index, 0, seq, cell_fmt)
            sheet.write(row_index, 1, 1, cell_fmt)
            sheet.write(row_index, 2, row['partner_id'], cell_fmt)
            sheet.write(row_index, 3, row['partner'], cell_fmt)
            sheet.write(row_index, 4, row['auth_number'], cell_fmt)
            sheet.write(row_index, 5, row['bill_number'], cell_fmt)
            sheet.write(row_index, 6, row['dui'], cell_fmt)
            sheet.write(row_index, 7, row['invoice_date'], cell_fmt)
            sheet.write(row_index, 8, round(float(row['amount_total']) * factor, 2), cell_fmt)
            sheet.write(row_index, 9, round(float(row['amount_ICE']) * factor, 2), cell_fmt)
            sheet.write(row_index, 10, '0,00', cell_fmt)
            sheet.write(row_index, 11, '0,00', cell_fmt)
            sheet.write(row_index, 12, round(float(row['tasas']) * factor, 2), cell_fmt)
            sheet.write(row_index, 13, round(float(row['no_credit']) * factor, 2), cell_fmt)
            sheet.write(row_index, 14, '0,00', cell_fmt)
            sheet.write(row_index, 15, round(float(row['tasa_cero']) * factor, 2), cell_fmt)
            sheet.write(row_index, 16, round(float(row['price_subtotal']) * factor, 2), cell_fmt)
            # NB: se mantiene el mismo orden de operaciones que el reporte original
            # (redondear antes de aplicar el factor de cambio), para no alterar los
            # totales ya conocidos por contabilidad en facturas de compra en USD.
            sheet.write(row_index, 17, round(float(row['bon_al_iva']), 2) * factor, cell_fmt)
            sheet.write(row_index, 18, '0,00', cell_fmt)
            sheet.write(row_index, 19, round(float(row['base_cf']) * factor, 2), cell_fmt)
            sheet.write(row_index, 20, round(float(row['credit']) * factor, 2), cell_fmt)
            sheet.write(row_index, 21, '1,00', cell_fmt)
            sheet.write(row_index, 22, str(row['control_code']), cell_fmt)
            sheet.write(row_index, 23, row['name'], cell_fmt)
            sheet.write(row_index, 24, row['unique_code'], cell_fmt)

            row_index += 1
            seq += 1
