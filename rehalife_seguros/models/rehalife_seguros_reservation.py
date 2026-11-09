# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Estados de la reserva a partir de los cuales se genera la Nota de
# Conformidad. Pagos anticipados, Fase 4 (decisión confirmada, plan
# punto 9): la NC nace SOLO al completar la atención. Reemplaza la decisión
# del 2026-09-17 (('IN_ROOM', 'IN_CONSULTATION', 'COMPLETED')): esa existía
# porque el copago del POS salía de la NC; desde la Fase 4 el copago sale
# del Pedido de Venta Marco del mes (_get_cobertura_info), así que la NC ya
# no hace falta para cobrar.
ESTADOS_FACTURABLES = ('COMPLETED',)

# Estados en los que la atención ya no va a ocurrir: si la reserva de seguro
# llega acá con una NC viva, esa NC se regulariza (o se alerta si ya está
# facturada) — ver nota_conformidad._regularizar_por_cancelacion_reserva().
ESTADOS_CANCELADOS = ('CANCELLED', 'NO_SHOW')


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
    # NC.
    # ⚠️ Pagos anticipados, Fase 4 (2026-11-09): sin NC, el copago YA NO es
    # "precio completo": sale de la línea del PVM del MES de la reserva (ver
    # _get_cobertura_info). Sin PVM aplicable la reserva no es cobrable en el
    # POS (nunca se cobra precio completo a un paciente de seguro).
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

    # ── Pagos anticipados, Fase 4: congelamiento al pagar ──────────────────
    # Se llenan UNA vez, en el servidor, cuando el POS marca la reserva como
    # pagada (rehalife_seguros_pos_order.py) y nunca se sobrescriben. La NC
    # usa estos valores (no el % actual del PVM): cambiar el % del PVM solo
    # afecta reservas no pagadas.
    precio_servicio_congelado = fields.Float(
        string='Precio del Servicio (congelado)', readonly=True, copy=False, digits=(16, 2),
    )
    porcentaje_cobertura_congelado = fields.Float(
        string='% Cobertura (congelado)', readonly=True, copy=False, digits=(16, 2),
    )
    monto_paciente_congelado = fields.Float(
        string='Copago Paciente (congelado)', readonly=True, copy=False, digits=(16, 2),
    )
    monto_aseguradora_congelado = fields.Float(
        string='Monto Aseguradora (congelado)', readonly=True, copy=False, digits=(16, 2),
    )
    fecha_congelamiento = fields.Datetime(
        string='Fecha de Congelamiento', readonly=True, copy=False,
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

    @api.depends('modalidad', 'aseguradora_id', 'reservation_date', 'service_type_external_id',
                 'pedido_marco_id', 'fecha_congelamiento', 'nota_conformidad_ids.monto_cubierto')
    def _compute_cobertura_seguro(self):
        # Sin _logger.warning por reserva (Fase 4): el diálogo del POS lee
        # muchas reservas a la vez. Sin cobertura conocida, el copago queda
        # en 0 y la reserva NO es cobrable (ver _get_cobertura_info): nunca
        # se cobra el precio completo a un paciente de seguro.
        for rec in self:
            if rec.modalidad != 'seguro':
                rec.monto_cobertura_seguro = 0.0
                rec.monto_a_pagar_paciente = 0.0
                continue
            info = rec._get_cobertura_info()
            rec.monto_cobertura_seguro = info['monto_aseguradora']
            rec.monto_a_pagar_paciente = info['monto_paciente']

    def _producto_para_cobertura(self):
        """Producto con el que el POS cobra la reserva (el 'ready' de
        get_pos_service_status) o, si no está listo, el de siempre."""
        self.ensure_one()
        status = self.get_pos_service_status(self.ids).get(self.id) or {}
        if status.get('product_id'):
            return self.env['product.product'].browse(status['product_id'])
        return self._resolve_product_servicio()

    def _get_cobertura_info(self, crear_pvm=False, producto=None):
        """Cobertura de una reserva de seguro. Devuelve {pvm, linea, precio,
        porcentaje, monto_aseguradora, monto_paciente, cobrable, motivo,
        origen, nota}. Prioridad:

        (a) valores congelados (la reserva ya se pagó);
        (b) Nota de Conformidad existente (no regularizada);
        (c) línea del PVM del MES de reservation_date para el producto. Si no
            existe el PVM: con crear_pvm=True se crea (clonando el más
            reciente, ver sale.order._asegurar_pedido_marco); con False se
            calcula con la línea del PVM que se clonaría y origen
            'pvm_a_crear' (solo informativo, para listar sin crear nada);
        (d) nada aplicable → cobrable=False con el motivo.

        Montos con el mismo redondeo que la NC: aseguradora = round(precio ×
        %/100), paciente = precio − aseguradora.
        """
        self.ensure_one()
        SaleOrder = self.env['sale.order'].sudo()
        SaleOrderLine = self.env['sale.order.line'].sudo()
        info = {
            'pvm': SaleOrder, 'linea': SaleOrderLine,
            'precio': 0.0, 'porcentaje': 0.0, 'monto_aseguradora': 0.0,
            'monto_paciente': 0.0, 'cobrable': False, 'motivo': '', 'origen': '', 'nota': '',
        }
        currency = self.env.company.currency_id

        # (a) Congelado
        if self.fecha_congelamiento:
            info.update(
                pvm=self.pedido_marco_id.sudo(), precio=self.precio_servicio_congelado,
                porcentaje=self.porcentaje_cobertura_congelado,
                monto_aseguradora=self.monto_aseguradora_congelado,
                monto_paciente=self.monto_paciente_congelado,
                cobrable=True, origen='congelado',
            )
            return info

        # (b) Nota de Conformidad existente
        nc = self.nota_conformidad_ids.sudo().filtered(lambda n: n.estado != 'regularizada')[:1]
        if nc:
            precio = nc.product_id.lst_price if nc.product_id else 0.0
            info.update(
                pvm=nc.pedido_marco_id, linea=nc.pedido_marco_line_id, precio=precio,
                porcentaje=nc.porcentaje_cobertura, monto_aseguradora=nc.monto_cubierto,
                monto_paciente=(nc.currency_id or currency).round(precio - nc.monto_cubierto),
                cobrable=True, origen='nota_conformidad',
            )
            return info

        # (c) PVM del mes
        if not self.aseguradora_id:
            info['motivo'] = 'La reserva de seguro no tiene aseguradora asignada.'
            return info
        if not self.reservation_date:
            info['motivo'] = 'La reserva de seguro no tiene fecha.'
            return info
        producto = producto or self._producto_para_cobertura()
        if not producto:
            info['motivo'] = 'No existe un producto en Odoo para el servicio %s.' % (
                self.service_type_name or self.service_type_external_id or '(sin servicio)')
            return info

        periodo = self.reservation_date.replace(day=1)
        pvm = self.pedido_marco_id.sudo()
        a_crear = False
        if not (pvm and pvm.state == 'sale' and pvm.periodo == periodo
                and pvm.partner_id == self.aseguradora_id):
            res = SaleOrder._asegurar_pedido_marco(self.aseguradora_id, periodo, crear=crear_pvm)
            pvm = res['pedido']
            if not pvm:
                if res['motivo'] or not res['fuente']:
                    info['motivo'] = res['motivo'] or 'Sin Pedido de Venta Marco aplicable.'
                    return info
                # crear_pvm=False y hay de dónde clonar: se calcula con la
                # fuente; el PVM se crea recién al cobrar.
                pvm = res['fuente']
                a_crear = True
                info['nota'] = 'El Pedido Marco de %s se creará al cobrar copiando %s.' % (
                    SaleOrder._nombre_mes(periodo), pvm.nombre_periodo or pvm.name)

        try:
            linea = self.env['rehalife.nota.conformidad'].sudo()._resolve_pedido_marco_line(
                self, order=pvm, product=producto)
        except UserError:
            info['motivo'] = 'El Pedido Marco %s no tiene una línea para el servicio %s.' % (
                pvm.nombre_periodo or pvm.name, producto.display_name)
            return info

        cur = pvm.currency_id or currency
        precio = producto.lst_price
        porcentaje = linea.price_unit
        monto_aseguradora = cur.round(precio * (porcentaje or 0.0) / 100.0)
        info.update(
            pvm=SaleOrder if a_crear else pvm,
            linea=SaleOrderLine if a_crear else linea,
            precio=precio, porcentaje=porcentaje,
            monto_aseguradora=monto_aseguradora,
            monto_paciente=cur.round(precio - monto_aseguradora),
            cobrable=True, origen='pvm_a_crear' if a_crear else 'pvm',
        )
        return info

    @api.model
    def get_cobertura_info(self, reservation_ids):
        """RPC (POS y Next, solo lectura: NO crea PVM). Por reserva:
        {modalidad, aseguradora_id, aseguradora_name, cobrable, motivo,
        origen, nota, precio, porcentaje, monto_aseguradora, monto_paciente,
        pvm_id, pvm_name, linea_id, congelado, fecha_congelamiento,
        nota_conformidad}."""
        result = {}
        for rec in self.browse(reservation_ids or []).exists():
            nc = rec.nota_conformidad_ids.sudo()[:1]
            base = {
                'modalidad': rec.modalidad or 'particular',
                'aseguradora_id': rec.aseguradora_id.id or False,
                'aseguradora_name': rec.aseguradora_id.name or '',
                'congelado': bool(rec.fecha_congelamiento),
                'fecha_congelamiento': fields.Datetime.to_string(rec.fecha_congelamiento)
                if rec.fecha_congelamiento else False,
                'nota_conformidad': {
                    'id': nc.id, 'name': nc.name, 'estado': nc.estado,
                    'estado_label': dict(nc._fields['estado'].selection).get(nc.estado, nc.estado),
                } if nc else False,
            }
            if rec.modalidad != 'seguro':
                base.update(cobrable=True, motivo='', origen='particular', nota='', precio=0.0,
                            porcentaje=0.0, monto_aseguradora=0.0, monto_paciente=0.0,
                            pvm_id=False, pvm_name='', linea_id=False)
                result[rec.id] = base
                continue
            info = rec._get_cobertura_info()
            base.update(
                cobrable=info['cobrable'], motivo=info['motivo'], origen=info['origen'],
                nota=info['nota'], precio=info['precio'], porcentaje=info['porcentaje'],
                monto_aseguradora=info['monto_aseguradora'], monto_paciente=info['monto_paciente'],
                pvm_id=info['pvm'].id or False,
                pvm_name=info['pvm'].nombre_periodo or info['pvm'].name or '',
                linea_id=info['linea'].id or False,
            )
            result[rec.id] = base
        return result

    def _congelar_cobertura(self):
        """Guarda precio, %, copago y monto de la aseguradora al pagar.
        Nunca sobrescribe (solo reservas de seguro sin fecha_congelamiento).
        Fija también pedido_marco_id si todavía no tiene uno."""
        for rec in self.filtered(lambda r: r.modalidad == 'seguro' and not r.fecha_congelamiento):
            info = rec._get_cobertura_info(crear_pvm=True)
            if not info['cobrable']:
                _logger.warning(
                    '[Seguros] Reserva %s pagada sin cobertura aplicable, no se congela: %s',
                    rec.external_id, info['motivo'],
                )
                continue
            vals = {
                'precio_servicio_congelado': info['precio'],
                'porcentaje_cobertura_congelado': info['porcentaje'],
                'monto_paciente_congelado': info['monto_paciente'],
                'monto_aseguradora_congelado': info['monto_aseguradora'],
                'fecha_congelamiento': fields.Datetime.now(),
            }
            if info['pvm'] and not rec.pedido_marco_id:
                vals['pedido_marco_id'] = info['pvm'].id
            rec.sudo().write(vals)
            _logger.info(
                '[Seguros] Reserva %s: cobertura congelada (precio %.2f, %.2f%%, paciente %.2f, '
                'aseguradora %.2f, origen %s).', rec.external_id, info['precio'],
                info['porcentaje'], info['monto_paciente'], info['monto_aseguradora'], info['origen'],
            )

    @api.model
    def get_pos_charge_info(self, reservation_ids):
        """Extiende el dato de cobro del POS (rehalife_o18) para las reservas
        de seguro: el paciente paga solo su copago."""
        # Fase 4: el copago sale del PVM del mes (_get_cobertura_info). Sin
        # cobertura aplicable la reserva NO es cobrable, y el servidor exige
        # que la línea tenga exactamente el copago (enforce_price). Solo en
        # el control al pagar (contexto rehalife_pos_paying) se crea el PVM
        # que falte.
        crear_pvm = bool(self.env.context.get('rehalife_pos_paying'))
        result = super().get_pos_charge_info(reservation_ids)
        for reservation in self.browse(list(result)).exists():
            info = result[reservation.id]
            info['modalidad'] = reservation.modalidad or 'particular'
            if reservation.modalidad != 'seguro' or not info['chargeable']:
                continue
            producto = self.env['product.product'].browse(info['product_id'])
            try:
                with self.env.cr.savepoint():
                    cob = reservation._get_cobertura_info(crear_pvm=crear_pvm, producto=producto)
            except Exception as e:
                _logger.exception(
                    '[Seguros] Reserva %s: no se pudo calcular la cobertura.', reservation.external_id)
                cob = {'cobrable': False, 'motivo': 'No se pudo calcular la cobertura: %s' % e}
            info['enforce_price'] = True
            if not cob['cobrable']:
                info.update(chargeable=False, reason=cob['motivo'], price_unit=0.0)
                continue
            nota = (' (%s)' % cob['nota']) if cob.get('nota') else ''
            info.update(
                price_unit=cob['monto_paciente'],
                insurer_amount=cob['monto_aseguradora'],
                coverage_pct=cob['porcentaje'],
                line_note='Seguro %.2f%%: cubre %.2f Bs.%s' % (
                    cob['porcentaje'], cob['monto_aseguradora'], nota),
            )
        return result

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
        No se toca rehalife_o18/models/rehalife_reservation.py.

        Además, si una reserva de seguro pasa a CANCELLED/NO_SHOW, regulariza
        sus Notas de Conformidad todavía no facturadas (la atención no
        ocurrió, no se le puede cobrar a la aseguradora)."""
        # Estado ANTES del sync: un CANCELLED repetido sobre una reserva ya
        # cancelada no llega como 'ignored_terminal' desde rehalife_o18 (mismo
        # estado → 'updated'), así que sin esto se volvería a procesar.
        previo = self.search([('external_id', '=', vals.get('external_id'))], limit=1)
        status_previo = previo.status if previo else False
        fecha_previa = previo.reservation_date if previo else False

        result = super().sync_from_nextjs(vals)

        if result.get('action') != 'ignored_terminal':
            record = self.browse(result.get('id'))
            if (record and record.modalidad == 'seguro'
                    and record.status in ESTADOS_CANCELADOS
                    and status_previo not in ESTADOS_CANCELADOS):
                try:
                    record.nota_conformidad_ids._regularizar_por_cancelacion_reserva()
                except Exception:
                    _logger.exception(
                        '[Seguros] Reserva %s: error al regularizar sus Notas de '
                        'Conformidad tras pasar a %s.', record.external_id, record.status,
                    )

        # Reprogramación a otro mes (Fase 4): si todavía no tiene NC, se
        # suelta el PVM para que al completarse tome el del mes nuevo. Si ya
        # se pagó, la NC usará igual el % congelado.
        record = self.browse(result.get('id')) if result.get('id') else self.browse()
        if (record and fecha_previa and record.reservation_date and record.pedido_marco_id
                and (fecha_previa.year, fecha_previa.month)
                != (record.reservation_date.year, record.reservation_date.month)
                and not record.nota_conformidad_ids.filtered(lambda n: n.estado != 'regularizada')):
            _logger.info(
                '[Seguros] Reserva %s reprogramada de %s a %s: se libera el PVM %s.',
                record.external_id, fecha_previa, record.reservation_date,
                record.pedido_marco_id.name,
            )
            record.pedido_marco_id = False

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
