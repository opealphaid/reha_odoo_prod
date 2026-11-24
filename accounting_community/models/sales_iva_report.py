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
        titular = self._siat_titular(inv)

        return {
            'invoice_date': inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else '',
            'invoice_number': getattr(inv, 'siat_numero_factura', '') or '',
            'auth_code': getattr(inv, 'siat_cuf', '') or '',
            'client_vat': titular['vat'],
            'client_complement': titular['complement'],
            'client_name': titular['name'],
            'amount_total': amount_total,
            'base_debito_fiscal': inv.amount_total_signed,
            'debito_fiscal': round(float(inv.amount_tax_signed), 2),
            'state': 'A' if inv.payment_state == 'reversed' else 'V',
            'name': inv.name or '',
            'unique_code': getattr(inv, 'unique_code', '') or '',
        }

    def _siat_titular(self, inv):
        """Titular al que realmente se emitió la factura en el SIAT, que
        puede no ser el partner_id de Odoo (Razón Social / NIT de
        facturación del contacto). Orden de prioridad:
          1. Lo que va en el XML enviado al SIAT (siat_xml_factura) — es la
             fuente de verdad, aunque el contacto se haya editado después.
          2. Los campos de facturación SIAT del contacto, si no son los
             valores por defecto (S/N / 0000000).
          3. Nombre y NIT/CI del contacto en Odoo.
        Solo se usa en el Libro de Ventas IVA."""
        partner = inv.partner_id
        titular = {
            'name': partner.name or '',
            'vat': partner.vat or '',
            'complement': getattr(partner, 'siat_complemento', '') or '',
        }

        razon = getattr(partner, 'siat_razon_social_facturacion', '') or ''
        nit = getattr(partner, 'siat_nit_facturacion', '') or ''
        if razon and razon != 'S/N':
            titular['name'] = razon
        if nit and nit != '0000000':
            titular['vat'] = nit

        xml_data = self._parse_siat_xml(getattr(inv, 'siat_xml_factura', '') or '')
        if xml_data.get('nombreRazonSocial'):
            titular['name'] = xml_data['nombreRazonSocial']
        if xml_data.get('numeroDocumento'):
            titular['vat'] = xml_data['numeroDocumento']
        if 'nombreRazonSocial' in xml_data:
            # Si hay XML, el complemento es el que se envió (puede ir vacío).
            titular['complement'] = xml_data.get('complemento', '')
        return titular

    def _parse_siat_xml(self, xml_string):
        """Extrae los datos del cliente de la cabecera del XML SIAT.
        Devuelve {} si no hay XML o no se puede leer."""
        if not xml_string:
            return {}
        try:
            from lxml import etree
            root = etree.fromstring(xml_string.encode('utf-8'))
        except Exception as e:  # XML corrupto: no romper el reporte
            _logger.warning('Libro Ventas IVA: no se pudo leer el XML SIAT: %s', e)
            return {}

        result = {}
        for tag in ('nombreRazonSocial', 'numeroDocumento', 'complemento'):
            nodes = root.xpath('//*[local-name()="cabecera"]/*[local-name()=$t]', t=tag)
            if nodes:
                result[tag] = (nodes[0].text or '').strip()
        return result

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
            sheet.write(r, 6, row['client_complement'], cell_fmt)
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
