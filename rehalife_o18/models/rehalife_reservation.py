import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Estados de los que una reserva ya no sale: sync_from_nextjs no los pisa.
TERMINAL_STATUSES = ('CANCELLED', 'NO_SHOW', 'COMPLETED')


class RehalifeReservation(models.Model):
    _name = 'rehalife.reservation'
    _description = 'Reserva Rehalife'
    _order = 'reservation_date desc'

    # ── Campos existentes (no tocar) ─────────────────────────────────────────
    external_id         = fields.Char(string='ID Externo', required=True, index=True)
    partner_id          = fields.Many2one('res.partner', string='Paciente', required=True)
    reservation_date    = fields.Date(string='Fecha')
    reservation_time    = fields.Char(string='Hora')
    status              = fields.Selection([
        ('PENDING',         'Pendiente'),
        ('IN_ROOM',         'En Sala'),
        ('IN_CONSULTATION', 'En Consulta'),
        ('COMPLETED',       'Completada'),
        ('CANCELLED',       'Cancelada'),
        ('NO_SHOW',         'No asistió'),
    ], string='Estado', default='PENDING')
    attention_type  = fields.Char(string='Tipo de Atención')
    sub_specialty   = fields.Char(string='Sub-especialidad')
    service_type_external_id = fields.Char(string='ID Externo Tipo de Servicio')
    service_type_name        = fields.Char(string='Tipo de Servicio')
    branch_name     = fields.Char(string='Sucursal')
    # Sucursal como registro real (FASE 1). branch_name se conserva: lo usan el
    # POS (reservation_button.js) y las vistas.
    branch_id       = fields.Many2one(
        'rehalife.branch', string='Sucursal (ref.)',
        index=True, ondelete='restrict',
    )
    doctor_name     = fields.Char(string='Doctor')
    notes           = fields.Text(string='Notas')
    diagnosis       = fields.Text(string='Diagnóstico')

    # ── Reestructuración CORE oct-2026 (solo informativos, todos opcionales) ──
    # La reserva dura lo que dura su tipo de servicio y ocupa un consultorio.
    # El consultorio va como Char (id + nombre del backend): en Odoo no hay
    # modelo de consultorio y no hace falta para facturar ni cobrar. Las
    # reservas anteriores a la reestructuración quedan en blanco.
    end_time                = fields.Char(string='Hora Fin')
    duration_minutes        = fields.Integer(string='Duración (min)')
    environment_external_id = fields.Char(string='ID Externo Consultorio')
    environment_name        = fields.Char(string='Consultorio')

    # ── Campos de facturación (invoice clásico — se mantiene por compatibilidad)
    invoice_id      = fields.Many2one('account.move', string='Factura', readonly=True)
    invoice_status  = fields.Selection([
        ('pending',  'Pendiente de Pago'),
        ('invoiced', 'Facturada'),
        ('paid',     'Pagada'),
        ('cancelled','Cancelada'),
    ], string='Estado de Factura', default='pending')

    # ── Monto pagado (solo informativo, importación de respaldo) ────────────
    paid_amount = fields.Float(
        string='Monto Pagado (Importado)', readonly=True, digits=(16, 2),
    )

    # ── Campos POS (nuevos) ──────────────────────────────────────────────────
    pos_order_id = fields.Many2one(
        'pos.order',
        string='Orden POS',
        readonly=True,
        ondelete='set null',
    )

    pos_order_ref = fields.Char(
        string='Ref. Orden POS',
        compute='_compute_pos_order_info',
        store=False,
    )

    pos_order_state_label = fields.Char(
        string='Estado Orden POS',
        compute='_compute_pos_order_info',
        store=False,
    )

    # ── Pagos anticipados (Fase 2) ───────────────────────────────────────────
    pos_paid_amount = fields.Float(
        string='Monto Pagado (POS)', readonly=True, digits=(16, 2), copy=False,
        help='Lo que se cobró por esta reserva en el POS: total de su línea '
             '(con impuestos) dividido entre las reservas que cubre la línea.',
    )
    pos_order_line_ids = fields.Many2many(
        'pos.order.line',
        'rehalife_pos_line_reservation_rel',
        'reservation_id', 'line_id',
        string='Líneas POS', readonly=True, copy=False,
    )
    alerta_pagada_cancelada = fields.Boolean(
        string='Pagada pero Cancelada/No asistió', readonly=True, copy=False,
        help='Llegó CANCELLED o NO_SHOW desde Rehalife para una reserva ya '
             'pagada. El pago no se devuelve: hay que reprogramarla en Rehalife '
             'y luego marcar la alerta como revisada.',
    )

    nc_error = fields.Char(
        string='Error al Generar Nota de Conformidad', readonly=True, copy=False,
    )

    # ── Sincronización del pago con el backend Next.js ───────────────────────
    backend_sync_state = fields.Selection([
        ('draft',  'Pendiente'),
        ('synced', 'Sincronizado'),
        ('error',  'Error'),
    ], string='Estado Sync. Backend', default='draft', readonly=True)
    backend_sync_error = fields.Text(string='Error de Sync. Backend', readonly=True)
    backend_last_sync  = fields.Datetime(string='Última Sync. Backend', readonly=True)

    @api.depends('pos_order_id', 'pos_order_id.state', 'pos_order_id.name')
    def _compute_pos_order_info(self):
        STATE_LABELS = {
            'draft': 'Borrador',
            'paid': 'Pagado',
            'done': 'Completado',
            'invoiced': 'Facturado',
            'cancel': 'Cancelado',
        }
        for rec in self:
            if rec.pos_order_id:
                rec.pos_order_ref = rec.pos_order_id.name or ''
                rec.pos_order_state_label = STATE_LABELS.get(
                    rec.pos_order_id.state, rec.pos_order_id.state or ''
                )
            else:
                rec.pos_order_ref = ''
                rec.pos_order_state_label = ''


    # ─── Helper: producto Consulta (sin taxes) ───────────────────────────────
    def _get_or_create_consulta_product(self):
        Product = self.env['product.product']
        product = Product.search(
            [('name', '=', 'Consulta'), ('active', '=', True)],
            limit=1,
        )
        if product:
            return product

        template = self.env['product.template'].create({
            'name':          'Consulta',
            'type':          'service',
            'list_price':    0.0,
            'sale_ok':       True,
            'purchase_ok':   False,
            'available_in_pos': True,
            'taxes_id':      [(5, 0, 0)],
        })
        return Product.search(
            [('product_tmpl_id', '=', template.id)],
            limit=1,
        )

    # ─── Helper: obtener sesión POS abierta ──────────────────────────────────
    def _get_open_pos_session(self):
        """
        Retorna la primera sesión POS abierta.
        Lanza UserError si no hay ninguna activa.
        """
        session = self.env['pos.session'].search(
            [('state', '=', 'opened')],
            limit=1,
        )
        if not session:
            raise UserError(
                'No hay ninguna sesión del Punto de Venta abierta.\n'
                'Por favor abre una sesión en POS antes de enviar la orden.'
            )
        return session

    # ─── Ver la orden POS vinculada ──────────────────────────────────────────
    def action_view_pos_order(self):
        self.ensure_one()
        if not self.pos_order_id:
            raise UserError('Esta reserva no tiene orden POS vinculada.')
        return {
            'type':      'ir.actions.act_window',
            'res_model': 'pos.order',
            'res_id':    self.pos_order_id.id,
            'view_mode': 'form',
            'target':    'current',
        }

    # ─── Notificar el pago al backend Next.js (usado por POS y por el botón
    #     de reintento manual) ─────────────────────────────────────────────
    def _notify_backend_payment(self):
        """
        Notifica el pago/facturación de la reserva al backend Next.js y
        actualiza los campos de estado de sincronización según el resultado.
        No relanza la excepción: nunca debe bloquear el flujo del POS.
        """
        self.ensure_one()
        if not self.pos_order_id:
            self.write({
                'backend_sync_state': 'error',
                'backend_sync_error': 'La reserva no tiene una orden POS asociada.',
            })
            return False

        paid_amount = self._get_backend_paid_amount()
        invoiced = bool(self.pos_order_id.to_invoice)

        try:
            self.env['rehalife.api'].register_payment(
                reservation_id=self.external_id,
                paid_amount=paid_amount,
                invoiced=invoiced,
            )
            self.write({
                'backend_sync_state': 'synced',
                'backend_sync_error': False,
                'backend_last_sync': fields.Datetime.now(),
            })
            _logger.info(
                '[POS] ✅ Pago notificado a Next.js | Reserva: %s', self.external_id,
            )
            return True
        except Exception as e:
            self.write({
                'backend_sync_state': 'error',
                'backend_sync_error': str(e),
            })
            _logger.warning(
                '[POS] ⚠️ No se pudo notificar el pago a Next.js | '
                'Reserva: %s | Error: %s',
                self.external_id, str(e),
            )
            return False

    def _get_backend_paid_amount(self):
        """Monto de ESTA reserva para register-payment.

        Desde la Fase 2 sale de pos_paid_amount (lo escribe
        pos.order._sync_rehalife_reservation). Reservas cobradas antes, sin
        ese dato: total de su línea (Many2one histórico) / qty; si tampoco
        hay línea, el total de la orden, como antes.
        """
        self.ensure_one()
        # sudo(): solo lectura de las líneas POS (el reintento manual lo puede
        # pulsar un administrador de Rehalife sin permisos del POS).
        rec = self.sudo()
        if rec.pos_paid_amount or rec.pos_order_line_ids:
            return rec.pos_paid_amount
        line = rec.pos_order_id.lines.filtered(
            lambda l: l.rehalife_reservation_id == rec and l.qty > 0
        )[:1]
        if line:
            return line.price_subtotal_incl / line.qty
        return rec.pos_order_id.amount_total or 0.0

    @api.model
    def _cron_retry_backend_payment(self, limit=20, max_consecutive_failures=3):
        """Cron: reintenta register-payment en reservas pagadas en el POS
        cuya notificación al backend falló.

        Lote chico y corte tras varios fallos seguidos: si el backend está
        caído, cada llamada espera hasta 15 s y no tiene sentido seguir. Cada
        intento actualiza write_date, así que la siguiente corrida empieza
        por las que llevan más tiempo sin reintentarse.
        """
        reservations = self.search([
            ('invoice_status', '=', 'paid'),
            ('backend_sync_state', '=', 'error'),
            ('pos_order_id', '!=', False),
        ], order='write_date asc, id asc', limit=limit)
        ok = failures = 0
        for reservation in reservations:
            if reservation._notify_backend_payment():
                ok += 1
                failures = 0
                continue
            failures += 1
            if failures >= max_consecutive_failures:
                _logger.warning(
                    '[Cron] Reintento de pagos cortado tras %s fallos seguidos.', failures,
                )
                break
        _logger.info(
            '[Cron] Reintento de pagos al backend: %s de %s reserva(s) sincronizadas.',
            ok, len(reservations),
        )

    def action_marcar_alerta_revisada(self):
        """Botón: apaga la alerta "pagada pero cancelada" (manual, Fase 2)."""
        self.write({'alerta_pagada_cancelada': False})
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_retry_backend_sync(self):
        """
        Botón: reintenta manualmente la notificación de pago al backend.

        Muestra un mensaje de éxito/error y además refresca la vista actual
        (lista o formulario) encadenando un 'soft_reload' en el parámetro
        'next' de la notificación, para no depender de que el usuario
        recargue la página manualmente.
        """
        self.ensure_one()
        success = self._notify_backend_payment()

        if success:
            params = {
                'title': 'Sincronización exitosa',
                'message': 'El pago fue notificado correctamente al backend Rehalife.',
                'type': 'success',
                'sticky': False,
            }
        else:
            params = {
                'title': 'Error de sincronización',
                'message': self.backend_sync_error or 'No se pudo notificar el pago al backend.',
                'type': 'danger',
                'sticky': True,
            }

        params['next'] = {'type': 'ir.actions.client', 'tag': 'soft_reload'}

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }

    # ─── Sincronizar estado de pago desde la orden POS ───────────────────────
    def _sync_pos_payment_state(self):
        """
        Llama esto desde un cron o desde el webhook para reflejar
        si la orden POS ya fue pagada.
        """
        for rec in self:
            if not rec.pos_order_id:
                continue
            if rec.pos_order_id.state in ('paid', 'done', 'invoiced'):
                rec.invoice_status = 'paid'
            elif rec.pos_order_id.state == 'cancel':
                rec.invoice_status = 'pending'

    # ─── (Se mantiene por compatibilidad con el flujo antiguo) ───────────────
    def action_create_invoice(self):
        """Crea account.move clásico — mantenido por compatibilidad."""
        self.ensure_one()
        if self.status in ('CANCELLED', 'NO_SHOW'):
            raise UserError('No se puede facturar una reserva cancelada o con ausencia.')
        if self.invoice_id:
            raise UserError(f'Esta reserva ya tiene la factura {self.invoice_id.name}.')
        if self.invoice_status in ('invoiced', 'paid'):
            raise UserError('Esta reserva ya fue facturada o pagada.')

        product = self._get_or_create_consulta_product()
        invoice_vals = {
            'move_type':    'out_invoice',
            'partner_id':   self.partner_id.id,
            'invoice_date': self.reservation_date,
            'state':        'draft',
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name':       f'Consulta — {self.sub_specialty or "General"}',
                'quantity':   1,
                'price_unit': product.list_price or 0.0,
                'tax_ids':    [(5, 0, 0)],
            })],
        }
        invoice = self.env['account.move'].create(invoice_vals)
        self.write({'invoice_id': invoice.id, 'invoice_status': 'invoiced'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_invoice(self):
        """Abre la factura clásica vinculada (compatibilidad)."""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError('Esta reserva no tiene factura vinculada.')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @staticmethod
    def _core_oct2026_vals(source, keys):
        """Campos de la reestructuración CORE oct-2026, tolerando null.

        `keys` = (end_time, duration_minutes, environment_id, environment_name)
        tal como se llaman en `source`. Solo se devuelven las claves que vienen
        en el payload: un cliente que todavía no las manda no borra lo que ya
        estaba guardado.
        """
        end_key, duration_key, env_id_key, env_name_key = keys
        out = {}
        if end_key in source:
            out['end_time'] = source.get(end_key) or False
        if duration_key in source:
            try:
                out['duration_minutes'] = int(source.get(duration_key) or 0)
            except (TypeError, ValueError):
                out['duration_minutes'] = 0
        if env_id_key in source:
            out['environment_external_id'] = source.get(env_id_key) or False
        if env_name_key in source:
            out['environment_name'] = source.get(env_name_key) or False
        return out

    @api.model
    def sync_from_nextjs(self, vals: dict):
        """
        Crea o actualiza una reserva recibida desde Next.js.
        """
        external_id = vals.get('external_id')
        if not external_id:
            raise UserError('external_id es requerido para sincronizar una reserva.')

        # Buscar el partner por su ID externo de Rehalife
        partner = self.env['res.partner'].search(
            [('rehalife_external_id', '=', vals.get('patient_external_id'))],
            limit=1,
        )
        if not partner:
            raise UserError(
                f'Paciente con ID {vals.get("patient_external_id")} no encontrado en Odoo. '
                'Sincroniza primero el paciente.'
            )

        # Mapeo de valores
        write_vals = {
            'partner_id': partner.id,
            'reservation_date': vals.get('date'),
            'reservation_time': vals.get('time'),
            'status': vals.get('status', 'PENDING'),
            'attention_type': vals.get('attention_type'),
            'sub_specialty': vals.get('sub_specialty'),
            'service_type_external_id': vals.get('service_type_external_id'),
            'service_type_name': vals.get('service_type_name'),
            'branch_name': vals.get('branch_name'),
            'doctor_name': vals.get('doctor_name'),
            'notes': vals.get('notes'),
            'diagnosis': vals.get('diagnosis'),
        }
        write_vals.update(self._core_oct2026_vals(
            vals,
            ('end_time', 'duration_minutes', 'environment_external_id', 'environment_name'),
        ))

        # Sucursal: solo se escribe si se pudo resolver. Si el payload no trae
        # datos de sucursal, no se toca el branch_id que ya tuviera la reserva.
        branch = self.env['rehalife.branch'].sudo()._get_or_create_from_external(
            vals.get('branch_external_id'), vals.get('branch_name'),
        )
        if branch:
            write_vals['branch_id'] = branch.id

        # Buscar si ya existe
        existing = self.search([('external_id', '=', external_id)], limit=1)

        if existing:
            new_status = write_vals['status']

            # Un estado final no se pisa: si llega otro estado (p. ej. un
            # IN_ROOM atrasado sobre una reserva ya cancelada), se ignora. Se
            # devuelve 'id' igual porque el override de rehalife_seguros lo usa.
            if existing.status in TERMINAL_STATUSES and new_status != existing.status:
                _logger.warning(
                    '[Webhook] Reserva %s ya está en %s: se ignora el cambio a %s.',
                    external_id, existing.status, new_status,
                )
                return {
                    'success': True,
                    'id': existing.id,
                    'action': 'ignored_terminal',
                    'external_id': external_id,
                }

            # Al cancelarse o marcarse "No asistió" deja de ser cobrable en el
            # POS. Lo ya cobrado o facturado no se toca: el pago no se devuelve.
            if (new_status in ('CANCELLED', 'NO_SHOW')
                    and existing.status not in ('CANCELLED', 'NO_SHOW')):
                if existing.invoice_status in ('paid', 'invoiced'):
                    # Pagos anticipados, Fase 2: se acepta el estado pero se
                    # marca la alerta para que un administrador la reprograme.
                    if existing.invoice_status == 'paid':
                        write_vals['alerta_pagada_cancelada'] = True
                    _logger.warning(
                        '[Webhook] Reserva pagada recibida como cancelada: %s '
                        '(invoice_status=%s, status=%s). No se cambia el cobro.',
                        external_id, existing.invoice_status, new_status,
                    )
                elif existing.invoice_status == 'pending' and not existing.pos_order_id:
                    write_vals['invoice_status'] = 'cancelled'

            existing.write(write_vals)
            _logger.info('[Webhook] Reserva actualizada: %s', external_id)
            return {
                'success': True,
                'id': existing.id,
                'action': 'updated',
                'external_id': external_id,
            }
        else:
            write_vals['external_id'] = external_id
            new_rec = self.create(write_vals)
            _logger.info('[Webhook] Reserva creada: %s', external_id)
            return {
                'success': True,
                'id': new_rec.id,
                'action': 'created',
                'external_id': external_id,
            }

    @api.model
    def sync_batch_from_nextjs(self, vals_list):
        """Sincroniza varias reservas en una sola llamada (Pagos anticipados,
        Fase 1: reservas recurrentes / en lote creadas desde Next.js).

        Llama a self.sync_from_nextjs (no a super) para que cada elemento pase
        también por el override de rehalife_seguros (modalidad, aseguradora,
        NC). Cada reserva va en su propio savepoint: si una falla (p. ej. el
        paciente todavía no está en Odoo), se revierte solo esa y las demás
        siguen.

        Devuelve una lista, en el mismo orden recibido, de
        {external_id, ok, action, id, error}.
        """
        results = []
        for vals in vals_list or []:
            if not isinstance(vals, dict):
                results.append({
                    'external_id': None, 'ok': False, 'action': None, 'id': None,
                    'error': 'Elemento inválido: se esperaba un objeto.',
                })
                continue
            external_id = vals.get('external_id')
            try:
                with self.env.cr.savepoint():
                    result = self.sync_from_nextjs(vals)
                results.append({
                    'external_id': external_id,
                    'ok': True,
                    'action': result.get('action'),
                    'id': result.get('id'),
                    'error': None,
                })
            except Exception as e:
                _logger.warning(
                    '[Webhook] Lote: no se pudo sincronizar la reserva %s: %s',
                    external_id, str(e),
                )
                results.append({
                    'external_id': external_id, 'ok': False, 'action': None, 'id': None,
                    'error': str(e),
                })
        return results

    @api.model
    def import_from_nextjs(self, raw: dict):
        """
        Importa una reserva desde el JSON crudo de GET /reservations.
        Aplica idempotencia: no duplica, no pisa estados avanzados.
        """
        external_id = raw.get('id')
        if not external_id:
            raise UserError('La reserva no tiene id.')

        if raw.get('status') != 'COMPLETED':
            return {'action': 'skipped', 'external_id': external_id, 'reason': 'not_completed'}

        patient = raw.get('patient') or {}
        patient_ext_id = patient.get('id')
        if not patient_ext_id:
            raise UserError('La reserva %s no tiene patient.id.' % external_id)

        partner = self.env['res.partner'].search(
            [('rehalife_external_id', '=', str(patient_ext_id))], limit=1,
        )
        if not partner:
            raise UserError(
                'Paciente con ID %s no encontrado en Odoo. Sincroniza primero los pacientes.'
                % patient_ext_id
            )

        doctor = raw.get('doctor') or {}
        write_vals = {
            'partner_id': partner.id,
            'reservation_date': raw.get('date'),
            'reservation_time': raw.get('time'),
            'status': 'COMPLETED',
            'attention_type': raw.get('attentionType'),
            'sub_specialty': raw.get('subSpecialtyName'),
            'service_type_external_id': raw.get('serviceTypeId'),
            'service_type_name': raw.get('serviceType'),
            'branch_name': raw.get('branchName'),
            'doctor_name': doctor.get('fullName'),
            'notes': raw.get('notes'),
            'diagnosis': raw.get('diagnosis'),
        }
        write_vals.update(self._core_oct2026_vals(
            raw,
            ('endTime', 'durationMinutes', 'environmentId', 'environmentName'),
        ))

        branch_raw = raw.get('branch') or {}
        branch = self.env['rehalife.branch'].sudo()._get_or_create_from_external(
            raw.get('branchId') or branch_raw.get('id'),
            raw.get('branchName') or branch_raw.get('name'),
        )

        paid = raw.get('paid')
        try:
            paid_amount_val = float(raw.get('paidAmount') or 0)
        except (TypeError, ValueError):
            paid_amount_val = 0.0

        target_status = 'paid' if (paid is True and paid_amount_val > 0) else 'pending'

        existing = self.search([('external_id', '=', external_id)], limit=1)

        if existing:
            # Completar la sucursal si faltaba. No altera el resultado ('action')
            # que se devuelve abajo: el wizard cuenta por esos valores.
            if branch and not existing.branch_id:
                existing.write({'branch_id': branch.id})
                _logger.info('[ImportReservations] Sucursal asignada a %s: %s', external_id, branch.name)

            # Nunca pisar si Odoo ya generó una factura o avanzó a invoiced
            if existing.invoice_id or existing.invoice_status == 'invoiced':
                _logger.info('[ImportReservations] Omitida %s (ya facturada en Odoo)', external_id)
                return {'action': 'skipped', 'external_id': external_id, 'reason': 'already_invoiced'}

            # Ya está pagada en Odoo, no tocar
            if existing.invoice_status == 'paid':
                _logger.info('[ImportReservations] Omitida %s (ya pagada)', external_id)
                return {'action': 'skipped', 'external_id': external_id, 'reason': 'already_paid'}

            # Pendiente en Odoo, pero el backend dice que ya fue pagada → actualizar
            if existing.invoice_status == 'pending' and target_status == 'paid':
                update_vals = {'invoice_status': 'paid'}
                if paid_amount_val > 0:
                    update_vals['paid_amount'] = paid_amount_val
                existing.write(update_vals)
                _logger.info('[ImportReservations] Actualizada a pagada: %s', external_id)
                return {'action': 'updated_to_paid', 'external_id': external_id, 'id': existing.id}

            _logger.info('[ImportReservations] Omitida %s (ya existe sin cambios)', external_id)
            return {'action': 'skipped', 'external_id': external_id, 'reason': 'already_exists'}

        # Crear nueva reserva
        write_vals['external_id'] = external_id
        write_vals['invoice_status'] = target_status
        if paid_amount_val > 0:
            write_vals['paid_amount'] = paid_amount_val
        if branch:
            write_vals['branch_id'] = branch.id

        new_rec = self.create(write_vals)
        _logger.info('[ImportReservations] Creada: %s (invoice_status=%s)', external_id, target_status)
        return {'action': 'created', 'external_id': external_id, 'id': new_rec.id}

    @api.model
    def _backfill_branch_id(self):
        """Asigna branch_id a reservas antiguas a partir de branch_name.

        Búsqueda EXACTA por nombre en rehalife.branch (no crea sucursales). Un
        write por grupo de nombre, no uno por registro. Los nombres sin
        coincidencia (o con más de una sucursal con ese nombre) se devuelven
        para que el admin cree/corrija la sucursal y vuelva a ejecutarlo.
        """
        Branch = self.env['rehalife.branch'].with_context(active_test=False)
        base_domain = [('branch_id', '=', False), ('branch_name', '!=', False)]
        groups = self._read_group(base_domain, ['branch_name'], ['__count'])

        actualizadas = sin_match = 0
        nombres_sin_match = []
        for branch_name, count in groups:
            branches = Branch.search([('name', '=', branch_name)], limit=2)
            if len(branches) != 1:
                sin_match += count
                nombres_sin_match.append(branch_name)
                continue
            reservations = self.search(base_domain + [('branch_name', '=', branch_name)])
            reservations.write({'branch_id': branches.id})
            actualizadas += len(reservations)

        _logger.info(
            '[Backfill] Sucursales asignadas: %d reservas actualizadas, %d sin match (%s).',
            actualizadas, sin_match, ', '.join(nombres_sin_match) or '-',
        )
        return {
            'actualizadas': actualizadas,
            'sin_match': sin_match,
            'nombres_sin_match': nombres_sin_match,
        }

    # ─── POS: restricción por sucursal (Fase 3) ──────────────────────────────
    @api.model
    def _is_pos_branch_restricted(self):
        """True si el usuario actual es recepcionista restringido por sucursal.

        Mismo criterio que las reglas de la Fase 2: las reglas de grupo se
        combinan con OR, así que un administrador (Rehalife o Ajustes) que
        además sea recepcionista NO queda restringido.
        """
        user = self.env.user
        return (
            user.has_group('rehalife_o18.group_rehalife_receptionist')
            and not user.has_group('rehalife_o18.group_rehalife_admin')
            and not user.has_group('base.group_system')
        )

    @api.model
    def get_pos_branch_info(self):
        """Sucursal del usuario para el diálogo "Reservas" del POS.

        Se consulta con orm.call al abrir el diálogo (no se carga
        rehalife.branch como modelo del POS). Solo informativo: el filtro real
        de las reservas lo hace la regla de registro.
        """
        branch = self.env.user.rehalife_branch_id
        return {
            'restricted': self._is_pos_branch_restricted(),
            'branch_id': branch.id or False,
            'branch_name': branch.sudo().name or '',
        }

    # ─── POS: estado del servicio de la reserva ──────────────────────────────
    # Orden de "cercanía" a estar listo: si un servicio tiene varias variantes
    # se informa la mejor. Por producto, las fallas se priorizan
    # not_found > not_in_pos > not_homologated (ver _pos_product_status).
    _POS_SERVICE_STATUS_RANK = {'ready': 0, 'not_homologated': 1, 'not_in_pos': 2}

    @staticmethod
    def _pos_product_status(product):
        if not product:
            return 'not_found'
        if not product.available_in_pos:
            return 'not_in_pos'
        # siat_homologado: campo calculado de alpha_siat (product.template).
        if not product.siat_homologado:
            return 'not_homologated'
        return 'ready'

    @api.model
    def get_pos_service_status(self, reservation_ids):
        """Estado del servicio de cada reserva para cobrarla en el POS.

        Devuelve {reservation_id: {status, product_id, product_name, list_price,
        message}} en una sola llamada (un solo search de productos para todas).
        Sin sudo(): solo se aceptan reservas que el usuario ya puede ver.
        Se busca el producto con el mismo criterio de siempre
        (product_tmpl_id.rehalife_external_id = service_type_external_id,
        producto activo).
        """
        reservations = self.browse(reservation_ids or []).exists()
        ext_ids = list({
            r.service_type_external_id for r in reservations if r.service_type_external_id
        })

        best_by_ext = {}
        if ext_ids:
            products = self.env['product.product'].search(
                [('product_tmpl_id.rehalife_external_id', 'in', ext_ids)], order='id',
            )
            for product in products:
                ext_id = product.product_tmpl_id.rehalife_external_id
                current = best_by_ext.get(ext_id)
                rank = self._POS_SERVICE_STATUS_RANK[self._pos_product_status(product)]
                if not current or rank < self._POS_SERVICE_STATUS_RANK[self._pos_product_status(current)]:
                    best_by_ext[ext_id] = product

        messages = {
            'not_found': 'No existe un producto en Odoo para el servicio %s.',
            'not_in_pos': 'El servicio %s no está disponible en el Punto de Venta.',
            'not_homologated': 'El servicio %s no está homologado para SIAT.',
        }
        result = {}
        for reservation in reservations:
            product = best_by_ext.get(reservation.service_type_external_id) \
                or self.env['product.product']
            status = self._pos_product_status(product)
            service_name = (
                reservation.service_type_name
                or reservation.service_type_external_id
                or '(sin servicio)'
            )
            ready = status == 'ready'
            result[reservation.id] = {
                'status': status,
                'product_id': product.id if ready else False,
                'product_name': product.name or '',
                # Mismo precio de lista que usaba el cobro (sin cambios en montos).
                'list_price': product.list_price if ready else 0.0,
                'message': messages[status] % service_name if not ready else '',
            }
        return result