# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ── Puente RPC para el POS: el JS nunca llama directo a ganadero.api ni
    #    conoce apiKey/usuario/token del banco, todo eso vive en Python. ────
    @api.model
    def ganadero_create_qr_order(self, amount, reference, transaction_id, currency='BOB', expiration_minutes=2):
        return self.env['ganadero.api'].create_qr_order(
            amount=amount,
            reference=reference,
            transaction_id=transaction_id,
            currency=currency,
            expiration_minutes=expiration_minutes,
        )

    @api.model
    def ganadero_get_qr_status(self, qr_id):
        return self.env['ganadero.api'].get_qr_status(qr_id)

    @api.model
    def ganadero_cancel_qr_order(self, qr_id):
        return self.env['ganadero.api'].cancel_qr_order(qr_id)

    # ── Datos de la representación gráfica de la factura SIAT ──────────────
    #    Un solo RPC para el recibo (receipt.js). Las líneas y los montos se
    #    calculan IGUAL que el XML de alpha_siat
    #    (alpha_siat/models/pos_order.py, _generar_xml_factura_siat) para que
    #    el papel coincida con lo enviado a Impuestos. Sin sudo: lo lee el
    #    usuario del POS con sus permisos normales (pos.order, res.partner,
    #    res.company, product y alpha.siat.unidad.medida tienen lectura para
    #    base.group_user).
    @api.model
    def get_receipt_siat_data(self, pos_reference):
        """Devuelve {'has_siat': False} si no hay orden o no tiene siat_cuf;
        si no, {'has_siat': True, 'siat_info': {...}, 'qr_url': str}."""
        if not pos_reference:
            return {'has_siat': False}
        order = self.search([('pos_reference', '=', pos_reference)], limit=1)
        if not order or not order.siat_cuf:
            return {'has_siat': False}

        company = order.company_id
        partner = order.partner_id
        lines, subtotal_total, descuento_total = order._receipt_siat_lines()

        siat_info = {
            'numero_factura': order.siat_numero_factura,
            'cuf': order.siat_cuf,
            'codigo_recepcion': order.siat_codigo_recepcion or '',
            # Mismo valor que leía antes receipt.js con searchRead (texto UTC).
            'fecha_emision': fields.Datetime.to_string(order.siat_fecha_envio) or '',
            'estado': order.siat_estado_envio or '',
            'empresa_nit': company.vat or '',
            'empresa_razon_social': company.name or '',
            'cliente_nit': partner.siat_nit_facturacion or '',
            'cliente_razon_social': partner.siat_razon_social_facturacion or '',
            'lines': lines,
            'subtotal': subtotal_total,
            'descuento': descuento_total,
            'total': round(order.amount_total, 2),
        }
        return {
            'has_siat': True,
            'siat_info': siat_info,
            'qr_url': order._receipt_siat_qr_url(),
            # Mismo total que imprime el recibo; misma función que el PDF de
            # la factura (alpha_siat/models/account_move_pdf.py).
            'monto_letras': self.env['account.move']._siat_monto_a_letras(order.amount_total),
        }

    def _receipt_siat_lines(self):
        """Líneas del recibo con el mismo filtro y cálculo que el XML de
        alpha_siat: salta productos no homologados; descripcion =
        product.name; unidad = unidad SIAT del template; subtotal =
        round(qty × price_unit, 2).

        El descuento se muestra en Bs. (qty × price_unit × discount / 100).
        Ojo: el XML de alpha_siat manda line.discount (un %) como
        montoDescuento; esa discrepancia no se corrige aquí."""
        self.ensure_one()
        lines = []
        subtotal_total = 0.0
        descuento_total = 0.0
        for line in self.lines:
            product = line.product_id
            product_tmpl = product.product_tmpl_id
            if not product_tmpl.siat_homologado:
                continue
            unidad_siat = product_tmpl.siat_unidad_medida_id
            unidad = unidad_siat.descripcion if unidad_siat else (product.uom_id.name or '')
            subtotal = round(line.qty * line.price_unit, 2)
            descuento = round(line.qty * line.price_unit * (line.discount or 0.0) / 100.0, 2)
            subtotal_total += subtotal
            descuento_total += descuento
            lines.append({
                'descripcion': (product.name or '')[:500],
                'unidad': unidad,
                'cantidad': line.qty,
                'precio_unitario': round(line.price_unit, 2),
                'descuento': descuento,
                'subtotal': subtotal,
            })
        return lines, round(subtotal_total, 2), round(descuento_total, 2)

    def _receipt_siat_qr_url(self):
        """URL del QR de consulta SIAT. Se mantiene el valor que armaba antes
        receipt.js (piloto, t=1); aislado aquí para poder reemplazarlo cuando
        dependa del ambiente SIAT."""
        self.ensure_one()
        return (
            'https://pilotosiat.impuestos.gob.bo/consulta/QR'
            f'?nit={self.company_id.vat}&cuf={self.siat_cuf}'
            f'&numero={self.siat_numero_factura}&t=1'
        )
