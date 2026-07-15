# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class GanaderoConfig(models.TransientModel):
    _name = 'ganadero.config'
    _description = 'Configuracion de Pago QR'

    ganadero_api_url = fields.Char(
        string='URL del Servicio QR',
        help='URL base del servicio de pago QR, ej: http://10.1.232.23:8080',
    )
    ganadero_user = fields.Char(
        string='Usuario (Login)',
        help='Usuario con el que Odoo se autentica en /service/v1/qrcode/access',
    )
    ganadero_password = fields.Char(
        string='Contrasena (Login)',
    )
    ganadero_username_ordenes = fields.Char(
        string='Usuario para Ordenes',
        help='Usuario enviado en el campo "userName" al crear/consultar/anular '
             'ordenes QR (puede ser el mismo usuario de login)',
    )
    ganadero_api_key = fields.Char(
        string='API Key',
        help='Clave de API (X-Api-Key) asignada por el proveedor del servicio QR',
    )
    ganadero_account_reference = fields.Char(
        string='Cuenta (accountReference)',
        help='Referencia de la cuenta a la que se acreditan los cobros QR',
    )

    @api.model
    def default_get(self, fields_list):
        """Carga los valores actuales desde ir.config_parameter."""
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()
        res['ganadero_api_url'] = ICP.get_param('ganadero.api_url', '')
        res['ganadero_user'] = ICP.get_param('ganadero.user', '')
        res['ganadero_password'] = ICP.get_param('ganadero.password', '')
        res['ganadero_username_ordenes'] = ICP.get_param('ganadero.username_ordenes', '')
        res['ganadero_api_key'] = ICP.get_param('ganadero.api_key', '')
        res['ganadero_account_reference'] = ICP.get_param('ganadero.account_reference', '')
        return res

    def action_save(self):
        """Guarda los valores en ir.config_parameter."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ganadero.api_url', self.ganadero_api_url or '')
        ICP.set_param('ganadero.user', self.ganadero_user or '')
        ICP.set_param('ganadero.password', self.ganadero_password or '')
        ICP.set_param('ganadero.username_ordenes', self.ganadero_username_ordenes or '')
        ICP.set_param('ganadero.api_key', self.ganadero_api_key or '')
        ICP.set_param('ganadero.account_reference', self.ganadero_account_reference or '')
        # Limpiar token para forzar nuevo login con las nuevas credenciales
        ICP.set_param('ganadero.jwt_token', '')
        ICP.set_param('ganadero.jwt_token_expiry', '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Configuracion guardada',
                'message': 'Los parametros de configuracion QR fueron guardados correctamente.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_test_connection(self):
        """Prueba la conexion (login) con el servicio QR del Banco Ganadero."""
        self.action_save()
        try:
            self.env['ganadero.api'].test_connection()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Conexion exitosa',
                    'message': 'La conexion con el servicio de pago QR funciona correctamente.',
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
