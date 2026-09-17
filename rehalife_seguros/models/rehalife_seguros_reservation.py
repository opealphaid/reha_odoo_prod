# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Estados de la reserva a partir de los cuales ya se puede documentar la
# atención con una Nota de Conformidad. Decisión confirmada con el usuario
# (2026-09-17, reemplaza la del 2026-09-12): ya NO se espera a que termine
# la atención — se genera desde que el paciente LLEGA al consultorio
# (status='IN_ROOM'). Se incluyen también 'IN_CONSULTATION' y 'COMPLETED'
# por si una reserva puntual salta directo a alguno de esos estados sin
# pasar antes por un sync en 'IN_ROOM' (ej. reservas importadas/backfill) —
# no genera duplicados: _asegurar_pedido_marco_y_nota_conformidad() ya
# revisa `if not reservation.nota_conformidad_ids` antes de crear.
#
# Con esto, este criterio vuelve a coincidir con el que ya usa el diálogo
# "Reservas" del POS para decidir cuándo se puede COBRAR la parte del
# paciente (rehalife_o18/static/src/js/reservation_button.js y
# rehalife_o18/models/rehalife_pos.py, lista ['IN_ROOM', 'IN_CONSULTATION',
# 'COMPLETED']) — pero siguen siendo dos listas literales independientes,
# sin import compartido: si se vuelve a desalinear este criterio, hay que
# tocar los dos lados a mano.
ESTADOS_FACTURABLES = ('IN_ROOM', 'IN_CONSULTATION', 'COMPLETED')


class RehalifeReservation(models.Model):
    _inherit = 'rehalife.reservation'

    modalidad = fields.Selection([
        ('particular', 'Particular'),
        ('seguro', 'Seguro'),
    ], string='Modalidad', default='particular')

    aseguradora_id = fields.Many2one(
        'res.partner', string='Aseguradora',
        domain="[('is_aseguradora', '=', True)]",
    )
    pedido_marco_id = fields.Many2one(
        'sale.order', string='Pedido de Venta Marco',
        # 'aseguradora_id' de sale.order se borró (2026-09-12) — el
        # "Customer" (partner_id) de un Pedido de Venta Marco ES la
        # aseguradora ahora, no un campo aparte.
        domain="[('es_pedido_marco', '=', True), ('partner_id', '=', aseguradora_id)]",
    )
    nota_conformidad_ids = fields.One2many(
        'rehalife.nota.conformidad', 'reservation_id', string='Notas de Conformidad',
    )

    # Incidente real de producción (2026-09-16): la generación automática de
    # NC puede fallar por varios motivos (Pedido de Venta Marco sin Periodo,
    # sin confirmar, inexistente, o — el bug real que se dio — ambigüedad al
    # calzar el producto cuando hay varias líneas) y hasta ahora esa falla
    # quedaba SOLO en el log del servidor: nadie se enteraba hasta que
    # alguien preguntaba por qué faltaba la NC. Este campo hace la falla
    # visible en la propia reserva — se limpia solo la próxima vez que el
    # proceso corre y sí funciona (no queda "pegado" mostrando un error
    # viejo ya resuelto).
    nc_error = fields.Char(
        string='Error al Generar Nota de Conformidad', readonly=True, copy=False,
    )

    # ── Split paciente/aseguradora (HU-12, 2026-09-11 — corregido el mismo
    # día: se descartó un modelo aparte de "Cobertura"; y el 2026-09-12: el
    # "precio" de la línea del Pedido Marco pasó a ser un % de cobertura,
    # no un monto en Bs.) ────────────────────────────────────────────────
    # Decisión confirmada con el usuario: NO existe una tabla de cobertura
    # separada. La Nota de Conformidad de la reserva ES la cobertura —
    # cuando se genera (_generar_desde_reservation), queda vinculada a la
    # línea del Pedido de Venta Marco (`pedido_marco_line_id`), y esa línea
    # trae el % que el administrador acordó con la aseguradora para ese
    # servicio (`price_unit`, interpretado como % 0-100 — ver
    # rehalife_seguros_sale_order_line.py). La NC ya calcula el monto real
    # en Bs. (`monto_cubierto` = precio del servicio × %/100) — acá solo se
    # reusa ese valor, no se recalcula el % dos veces. "Si se acepta [la
    # NC], ese monto lo paga la aseguradora" — la aprobación confirma el
    # pago, no cambia el monto: el monto ya es conocido desde que existe la
    # NC. Sin NC todavía (reserva aún no llegó a un estado facturable, o
    # sin Pedido Marco asignado), no hay monto de cobertura conocido — el
    # paciente queda cobrando el precio completo por defecto (nunca se
    # inventa un descuento) hasta que exista la NC.
    #
    # A PROPÓSITO sin store=True: se calculan al vuelo cada vez que se leen
    # (form, list, o el searchRead del POS) para no depender de un compute
    # cruzando a otro modelo (nota_conformidad_ids.monto_cubierto) que
    # podría no invalidarse a tiempo.
    monto_cobertura_seguro = fields.Float(
        string='Monto Cubierto por Seguro', compute='_compute_cobertura_seguro',
    )
    monto_a_pagar_paciente = fields.Float(
        string='Monto a Pagar por el Paciente', compute='_compute_cobertura_seguro',
    )

    def _resolve_product_servicio(self):
        """Producto de Odoo que corresponde al servicio de esta reserva —
        mismo criterio (match exacto por rehalife_external_id) que ya usa
        reservation_button.js del lado del POS, para que ambos lados
        siempre miren el mismo producto."""
        self.ensure_one()
        if not self.service_type_external_id:
            return self.env['product.product']
        return self.env['product.product'].search([
            ('product_tmpl_id.rehalife_external_id', '=', self.service_type_external_id),
        ], limit=1)

    @api.depends('modalidad', 'service_type_external_id', 'nota_conformidad_ids.monto_cubierto')
    def _compute_cobertura_seguro(self):
        for rec in self:
            if rec.modalidad != 'seguro':
                rec.monto_cobertura_seguro = 0.0
                rec.monto_a_pagar_paciente = 0.0
                continue

            nc = rec.nota_conformidad_ids[:1]

            if not nc:
                product = rec._resolve_product_servicio()
                precio_real = product.lst_price if product else 0.0
                _logger.warning(
                    '[Seguros] Reserva %s: todavía no tiene Nota de '
                    'Conformidad (falta llegar a un estado facturable, o no '
                    'tiene Pedido de Venta Marco asignado) — el paciente '
                    'queda cobrando el precio completo (%.2f) hasta que '
                    'exista.', rec.external_id, precio_real,
                )
                rec.monto_cobertura_seguro = 0.0
                rec.monto_a_pagar_paciente = precio_real
                continue

            # Reusa el monto ya calculado por la propia NC — mismo producto
            # (pedido_marco_line_id.product_id), no se recalcula aparte.
            precio_real = nc.product_id.lst_price if nc.product_id else 0.0
            rec.monto_cobertura_seguro = nc.monto_cubierto
            rec.monto_a_pagar_paciente = precio_real - nc.monto_cubierto

    @api.onchange('aseguradora_id')
    def _onchange_aseguradora_id_reset_pedido_marco(self):
        if self.pedido_marco_id and self.pedido_marco_id.partner_id != self.aseguradora_id:
            self.pedido_marco_id = False

    @api.onchange('modalidad')
    def _onchange_modalidad(self):
        if self.modalidad != 'seguro':
            self.aseguradora_id = False
            self.pedido_marco_id = False

    @api.model
    def sync_from_nextjs(self, vals: dict):
        """Extiende el sync base (rehalife_o18) para reflejar modalidad y
        aseguradora en el espejo. Payload nuevo, opcional:
        - modality_type: 'PARTICULAR' | 'SEGURO'
        - insurance_provider_external_id: id de la aseguradora en el backend
          Rehalife (solo cuando modality_type es 'SEGURO')
        No se toca rehalife_o18/models/rehalife_reservation.py."""
        result = super().sync_from_nextjs(vals)

        modality_type = vals.get('modality_type')
        if not modality_type:
            return result

        record = self.browse(result.get('id'))
        if not record:
            return result

        aseguradora = self.env['res.partner']
        if modality_type == 'SEGURO':
            provider_ext_id = vals.get('insurance_provider_external_id')
            if provider_ext_id:
                aseguradora = self.env['res.partner'].search(
                    [('rehalife_external_id', '=', provider_ext_id)], limit=1,
                )

        record.write({
            'modalidad': 'seguro' if modality_type == 'SEGURO' else 'particular',
            'aseguradora_id': aseguradora.id if aseguradora else False,
        })
        record._asegurar_pedido_marco_y_nota_conformidad()
        return result

    # ── Pedido de Venta Marco + Nota de Conformidad automáticos ─────────────
    # Decisión confirmada con el usuario (2026-09-08): al llegar a un estado
    # facturable (ver ESTADOS_FACTURABLES), una reserva de modalidad 'seguro'
    # debe (1) asignarse sola al Pedido de Venta Marco vigente de su
    # aseguradora+período si todavía no tiene uno, y (2) generar su Nota de
    # Conformidad si todavía no tiene una. NUNCA crea un Pedido de Venta Marco
    # nuevo — debe existir ya, creado por un administrador (HU-6); si no
    # existe, solo se registra en el log (no bloquea el sync de la reserva,
    # mismo patrón de "errores de sync silenciosos" del resto del proyecto).
    def _find_pedido_marco_vigente(self):
        self.ensure_one()
        if not self.aseguradora_id or not self.reservation_date:
            return self.env['sale.order']
        periodo = self.reservation_date.replace(day=1)
        return self.env['sale.order'].search([
            ('es_pedido_marco', '=', True),
            ('partner_id', '=', self.aseguradora_id.id),
            ('periodo', '=', periodo),
            ('state', '=', 'sale'),
        ], limit=1)

    def _asegurar_pedido_marco_y_nota_conformidad(self):
        for reservation in self:
            if reservation.modalidad != 'seguro' or reservation.status not in ESTADOS_FACTURABLES:
                continue
            try:
                if not reservation.pedido_marco_id:
                    pedido = reservation._find_pedido_marco_vigente()
                    if not pedido:
                        mensaje = (
                            'Sin Pedido de Venta Marco vigente para "%s" / periodo '
                            '%s — créalo (confirmado, con Periodo) desde Seguros > '
                            'Pedidos de Venta Marco.' % (
                                reservation.aseguradora_id.name,
                                reservation.reservation_date.replace(day=1),
                            )
                        )
                        _logger.warning(
                            '[Seguros] Reserva %s: %s', reservation.external_id, mensaje,
                        )
                        reservation.nc_error = mensaje
                        continue
                    reservation.pedido_marco_id = pedido.id

                if not reservation.nota_conformidad_ids:
                    self.env['rehalife.nota.conformidad']._generar_desde_reservation(reservation)

                # Si llegamos hasta acá sin excepción (NC generada ahora, o ya
                # existía de antes), cualquier error previo queda superado.
                reservation.nc_error = False
            except Exception as e:
                _logger.exception(
                    '[Seguros] No se pudo generar la Nota de Conformidad para la '
                    'reserva %s.', reservation.external_id,
                )
                reservation.nc_error = str(e)

    def action_reintentar_nota_conformidad(self):
        """Botón manual en la reserva (visible cuando hay `nc_error`, o
        modalidad='seguro' en general) — corre exactamente el mismo proceso
        que el sync automático, para cuando la falla ya se corrigió (ej. se
        confirmó/completó el Pedido de Venta Marco) y no va a llegar un
        nuevo cambio de estado desde el frontend que dispare el reintento
        solo (la reserva ya está en un estado terminal). Sin esto, la única
        forma de recuperar una reserva atascada era por consola de Odoo."""
        self._asegurar_pedido_marco_y_nota_conformidad()
        con_error = self.filtered('nc_error')
        if con_error:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Nota de Conformidad',
                    'message': 'Sigue sin poderse generar: %s' % con_error[0].nc_error,
                    'type': 'warning',
                    'sticky': True,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Nota de Conformidad',
                'message': 'Generada correctamente.',
                'type': 'success',
            },
        }
