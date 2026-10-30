import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

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

    @api.model
    def _check_rehalife_reservation_branch(self, reservation_ids):
        """Fase 3: un recepcionista solo puede cobrar reservas de su sucursal.

        Se valida comparando la sucursal (no con check_access): da un mensaje
        claro con las dos sucursales, no depende de la caché de ir.rule y
        aplica exactamente el mismo criterio que la regla de la Fase 2
        (branch_id en la sucursal del usuario; sin sucursal → rechazada).
        Para los usuarios no restringidos no hace nada.
        """
        Reservation = self.env['rehalife.reservation']
        reservation_ids = [rid for rid in set(reservation_ids or []) if rid]
        if not reservation_ids or not Reservation._is_pos_branch_restricted():
            return

        user_branch = self.env.user.rehalife_branch_id
        # sudo() solo para leer la reserva ajena y armar el mensaje.
        for reservation in Reservation.sudo().browse(reservation_ids).exists():
            if reservation.branch_id and reservation.branch_id in user_branch:
                continue
            _logger.warning(
                '[POS] Cobro rechazado: reserva %s (sucursal %s) por el usuario %s (sucursal %s).',
                reservation.external_id, reservation.branch_id.name or '-',
                self.env.user.login, user_branch.sudo().name or '-',
            )
            raise UserError(
                'La reserva %s pertenece a la sucursal %s. '
                'Tu usuario solo puede cobrar reservas de %s.' % (
                    '%s (%s %s)' % (
                        reservation.partner_id.name or reservation.external_id,
                        reservation.reservation_date or '',
                        reservation.reservation_time or '',
                    ),
                    reservation.branch_id.name or reservation.branch_name or 'sin sucursal asignada',
                    user_branch.sudo().name or 'ninguna sucursal (no tienes Sucursal SIAT/Rehalife asignada)',
                )
            )

    @api.model_create_multi
    def create(self, vals_list):
        # Antes de crear: si falla, no se guarda nada de la orden.
        self._check_rehalife_reservation_branch(
            [vals.get('rehalife_reservation_id') for vals in vals_list]
        )
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

    def write(self, vals):
        # Un re-sync de la orden puede actualizar una línea existente.
        if vals.get('rehalife_reservation_id'):
            self._check_rehalife_reservation_branch([vals['rehalife_reservation_id']])
        return super().write(vals)


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