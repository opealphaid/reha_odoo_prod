# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression

_logger = logging.getLogger(__name__)

_MESES_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre',
    12: 'Diciembre',
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # NOTA (2026-09-12): antes existía un campo `aseguradora_id` aparte,
    # redundante con el "Customer" (`partner_id`) nativo — el pedido
    # de venta marco siempre se factura al mismo partner que ya era su
    # Customer. Decisión confirmada con el usuario: se borró ese campo;
    # ahora `partner_id` ES la aseguradora (relabeled a "Aseguradora" y
    # con domain a is_aseguradora=True, solo en la vista de formulario
    # dedicada a Pedidos de Venta Marco — ver
    # view_order_form_rehalife_seguros_pedido_marco en
    # rehalife_seguros_sale_order_views.xml, no se toca el campo nativo
    # para el resto de Sales Orders/Quotations de Odoo).
    es_pedido_marco = fields.Boolean(string='Es Pedido de Venta Marco', default=False)
    periodo = fields.Date(
        string='Periodo',
        help='Día 1 del mes que representa este pedido marco.',
    )
    nombre_periodo = fields.Char(
        string='Nombre del Periodo', compute='_compute_nombre_periodo', store=True,
    )

    # NOTA (2026-09-11, corregida 2026-09-12 — HU-18): el Pedido de Venta
    # Marco sigue sin ser el trigger AUTOMÁTICO de facturación (documento de
    # estimación/seguimiento, HU-6/HU-7) — pero ahora sí es desde donde se
    # dispara la facturación EN LOTE: botón "Facturar NC"
    # (action_facturar_notas_conformidad) toma todas las NC en estado
    # 'aprobada' sin factura de este pedido y genera UNA sola factura para
    # todas (una línea por NC — ver
    # rehalife.nota.conformidad._generar_factura_agrupada). También existe
    # un botón individual "Generar Factura" en cada NC. Para ver TODAS las
    # facturas generadas a partir de las líneas de este pedido, usa el
    # smart button nativo "Facturas" del formulario (funciona solo porque
    # cada línea de factura lleva `sale_line_ids` apuntando a la línea del
    # pedido marco).
    nota_conformidad_ids = fields.One2many(
        'rehalife.nota.conformidad', 'pedido_marco_id', string='Notas de Conformidad',
    )
    nota_conformidad_count = fields.Integer(
        string='Cant. Notas de Conformidad', compute='_compute_nota_conformidad_count',
    )

    @api.depends('partner_id', 'periodo')
    def _compute_nombre_periodo(self):
        for order in self:
            if order.partner_id and order.periodo:
                mes = _MESES_ES.get(order.periodo.month, '')
                anio = str(order.periodo.year)[-2:]
                order.nombre_periodo = f'{order.partner_id.name}-{mes}{anio}'
            else:
                order.nombre_periodo = False

    def _compute_nota_conformidad_count(self):
        for order in self:
            order.nota_conformidad_count = len(order.nota_conformidad_ids)

    # Bug real de producción (2026-09-17): un Pedido de Venta Marco se
    # guardó con `periodo` = 17/09/2026 (el día en que se lo creó) en vez
    # del día 1 del mes — el "Nombre del Periodo" calculado ("...-Septiembre26")
    # se veía perfecto porque solo usa mes/año, así que nadie notó nada raro
    # a simple vista. Pero `_find_pedido_marco_vigente()` busca por
    # `periodo` EXACTO (= reservation_date con day=1), así que ese pedido
    # nunca calzó con ninguna reserva de esa aseguradora en ese mes — la
    # Nota de Conformidad se quedó sin generar, otra vez en silencio (ver
    # nc_error). En vez de depender de que quien lo carga escriba el día 1
    # a mano, se normaliza acá: cualquier día que se guarde en `periodo` se
    # fuerza al día 1 de ese mes, sin excepción.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('periodo'):
                vals['periodo'] = fields.Date.to_date(vals['periodo']).replace(day=1)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('periodo'):
            vals['periodo'] = fields.Date.to_date(vals['periodo']).replace(day=1)
        return super().write(vals)

    @api.constrains('es_pedido_marco', 'partner_id')
    def _check_pedido_marco_aseguradora(self):
        for order in self:
            if not order.es_pedido_marco:
                continue
            if not order.partner_id:
                raise ValidationError(
                    'Un Pedido de Venta Marco requiere una Aseguradora (Customer).'
                )
            if not order.partner_id.is_aseguradora:
                raise ValidationError(
                    'El Customer de un Pedido de Venta Marco debe ser una '
                    'Aseguradora — marca "Es Aseguradora" en el contacto de '
                    '"%s" primero.' % order.partner_id.name
                )

    # Bug real de producción (2026-09-16): un Pedido de Venta Marco se
    # guardó sin `periodo` (el campo no era obligatorio a nivel de modelo,
    # solo tenía el placeholder de ayuda en la vista). Sin `periodo`,
    # `rehalife.reservation._find_pedido_marco_vigente()` nunca lo
    # encuentra (busca por aseguradora + período EXACTO) — la reserva se
    # queda sin `pedido_marco_id`, y como ese campo es requisito para
    # `_generar_desde_reservation()`, la Nota de Conformidad tampoco se
    # genera. Todo eso queda solo en el log
    # (`_asegurar_pedido_marco_y_nota_conformidad` traga la excepción a
    # propósito para no romper el sync de la reserva) — nadie lo nota hasta
    # que alguien pregunta por qué falta la NC. Este constraint cierra el
    # hueco de raíz: ya no se puede guardar un Pedido de Venta Marco sin
    # Periodo.
    @api.constrains('es_pedido_marco', 'periodo')
    def _check_pedido_marco_periodo_requerido(self):
        for order in self:
            if order.es_pedido_marco and not order.periodo:
                raise ValidationError(
                    'Un Pedido de Venta Marco requiere un Periodo (el día 1 '
                    'del mes que cubre) — sin esto, las reservas de esa '
                    'aseguradora nunca lo van a encontrar y se quedan sin su '
                    'Nota de Conformidad.'
                )

    # No duplicar Pedido de Venta Marco por aseguradora+período (pedido
    # explícito del usuario, 2026-09-10). Un pedido Cancelado no cuenta —
    # si se cancela uno, debe poder crearse otro para el mismo
    # aseguradora/período. Se valida en Python (no _sql_constraints) para
    # dar un mensaje claro y porque solo aplica cuando es_pedido_marco=True
    # (una constraint SQL UNIQUE(partner_id, periodo) aplicaría a nivel
    # de toda la tabla sale.order, no solo a los pedidos marco).
    @api.constrains('es_pedido_marco', 'partner_id', 'periodo', 'state')
    def _check_pedido_marco_periodo_unico(self):
        for order in self:
            if not order.es_pedido_marco or not order.partner_id or not order.periodo:
                continue
            duplicado = self.search([
                ('id', '!=', order.id),
                ('es_pedido_marco', '=', True),
                ('partner_id', '=', order.partner_id.id),
                ('periodo', '=', order.periodo),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if duplicado:
                raise ValidationError(
                    'Ya existe un Pedido de Venta Marco ("%s") para "%s" en '
                    'el período %s. No se puede duplicar — edita el '
                    'existente en vez de crear uno nuevo (o cancélalo '
                    'primero si de verdad necesitas reemplazarlo).' % (
                        duplicado.name, order.partner_id.name,
                        order.nombre_periodo or order.periodo,
                    )
                )

    # Buscar un Pedido de Venta Marco por su "Nombre del Periodo" (ej.
    # "ClinicaXYZ-Sep25"), no solo por su número de pedido (ej. "S00023") —
    # una misma aseguradora tiene un Pedido de Venta Marco distinto por cada
    # período (ya garantizado único por `_check_pedido_marco_periodo_unico`
    # más arriba), así que hoy cualquier Many2one a sale.order en el módulo
    # (rehalife.nota.conformidad.pedido_marco_id, rehalife.reservation.
    # pedido_marco_id, el wizard de Reportes, etc.) solo dejaba buscar
    # escribiendo el número de pedido, que el usuario no tiene motivo para
    # memorizar. Se hace UNA sola vez a nivel de modelo, en vez de tocar cada
    # vista, para que aplique automáticamente a todos esos campos.
    # No afecta sale.order normales: nombre_periodo solo se computa cuando
    # es_pedido_marco=True (_compute_nombre_periodo más arriba), así que en
    # el resto de Sales Orders/Quotations el OR de abajo simplemente no
    # matchea nada.
    def _search_display_name(self, operator, value):
        domain = super()._search_display_name(operator, value)
        if value:
            domain = expression.OR([domain, [('nombre_periodo', operator, value)]])
        return domain

    # El desplegable Many2one (y cualquier breadcrumb/tag) muestra
    # `display_name` — sin esto, buscar "Sep25" encontraría el pedido
    # correcto pero el resultado listado seguiría mostrando solo su número
    # ("S00023"), sin pista de a qué período corresponde. Ojo: esto NO toca
    # `name` (el número de pedido sigue igual en reportes/breadcrumbs que
    # usan `name` directamente) — solo el `display_name` calculado.
    def _compute_display_name(self):
        super()._compute_display_name()
        for order in self:
            if order.es_pedido_marco and order.nombre_periodo:
                order.display_name = '%s (%s)' % (order.display_name, order.nombre_periodo)

    # ── PVM por mes: búsqueda, clonado bajo demanda y cron ───────────────────
    # Pagos anticipados, Fase 4. Cada reserva de seguro usa el PVM del MES de
    # su fecha. El cron asegura el mes actual y el siguiente por aseguradora;
    # al COBRAR una reserva de un mes más lejano se crea bajo demanda (ver
    # rehalife.reservation._get_cobertura_info). Un PVM nuevo se clona del
    # más reciente confirmado de esa aseguradora; si nunca tuvo uno, no se
    # inventa nada.
    @staticmethod
    def _nombre_mes(periodo):
        return '%s %s' % (_MESES_ES.get(periodo.month, ''), periodo.year)

    @api.model
    def _buscar_pedido_marco(self, aseguradora, periodo):
        """PVM no cancelado de aseguradora+período (puede estar en borrador)."""
        return self.sudo().search([
            ('es_pedido_marco', '=', True),
            ('partner_id', '=', aseguradora.id),
            ('periodo', '=', periodo),
            ('state', '!=', 'cancel'),
        ], order='id desc', limit=1)

    @api.model
    def _fuente_pedido_marco(self, aseguradora):
        """PVM confirmado más reciente (por período) de la aseguradora: el
        que se clona para crear uno nuevo."""
        return self.sudo().search([
            ('es_pedido_marco', '=', True),
            ('partner_id', '=', aseguradora.id),
            ('periodo', '!=', False),
            ('state', '=', 'sale'),
        ], order='periodo desc, id desc', limit=1)

    @api.model
    def _asegurar_pedido_marco(self, aseguradora, periodo, crear=True):
        """Devuelve {'pedido', 'motivo', 'fuente', 'creado'} para
        aseguradora+período (`periodo` se normaliza al día 1).

        - Hay un PVM confirmado → ese.
        - Hay uno en borrador/enviado → no se crea ni se confirma; `motivo`
          explica que hay que confirmarlo en Odoo.
        - No hay → con crear=True se clona `fuente` (mismas líneas: producto,
          % en porcentaje_cobertura, cantidad estimada; qty_conformidad/qty_confirmada
          en 0) y se confirma. Con crear=False solo se informa la fuente.
        - La aseguradora nunca tuvo PVM → pedido vacío y `motivo`.

        Concurrencia: pg_advisory_xact_lock por (aseguradora, período) antes
        de buscar y crear; _check_pedido_marco_periodo_unico es una
        constraint Python y no protege contra dos creaciones simultáneas.
        """
        SaleOrder = self.env['sale.order'].sudo()
        periodo = fields.Date.to_date(periodo).replace(day=1)
        result = {
            'pedido': SaleOrder, 'motivo': '', 'fuente': SaleOrder, 'creado': False,
        }
        if not aseguradora:
            result['motivo'] = 'La reserva de seguro no tiene aseguradora.'
            return result

        if crear:
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (aseguradora.id, periodo.year * 100 + periodo.month),
            )

        existente = self._buscar_pedido_marco(aseguradora, periodo)
        if existente:
            if existente.state == 'sale':
                result['pedido'] = existente
            else:
                result['motivo'] = (
                    'El Pedido Marco de %s está en borrador; confírmalo en Odoo.'
                    % self._nombre_mes(periodo)
                )
            return result

        fuente = self._fuente_pedido_marco(aseguradora)
        result['fuente'] = fuente
        if not fuente:
            result['motivo'] = (
                'La aseguradora "%s" no tiene ningún Pedido de Venta Marco: créalo y '
                'confírmalo en Odoo (Seguros > Pedidos de Venta Marco).' % aseguradora.name
            )
            return result
        if not crear:
            return result

        lineas = [(0, 0, {
            'sequence': line.sequence,
            'product_id': line.product_id.id,
            'name': line.name,
            'product_uom_qty': line.product_uom_qty,
            'product_uom': line.product_uom.id,
            # Fase 6: se copia el %; precio_servicio_pvm toma el precio
            # VIGENTE del servicio y price_unit (monto de la aseguradora) se
            # calcula solo. Ya no hace falta technical_price_unit: las líneas
            # de PVM no pasan por la lista de precios.
            'porcentaje_cobertura': line.porcentaje_cobertura,
            'tax_id': [(6, 0, line.tax_id.ids)],
        }) for line in fuente.order_line if not line.display_type]
        nuevo = SaleOrder.create({
            'partner_id': aseguradora.id,
            'es_pedido_marco': True,
            'periodo': periodo,
            'company_id': fuente.company_id.id,
            'pricelist_id': fuente.pricelist_id.id,
            'user_id': fuente.user_id.id,
            'origin': 'Copia automática de %s' % (fuente.nombre_periodo or fuente.name),
            'order_line': lineas,
        })
        nuevo.action_confirm()
        nuevo.message_post(body=(
            'Creado automáticamente para %s copiando el Pedido Marco %s.'
            % (self._nombre_mes(periodo), fuente.nombre_periodo or fuente.name)
        ))
        _logger.info(
            '[Seguros] PVM %s creado para "%s" / %s copiando %s.',
            nuevo.name, aseguradora.name, periodo, fuente.name,
        )
        result.update(pedido=nuevo, creado=True)
        return result

    @api.model
    def _cron_asegurar_pedidos_marco(self):
        """Cron diario: para cada aseguradora con al menos un PVM confirmado,
        asegura el del mes actual y el del siguiente. Errores silenciosos:
        se registran en el log y se sigue con la siguiente."""
        hoy = fields.Date.context_today(self).replace(day=1)
        periodos = (hoy, hoy + relativedelta(months=1))
        aseguradoras = self.sudo().search([
            ('es_pedido_marco', '=', True), ('state', '=', 'sale'),
        ]).mapped('partner_id')
        for aseguradora in aseguradoras:
            for periodo in periodos:
                try:
                    with self.env.cr.savepoint():
                        res = self._asegurar_pedido_marco(aseguradora, periodo, crear=True)
                    if res['creado']:
                        _logger.info(
                            '[Seguros][cron PVM] "%s" %s: creado %s.',
                            aseguradora.name, periodo, res['pedido'].name,
                        )
                    elif res['motivo']:
                        _logger.warning(
                            '[Seguros][cron PVM] "%s" %s: %s',
                            aseguradora.name, periodo, res['motivo'],
                        )
                except Exception:
                    _logger.exception(
                        '[Seguros][cron PVM] "%s" %s: no se pudo asegurar el Pedido Marco.',
                        aseguradora.name, periodo,
                    )

    # ── Lectura para Next.js (Pagos anticipados, Fase 5) — SOLO LECTURA ──────
    # Nunca crean ni modifican nada: Next muestra los PVM y estima a qué PVM
    # irá una reserva. Se llaman por JSON-RPC con el usuario técnico.
    _ESTADOS_PVM = {'draft': 'Borrador', 'sent': 'Enviado', 'sale': 'Confirmado', 'cancel': 'Cancelado'}

    def _pvm_nextjs_dict(self, con_lineas=True):
        self.ensure_one()
        currency = self.currency_id
        data = {
            'id': self.id,
            'name': self.name,
            'nombre_periodo': self.nombre_periodo or '',
            'periodo': fields.Date.to_string(self.periodo) if self.periodo else False,
            'state': self.state,
            'state_label': self._ESTADOS_PVM.get(self.state, self.state),
            'origin': self.origin or '',
            'aseguradora': {
                'id': self.partner_id.id,
                'name': self.partner_id.name or '',
                'external_id': self.partner_id.rehalife_external_id or False,
            },
            'currency': currency.name or '',
            'nota_conformidad_count': len(self.nota_conformidad_ids),
        }
        if con_lineas:
            lineas = []
            for line in self.order_line.filtered(lambda l: not l.display_type):
                precio = line.product_id.lst_price
                monto_aseg = currency.round(precio * (line.porcentaje_cobertura or 0.0) / 100.0)
                lineas.append({
                    'id': line.id,
                    'product_id': line.product_id.id,
                    'product_name': line.product_id.display_name or line.name or '',
                    'service_external_id': line.product_id.product_tmpl_id.rehalife_external_id or False,
                    'porcentaje': line.porcentaje_cobertura,
                    # Lo que dice el PVM (fijado al poner el % o el producto).
                    'precio_servicio_pvm': line.precio_servicio_pvm,
                    'monto_pvm': line.price_unit,
                    'cantidad_estimada': line.product_uom_qty,
                    'qty_conformidad': line.qty_conformidad,
                    'qty_confirmada': line.qty_confirmada,
                    'precio_servicio': precio,
                    'monto_aseguradora': monto_aseg,
                    'monto_paciente': currency.round(precio - monto_aseg),
                })
            data['lineas'] = lineas
        return data

    @api.model
    def get_pedidos_marco_nextjs(self, filtros=None):
        """Lista de PVM (no cancelados) con sus líneas, en UNA llamada.
        filtros: {mes: 'AAAA-MM', aseguradora_external_id}."""
        filtros = filtros or {}
        domain = [('es_pedido_marco', '=', True), ('state', '!=', 'cancel')]
        if filtros.get('mes'):
            periodo = fields.Date.to_date('%s-01' % filtros['mes'])
            domain.append(('periodo', '=', periodo))
        if filtros.get('aseguradora_external_id'):
            domain.append(('partner_id.rehalife_external_id', '=', filtros['aseguradora_external_id']))
        pedidos = self.sudo().search(domain, order='periodo desc, id desc', limit=500)
        return [p._pvm_nextjs_dict() for p in pedidos]

    @api.model
    def get_pedido_marco_detalle_nextjs(self, pedido_id):
        pedido = self.sudo().browse(int(pedido_id)).exists()
        if not pedido or not pedido.es_pedido_marco:
            return False
        data = pedido._pvm_nextjs_dict()
        resumen = {}
        for nc in pedido.nota_conformidad_ids:
            resumen[nc.estado] = resumen.get(nc.estado, 0) + 1
        etiquetas = dict(self.env['rehalife.nota.conformidad']._fields['estado'].selection)
        data['notas_por_estado'] = [
            {'estado': k, 'label': etiquetas.get(k, k), 'count': v} for k, v in resumen.items()
        ]
        return data

    @api.model
    def resolver_pedido_marco_nextjs(self, aseguradora_external_id, fechas, service_type_external_id):
        """A qué PVM iría una reserva que todavía no existe (asistente).
        NO crea nada. Una entrada por mes de `fechas` ('AAAA-MM-DD'):
        {mes, estado, mensaje, pvm_id, pvm_name, porcentaje, precio,
        monto_aseguradora, monto_paciente}. estado ∈ existe | se_creara |
        borrador | sin_pvm | sin_linea | sin_producto | sin_aseguradora."""
        Partner = self.env['res.partner'].sudo()
        aseguradora = Partner.search(
            [('rehalife_external_id', '=', aseguradora_external_id)], limit=1,
        ) if aseguradora_external_id else Partner
        producto = self.env['rehalife.reservation'].sudo()._producto_de_servicio(
            service_type_external_id)
        meses = sorted({str(f)[:7] for f in (fechas or []) if f})
        result = []
        for mes in meses:
            periodo = fields.Date.to_date('%s-01' % mes)
            entry = {
                'mes': mes, 'estado': '', 'mensaje': '', 'pvm_id': False, 'pvm_name': '',
                'porcentaje': 0.0, 'precio': 0.0, 'monto_aseguradora': 0.0, 'monto_paciente': 0.0,
            }
            result.append(entry)
            if not aseguradora:
                entry.update(estado='sin_aseguradora',
                             mensaje='La aseguradora no está sincronizada en Odoo.')
                continue
            if not producto:
                entry.update(estado='sin_producto',
                             mensaje='El servicio no tiene producto en Odoo.')
                continue
            res = self._asegurar_pedido_marco(aseguradora, periodo, crear=False)
            pvm = res['pedido'] or res['fuente']
            if not pvm:
                entry.update(
                    estado='borrador' if self._buscar_pedido_marco(aseguradora, periodo) else 'sin_pvm',
                    mensaje=res['motivo'] or 'Sin Pedido de Venta Marco.',
                )
                continue
            if res['pedido']:
                entry.update(estado='existe', pvm_id=pvm.id, pvm_name=pvm.nombre_periodo or pvm.name)
            else:
                entry.update(
                    estado='se_creara',
                    mensaje='Se creará al cobrar copiando el de %s.' % (
                        self._nombre_mes(pvm.periodo) if pvm.periodo else pvm.name),
                )
            try:
                linea = self.env['rehalife.nota.conformidad'].sudo()._resolve_pedido_marco_line(
                    self.env['rehalife.reservation'], order=pvm, product=producto)
            except UserError:
                entry.update(estado='sin_linea', mensaje='El Pedido Marco %s no incluye el servicio %s.' % (
                    pvm.nombre_periodo or pvm.name, producto.display_name))
                continue
            cur = pvm.currency_id or self.env.company.currency_id
            precio = producto.lst_price
            monto_aseg = cur.round(precio * (linea.porcentaje_cobertura or 0.0) / 100.0)
            entry.update(porcentaje=linea.porcentaje_cobertura, precio=precio,
                         monto_aseguradora=monto_aseg, monto_paciente=cur.round(precio - monto_aseg))
        return result

    def action_view_notas_conformidad(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Notas de Conformidad',
            'res_model': 'rehalife.nota.conformidad',
            'view_mode': 'list,form',
            'domain': [('pedido_marco_id', '=', self.id)],
            'context': {'default_pedido_marco_id': self.id},
        }

    def action_facturar_notas_conformidad(self):
        """Botón "Facturar NC" (HU-18): agrupa TODAS las Notas de
        Conformidad en estado 'aprobada' sin factura de este Pedido de
        Venta Marco en UNA sola factura (una línea por NC, no se pierde de
        qué paciente es cada una). No incluye 'pendiente'/'rechazada'/
        'regularizada'/'facturada' — solo 'aprobada' sin `factura_id` aún."""
        self.ensure_one()
        notas = self.nota_conformidad_ids.filtered(
            lambda n: n.estado == 'aprobada' and not n.factura_id
        )
        if not notas:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Facturar Notas de Conformidad',
                    'message': 'No hay Notas de Conformidad pendientes de '
                               'facturar en este Pedido de Venta Marco — o no '
                               'hay ninguna Aprobada todavía, o las Aprobadas '
                               'ya tienen su propia factura individual '
                               '(generada con el botón "Generar Factura" de '
                               'cada NC).',
                    'type': 'warning',
                    'sticky': True,
                },
            }
        invoice = notas._generar_factura_agrupada()
        return notas._action_factura_generada_notification(invoice)
