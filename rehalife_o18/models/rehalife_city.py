# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RehalifeCity(models.Model):
    _name = 'rehalife.city'
    _description = 'Ciudad Rehalife'
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(string='Nombre', required=True, index=True)
    external_id = fields.Char(
        string='ID Externo (Backend)',
        index=True,
        copy=False,
    )
    description = fields.Char(string='Descripcion')
    active = fields.Boolean(string='Activo', default=True)

    # Estado de sincronizacion (igual que en res.partner)
    rehalife_sync_state = fields.Selection(
        selection=[
            ('draft', 'No sincronizado'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado Sync',
        default='draft',
        readonly=True,
    )
    rehalife_sync_error = fields.Text(string='Error de Sync', readonly=True)
    rehalife_last_sync = fields.Datetime(string='Ultima Sincronizacion', readonly=True)

    patient_count = fields.Integer(
        string='Pacientes',
        compute='_compute_patient_count',
    )

    _sql_constraints = [
        ('external_id_uniq', 'UNIQUE(external_id)',
         'Ya existe una ciudad con ese ID externo.'),
    ]

    def _compute_patient_count(self):
        for city in self:
            city.patient_count = self.env['res.partner'].search_count(
                [('rehalife_city_id', '=', city.id), ('es_paciente', '=', True)]
            )

    def action_view_patients(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pacientes de %s' % self.name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('rehalife_city_id', '=', self.id), ('es_paciente', '=', True)],
            'context': {'default_rehalife_city_id': self.id, 'default_es_paciente': True},
        }

    # ──────────────────────────────────────────────
    #  SYNC: Odoo → Backend (Next.js)
    # ──────────────────────────────────────────────

    def _build_city_payload(self):
        """Construye el payload JSON para enviar al backend."""
        self.ensure_one()
        api_service = self.env['rehalife.api']
        admin_user_id = api_service._get_admin_user_id()
        return {
            'name': self.name or '',
            'description': self.description or '',
            'status': self.active,
            'userId': admin_user_id,
        }

    def _sync_create(self):
        """Crea la ciudad en el backend y guarda el external_id devuelto."""
        self.ensure_one()
        api_service = self.env['rehalife.api']
        payload = self._build_city_payload()
        _logger.info('Rehalife city: Creando ciudad "%s" payload: %s', self.name, payload)
        try:
            result = api_service.create_city(payload)
            ext_id = (
                result.get('data', {}).get('id')
                or result.get('id')
            )
            if not ext_id:
                raise UserError('El backend no devolvio un ID para la ciudad.')
            self.sudo().write({
                'external_id': str(ext_id),
                'rehalife_sync_state': 'synced',
                'rehalife_sync_error': False,
                'rehalife_last_sync': fields.Datetime.now(),
            })
        except UserError as e:
            self.sudo().write({
                'rehalife_sync_state': 'error',
                'rehalife_sync_error': str(e),
            })
            raise

    def _sync_update(self):
        """Actualiza la ciudad en el backend."""
        self.ensure_one()
        api_service = self.env['rehalife.api']
        payload = self._build_city_payload()
        _logger.info('Rehalife city: Actualizando ciudad %s payload: %s', self.external_id, payload)
        try:
            api_service.update_city(self.external_id, payload)
            self.sudo().write({
                'rehalife_sync_state': 'synced',
                'rehalife_sync_error': False,
                'rehalife_last_sync': fields.Datetime.now(),
            })
        except UserError as e:
            self.sudo().write({
                'rehalife_sync_state': 'error',
                'rehalife_sync_error': str(e),
            })
            raise

    def action_sync_rehalife(self):
        """Boton: Sincronizar / Actualizar ciudad en el backend Rehalife."""
        self.ensure_one()
        is_new = not self.external_id

        if is_new:
            self._sync_create()
            titulo = 'Ciudad creada'
            mensaje = 'La ciudad fue enviada al backend Rehalife correctamente.'
        else:
            self._sync_update()
            titulo = 'Ciudad actualizada'
            mensaje = 'Los datos de la ciudad fueron actualizados en el backend Rehalife.'

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_delete_from_backend(self):
        """Boton: Eliminar ciudad del backend Rehalife (mantiene el registro en Odoo)."""
        self.ensure_one()
        if not self.external_id:
            raise UserError('Esta ciudad no esta sincronizada con el backend.')

        api_service = self.env['rehalife.api']
        try:
            api_service.delete_city(self.external_id)
            self.sudo().write({
                'external_id': False,
                'rehalife_sync_state': 'draft',
                'rehalife_sync_error': False,
            })
        except UserError as e:
            self.sudo().write({
                'rehalife_sync_state': 'error',
                'rehalife_sync_error': str(e),
            })
            raise

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    # ──────────────────────────────────────────────
    #  SYNC: Backend (Next.js) → Odoo
    # ──────────────────────────────────────────────

    @api.model
    def sync_from_backend(self):
        """Importa y actualiza todas las ciudades desde el backend."""
        api_service = self.env['rehalife.api']
        cities_data = api_service.get_cities()
        created = updated = 0
        for city_data in cities_data:
            ext_id = city_data.get('id')
            if not ext_id:
                continue
            existing = self.search([('external_id', '=', ext_id)], limit=1)
            vals = {
                'name': city_data.get('name', ''),
                'description': city_data.get('description', ''),
                'active': city_data.get('status', True),
                'external_id': str(ext_id),
                'rehalife_sync_state': 'synced',
                'rehalife_last_sync': fields.Datetime.now(),
            }
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.create(vals)
                created += 1
        _logger.info('Rehalife ciudades: %d creadas, %d actualizadas.', created, updated)
        return {'created': created, 'updated': updated}