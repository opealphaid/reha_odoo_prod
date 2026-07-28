from datetime import datetime
from odoo import models

_USD_RATE = 6.96


class SalesBankingXlsx(models.AbstractModel):
    _name = 'report.accounting_community.report_sales_banking_xlsx'
    _inherit = 'report.report_xlsx.abstract'

    # ------------------------------------------------------------------
    # Conversión y formato
    # ------------------------------------------------------------------

    def _to_bob(self, amount, currency_name):
        if not amount:
            return 0.0
        return amount * _USD_RATE if currency_name == 'USD' else float(amount)

    def _fmt_date(self, d):
        try:
            return d.strftime('%d/%m/%Y') if d else ''
        except Exception:
            return ''

    # ------------------------------------------------------------------
    # Punto de entrada del reporte
    # ------------------------------------------------------------------

    def generate_xlsx_report(self, workbook, data, records):
        sheet = workbook.add_worksheet('Bancarización Ventas')
        start_date = data['start_date']
        end_date = data['end_date']

        included_pay_ids = set()
        rows = {}
        idx = 0

        # ----------------------------------------------------------------
        # PASO 1: Pagos con facturas de venta conciliadas
        # ----------------------------------------------------------------
        self._cr.execute('''
            SELECT
                pay.id  AS pay_id,
                inv.id  AS inv_id
            FROM account_payment         pay
            JOIN account_move            pm   ON pm.id  = pay.move_id
            JOIN account_move_line       ml   ON ml.move_id = pm.id
            JOIN account_partial_reconcile pr
                 ON pr.debit_move_id = ml.id OR pr.credit_move_id = ml.id
            JOIN account_move_line       cl   ON cl.id = CASE
                                                           WHEN pr.debit_move_id  = ml.id THEN pr.credit_move_id
                                                           ELSE pr.debit_move_id
                                                         END
            JOIN account_move            inv  ON inv.id = cl.move_id
            JOIN account_account         aa   ON aa.id  = ml.account_id
            WHERE aa.account_type IN ('asset_receivable', 'liability_payable')
              AND ml.id != cl.id
              AND inv.move_type IN ('out_invoice', 'out_refund', 'out_receipt')
              AND pay.banking_date BETWEEN %s AND %s
              AND pay.banking_required = TRUE
            GROUP BY pay.id, inv.id
            ORDER BY pay.banking_date, inv.id
        ''', (start_date, end_date))

        for res in self._cr.dictfetchall():
            pay = self.env['account.payment'].browse(res['pay_id'])
            inv = self.env['account.move'].browse(res['inv_id'])
            if pay.id in included_pay_ids:
                continue

            rows[idx] = self._sale_row_from_invoice(pay, inv)
            idx += 1
            included_pay_ids.add(pay.id)

        # ----------------------------------------------------------------
        # PASO 2: Pagos conciliados solo con asientos (entry), sin facturas de venta
        # ----------------------------------------------------------------
        self._cr.execute('''
            SELECT
                p.id        AS pay_id,
                MIN(inv.id) AS entry_id
            FROM account_payment         p
            JOIN account_move            pm  ON pm.id = p.move_id
            JOIN account_move_line       ml  ON ml.move_id = pm.id
            JOIN account_partial_reconcile pr
                 ON pr.debit_move_id = ml.id OR pr.credit_move_id = ml.id
            JOIN account_move_line       cl  ON cl.id IN (pr.debit_move_id, pr.credit_move_id)
                                            AND cl.id <> ml.id
            JOIN account_move            inv ON inv.id = cl.move_id
            JOIN account_account         aa  ON aa.id  = ml.account_id
            WHERE aa.account_type IN ('asset_receivable', 'liability_payable')
              AND p.banking_date BETWEEN %s AND %s
              AND p.banking_required = TRUE
            GROUP BY p.id
            HAVING SUM(CASE WHEN inv.move_type IN ('out_invoice','out_refund','out_receipt') THEN 1 ELSE 0 END) = 0
               AND SUM(CASE WHEN inv.move_type = 'entry' THEN 1 ELSE 0 END) > 0
            ORDER BY MIN(p.banking_date)
        ''', (start_date, end_date))

        for res in self._cr.dictfetchall():
            pay = self.env['account.payment'].browse(res['pay_id'])
            if pay.id in included_pay_ids:
                continue

            entry = self.env['account.move'].browse(res['entry_id']) if res.get('entry_id') else False
            invoice_date = (
                self._fmt_date(entry.date) if entry and entry.date
                else self._fmt_date(pay.banking_date)
            )
            rows[idx] = self._sale_row_no_invoice(pay, invoice_date)
            idx += 1
            included_pay_ids.add(pay.id)

        # ----------------------------------------------------------------
        # PASO 3: Pagos customer sin conciliaciones → match por name con entry
        # ----------------------------------------------------------------
        self._cr.execute('''
            SELECT p.id AS pay_id
            FROM account_payment p
            JOIN account_move    m ON m.id = p.move_id
            WHERE p.banking_required = TRUE
              AND p.partner_type = 'customer'
              AND p.banking_date BETWEEN %s AND %s
              AND NOT EXISTS (
                    SELECT 1
                    FROM account_move_line       l
                    JOIN account_account         a  ON a.id = l.account_id
                    JOIN account_partial_reconcile pr
                         ON pr.debit_move_id = l.id OR pr.credit_move_id = l.id
                    WHERE l.move_id = m.id
                      AND a.account_type IN ('asset_receivable', 'liability_payable')
              )
        ''', (start_date, end_date))

        for res in self._cr.dictfetchall():
            pay = self.env['account.payment'].browse(res['pay_id'])
            if pay.id in included_pay_ids:
                continue

            move_name = (pay.move_id.name or '').strip()
            if not move_name:
                continue

            entry = self.env['account.move'].search(
                [('move_type', '=', 'entry'), ('name', '=', move_name)], limit=1
            )
            if not entry:
                continue

            invoice_date = self._fmt_date(entry.date) or self._fmt_date(pay.banking_date)
            rows[idx] = self._sale_row_no_invoice(pay, invoice_date)
            idx += 1
            included_pay_ids.add(pay.id)

        # ----------------------------------------------------------------
        # Ordenar y escribir Excel
        # ----------------------------------------------------------------
        def _parse(s):
            try:
                return datetime.strptime(s or '01/01/0001', '%d/%m/%Y')
            except Exception:
                return datetime.min

        sorted_rows = sorted(rows.items(), key=lambda x: _parse(x[1].get('invoice_date')))
        self._write_sheet(workbook, sheet, sorted_rows)

    # ------------------------------------------------------------------
    # Construcción de filas
    # ------------------------------------------------------------------

    def _sale_row_from_invoice(self, pay, inv):
        amount_total = self._to_bob(inv.amount_total, inv.currency_id.name)
        amount_payment = self._to_bob(pay.amount, pay.currency_id.name)
        return {
            'invoice_date':     self._fmt_date(inv.invoice_date),
            'client_vat':       inv.partner_id.vat or '',
            'client_name':      inv.partner_id.name or '',
            'invoice_number':   getattr(inv, 'l10n_bo_invoice_number', '') or '',
            'auth_code':        getattr(inv, 'auth_number', '') or getattr(inv, 'l10n_bo_cuf', '') or '',
            'payment_ref':      pay.banking_transaction_ref or '',
            'payment_date':     self._fmt_date(pay.banking_date),
            'amount_total':     amount_total,
            'amount_payment':   amount_payment,
            'account_num':      self._journal_account_number(pay),
            'bank_vat':         self._journal_bank_vat(pay),
            'payment_method':   self._payment_method_code(pay),
            'sale_type':        pay.banking_sale_type or '',
            'payment_form':     pay.banking_payment_form or '',
            'nit_complement':   pay.banking_nit_complement or '',
            'support_doc_type': pay.banking_support_doc_type or '',
            'support_doc_num':  pay.banking_support_doc_number or '',
            'contract_number':  pay.banking_contract_number or '',
        }

    def _sale_row_no_invoice(self, pay, invoice_date):
        amount_payment = self._to_bob(pay.amount, pay.currency_id.name)
        return {
            'invoice_date':     invoice_date,
            'client_vat':       pay.partner_id.vat or '',
            'client_name':      pay.partner_id.name or '',
            'invoice_number':   '',
            'auth_code':        '',
            'payment_ref':      pay.banking_transaction_ref or '',
            'payment_date':     self._fmt_date(pay.banking_date),
            'amount_total':     0.0,
            'amount_payment':   amount_payment,
            'account_num':      self._journal_account_number(pay),
            'bank_vat':         self._journal_bank_vat(pay),
            'payment_method':   self._payment_method_code(pay),
            'sale_type':        pay.banking_sale_type or '',
            'payment_form':     pay.banking_payment_form or '',
            'nit_complement':   pay.banking_nit_complement or '',
            'support_doc_type': pay.banking_support_doc_type or '',
            'support_doc_num':  pay.banking_support_doc_number or '',
            'contract_number':  pay.banking_contract_number or '',
        }

    # ------------------------------------------------------------------
    # Helpers de relaciones
    # ------------------------------------------------------------------

    def _journal_account_number(self, pay):
        bk = pay.move_id.journal_id.bank_account_id
        return bk.acc_number or '' if bk else ''

    def _journal_bank_vat(self, pay):
        bk = pay.move_id.journal_id.bank_account_id
        return (bk.bank_id.vat or '') if (bk and bk.bank_id) else ''

    def _payment_method_code(self, pay):
        return (pay.payment_method_id.banking_code or '') if pay.payment_method_id else ''

    # ------------------------------------------------------------------
    # Escritura del Excel
    # ------------------------------------------------------------------

    def _write_sheet(self, workbook, sheet, sorted_rows):
        title_fmt = workbook.add_format({
            'align': 'left', 'bold': True, 'font_size': 16, 'font_color': 'blue',
        })
        sub_fmt = workbook.add_format({'font_size': 10})
        head_fmt = workbook.add_format({
            'align': 'center', 'bold': True, 'font_size': 12,
            'font_color': 'white', 'bg_color': '#003399', 'border': 1,
        })
        cell_fmt = workbook.add_format({'font_size': 10, 'border': 1})

        sheet.set_column('A:S', 25)
        sheet.merge_range('A1:S2', 'Reporte de Bancarización – Ventas', title_fmt)
        sheet.merge_range('A3:B3', '(Expresado en Bolivianos)', sub_fmt)

        headers = [
            'N°',
            'TIPO DE TRANSACCIÓN',
            'FORMA DE PAGO',
            'NIT/CI',
            'COMPLEMENTO',
            'NOMBRE O RAZÓN SOCIAL',
            'CÓDIGO DE AUTORIZACIÓN',
            'NÚMERO DE FACTURA',
            'TIPO DOC. RESPALDO',
            'NÚMERO DOC. RESPALDO',
            'FECHA FACTURA / DOC. RESPALDO',
            'MONTO FACTURADO (BS)',
            'N° CONTRATO O ACUERDO',
            'TIPO DOC. DE PAGO',
            'FECHA DOC. DE PAGO',
            'N° CUENTA (ABONO)',
            'NIT ENTIDAD FINANCIERA (ABONO)',
            'N° TRANSACCIÓN / OPERACIÓN',
            'MONTO PERCIBIDO (BS)',
        ]
        for col, h in enumerate(headers):
            sheet.write(3, col, h, head_fmt)

        for seq, (_, row) in enumerate(sorted_rows):
            r = seq + 4
            sheet.write(r, 0,  seq + 1,                         cell_fmt)
            sheet.write(r, 1,  row.get('sale_type', ''),         cell_fmt)
            sheet.write(r, 2,  row.get('payment_form', ''),      cell_fmt)
            sheet.write(r, 3,  row.get('client_vat', ''),        cell_fmt)
            sheet.write(r, 4,  row.get('nit_complement', ''),    cell_fmt)
            sheet.write(r, 5,  row.get('client_name', ''),       cell_fmt)
            sheet.write(r, 6,  row.get('auth_code', ''),         cell_fmt)
            sheet.write(r, 7,  row.get('invoice_number', ''),    cell_fmt)
            sheet.write(r, 8,  row.get('support_doc_type', ''),  cell_fmt)
            sheet.write(r, 9,  row.get('support_doc_num', ''),   cell_fmt)
            sheet.write(r, 10, row.get('invoice_date', ''),      cell_fmt)
            sheet.write(r, 11, row.get('amount_total', 0.0),     cell_fmt)
            sheet.write(r, 12, row.get('contract_number', ''),   cell_fmt)
            sheet.write(r, 13, row.get('payment_method', ''),    cell_fmt)
            sheet.write(r, 14, row.get('payment_date', ''),      cell_fmt)
            sheet.write(r, 15, row.get('account_num', ''),       cell_fmt)
            sheet.write(r, 16, row.get('bank_vat', ''),          cell_fmt)
            sheet.write(r, 17, row.get('payment_ref', ''),       cell_fmt)
            sheet.write(r, 18, row.get('amount_payment', 0.0),   cell_fmt)
