import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    rehalife_reservation_id = fields.Many2one(
        'rehalife.reservation',
        string='Reserva Rehalife',
        copy=False,
    )

    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        return fields_list + ['rehalife_reservation_id']

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)

        # Red de seguridad: el diálogo "Reservas" (reservation_button.js)
        # agrega la línea con pos.models["pos.order.line"].create() del lado
        # del cliente, un create() de bajo nivel que no pasa por
        # order.add_product() (el flujo nativo de Odoo que calcula
        # tax_ids a partir del producto). Eso dejaba la línea sin
        # impuestos y, por lo tanto, la factura generada por el POS
        # tampoco los tenía. Se corrige acá, en el servidor, para no
        # depender del formato interno (frágil) del modelo reactivo del
        # POS en el frontend.
        for line in lines:
            if not line.tax_ids and line.product_id.taxes_id:
                line.tax_ids = [(6, 0, line.product_id.taxes_id.ids)]

        return lines


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        for order in self:
            self._sync_rehalife_reservation(order)
        return result

    def write(self, vals):
        result = super().write(vals)
        if 'account_move' in vals:
            for order in self:
                self._sync_rehalife_reservation_invoice(order)
        return result

    def _sync_rehalife_reservation_invoice(self, order):
        """
        Vincula la factura (account.move) generada por el POS a la reserva
        asociada, para poder acceder a ella desde la ficha de la reserva.
        """
        if not order.account_move:
            return

        reservation = self.env['rehalife.reservation'].search([
            ('pos_order_id', '=', order.id),
        ], limit=1)

        if not reservation or reservation.invoice_id == order.account_move:
            return

        reservation.write({'invoice_id': order.account_move.id})
        _logger.info(
            '[POS] Factura %s vinculada a reserva %s',
            order.account_move.name, reservation.external_id,
        )

    def _sync_rehalife_reservation(self, order):
        if not order.partner_id:
            return

        # ── 1. Match exacto: reservas vinculadas directamente a las líneas ──
        reservations = order.lines.mapped('rehalife_reservation_id')
        # Salvaguarda: solo reservas del mismo paciente de la orden
        reservations = reservations.filtered(
            lambda r: r.partner_id == order.partner_id
        )

        # ── 2. Fallback: heurística anterior (compatibilidad hacia atrás,
        #      para órdenes que no pasaron por el diálogo "Reservas" o vienen
        #      de antes de este fix) ─────────────────────────────────────────
        if not reservations:
            reservations = self.env['rehalife.reservation'].search([
                ('partner_id',     '=', order.partner_id.id),
                ('invoice_status', '=', 'pending'),
                ('status',         'in', ['IN_ROOM', 'IN_CONSULTATION', 'COMPLETED']),
            ], limit=1, order='reservation_date desc')

        if not reservations:
            _logger.info(
                '[POS] Sin reserva pendiente para: %s',
                order.partner_id.name,
            )
            return

        # ── 3. Calcular datos del pago ────────────────────────────────────
        paid_amount = order.amount_total or 0.0
        invoiced    = bool(order.to_invoice)

        # ── 4. Actualizar estado en Odoo y notificar al backend Next.js ────
        # No bloquea el flujo del POS si falla la notificación; el resultado
        # (y el error, si lo hay) queda registrado en la reserva para
        # reintentar manualmente.
        for reservation in reservations:
            reservation_vals = {
                'invoice_status': 'paid',
                'pos_order_id':   order.id,
            }
            if order.account_move:
                reservation_vals['invoice_id'] = order.account_move.id
            reservation.write(reservation_vals)

            _logger.info(
                '[POS] Reserva %s → PAGADA | Orden: %s | Monto: %s | Factura: %s',
                reservation.external_id, order.name, paid_amount, invoiced,
            )

            reservation._notify_backend_payment()