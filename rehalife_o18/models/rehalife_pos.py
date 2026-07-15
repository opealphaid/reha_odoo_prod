import logging
from odoo import models

_logger = logging.getLogger(__name__)


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

        # ── 1. Buscar reserva pendiente del paciente ──────────────────────
        reservation = self.env['rehalife.reservation'].search([
            ('partner_id',     '=', order.partner_id.id),
            ('invoice_status', '=', 'pending'),
            ('status',         '=', 'COMPLETED'),
        ], limit=1, order='reservation_date desc')

        if not reservation:
            _logger.info(
                '[POS] Sin reserva pendiente para: %s',
                order.partner_id.name,
            )
            return

        # ── 2. Calcular datos del pago ────────────────────────────────────
        paid_amount = order.amount_total or 0.0
        invoiced    = bool(order.to_invoice)

        # ── 3. Actualizar estado en Odoo ──────────────────────────────────
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

        # ── 4. Notificar al backend Next.js via rehalife.api ──────────────
        # No bloquea el flujo del POS si falla; el resultado (y el error, si
        # lo hay) queda registrado en la reserva para reintentar manualmente.
        reservation._notify_backend_payment()