# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RehalifeNotaConformidad(models.Model):
    _name = 'rehalife.nota.conformidad'
    _description = 'Nota de Conformidad'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fecha_emision desc, id desc'

    name = fields.Char(
        string='Referencia', required=True, copy=False, readonly=True, default='/',
    )

    # ── Administrativo / contable ────────────────────────────────────────────
    partner_id = fields.Many2one('res.partner', string='Paciente', tracking=True)
    aseguradora_id = fields.Many2one(
        'res.partner', string='Aseguradora',
        domain="[('is_aseguradora', '=', True)]",
        tracking=True,
    )
    reservation_id = fields.Many2one('rehalife.reservation', string='Reserva')
    pedido_marco_id = fields.Many2one(
        'sale.order', string='Pedido de Venta Marco',
        domain="[('es_pedido_marco', '=', True)]",
        tracking=True,
    )
    pedido_marco_line_id = fields.Many2one(
        'sale.order.line', string='Línea del Pedido Marco',
        domain="[('order_id', '=', pedido_marco_id)]",
    )
    product_id = fields.Many2one(
        'product.product', string='Servicio',
        related='pedido_marco_line_id.product_id', store=True, readonly=True,
    )
    cantidad = fields.Float(string='Cantidad', default=1.0, readonly=True)
    # El "Precio Unitario" de la línea del Pedido de Venta Marco YA NO es un
    # monto en Bs. — es el PORCENTAJE (0-100) que la aseguradora cubre de
    # ese servicio (decisión confirmada con el usuario, 2026-09-12). Se
    # sigue llamando `price_unit` del lado de `sale.order.line` (campo
    # nativo de Odoo, no se renombra ahí — ver
    # rehalife_seguros_sale_order_line.py para la validación 0-100), pero
    # de este lado se expone con el nombre correcto.
    porcentaje_cobertura = fields.Float(
        string='% Cobertura Aseguradora',
        related='pedido_marco_line_id.price_unit', store=True, readonly=True,
    )
    # Monto real en Bs. que paga la aseguradora — precio real del servicio
    # (product_id.lst_price) × porcentaje_cobertura/100, redondeado a 2
    # decimales de moneda ("en casos necesarios manejar hasta 2 decimales
    # para los centavos"). Este es el monto que realmente se factura (ver
    # _generar_factura) — `porcentaje_cobertura` es solo el dato de origen.
    monto_cubierto = fields.Monetary(
        string='Monto Cubierto (Bs.)', compute='_compute_monto_cubierto', store=True,
    )
    importe_total = fields.Monetary(
        string='Importe Total', compute='_compute_importe_total', store=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda',
        related='pedido_marco_id.currency_id', store=True, readonly=True,
    )
    # 'facturada' se dispara cuando se PUBLICA (posted) la factura que la
    # incluye, no cuando se genera en borrador — ver account.move.action_post()
    # en rehalife_seguros_account_move.py. 'pagada' se dispara cuando esa
    # factura queda payment_state='paid' — ver
    # account.move._compute_payment_state() en el mismo archivo. Decisión
    # confirmada con el usuario (2026-09-08): son dos hechos distintos y
    # separados en el tiempo, no un solo paso.
    # NOTA (2026-09-11, corregida el 2026-09-12 — HU-18): aprobar una NC ya
    # NO genera su factura sola. La factura se genera a mano, con uno de
    # dos botones: "Generar Factura" en la propia NC (individual —
    # action_generar_factura) o "Facturar NC" en el Pedido de Venta Marco
    # (agrupado: TODAS las NC en 'aprobada' sin factura de ese pedido, en
    # UNA sola factura con una línea por NC — sale.order.action_facturar_notas_conformidad
    # → rehalife.nota.conformidad._generar_factura_agrupada). El Pedido de
    # Venta Marco sigue sin ser el trigger automático — solo el lugar desde
    # donde se dispara la facturación en lote (HU-18: "La facturación
    # deberá realizarse desde el Pedido de Venta Marco correspondiente").
    # NO se agregó un estado "Completo" (pedido explícito del usuario): se
    # reusa 'facturada', que ya se maneja igual que antes — se dispara
    # cuando la factura se PUBLICA (ver más abajo), no al generarla.
    estado = fields.Selection([
        ('pendiente', 'Pendiente de Aprobación'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
        ('facturada', 'Facturada'),
        ('pagada', 'Pagada'),
        ('regularizada', 'Regularizada'),
    ], string='Estado', default='pendiente', tracking=True, required=True)
    factura_id = fields.Many2one('account.move', string='Factura', readonly=True, copy=False)
    fecha_emision = fields.Date(string='Fecha de Emisión', default=fields.Date.context_today)

    # La NC puede generarse ANTES de que termine la atención (ver
    # ESTADOS_FACTURABLES en rehalife_seguros_reservation.py: En Sala, En
    # Consulta o Completada) — este campo distingue, al momento de revisarla
    # (ej. la aseguradora, o un administrador), si el paciente ya fue
    # atendido de verdad o la reserva todavía sigue en curso. Se recalcula
    # solo con el estado actual de la reserva, no queda "congelado" al
    # momento de crear la NC.
    paciente_atendido = fields.Boolean(
        string='Paciente Atendido', compute='_compute_paciente_atendido', store=True,
    )

    @api.depends('reservation_id.status')
    def _compute_paciente_atendido(self):
        for rec in self:
            rec.paciente_atendido = rec.reservation_id.status == 'COMPLETED'

    # ── Clínico (autocompletado desde la reserva, editable después) ─────────
    institucion_id = fields.Many2one(
        'res.company', string='Institución', default=lambda self: self.env.company,
    )
    documento_identidad = fields.Char(
        string='Documento de Identidad', related='partner_id.vat', readonly=True,
    )
    fecha_nacimiento = fields.Date(
        string='Fecha de Nacimiento', related='partner_id.birth_date', readonly=True,
    )
    fecha_atencion = fields.Date(
        string='Fecha de Atención', related='reservation_id.reservation_date', readonly=True,
    )
    servicio_nombre = fields.Char(string='Servicio Prestado')
    diagnostico = fields.Text(string='Diagnóstico')
    procedimientos = fields.Text(string='Procedimientos')
    estudios_complementarios = fields.Text(string='Estudios Complementarios')
    tratamiento_indicado = fields.Text(string='Tratamiento Indicado')
    medico_nombre = fields.Char(string='Médico')
    medico_matricula = fields.Char(string='Matrícula del Médico')

    @api.depends('product_id', 'porcentaje_cobertura', 'currency_id')
    def _compute_monto_cubierto(self):
        for rec in self:
            precio_real = rec.product_id.lst_price if rec.product_id else 0.0
            monto = precio_real * (rec.porcentaje_cobertura or 0.0) / 100.0
            rec.monto_cubierto = rec.currency_id.round(monto) if rec.currency_id else round(monto, 2)

    @api.depends('cantidad', 'monto_cubierto')
    def _compute_importe_total(self):
        for rec in self:
            rec.importe_total = (rec.cantidad or 0.0) * (rec.monto_cubierto or 0.0)

    @api.onchange('reservation_id')
    def _onchange_reservation_id(self):
        for rec in self:
            if rec.reservation_id:
                rec.partner_id = rec.reservation_id.partner_id
                rec.aseguradora_id = rec.reservation_id.aseguradora_id
                rec.pedido_marco_id = rec.reservation_id.pedido_marco_id
                rec.servicio_nombre = rec.reservation_id.service_type_name
                rec.diagnostico = rec.reservation_id.diagnosis
                rec.medico_nombre = rec.reservation_id.doctor_name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'rehalife.nota.conformidad'
                ) or '/'
        records = super().create(vals_list)
        for rec in records:
            if rec.pedido_marco_line_id:
                rec.pedido_marco_line_id.qty_conformidad += rec.cantidad
        return records

    def _resolve_pedido_marco_line(self, reservation):
        """Busca en el pedido marco la línea correspondiente al servicio de la
        reserva. Si el pedido marco tiene una sola línea, se asume esa.

        BUG real de producción (2026-09-16): con varias líneas, antes se
        calzaba por SUBSTRING del nombre (`service_name in product.name`) —
        con productos como "FISIOTERAPIA" y "Fisioterapia . 10 sesiones
        CDLA", el segundo nombre CONTIENE al primero como texto, así que
        ambos "matcheaban" → quedaba ambiguo (`len(match) != 1`) → se
        lanzaba UserError, atrapado en silencio por
        `_asegurar_pedido_marco_y_nota_conformidad` — la reserva se quedaba
        con `pedido_marco_id` puesto pero SIN Nota de Conformidad, sin
        ningún aviso visible para el usuario.

        Fix: primero intenta un match EXACTO por producto — el mismo que ya
        usa `reservation._resolve_product_servicio()` (match único por
        `rehalife_external_id`, sin ambigüedad posible, ya usado del lado
        del split paciente/aseguradora). Si esa reserva no tiene un
        `service_type_external_id` resoluble (o el pedido marco no incluye
        ese producto exacto), cae a un match por nombre — pero EXACTO, no
        substring, para no repetir el mismo bug con otro par de productos.
        """
        order = reservation.pedido_marco_id
        lines = order.order_line.filtered(lambda l: not l.display_type)
        if len(lines) == 1:
            return lines

        product = reservation._resolve_product_servicio()
        if product:
            match = lines.filtered(lambda l: l.product_id == product)
            if len(match) == 1:
                return match

        service_name = (reservation.service_type_name or '').strip().lower()
        if service_name:
            match = lines.filtered(
                lambda l: l.product_id and (l.product_id.name or '').strip().lower() == service_name
            )
            if len(match) == 1:
                return match

        raise UserError(
            'No se pudo determinar automáticamente la línea del Pedido de Venta '
            'Marco "%s" para el servicio "%s" de la reserva %s. '
            'Vincule la línea manualmente en la Nota de Conformidad.'
            % (order.name, reservation.service_type_name, reservation.external_id)
        )

    @api.model
    def _generar_desde_reservation(self, reservation):
        """Crea (si no existe) la Nota de Conformidad para una reserva en
        modalidad 'seguro' ya completada. No duplica si la reserva ya tiene
        una NC asociada.
        """
        if reservation.nota_conformidad_ids:
            _logger.info(
                '[Seguros] Reserva %s ya tiene Nota de Conformidad, no se duplica.',
                reservation.external_id,
            )
            return reservation.nota_conformidad_ids[0]

        if not reservation.aseguradora_id or not reservation.pedido_marco_id:
            raise UserError(
                'La reserva %s está en modalidad Seguro pero no tiene Aseguradora '
                'o Pedido de Venta Marco asignados.' % reservation.external_id
            )

        line = self._resolve_pedido_marco_line(reservation)

        vals = {
            'partner_id': reservation.partner_id.id,
            'aseguradora_id': reservation.aseguradora_id.id,
            'reservation_id': reservation.id,
            'pedido_marco_id': reservation.pedido_marco_id.id,
            'pedido_marco_line_id': line.id,
            'servicio_nombre': reservation.service_type_name,
            'diagnostico': reservation.diagnosis,
            'medico_nombre': reservation.doctor_name,
        }
        return self.create(vals)

    def _prepare_invoice_line_vals(self):
        """Dict (0,0,{...}) para UNA línea de factura a partir de esta NC —
        usado tanto por la factura individual como por la agrupada, para no
        duplicar la lógica de qué va en cada línea."""
        self.ensure_one()
        line = self.pedido_marco_line_id
        nombre_linea = '%s — %s (%s)' % (
            self.servicio_nombre or line.product_id.display_name,
            self.partner_id.name or '',
            self.name,
        )
        return (0, 0, {
            'product_id': line.product_id.id,
            'name': nombre_linea,
            'quantity': self.cantidad,
            # El monto REAL en Bs. (precio del servicio × % de cobertura) —
            # no el porcentaje crudo.
            'price_unit': self.monto_cubierto,
            'tax_ids': [(6, 0, line.tax_id.ids)],
            'sale_line_ids': [(6, 0, [line.id])],
        })

    def _generar_factura_agrupada(self):
        """Genera UNA factura (borrador) para todas las NC en `self` — una
        línea por NC, trazable a su paciente y servicio (no se agregan
        varios pacientes en una sola línea). `self` puede ser una sola NC
        (botón "Generar Factura" individual) o varias del mismo Pedido de
        Venta Marco (botón "Facturar NC" agrupado, HU-18) — todas deben ser
        de la misma aseguradora (un Pedido de Venta Marco siempre lo es).
        Ignora las que ya tengan factura (no duplica). No valida `estado`
        aquí — eso lo hacen los botones que llaman a este método."""
        notas = self.filtered(lambda n: not n.factura_id)
        if not notas:
            return self.env['account.move']

        sin_datos = notas.filtered(
            lambda n: not n.pedido_marco_line_id or not n.aseguradora_id
        )
        if sin_datos:
            raise UserError(
                'Estas Notas de Conformidad no tienen línea de Pedido de '
                'Venta Marco o Aseguradora asignada — no se pueden '
                'facturar: %s' % ', '.join(sin_datos.mapped('name'))
            )

        aseguradoras = notas.mapped('aseguradora_id')
        if len(aseguradoras) != 1:
            raise UserError(
                'No se puede generar una sola factura para Notas de '
                'Conformidad de distintas aseguradoras: %s'
                % ', '.join(aseguradoras.mapped('name'))
            )

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': aseguradoras.id,
            'invoice_origin': ', '.join(notas.mapped('name')),
            'invoice_line_ids': [nc._prepare_invoice_line_vals() for nc in notas],
        })
        notas.write({'factura_id': invoice.id})
        return invoice

    def action_generar_factura(self):
        """Botón individual en la propia NC — genera su factura (una NC,
        una factura). Reusa _generar_factura_agrupada, que también acepta
        un solo registro."""
        for rec in self:
            if rec.estado != 'aprobada':
                raise UserError(
                    'Solo se puede generar factura para una Nota de '
                    'Conformidad en estado Aprobada — "%s" está en "%s".'
                    % (rec.name, dict(rec._fields['estado'].selection).get(rec.estado))
                )
        invoice = self._generar_factura_agrupada()
        return self._action_factura_generada_notification(invoice)

    def _action_factura_generada_notification(self, invoice):
        """Notificación de éxito + redirige a la factura recién generada
        (pedido explícito del usuario, 2026-09-12) — usada tanto por
        `action_generar_factura` (individual) como por
        `sale.order.action_facturar_notas_conformidad` (agrupado)."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Factura generada',
                'message': '%d Nota(s) de Conformidad facturada(s): %s.' % (
                    len(self), ', '.join(self.mapped('name')),
                ),
                'type': 'success',
                'sticky': True,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': 'Factura',
                    'res_model': 'account.move',
                    'res_id': invoice.id,
                    'views': [(False, 'form')],
                    'view_mode': 'form',
                    'target': 'current',
                },
            },
        }

    def action_aprobar(self):
        for rec in self:
            if rec.estado != 'pendiente':
                raise UserError(
                    'Solo se pueden aprobar Notas de Conformidad en estado Pendiente.'
                )
            rec.estado = 'aprobada'
            if rec.pedido_marco_line_id:
                rec.pedido_marco_line_id.qty_confirmada += rec.cantidad

    def action_rechazar(self):
        for rec in self:
            if rec.estado != 'pendiente':
                raise UserError(
                    'Solo se pueden rechazar Notas de Conformidad en estado Pendiente.'
                )
            rec.estado = 'rechazada'

    def action_regularizar(self):
        for rec in self:
            if rec.factura_id:
                raise UserError(
                    'No se puede regularizar la Nota de Conformidad "%s": ya fue '
                    'incluida en la factura %s.' % (rec.name, rec.factura_id.name)
                )
            if rec.estado == 'regularizada':
                raise UserError('Esta Nota de Conformidad ya está regularizada.')

            line = rec.pedido_marco_line_id
            if line:
                line.qty_conformidad -= rec.cantidad
                if rec.estado == 'aprobada':
                    line.qty_confirmada -= rec.cantidad

            rec.with_context(rehalife_seguros_allow_cantidad_write=True).write({
                'cantidad': 0.0,
                'estado': 'regularizada',
            })

    def write(self, vals):
        if 'cantidad' in vals and not self.env.context.get('rehalife_seguros_allow_cantidad_write'):
            raise UserError(
                'La cantidad de una Nota de Conformidad no se edita directamente; '
                'use la acción "Regularizar" para anularla.'
            )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.estado == 'facturada':
                raise UserError(
                    'No se puede eliminar la Nota de Conformidad "%s": ya fue '
                    'facturada.' % rec.name
                )
            if rec.estado == 'pagada':
                raise UserError(
                    'No se puede eliminar la Nota de Conformidad "%s": ya fue '
                    'pagada.' % rec.name
                )
            if rec.estado == 'regularizada':
                raise UserError(
                    'No se puede eliminar la Nota de Conformidad "%s": está '
                    'regularizada, no se borra.' % rec.name
                )
        return super().unlink()
