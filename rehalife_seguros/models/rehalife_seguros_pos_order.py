# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _sync_rehalife_reservation(self, order):
        """Pagos anticipados, Fase 4: tras marcar como pagadas las reservas de
        la orden (rehalife_o18), congela la cobertura de las de seguro
        (precio, %, copago y monto de la aseguradora).

        Corre dentro de action_pos_order_paid, que Odoo 18 envuelve en un
        try/except que solo registra el error: por eso va en un savepoint y
        nunca lanza (un fallo aquí no debe dejar la orden a medio pagar). El
        copago ya se validó con las filas bloqueadas en
        _rehalife_check_before_paid (y ahí se creó el PVM que faltaba), así
        que los valores coinciden con lo cobrado.
        """
        result = super()._sync_rehalife_reservation(order)
        reservations = self.env['rehalife.reservation'].sudo().search([
            ('pos_order_id', '=', order.id),
            ('invoice_status', '=', 'paid'),
            ('modalidad', '=', 'seguro'),
            ('fecha_congelamiento', '=', False),
        ])
        for reservation in reservations:
            try:
                with self.env.cr.savepoint():
                    reservation._congelar_cobertura()
            except Exception:
                _logger.exception(
                    '[Seguros] Orden %s: no se pudo congelar la cobertura de la reserva %s.',
                    order.name, reservation.external_id,
                )
        return result
