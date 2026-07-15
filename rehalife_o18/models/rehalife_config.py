# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class RehalifeConfig(models.TransientModel):
    _name = 'rehalife.config'
    _description = 'Configuracion Rehalife'

    rehalife_api_url = fields.Char(
        string='URL del Backend',
        help='URL base del backend Rehalife, ej: http://localhost:8080',
    )
    rehalife_admin_email = fields.Char(
        string='Email del Administrador',
    )
    rehalife_admin_password = fields.Char(
        string='Contrasena del Administrador',
    )

    @api.model
    def default_get(self, fields_list):
        """Carga los valores actuales desde ir.config_parameter."""
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()
        res['rehalife_api_url'] = ICP.get_param('rehalife.api_url', '')
        res['rehalife_admin_email'] = ICP.get_param('rehalife.admin_email', '')
        res['rehalife_admin_password'] = ICP.get_param('rehalife.admin_password', '')
        return res

    def action_save(self):
        """Guarda los valores en ir.config_parameter."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('rehalife.api_url', self.rehalife_api_url or '')
        ICP.set_param('rehalife.admin_email', self.rehalife_admin_email or '')
        ICP.set_param('rehalife.admin_password', self.rehalife_admin_password or '')
        # Limpiar token para forzar nuevo login con nuevas credenciales
        ICP.set_param('rehalife.jwt_token', '')
        ICP.set_param('rehalife.jwt_token_expiry', '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Configuracion guardada',
                'message': 'Los parametros del backend Rehalife fueron guardados correctamente.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_test_rehalife_connection(self):
        """Prueba la conexion con el backend."""
        self.action_save()
        try:
            self.env['rehalife.api'].test_connection()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Conexion exitosa',
                    'message': 'La conexion con el backend Rehalife funciona correctamente.',
                    'type': 'success',
                    'sticky': False,
                },
            }
        except UserError as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de conexion',
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                },
            }

    def action_sync_cities(self):
        """Sincroniza ciudades desde el backend."""
        self.action_save()
        result = self.env['rehalife.city'].sync_from_backend()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Ciudades sincronizadas',
                'message': '%d creadas, %d actualizadas.' % (result['created'], result['updated']),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_sync_patients(self):
        """Importa pacientes desde el backend."""
        self.action_save()
        result = self.env['res.partner'].sync_patients_from_backend()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pacientes sincronizados',
                'message': '%d creados, %d actualizados, %d omitidos.' % (
                    result['created'], result['updated'], result['skipped']
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_import_reservations(self):
        """Abre el wizard de importacion de reservas completadas."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rehalife.import.reservations.wizard',
            'view_mode': 'form',
            'target': 'new',
        }