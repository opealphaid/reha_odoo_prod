# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RehalifeServicesSyncWizard(models.TransientModel):
    _name = 'rehalife.services.sync.wizard'
    _description = 'Sincronizar Servicios con el Backend Rehalife'

    direccion = fields.Selection(
        selection=[
            ('jalar', 'Traer del backend  (backend → Odoo)'),
            ('enviar', 'Enviar al backend  (Odoo → backend)'),
        ],
        string='Que quiero hacer',
        default='jalar',
        required=True,
        help='"Traer" importa los tipos de servicio del backend y los crea o '
             'actualiza como productos en Odoo. "Enviar" hace lo inverso: crea '
             'en el backend los servicios que solo existen en Odoo (carga '
             'manual o por plantilla).',
    )

    # ── Opciones del envio (Odoo → backend) ──────────────────────────────
    scope = fields.Selection(
        selection=[
            ('pendientes', 'Solo los que faltan en el backend'),
            ('todos', 'Todos (crear los que faltan y actualizar el resto)'),
        ],
        string='Alcance',
        default='pendientes',
        help='"Solo los que faltan" envia unicamente los servicios sin ID '
             'Externo, es decir los creados en Odoo (a mano o por plantilla). '
             '"Todos" ademas sobrescribe en el backend los que ya estaban '
             'sincronizados, con los datos que hoy tiene Odoo.',
    )
    batch_size = fields.Integer(
        string='Servicios por Tanda',
        default=100,
        help='Cuantos servicios procesa cada corrida. Con 0 procesa todos de '
             'una. El envio es un request HTTP por servicio, asi que en '
             'catalogos grandes conviene ir por tandas para no agotar el '
             'tiempo de respuesta. Lo ya enviado se confirma en base cada 20 '
             'servicios: si se corta, no se pierde y se puede retomar.',
    )

    # Cursor de avance: id del ultimo servicio procesado. La siguiente tanda
    # arranca despues de este. Sin esto, con `scope='todos'` cada tanda volveria
    # a tomar los mismos primeros N registros y el barrido no avanzaria nunca.
    last_id = fields.Integer(string='Ultimo ID Procesado', default=0)

    # Se llena al terminar cada tanda de envio (no es compute: describe esa
    # corrida, no el estado general del catalogo).
    restantes_count = fields.Integer(string='Pendientes de Procesar', readonly=True)

    # ── Panorama actual ──────────────────────────────────────────────────
    pendientes_count = fields.Integer(
        string='Faltan en el Backend', compute='_compute_counts')
    sincronizados_count = fields.Integer(
        string='Ya Sincronizados', compute='_compute_counts')
    total_count = fields.Integer(
        string='Total de Servicios en Odoo', compute='_compute_counts')

    result_message = fields.Text(string='Resultado', readonly=True)
    state = fields.Selection(
        [('draft', 'Configurar'), ('done', 'Completado')],
        default='draft',
    )

    # Cada cuantos servicios se confirma en base durante el barrido de envio.
    _COMMIT_EVERY = 20

    @api.depends('direccion')
    def _compute_counts(self):
        Product = self.env['product.template']
        base_domain = [('reservas_rehalife', '=', True)]
        pendientes = Product.search_count(
            base_domain + [('rehalife_external_id', '=', False)])
        total = Product.search_count(base_domain)
        for wizard in self:
            wizard.pendientes_count = pendientes
            wizard.total_count = total
            wizard.sincronizados_count = total - pendientes

    @api.onchange('direccion', 'scope')
    def _onchange_reset_cursor(self):
        """Cambiar de direccion o de alcance empieza un barrido nuevo."""
        for wizard in self:
            wizard.last_id = 0
            wizard.restantes_count = 0

    # ── Ejecucion ────────────────────────────────────────────────────────

    def action_run(self):
        self.ensure_one()
        if self.direccion == 'jalar':
            lines = self._run_pull()
        else:
            lines = self._run_push()

        self.write({'result_message': '\n'.join(lines), 'state': 'done'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        """Vuelve a la pantalla de configuracion para otra sincronizacion."""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'result_message': False,
            'last_id': 0,
            'restantes_count': 0,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _run_pull(self):
        """Backend → Odoo. Trae todos los service types activos de una: es un
        GET paginado, no un request por servicio, asi que no necesita tandas."""
        self.ensure_one()
        resultado = self.env['product.template'].sync_service_types_from_backend()
        lines = [
            'Traidos del backend (backend → Odoo)',
            '',
            'Creados en Odoo: %d' % resultado['created'],
            'Actualizados en Odoo: %d' % resultado['updated'],
            'Omitidos (sin ID en el backend): %d' % resultado['skipped'],
        ]
        if resultado['pending_homologation']:
            lines.append('')
            lines.append(
                '%d servicio(s) requieren homologacion SIAT (Codigo de '
                'Producto, Actividad Economica y Unidad de Medida) antes de '
                'poder venderse o cobrarse en el POS. Los lista el filtro '
                '"Pendientes de Homologacion SIAT" del menu Servicios.'
                % resultado['pending_homologation']
            )
        return lines

    def _run_push(self):
        """Odoo → backend, por tandas."""
        self.ensure_one()
        if self.batch_size < 0:
            raise UserError('Los servicios por tanda no pueden ser negativos.')

        Product = self.env['product.template']
        alcance_total = Product.search_count(self._get_push_domain(desde_cursor=False))
        por_procesar = Product.search_count(self._get_push_domain())
        if not por_procesar:
            raise UserError(
                'No quedan servicios por enviar con el alcance seleccionado.'
                if self.last_id else
                'No hay servicios para enviar con el alcance seleccionado.'
            )

        # order='id' + cursor: las tandas sucesivas avanzan sin repetir.
        servicios = Product.search(
            self._get_push_domain(), limit=self.batch_size or None, order='id')

        resultado = servicios._push_services_to_backend(
            commit_every=self._COMMIT_EVERY)

        self.last_id = max(servicios.ids)
        restantes = Product.search_count(self._get_push_domain())
        self.restantes_count = restantes

        lines = [
            'Enviados al backend (Odoo → backend)',
            '',
            'Servicios en el alcance: %d' % alcance_total,
            'Procesados en esta tanda: %d' % len(servicios),
            'Creados en el backend: %d' % resultado['creados'],
            'Actualizados en el backend: %d' % resultado['actualizados'],
            'Errores: %d' % len(resultado['errores']),
            'Quedan por procesar: %d' % restantes,
        ]
        if restantes:
            lines.append('')
            lines.append(
                'Usa "Continuar con la Siguiente Tanda" para seguir donde quedo.'
            )
        if resultado['errores']:
            lines.append('')
            lines.append('Detalle de errores:')
            lines.extend('  - %s' % error for error in resultado['errores'])
            lines.append('')
            lines.append(
                'Cada uno quedo marcado con Estado Sync = Error y el detalle en '
                'su campo Error de Sync. El filtro "No Sincronizados" del menu '
                'Servicios los lista. Los servicios con error NO se reintentan '
                'en las siguientes tandas: corregilos y volve a enviarlos desde '
                'la lista de Servicios.'
            )
        return lines

    def _get_push_domain(self, desde_cursor=True):
        """Servicios que entran en el alcance elegido.

        desde_cursor=True agrega el cursor de avance, para no repetir lo que ya
        se proceso en tandas anteriores de este mismo asistente.
        """
        self.ensure_one()
        domain = [('reservas_rehalife', '=', True)]
        if self.scope == 'pendientes':
            domain.append(('rehalife_external_id', '=', False))
        if desde_cursor and self.last_id:
            domain.append(('id', '>', self.last_id))
        return domain
