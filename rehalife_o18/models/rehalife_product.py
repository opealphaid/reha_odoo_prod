# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    reservas_rehalife = fields.Boolean(
        string='Reservas Rehalife',
        index=True,
        copy=False,
        help='Marca los productos que representan un Tipo de Servicio '
             '(ServiceType) reservable del backend Rehalife. Separa estos '
             'servicios del resto del catalogo y alimenta el menu '
             'Rehalife > Servicios.',
    )

    rehalife_external_id = fields.Char(
        string='ID Externo (Service Type)',
        index=True,
        copy=False,
    )
    rehalife_sync_state = fields.Selection(
        selection=[
            ('draft', 'No sincronizado'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado Sync Rehalife',
        default='draft',
        readonly=True,
    )
    rehalife_sync_error = fields.Text(string='Error de Sync', readonly=True)
    rehalife_last_sync = fields.Datetime(string='Ultima Sincronizacion', readonly=True)

    rehalife_service_description = fields.Text(
        string='Descripcion del Servicio',
        help='Descripcion del Tipo de Servicio tal como esta en el backend '
             'Rehalife. No se imprime en documentos: para eso estan los '
             'campos nativos de Odoo (Notas internas / Descripcion de venta).',
    )
    rehalife_requires_evaluation = fields.Boolean(
        string='Requiere Evaluacion',
        help='El servicio exige una evaluacion previa antes de poder reservarse.',
    )
    rehalife_cancel_window_hours = fields.Integer(
        string='Horas Limite de Cancelacion',
        help='Horas de antelacion minimas para poder cancelar la reserva.',
    )
    rehalife_open_window_hours = fields.Integer(
        string='Horas de Apertura de Agenda',
        help='Horas de antelacion con las que se abre la agenda del servicio.',
    )
    rehalife_reminder_hours_before = fields.Integer(
        string='Horas de Recordatorio',
        help='Horas antes de la cita en que se envia el recordatorio al paciente.',
    )
    rehalife_max_advance_days = fields.Integer(
        string='Dias Max. de Anticipacion',
        help='Dias maximos con los que se puede reservar el servicio por adelantado.',
    )

    rehalife_siat_actividad_codigo = fields.Char(
        string='Cod. Actividad SIAT',
        compute='_compute_rehalife_siat_codigos',
        inverse='_inverse_rehalife_siat_codigos',
        help='Codigo CAEB de la Actividad Economica SIAT. Al escribirlo se '
             'resuelve y asigna la Actividad Economica del producto.',
    )
    rehalife_siat_producto_codigo = fields.Char(
        string='Cod. Producto SIAT',
        compute='_compute_rehalife_siat_codigos',
        inverse='_inverse_rehalife_siat_codigos',
        help='Codigo del Producto/Servicio en el catalogo SIAT. Se busca '
             'dentro de la actividad economica indicada, que es lo que lo '
             'hace univoco.',
    )
    rehalife_siat_unidad_codigo = fields.Char(
        string='Cod. Unidad Medida SIAT',
        compute='_compute_rehalife_siat_codigos',
        inverse='_inverse_rehalife_siat_codigos',
        help='Codigo clasificador de la Unidad de Medida SIAT.',
    )

    _sql_constraints = [
        ('rehalife_external_id_uniq', 'UNIQUE(rehalife_external_id)',
         'Ya existe un producto sincronizado con ese Service Type.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Un servicio reservable no se compra. En Odoo `purchase_ok` viene
            # con default=True, asi que hay que apagarlo explicitamente — es el
            # mismo criterio que ya aplica sync_service_types_from_backend()
            # a los servicios que llegan del backend. Se hace aca para que la
            # plantilla de importacion no tenga que traer esa columna.
            if vals.get('reservas_rehalife') and 'purchase_ok' not in vals:
                vals['purchase_ok'] = False
        return super().create(vals_list)

    # ──────────────────────────────────────────────
    #  Homologacion SIAT por codigo
    # ──────────────────────────────────────────────

    @api.depends('siat_actividad_economica_id', 'siat_codigo_producto_sin',
                 'siat_unidad_medida_id')
    def _compute_rehalife_siat_codigos(self):
        for product in self:
            product.rehalife_siat_actividad_codigo = (
                    product.siat_actividad_economica_id.codigo_caeb or False)
            product.rehalife_siat_producto_codigo = (
                    product.siat_codigo_producto_sin.codigo_producto or False)
            unidad = product.siat_unidad_medida_id
            product.rehalife_siat_unidad_codigo = (
                str(unidad.codigo_clasificador) if unidad else False)

    def _inverse_rehalife_siat_codigos(self):
        """Resuelve los tres codigos a sus registros del catalogo SIAT.

        Los tres campos comparten este inverse a proposito: Odoo lo llama una
        sola vez con los tres valores ya asignados, asi que podemos resolver la
        actividad primero y usarla para acotar la busqueda del producto (el
        codigo de producto solo es unico dentro de su actividad).
        """
        for product in self:
            # Se leen los tres ANTES de escribir ningun Many2one: cada escritura
            # invalida el compute y volveria a leer el valor derivado en vez del
            # que se acaba de asignar.
            codigo_actividad = (product.rehalife_siat_actividad_codigo or '').strip()
            codigo_producto = (product.rehalife_siat_producto_codigo or '').strip()
            codigo_unidad = (product.rehalife_siat_unidad_codigo or '').strip()
            company = product.company_id or self.env.company

            if codigo_actividad:
                product.siat_actividad_economica_id = product._buscar_siat_actividad(
                    codigo_actividad, company)

            if codigo_producto:
                product.siat_codigo_producto_sin = product._buscar_siat_producto(
                    codigo_producto, codigo_actividad, company)

            if codigo_unidad:
                product.siat_unidad_medida_id = product._buscar_siat_unidad(
                    codigo_unidad, company)

    def _buscar_siat_actividad(self, codigo, company):
        actividad = self.env['alpha.siat.actividad'].search([
            ('codigo_caeb', '=', codigo),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], limit=1)
        if not actividad:
            raise ValidationError(
                'No existe una Actividad Economica SIAT activa con el codigo '
                'CAEB "%s" para la compania %s.' % (codigo, company.name)
            )
        return actividad

    def _buscar_siat_producto(self, codigo, codigo_actividad, company):
        domain = [
            ('codigo_producto', '=', codigo),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ]
        # El codigo de producto se repite entre actividades: sin la actividad
        # no se puede elegir uno solo sin adivinar.
        if codigo_actividad:
            domain.append(('codigo_actividad', '=', codigo_actividad))

        productos = self.env['alpha.siat.producto.servicio'].search(domain, limit=2)
        if not productos:
            detalle = (' dentro de la actividad %s' % codigo_actividad
                       if codigo_actividad else '')
            raise ValidationError(
                'No existe un Producto/Servicio SIAT activo con el codigo "%s"%s '
                'para la compania %s.' % (codigo, detalle, company.name)
            )
        if len(productos) > 1:
            raise ValidationError(
                'El codigo de Producto SIAT "%s" corresponde a mas de una '
                'actividad economica. Indica tambien el Cod. Actividad SIAT '
                'para desambiguarlo.' % codigo
            )
        return productos

    def _buscar_siat_unidad(self, codigo, company):
        try:
            codigo_int = int(float(codigo))
        except (TypeError, ValueError):
            raise ValidationError(
                'El Cod. Unidad Medida SIAT debe ser un numero. Recibido: "%s".'
                % codigo
            )
        unidad = self.env['alpha.siat.unidad.medida'].search([
            ('codigo_clasificador', '=', codigo_int),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], limit=1)
        if not unidad:
            raise ValidationError(
                'No existe una Unidad de Medida SIAT activa con el codigo '
                'clasificador %s para la compania %s.' % (codigo_int, company.name)
            )
        return unidad

    # ──────────────────────────────────────────────
    #  SYNC: Backend (Next.js) → Odoo
    # ──────────────────────────────────────────────

    @staticmethod
    def _rehalife_vals_para_write(existing, vals):
        """Saca del write los campos que no cambiaron y que disparan validaciones.

        `default_code` es el unico campo de este sync que aparece en la
        constraint de homologacion de alpha_siat (`_check_siat_homologation`),
        y Odoo evalua las constraints por los campos PRESENTES en el write,
        aunque el valor sea identico al que ya estaba. Resultado: reescribir la
        misma referencia — que no cambia absolutamente nada — hacia fallar la
        sincronizacion entera sobre cualquier producto vendible o disponible en
        POS al que le faltara la homologacion SIAT.

        Traer un servicio del backend no deberia depender de si en Odoo esta
        homologado o no: la homologacion es un tema de Odoo, no del backend. Si
        la referencia no cambio, se omite y la validacion ni se entera.
        """
        vals = dict(vals)
        if (existing.default_code or False) == (vals.get('default_code') or False):
            vals.pop('default_code', None)
        return vals

    @staticmethod
    def _rehalife_as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @api.model
    def sync_service_types_from_backend(self):
        """Importa y actualiza los Service Types del backend como productos."""
        api_service = self.env['rehalife.api']
        service_types = api_service.get_service_types()
        created = updated = skipped = 0
        errors = []
        for service_type in service_types:
            ext_id = service_type.get('id')
            if not ext_id:
                skipped += 1
                continue

            price = service_type.get('price')
            has_price = price is not None
            vals = {
                'name': service_type.get('name', ''),
                'default_code': service_type.get('reference') or False,
                'list_price': float(price) if has_price else 0.0,
                'rehalife_external_id': str(ext_id),
                'reservas_rehalife': True,
                'rehalife_service_description': service_type.get('description') or False,
                'rehalife_requires_evaluation': bool(service_type.get('requiresEvaluation')),
                'rehalife_cancel_window_hours': self._rehalife_as_int(
                    service_type.get('cancelWindowHours')),
                'rehalife_open_window_hours': self._rehalife_as_int(
                    service_type.get('openWindowHours')),
                'rehalife_reminder_hours_before': self._rehalife_as_int(
                    service_type.get('reminderHoursBeforeAppointment')),
                'rehalife_max_advance_days': self._rehalife_as_int(
                    service_type.get('maxAdvanceDays')),
                'rehalife_last_sync': fields.Datetime.now(),
            }
            if has_price:
                vals['rehalife_sync_state'] = 'synced'
                vals['rehalife_sync_error'] = False
            else:
                # No bloquea la sincronizacion, pero deja evidencia de que el
                # producto quedo a precio 0 porque el backend aun no tiene un
                # precio definido para este servicio.
                vals['rehalife_sync_state'] = 'draft'
                vals['rehalife_sync_error'] = 'Sin precio definido en el backend.'

            existing = self.with_context(active_test=False).search(
                [('rehalife_external_id', '=', str(ext_id))], limit=1,
            )

            # Savepoint por servicio: el sync es una operacion masiva y un
            # registro que no se puede guardar no debe abortar a los demas.
            # El caso tipico es la constraint de homologacion de alpha_siat
            # (_check_siat_homologation): se dispara en cualquier write que
            # incluya `default_code` — y este siempre lo incluye — sobre un
            # producto vendible o disponible en POS al que le falte algun
            # codigo SIAT. Eso es un dato a corregir en ESE producto, no un
            # motivo para dejar sin sincronizar al resto del catalogo.
            try:
                with self.env.cr.savepoint():
                    if existing:
                        # No se pisa sale_ok/available_in_pos: si contabilidad ya
                        # homologó y activó el producto a mano, el sync no debe
                        # desactivarlo ni reactivarlo.
                        existing.write(self._rehalife_vals_para_write(existing, vals))
                    else:
                        # Nace como borrador (no vendible): la homologación SIAT
                        # (Código de Producto, Actividad Económica, Unidad de
                        # Medida) es distinta por servicio y no se puede
                        # autoasignar, así que queda como paso manual de
                        # contabilidad por producto.
                        vals.update({
                            'type': 'service',
                            'sale_ok': False,
                            'purchase_ok': False,
                            'available_in_pos': False,
                            'taxes_id': [(5, 0, 0)],
                        })
                        self.create(vals)
            except Exception as e:
                mensaje_error = str(e)
                nombre = service_type.get('name') or str(ext_id)
                errors.append('%s: %s' % (nombre, mensaje_error))
                _logger.warning(
                    '[SyncServicios] No se pudo sincronizar "%s" (%s): %s',
                    nombre, ext_id, mensaje_error,
                )
                if existing:
                    # Queda la marca en el producto para poder encontrarlo con
                    # el filtro "No Sincronizados". Estos dos campos no estan en
                    # la constraint de alpha_siat, asi que este write no vuelve
                    # a fallar por lo mismo.
                    existing.write({
                        'rehalife_sync_state': 'error',
                        'rehalife_sync_error': mensaje_error,
                    })
                continue

            if existing:
                updated += 1
            else:
                created += 1

        pending_homologation = self.search_count([
            ('rehalife_external_id', '!=', False),
            ('siat_homologado', '=', False),
            ('reservas_rehalife', '=', True),
        ])

        _logger.info(
            'Rehalife service types: %d creados, %d actualizados, %d omitidos, '
            '%d con error, %d pendientes de homologacion SIAT.',
            created, updated, skipped, len(errors), pending_homologation,
        )
        return {
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
            'pending_homologation': pending_homologation,
        }

    def _prepare_rehalife_service_payload(self):

        self.ensure_one()

        name = (self.name or '').strip()
        if not name:
            raise UserError('El servicio necesita un nombre.')
        if len(name) > 100:
            raise UserError(
                'El nombre no puede exceder 100 caracteres (limite del backend '
                'Rehalife). Actual: %d.' % len(name)
            )

        reference = (self.default_code or '').strip()
        if len(reference) > 100:
            raise UserError(
                'La referencia interna no puede exceder 100 caracteres (limite '
                'del backend Rehalife). Actual: %d.' % len(reference)
            )

        def _positivo_o_nulo(valor):
            return valor if valor and valor > 0 else None

        open_window = _positivo_o_nulo(self.rehalife_open_window_hours)
        max_advance = _positivo_o_nulo(self.rehalife_max_advance_days)

        if open_window and max_advance and open_window > max_advance * 24:
            raise UserError(
                'Configuracion invalida: las Horas de Apertura de Agenda (%d) '
                'superan a los Dias Max. de Anticipacion (%d dias = %d horas). '
                'Ninguna fecha seria reservable.'
                % (open_window, max_advance, max_advance * 24)
            )

        return {
            'name': name,
            'description': self.rehalife_service_description or None,
            'reference': reference or None,
            'requiresEvaluation': bool(self.rehalife_requires_evaluation),
            'cancelWindowHours': self.rehalife_cancel_window_hours,
            'openWindowHours': open_window,
            'reminderHoursBeforeAppointment': _positivo_o_nulo(
                self.rehalife_reminder_hours_before),
            'maxAdvanceDays': max_advance,
            'price': round(self.list_price or 0.0, 2),
        }

    def _push_services_to_backend(self, commit_every=0):

        api_service = self.env['rehalife.api']
        servicios = self.filtered('reservas_rehalife')
        ignorados = len(self) - len(servicios)

        creados = actualizados = 0
        errores = []
        for procesados, producto in enumerate(servicios, start=1):
            try:
                with self.env.cr.savepoint():
                    payload = producto._prepare_rehalife_service_payload()

                    if producto.rehalife_external_id:
                        remoto = api_service.get_service_type(
                            producto.rehalife_external_id)
                        payload['branchIds'] = [
                            sucursal['id']
                            for sucursal in (remoto.get('branches') or [])
                            if sucursal.get('id')
                        ]
                        api_service.update_service_type(
                            producto.rehalife_external_id, payload)
                        actualizados += 1
                    else:
                        creado = api_service.create_service_type(payload)
                        nuevo_id = creado.get('id')
                        if not nuevo_id:
                            raise UserError(
                                'El backend no devolvio el ID del servicio creado.')
                        producto.rehalife_external_id = str(nuevo_id)
                        creados += 1

                    producto.write({
                        'rehalife_sync_state': 'synced',
                        'rehalife_sync_error': False,
                        'rehalife_last_sync': fields.Datetime.now(),
                    })
            except Exception as e:
                mensaje_error = str(e)
                errores.append('%s: %s' % (producto.display_name, mensaje_error))
                _logger.warning(
                    '[PushServicios] %s: %s', producto.display_name, mensaje_error)
                producto.write({
                    'rehalife_sync_state': 'error',
                    'rehalife_sync_error': mensaje_error,
                })

            if commit_every and procesados % commit_every == 0:
                self.env.cr.commit()

        if commit_every:
            self.env.cr.commit()

        _logger.info(
            'Rehalife push de servicios: %d creados, %d actualizados, '
            '%d con error, %d omitidos.',
            creados, actualizados, len(errores), ignorados,
        )
        return {
            'creados': creados,
            'actualizados': actualizados,
            'errores': errores,
            'ignorados': ignorados,
        }

    def action_push_service_to_backend(self):
        if not self.filtered('reservas_rehalife'):
            raise UserError(
                'Ninguno de los productos seleccionados esta marcado como '
                'Servicio Rehalife.'
            )

        resultado = self._push_services_to_backend()
        creados = resultado['creados']
        actualizados = resultado['actualizados']
        errores = resultado['errores']
        ignorados = resultado['ignorados']

        mensaje = '%d creado(s) y %d actualizado(s) en el backend.' % (
            creados, actualizados)
        if ignorados:
            mensaje += (
                    '\n%d producto(s) omitido(s) por no ser Servicio Rehalife.'
                    % ignorados
            )
        if errores:
            mensaje += '\n\n%d con error:\n%s' % (
                len(errores), '\n'.join(errores[:10]))
            if len(errores) > 10:
                mensaje += '\n(y %d mas — ver el campo Error de Sync de cada uno)' % (
                        len(errores) - 10)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Servicios enviados al backend',
                'message': mensaje,
                'type': 'danger' if errores else 'success',
                'sticky': bool(errores),
            },
        }
