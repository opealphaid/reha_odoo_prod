import json
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Pagos anticipados, Fase 2. Una reserva está "cobrada en otra orden" solo si
# esa orden ya se pagó. Un borrador abandonado en otra caja no la bloquea; dos
# cajas cobrando a la vez se resuelven con el bloqueo de filas del control al
# pagar (ver PosOrder._rehalife_check_before_paid).
REHALIFE_PAID_ORDER_STATES = ('paid', 'done', 'invoiced')

# Campos de pos.order.line que obligan a revalidar las reservas en write().
REHALIFE_LINE_KEYS = {
    'rehalife_reservation_id', 'rehalife_reservation_ids',
    'rehalife_reservation_ids_json', 'product_id', 'qty',
    'refunded_orderline_id', 'order_id',
}

REHALIFE_REFUND_MSG = 'Las reservas pagadas no se devuelven; deben reprogramarse.'


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # Histórico: una línea = una reserva. Se conserva por compatibilidad con
    # las órdenes ya cobradas y con el diálogo del POS hasta la Fase 3.
    rehalife_reservation_id = fields.Many2one(
        'rehalife.reservation',
        string='Reserva Rehalife',
        copy=False,
    )
    # Fase 2: una línea puede cubrir N reservas (qty == N).
    rehalife_reservation_ids = fields.Many2many(
        'rehalife.reservation',
        'rehalife_pos_line_reservation_rel',
        'line_id', 'reservation_id',
        string='Reservas Rehalife',
        copy=False,
    )
    # Transporte desde el POS: lista JSON de ids de reserva. rehalife.reservation
    # no es un modelo cargado en el POS, así que un Many2many directo dependería
    # del formato interno del modelo reactivo. Se convierte al Many2many en
    # create()/write().
    rehalife_reservation_ids_json = fields.Char(
        string='Reservas Rehalife (POS)',
        copy=False,
    )

    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        return fields_list + ['rehalife_reservation_id', 'rehalife_reservation_ids_json']

    # ─── Helpers ─────────────────────────────────────────────────────────────
    @api.model
    def _rehalife_parse_ids_json(self, raw):
        if raw in (False, None, ''):
            return []
        try:
            ids = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            ids = None
        if not isinstance(ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids
        ):
            raise UserError(
                'Formato inválido en las reservas de la línea del POS: '
                'se esperaba una lista de ids de reserva.'
            )
        return ids

    @api.model
    def _rehalife_prepare_vals(self, vals):
        """Convierte rehalife_reservation_ids_json al Many2many."""
        if 'rehalife_reservation_ids_json' in vals:
            ids = self._rehalife_parse_ids_json(vals['rehalife_reservation_ids_json'])
            vals = dict(vals, rehalife_reservation_ids=[(6, 0, ids)])
        return vals

    def _rehalife_reservations(self):
        """Reservas que cubre la línea: Many2one histórico + Many2many."""
        return self.rehalife_reservation_id | self.rehalife_reservation_ids

    @staticmethod
    def _rehalife_label(reservation):
        return '%s (%s %s)' % (
            reservation.partner_id.name or reservation.external_id or reservation.id,
            reservation.reservation_date or '',
            reservation.reservation_time or '',
        )

    @api.model
    def _rehalife_entries_from_lines(self, lines):
        """Pasa líneas a la forma que valida _validate_rehalife_reservations."""
        entries = []
        for line in lines:
            refunded = line.refunded_orderline_id
            entries.append({
                'label': line.full_product_name or line.product_id.display_name or '',
                'partner': line.order_id.partner_id,
                'product_id': line.product_id.id,
                'qty': line.qty,
                'reservation_ids': line._rehalife_reservations().ids,
                'is_refund': bool(refunded) or line.qty < 0,
                'refunded_has_reservations': bool(refunded and refunded._rehalife_reservations()),
            })
        return entries

    # ─── Núcleo de validación ────────────────────────────────────────────────
    @api.model
    def _validate_rehalife_reservations(self, entries, ignore_order_ids=(), lock=False,
                                        check_duplicates=False):
        """Valida las reservas de un conjunto de líneas y devuelve los errores.

        `entries`: dicts {label, partner, product_id, qty, reservation_ids,
        is_refund, refunded_has_reservations}.
        `ignore_order_ids`: órdenes propias (no cuentan como "otra orden").
        `lock`: bloquea las filas de las reservas (SELECT ... FOR UPDATE,
        ordenado por id para no generar deadlocks entre dos cajas).
        `check_duplicates`: la misma reserva no puede estar dos veces entre
        las entradas (se usa cuando las entradas son la orden completa).

        No lanza excepciones de negocio: devuelve una lista de mensajes.
        """
        errors = []
        ignore_order_ids = tuple(ignore_order_ids or ())

        # Devoluciones: nunca se devuelve una línea con reservas.
        for entry in entries:
            if entry['is_refund'] and (entry['reservation_ids'] or entry.get('refunded_has_reservations')):
                errors.append(REHALIFE_REFUND_MSG)

        charge_entries = [e for e in entries if not e['is_refund'] and e['reservation_ids']]
        all_ids = sorted({rid for e in charge_entries for rid in e['reservation_ids']})
        if not all_ids:
            return list(dict.fromkeys(errors))

        Reservation = self.env['rehalife.reservation'].sudo()
        if lock:
            self.env.cr.execute(
                'SELECT id FROM rehalife_reservation WHERE id IN %s ORDER BY id FOR UPDATE',
                (tuple(all_ids),),
            )
            # Lo que el ORM tenga en caché puede ser anterior al bloqueo.
            Reservation.browse(all_ids).invalidate_recordset()

        reservations = Reservation.browse(all_ids).exists()
        by_id = {r.id: r for r in reservations}

        # Reservas ya vinculadas a una línea de OTRA orden pagada (por el
        # Many2one histórico o por el Many2many).
        self.env.cr.execute("""
            SELECT x.reservation_id, o.name
              FROM (
                    SELECT l.rehalife_reservation_id AS reservation_id, l.order_id
                      FROM pos_order_line l
                     WHERE l.rehalife_reservation_id IN %(ids)s
                    UNION
                    SELECT rel.reservation_id, l.order_id
                      FROM rehalife_pos_line_reservation_rel rel
                      JOIN pos_order_line l ON l.id = rel.line_id
                     WHERE rel.reservation_id IN %(ids)s
                   ) x
              JOIN pos_order o ON o.id = x.order_id
             WHERE o.state IN %(states)s
               AND o.id NOT IN %(ignore)s
        """, {
            'ids': tuple(all_ids),
            'states': REHALIFE_PAID_ORDER_STATES,
            'ignore': ignore_order_ids or (0,),
        })
        other_orders = {}
        for reservation_id, order_name in self.env.cr.fetchall():
            other_orders.setdefault(reservation_id, order_name)

        service_status = self.env['rehalife.reservation'].sudo().get_pos_service_status(all_ids)

        branch_restricted = self.env['rehalife.reservation']._is_pos_branch_restricted()
        user_branch = self.env.user.rehalife_branch_id

        seen = {}
        for entry in charge_entries:
            ids = entry['reservation_ids']
            partner = entry['partner']

            if not partner:
                errors.append(
                    'La venta no tiene cliente: asigna el paciente de las reservas antes de cobrar.'
                )

            if entry['qty'] <= 0 or entry['qty'] != len(ids):
                errors.append(
                    'La línea "%s" tiene cantidad %s pero cubre %s reserva(s): deben coincidir. '
                    'Elimina la línea y vuelve a agregar las reservas desde el diálogo.' % (
                        entry['label'], entry['qty'], len(ids),
                    )
                )

            for rid in ids:
                seen[rid] = seen.get(rid, 0) + 1
                reservation = by_id.get(rid)
                if not reservation:
                    errors.append('La reserva %s no existe.' % rid)
                    continue
                label = self._rehalife_label(reservation)

                if partner and reservation.partner_id != partner:
                    errors.append(
                        'La reserva %s es de otro paciente: la venta es de %s.' % (label, partner.name)
                    )

                if branch_restricted and not (
                    reservation.branch_id and reservation.branch_id in user_branch
                ):
                    _logger.warning(
                        '[POS] Cobro rechazado: reserva %s (sucursal %s) por el usuario %s (sucursal %s).',
                        reservation.external_id, reservation.branch_id.name or '-',
                        self.env.user.login, user_branch.sudo().name or '-',
                    )
                    errors.append(
                        'La reserva %s pertenece a la sucursal %s. Tu usuario solo puede cobrar '
                        'reservas de %s.' % (
                            label,
                            reservation.branch_id.name or reservation.branch_name or 'sin sucursal asignada',
                            user_branch.sudo().name
                            or 'ninguna sucursal (no tienes Sucursal SIAT/Rehalife asignada)',
                        )
                    )

                if reservation.status in ('CANCELLED', 'NO_SHOW'):
                    errors.append(
                        'La reserva %s está %s: no se puede cobrar.' % (
                            label, dict(reservation._fields['status'].selection).get(
                                reservation.status, reservation.status),
                        )
                    )

                # Re-sincronización de una orden ya cobrada: la reserva pagada
                # por esta misma orden no es un doble pago.
                paid_by_own_order = (
                    reservation.invoice_status == 'paid'
                    and reservation.pos_order_id.id in ignore_order_ids
                )
                if not paid_by_own_order:
                    if reservation.invoice_status != 'pending':
                        errors.append(
                            'La reserva %s ya no está pendiente de pago (estado: %s)%s.' % (
                                label,
                                dict(reservation._fields['invoice_status'].selection).get(
                                    reservation.invoice_status, reservation.invoice_status),
                                ', orden %s' % reservation.pos_order_id.name
                                if reservation.pos_order_id else '',
                            )
                        )
                    elif rid in other_orders:
                        errors.append(
                            'La reserva %s ya está cobrada en la orden %s.' % (label, other_orders[rid])
                        )

                info = service_status.get(rid)
                if not info or info['status'] != 'ready':
                    motivo = info['message'] if info else 'la reserva no existe.'
                    errors.append('La reserva %s no se puede cobrar: %s' % (label, motivo))
                elif info['product_id'] != entry['product_id']:
                    errors.append(
                        'La reserva %s no se puede cobrar: la línea no usa el producto del '
                        'servicio (%s).' % (label, info['product_name'])
                    )

        if check_duplicates:
            for rid, count in seen.items():
                if count > 1:
                    reservation = by_id.get(rid)
                    errors.append(
                        'La reserva %s está más de una vez en la venta.' % (
                            self._rehalife_label(reservation) if reservation else rid,
                        )
                    )

        errors = list(dict.fromkeys(errors))
        if errors:
            _logger.warning('[POS] Reservas no cobrables: %s', ' | '.join(errors))
        return errors

    def _rehalife_check_lines(self):
        """Aviso temprano en create/write: valida y bloquea las reservas de
        las líneas tocadas. La defensa definitiva es el control al pagar
        (PosOrder._rehalife_check_before_paid), sobre la orden completa.

        No se revisan aquí los duplicados dentro de la orden: mientras el POS
        sincroniza un borrador, las líneas viejas y nuevas pueden coexistir un
        instante; eso se valida con la orden ya completa al pagar.
        """
        relevant = self.filtered(
            lambda l: l._rehalife_reservations()
            or (l.refunded_orderline_id and l.refunded_orderline_id._rehalife_reservations())
        )
        if not relevant:
            return
        errors = self._validate_rehalife_reservations(
            self._rehalife_entries_from_lines(relevant),
            ignore_order_ids=relevant.order_id.ids,
            lock=True,
        )
        if errors:
            raise UserError('\n'.join(errors))

    # ─── ORM ─────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._rehalife_prepare_vals(vals) for vals in vals_list]
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

        # Si falla, se revierte toda la transacción (la orden no se guarda).
        lines._rehalife_check_lines()
        return lines

    def write(self, vals):
        vals = self._rehalife_prepare_vals(vals)
        result = super().write(vals)
        if REHALIFE_LINE_KEYS & set(vals):
            self._rehalife_check_lines()
        return result

    # ─── RPC para el POS (Fase 3) ────────────────────────────────────────────
    @api.model
    def check_reservations_payable(self, partner_id, order_uuid, lines):
        """Verificación previa al pago, llamada desde el POS.

        `lines` = [{product_id, qty, reservation_ids}]. `order_uuid` es la
        orden actual: si ya se sincronizó al servidor, no cuenta como "otra
        orden". Mismas validaciones que el control al pagar, sin bloquear
        filas. Nunca lanza excepción: devuelve {ok, errors}.
        """
        try:
            partner = self.env['res.partner'].browse(partner_id).exists() if partner_id \
                else self.env['res.partner']
            ignore_ids = self.env['pos.order'].search([('uuid', '=', order_uuid)]).ids \
                if order_uuid else []
            errors = []
            entries = []
            for line in lines or []:
                ids = line.get('reservation_ids') or []
                if not isinstance(ids, list) or not all(
                    isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids
                ):
                    errors.append('Formato inválido en las reservas de una línea de la venta.')
                    continue
                qty = line.get('qty') or 0
                entries.append({
                    'label': line.get('label') or '',
                    'partner': partner,
                    'product_id': line.get('product_id'),
                    'qty': qty,
                    'reservation_ids': ids,
                    'is_refund': qty < 0,
                    'refunded_has_reservations': False,
                })
            errors += self._validate_rehalife_reservations(
                entries, ignore_order_ids=ignore_ids, lock=False, check_duplicates=True,
            )
            errors = list(dict.fromkeys(errors))
            return {'ok': not errors, 'errors': errors}
        except Exception as e:
            _logger.exception('[POS] check_reservations_payable falló')
            return {'ok': False, 'errors': ['No se pudieron verificar las reservas: %s' % e]}


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ─── Control al pagar (Fase 2, defensa definitiva) ───────────────────────
    def _rehalife_check_before_paid(self):
        """Revalida, con las filas bloqueadas, TODAS las reservas de las
        órdenes que están por pasar a pagadas, ignorando solo la propia.

        Es la defensa contra el doble cobro: con dos cajas cobrando la misma
        reserva, la segunda transacción espera el bloqueo y, cuando la
        primera confirma, ve la reserva 'paid' (o PostgreSQL aborta por
        acceso concurrente y Odoo reintenta la llamada, que entonces la ve
        pagada). Si falla, UserError y no se marca ninguna reserva.
        """
        orders = self.filtered(lambda o: o.state == 'draft')
        if not orders:
            return
        lines = orders.lines.filtered(
            lambda l: l._rehalife_reservations()
            or (l.refunded_orderline_id and l.refunded_orderline_id._rehalife_reservations())
        )
        if not lines:
            return
        _logger.info(
            '[POS] Control de reservas antes de pagar: %s',
            ', '.join(orders.mapped(lambda o: o.name or o.uuid or str(o.id))),
        )
        Line = self.env['pos.order.line']
        for order in orders:
            order_lines = lines.filtered(lambda l: l.order_id == order)
            if not order_lines:
                continue
            errors = Line._validate_rehalife_reservations(
                Line._rehalife_entries_from_lines(order_lines),
                ignore_order_ids=order.ids,
                lock=True,
                check_duplicates=True,
            )
            if errors:
                raise UserError(
                    'No se puede cobrar la venta %s:\n%s' % (order.name or '', '\n'.join(errors))
                )

    def _process_saved_order(self, draft):
        # Odoo 18 (point_of_sale, pos.order._process_saved_order) llama a
        # action_pos_order_paid() dentro de un try/except Exception que solo
        # registra el error en el log: un UserError lanzado allí NO cortaría
        # la sincronización (la orden quedaría guardada en borrador con sus
        # pagos y el POS mostraría el cobro como hecho). Por eso el control se
        # ejecuta aquí, antes de super(), donde el error sí sube hasta
        # sync_from_ui, revierte toda la transacción y el POS muestra el
        # mensaje sin guardar la orden.
        if not draft:
            self._rehalife_check_before_paid()
        return super()._process_saved_order(draft)

    def action_pos_order_paid(self):
        # También aquí, para las otras vías que pagan una orden (p. ej. el
        # asistente de pago del backend). En el flujo del POS ya pasó por
        # _process_saved_order; repetirlo es barato (las filas ya están
        # bloqueadas por esta transacción).
        self._rehalife_check_before_paid()
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
        Vincula la factura (account.move) generada por el POS a TODAS las
        reservas cobradas en la orden.
        """
        if not order.account_move:
            return

        reservations = self.env['rehalife.reservation'].search([
            ('pos_order_id', '=', order.id),
            ('invoice_id', '!=', order.account_move.id),
        ])
        if not reservations:
            return

        reservations.write({'invoice_id': order.account_move.id})
        _logger.info(
            '[POS] Factura %s vinculada a %s reserva(s): %s',
            order.account_move.name, len(reservations),
            ', '.join(reservations.mapped('external_id')),
        )

    def _sync_rehalife_reservation(self, order):
        """Marca como pagadas las reservas vinculadas a las líneas de la orden.

        Solo las vinculadas explícitamente (Many2one histórico + Many2many).
        Ya no existe el respaldo que, sin reservas en la orden, marcaba "la
        última reserva pendiente" del paciente (marcaba pagada una reserva en
        devoluciones o ventas sueltas).
        Monto por reserva = total de su línea (con impuestos) / reservas de la
        línea; el resto del redondeo va a la última, para que la suma cuadre.
        """
        if not order.partner_id:
            return

        currency = order.currency_id
        Reservation = self.env['rehalife.reservation']
        paid = Reservation
        service_lines_without_reservations = []
        for line in order.lines:
            if line.qty <= 0 or line.refunded_orderline_id:
                continue
            if not line._rehalife_reservations():
                if line.product_id.product_tmpl_id.rehalife_external_id:
                    service_lines_without_reservations.append(line)
                continue
            # Salvaguarda: solo reservas del mismo paciente de la orden (ya
            # validado en _rehalife_check_before_paid).
            reservations = line._rehalife_reservations().filtered(
                lambda r: r.partner_id == order.partner_id
            ).sorted(lambda r: (r.reservation_date or fields.Date.today(), r.reservation_time or '', r.id))
            if not reservations:
                continue

            total = currency.round(line.price_subtotal_incl)
            count = len(reservations)
            unit = currency.round(total / count)
            amounts = [unit] * (count - 1) + [currency.round(total - unit * (count - 1))]

            for reservation, amount in zip(reservations, amounts):
                reservation_vals = {
                    'invoice_status': 'paid',
                    'pos_order_id': order.id,
                    'pos_paid_amount': amount,
                }
                if order.account_move:
                    reservation_vals['invoice_id'] = order.account_move.id
                reservation.write(reservation_vals)
                paid |= reservation
                _logger.info(
                    '[POS] Reserva %s → PAGADA | Orden: %s | Monto: %s | Factura: %s',
                    reservation.external_id, order.name, amount, bool(order.to_invoice),
                )

        # Una línea de servicio Rehalife sin reservas no se bloquea (puede ser
        # una venta legítima), pero no debe pasar en silencio: si era el cobro
        # de una reserva, el vínculo no llegó al servidor.
        for line in service_lines_without_reservations:
            _logger.warning(
                '[POS] Orden %s: la línea "%s" es del servicio %s pero no tiene reservas '
                'vinculadas; ninguna reserva se marcó como pagada. Si era el cobro de una '
                'reserva, revisar el diálogo del POS.',
                order.name, line.full_product_name or line.product_id.display_name,
                line.product_id.display_name,
            )

        if not paid:
            log = _logger.warning if service_lines_without_reservations else _logger.info
            log('[POS] Orden %s sin reservas vinculadas.', order.name)
            return

        # Una llamada a register-payment por reserva. No bloquea el POS: el
        # error queda en la reserva y el cron lo reintenta. Tras el primer
        # fallo no se llama por las demás (si el backend está caído, cada
        # llamada esperaría hasta 15 s con el POS bloqueado).
        failed = False
        for reservation in paid:
            if failed:
                reservation.write({
                    'backend_sync_state': 'error',
                    'backend_sync_error': 'No se intentó: falló la notificación de otra reserva '
                                          'de la misma orden. Se reintenta por cron.',
                })
                continue
            if not reservation._notify_backend_payment():
                failed = True
