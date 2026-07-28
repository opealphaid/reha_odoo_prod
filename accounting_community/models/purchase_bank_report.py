from odoo import models

_USD_RATE = 6.96


class PurchaseBankingXlsx(models.AbstractModel):
    _name = 'report.accounting_community.report_purchase_banking_xlsx'
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
        sheet = workbook.add_worksheet('Bancarización Compras')
        start_date = data['start_date']
        end_date = data['end_date']

        included_pay_ids = set()
        rows = {}
        idx = 0

        # ----------------------------------------------------------------
        # PASO 1: Facturas de compra conciliadas con el pago
        #         Excluye líneas de producto cuyo nombre contiene "DIM"
        #         Calcula monto acumulado de pagos parciales por factura
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
              AND inv.move_type IN ('in_invoice', 'in_refund')
              AND pay.banking_date BETWEEN %s AND %s
              AND pay.banking_required = TRUE
              AND NOT EXISTS (
                    SELECT 1
                    FROM account_move_line  il
                    JOIN product_product    pp ON pp.id = il.product_id
                    JOIN product_template   pt ON pt.id = pp.product_tmpl_id
                    WHERE il.move_id = inv.id
                      AND pt.name::text ILIKE '%%DIM%%'
              )
            GROUP BY pay.id, inv.id
            ORDER BY pay.banking_date, inv.id
        ''', (start_date, end_date))

        prev_inv_id = 0
        previous_amount = 0.0

        for res in self._cr.dictfetchall():
            pay = self.env['account.payment'].browse(res['pay_id'])
            inv = self.env['account.move'].browse(res['inv_id'])

            included_pay_ids.add(pay.id)

            # Acumulado de pagos anteriores para la misma factura
            if inv.id != prev_inv_id:
                prev_inv_id = inv.id
                previous_amount = 0.0
                self._cr.execute('''
                    SELECT pay2.amount AS amount
                    FROM account_payment         pay2
                    JOIN account_move            pm2  ON pm2.id  = pay2.move_id
                    JOIN account_move_line       ml2  ON ml2.move_id = pm2.id
                    JOIN account_partial_reconcile pr2
                         ON pr2.debit_move_id = ml2.id OR pr2.credit_move_id = ml2.id
                    JOIN account_move_line       cl2  ON cl2.id = CASE
                                                                    WHEN pr2.debit_move_id  = ml2.id THEN pr2.credit_move_id
                                                                    ELSE pr2.debit_move_id
                                                                  END
                    JOIN account_move            inv2 ON inv2.id = cl2.move_id
                    WHERE inv2.id = %s
                      AND pay2.banking_date < %s
                ''', (inv.id, pay.banking_date))
                for prev in self._cr.dictfetchall():
                    previous_amount += prev['amount']

            amount_total = self._to_bob(inv.amount_total, inv.currency_id.name)
            amount_payment = self._to_bob(pay.amount, pay.currency_id.name)
            amount_payment_acum = self._to_bob(pay.amount + previous_amount, pay.currency_id.name)

            rows[idx] = self._purchase_row_from_invoice(pay, inv, amount_total, amount_payment, amount_payment_acum)
            idx += 1

        # ----------------------------------------------------------------
        # PASO 2: Pagos supplier con asientos (entry), sin facturas de compra
        # ----------------------------------------------------------------
        pay_ids_exclude = list(included_pay_ids)
        exclude_clause = 'AND p.id <> ALL(%s)' if pay_ids_exclude else ''
        params_step2 = [start_date, end_date]
        if pay_ids_exclude:
            params_step2.append(pay_ids_exclude)

        self._cr.execute(f'''
            SELECT
                p.id                                                    AS pay_id,
                MIN(CASE WHEN inv.move_type = 'entry' THEN inv.id END)  AS entry_id,
                SUM(CASE WHEN inv.move_type IN ('in_invoice','in_refund') THEN 1 ELSE 0 END) AS inv_count
            FROM account_payment         p
            JOIN account_move            pm  ON pm.id = p.move_id
            JOIN account_move_line       ml  ON ml.move_id = pm.id
            JOIN account_partial_reconcile pr
                 ON pr.debit_move_id = ml.id OR pr.credit_move_id = ml.id
            JOIN account_move_line       cl  ON cl.id = CASE
                                                          WHEN pr.debit_move_id = ml.id THEN pr.credit_move_id
                                                          ELSE pr.debit_move_id
                                                        END
            JOIN account_move            inv ON inv.id = cl.move_id
            JOIN account_account         aa  ON aa.id  = ml.account_id
            WHERE p.banking_required = TRUE
              AND p.partner_type = 'supplier'
              AND p.banking_date BETWEEN %s AND %s
              AND aa.account_type IN ('asset_receivable', 'liability_payable')
              {exclude_clause}
            GROUP BY p.id
            HAVING SUM(CASE WHEN inv.move_type IN ('in_invoice','in_refund') THEN 1 ELSE 0 END) = 0
               AND SUM(CASE WHEN inv.move_type = 'entry' THEN 1 ELSE 0 END) > 0
        ''', tuple(params_step2))

        for res in self._cr.dictfetchall():
            pay = self.env['account.payment'].browse(res['pay_id'])
            if pay.id in included_pay_ids:
                continue

            entry = self.env['account.move'].browse(res['entry_id']) if res.get('entry_id') else False
            invoice_date = (
                self._fmt_date(entry.date) if entry and entry.date
                else self._fmt_date(pay.banking_date)
            )
            amount_payment = self._to_bob(pay.amount, pay.currency_id.name)

            rows[idx] = self._purchase_row_no_invoice(pay, invoice_date, amount_payment)
            idx += 1
            included_pay_ids.add(pay.id)

        # ----------------------------------------------------------------
        # PASO 3: Pagos supplier sin conciliaciones → match por name con entry
        # ----------------------------------------------------------------
        self._cr.execute('''
            SELECT p.id AS pay_id
            FROM account_payment p
            JOIN account_move    m ON m.id = p.move_id
            WHERE p.banking_required = TRUE
              AND p.partner_type = 'supplier'
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
            amount_payment = self._to_bob(pay.amount, pay.currency_id.name)

            rows[idx] = self._purchase_row_no_invoice(pay, invoice_date, amount_payment)
            idx += 1
            included_pay_ids.add(pay.id)

        # ----------------------------------------------------------------
        # Escribir Excel (sin ordenación: el reporte compras mantiene orden por fecha de pago)
        # ----------------------------------------------------------------
        self._write_sheet(workbook, sheet, rows)

    # ------------------------------------------------------------------
    # Construcción de filas
    # ------------------------------------------------------------------

    def _purchase_row_from_invoice(self, pay, inv, amount_total, amount_payment, amount_payment_acum):
        return {
            'invoice_date':       self._fmt_date(inv.invoice_date),
            'client_vat':         inv.partner_id.vat or '',
            'client_name':        inv.partner_id.name or '',
            'invoice_number':     getattr(inv, 'l10n_bo_invoice_number', '') or '',
            'auth_code':          getattr(inv, 'auth_number', '') or getattr(inv, 'l10n_bo_cuf', '') or '',
            'payment_ref':        pay.banking_transaction_ref or '',
            'payment_date':       self._fmt_date(pay.banking_date),
            'amount_total':       amount_total,
            'amount_payment':     amount_payment,
            'amount_payment_acum': amount_payment_acum,
            'account_num':        self._journal_account_number(pay),
            'bank_vat':           self._journal_bank_vat(pay),
            'payment_method':     self._payment_method_code(pay),
            'purchase_type':      pay.banking_purchase_type or '',
            'payment_form':       pay.banking_payment_form or '',
            'nit_complement':     pay.banking_nit_complement or '',
            'support_doc_type':   pay.banking_support_doc_type or '',
            'support_doc_num':    pay.banking_support_doc_number or '',
            'contract_number':    pay.banking_contract_number or '',
            'credit_account':     pay.banking_credit_account or '',
            'credit_entity_nit':  pay.banking_credit_entity_nit or '',
        }

    def _purchase_row_no_invoice(self, pay, invoice_date, amount_payment):
        return {
            'invoice_date':       invoice_date,
            'client_vat':         pay.partner_id.vat or '',
            'client_name':        pay.partner_id.name or '',
            'invoice_number':     '',
            'auth_code':          '',
            'payment_ref':        pay.banking_transaction_ref or '',
            'payment_date':       self._fmt_date(pay.banking_date),
            'amount_total':       0.0,
            'amount_payment':     amount_payment,
            'amount_payment_acum': amount_payment,
            'account_num':        self._journal_account_number(pay),
            'bank_vat':           self._journal_bank_vat(pay),
            'payment_method':     self._payment_method_code(pay),
            'purchase_type':      pay.banking_purchase_type or '',
            'payment_form':       pay.banking_payment_form or '',
            'nit_complement':     pay.banking_nit_complement or '',
            'support_doc_type':   pay.banking_support_doc_type or '',
            'support_doc_num':    pay.banking_support_doc_number or '',
            'contract_number':    pay.banking_contract_number or '',
            'credit_account':     pay.banking_credit_account or '',
            'credit_entity_nit':  pay.banking_credit_entity_nit or '',
        }

    # ------------------------------------------------------------------
    # Helpers de relaciones
    # ------------------------------------------------------------------

    def _journal_account_number(self, pay):
        bk = pay.move_id.journal_id.bank_account_id
        return bk.acc_number or '' if bk else ''

    def _journal_bank_vat(self, pay):
        bk = pay.move_id.journal_id.bank_account_id
        return (bk.bank_id and getattr(bk.bank_id, 'vat', '')) or ''

    def _payment_method_code(self, pay):
        return (pay.payment_method_id.banking_code or '') if pay.payment_method_id else ''

    # ------------------------------------------------------------------
    # Escritura del Excel
    # ------------------------------------------------------------------

    def _write_sheet(self, workbook, sheet, rows):
        title_fmt = workbook.add_format({
            'align': 'left', 'bold': True, 'font_size': 16, 'font_color': 'blue',
        })
        sub_fmt = workbook.add_format({'font_size': 10})
        head_fmt = workbook.add_format({
            'align': 'center', 'bold': True, 'font_size': 12,
            'font_color': 'white', 'bg_color': '#003399', 'border': 1,
        })
        cell_fmt = workbook.add_format({'font_size': 10, 'border': 1})

        sheet.set_column('A:U', 25)
        sheet.merge_range('A1:U2', 'Reporte de Bancarización – Compras', title_fmt)
        sheet.merge_range('A3:B3', '(Expresado en Bolivianos)', sub_fmt)

        headers = [
            'N°',
            'TIPO DE TRANSACCIÓN',
            'FORMA DE PAGO',
            'NIT/CI PROVEEDOR',
            'COMPLEMENTO',
            'NOMBRE O RAZÓN SOCIAL PROVEEDOR',
            'CÓDIGO DE AUTORIZACIÓN',
            'NÚMERO FACTURA',
            'TIPO DOC. RESPALDO',
            'NÚMERO DOC. RESPALDO',
            'FECHA FACTURA / DOC. RESPALDO',
            'MONTO FACTURADO COMPRA (BS)',
            'N° CONTRATO O ACUERDO',
            'TIPO DOC. DE PAGO',
            'FECHA DOC. DE TRANSACCIÓN FINANCIERA',
            'N° CUENTA COMPRADOR (DÉBITO)',
            'N° CUENTA PROVEEDOR (ABONO)',
            'NIT ENTIDAD FINANCIERA (DÉBITO)',
            'NIT ENTIDAD FINANCIERA (ABONO)',
            'N° TRANSACCIÓN / OPERACIÓN',
            'MONTO PAGADO (BS)',
        ]
        for col, h in enumerate(headers):
            sheet.write(3, col, h, head_fmt)

        for seq, (_, row) in enumerate(rows.items()):
            r = seq + 4
            sheet.write(r, 0,  seq + 1,                            cell_fmt)
            sheet.write(r, 1,  row.get('purchase_type', ''),        cell_fmt)
            sheet.write(r, 2,  row.get('payment_form', ''),         cell_fmt)
            sheet.write(r, 3,  row.get('client_vat', ''),           cell_fmt)
            sheet.write(r, 4,  row.get('nit_complement', ''),       cell_fmt)
            sheet.write(r, 5,  row.get('client_name', ''),          cell_fmt)
            sheet.write(r, 6,  row.get('auth_code', ''),            cell_fmt)
            sheet.write(r, 7,  row.get('invoice_number', ''),       cell_fmt)
            sheet.write(r, 8,  row.get('support_doc_type', ''),     cell_fmt)
            sheet.write(r, 9,  row.get('support_doc_num', ''),      cell_fmt)
            sheet.write(r, 10, row.get('invoice_date', ''),         cell_fmt)
            sheet.write(r, 11, row.get('amount_total', 0.0),        cell_fmt)
            sheet.write(r, 12, row.get('contract_number', ''),      cell_fmt)
            sheet.write(r, 13, row.get('payment_method', ''),       cell_fmt)
            sheet.write(r, 14, row.get('payment_date', ''),         cell_fmt)
            sheet.write(r, 15, row.get('account_num', ''),          cell_fmt)
            sheet.write(r, 16, row.get('credit_account', ''),       cell_fmt)
            sheet.write(r, 17, row.get('bank_vat', ''),             cell_fmt)
            sheet.write(r, 18, row.get('credit_entity_nit', ''),    cell_fmt)
            sheet.write(r, 19, row.get('payment_ref', ''),          cell_fmt)
            sheet.write(r, 20, row.get('amount_payment', 0.0),      cell_fmt)
