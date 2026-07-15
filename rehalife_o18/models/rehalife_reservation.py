import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


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
        ('PENDING',    'Pendiente'),
        ('COMPLETED',  'Completada'),
        ('CANCELLED',  'Cancelada'),
        ('NO_SHOW',    'No asistió'),
    ], string='Estado', default='PENDING')
    attention_type  = fields.Char(string='Tipo de Atención')
    sub_specialty   = fields.Char(string='Sub-especialidad')
    branch_name     = fields.Char(string='Sucursal')
    doctor_name     = fields.Char(string='Doctor')
    notes           = fields.Text(string='Notas')
    diagnosis       = fields.Text(string='Diagnóstico')

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

    # ─── Acción principal: Enviar a POS ──────────────────────────────────────
    def action_send_to_pos(self):
        self.ensure_one()

        if self.status in ('CANCELLED', 'NO_SHOW'):
            raise UserError('No se puede enviar a caja una reserva cancelada o con ausencia.')

        if self.pos_order_id and self.pos_order_id.state not in ('cancel',):
            raise UserError(
                f'Esta reserva ya tiene la orden POS {self.pos_order_id.name}. '
                'No se puede generar una segunda orden.'
            )

        if self.invoice_status in ('invoiced', 'paid'):
            raise UserError('Esta reserva ya fue facturada o pagada.')

        session = self._get_open_pos_session()
        product = self._get_or_create_consulta_product()

        if not product.product_tmpl_id.available_in_pos:
            product.product_tmpl_id.available_in_pos = True

        price = product.list_price or 0.0

        pos_order_vals = {
            'session_id': session.id,
            'partner_id': self.partner_id.id,
            'state': 'draft',
            'amount_tax': 0.0,
            'amount_total': price,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [(0, 0, {
                'product_id': product.id,
                'full_product_name': f'Consulta — {self.sub_specialty or "General"}',
                'qty': 1,
                'price_unit': price,
                'price_subtotal': price,
                'price_subtotal_incl': price,
                'tax_ids': [(5, 0, 0)],
            })],
        }

        pos_order = self.env['pos.order'].create(pos_order_vals)

        self.write({
            'pos_order_id': pos_order.id,
            'invoice_status': 'invoiced',
        })

        _logger.info(
            'Orden POS %s creada para reserva %s (paciente: %s)',
            pos_order.name, self.external_id, self.partner_id.name,
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pos.order',
            'res_id': pos_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

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

        paid_amount = self.pos_order_id.amount_total or 0.0
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
            'branch_name': vals.get('branch_name'),
            'doctor_name': vals.get('doctor_name'),
            'notes': vals.get('notes'),
            'diagnosis': vals.get('diagnosis'),
        }

        # Buscar si ya existe
        existing = self.search([('external_id', '=', external_id)], limit=1)

        if existing:
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
            'branch_name': raw.get('branchName'),
            'doctor_name': doctor.get('fullName'),
            'notes': raw.get('notes'),
            'diagnosis': raw.get('diagnosis'),
        }

        paid = raw.get('paid')
        try:
            paid_amount_val = float(raw.get('paidAmount') or 0)
        except (TypeError, ValueError):
            paid_amount_val = 0.0

        target_status = 'paid' if (paid is True and paid_amount_val > 0) else 'pending'

        existing = self.search([('external_id', '=', external_id)], limit=1)

        if existing:
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

        new_rec = self.create(write_vals)
        _logger.info('[ImportReservations] Creada: %s (invoice_status=%s)', external_id, target_status)
        return {'action': 'created', 'external_id': external_id, 'id': new_rec.id}