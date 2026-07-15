# -*- coding: utf-8 -*-
import requests
import logging
from datetime import datetime, timedelta
from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RehalifeAPI(models.AbstractModel):
    _name = 'rehalife.api'
    _description = 'Servicio API Rehalife'

    def _get_base_url(self):
        url = self.env['ir.config_parameter'].sudo().get_param('rehalife.api_url', '')
        if not url:
            raise UserError('La URL del backend Rehalife no esta configurada.')
        return url.rstrip('/')

    def _get_credentials(self):
        ICP = self.env['ir.config_parameter'].sudo()
        email = ICP.get_param('rehalife.admin_email', '')
        password = ICP.get_param('rehalife.admin_password', '')
        if not email or not password:
            raise UserError('Las credenciales del backend Rehalife no estan configuradas.')
        return email, password

    def _get_token(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('rehalife.jwt_token', '')
        token_expiry_str = ICP.get_param('rehalife.jwt_token_expiry', '')
        if token and token_expiry_str:
            try:
                token_expiry = datetime.fromisoformat(token_expiry_str)
                if datetime.now() < token_expiry - timedelta(minutes=5):
                    return token
            except (ValueError, TypeError):
                pass
        return self._login()

    def _login(self):
        base_url = self._get_base_url()
        email, password = self._get_credentials()
        try:
            response = requests.post(
                '%s/auth/login' % base_url,
                json={'email': email, 'password': password},
                timeout=15,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise UserError('No se pudo conectar al backend Rehalife: %s' % base_url)
        except requests.exceptions.Timeout:
            raise UserError('Tiempo de espera agotado.')
        except requests.exceptions.HTTPError as e:
            raise UserError('Error de autenticacion: %s' % e)

        data = response.json()
        if not data.get('success'):
            raise UserError('Login fallido: %s' % data.get('message', ''))

        token = data['data']['token']
        # Guardar tambien el userId del admin para usarlo en los requests
        admin_user_id = data['data']['id']
        expiry = datetime.now() + timedelta(hours=23)

        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('rehalife.jwt_token', token)
        ICP.set_param('rehalife.jwt_token_expiry', expiry.isoformat())
        ICP.set_param('rehalife.admin_user_id', admin_user_id)

        _logger.info('Rehalife: Login exitoso. Token renovado hasta %s', expiry)
        return token

    def _get_admin_user_id(self):
        """Retorna el userId del admin, haciendo login si es necesario."""
        self._get_token()  # Asegura que el login se hizo
        return self.env['ir.config_parameter'].sudo().get_param('rehalife.admin_user_id', '')

    def _get_headers(self):
        token = self._get_token()
        return {
            'Authorization': 'Bearer %s' % token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _request(self, method, endpoint, data=None, retry=True):
        base_url = self._get_base_url()
        url = '%s%s' % (base_url, endpoint)
        headers = self._get_headers()
        try:
            response = requests.request(
                method=method, url=url, headers=headers, json=data, timeout=15,
            )
            if response.status_code == 401 and retry:
                ICP = self.env['ir.config_parameter'].sudo()
                ICP.set_param('rehalife.jwt_token', '')
                ICP.set_param('rehalife.jwt_token_expiry', '')
                return self._request(method, endpoint, data=data, retry=False)

            if not response.ok:
                # Intentar parsear el cuerpo JSON del error
                try:
                    err_body = response.json()
                except Exception:
                    err_body = {}

                message = err_body.get('message', response.reason or 'Error desconocido')

                detail = err_body.get('data')
                if isinstance(detail, dict) and detail:
                    detail_lines = ['%s: %s' % (k, v) for k, v in detail.items()]
                    message = '%s\n%s' % (message, '\n'.join(detail_lines))
                elif isinstance(detail, str) and detail:
                    message = '%s: %s' % (message, detail)

                raise UserError('Error en el backend: %s' % message)

        except requests.exceptions.ConnectionError:
            raise UserError('No se pudo conectar al backend: %s' % base_url)
        except requests.exceptions.Timeout:
            raise UserError('Tiempo de espera agotado.')
        except UserError:
            raise
        except Exception as e:
            raise UserError('Error inesperado: %s' % str(e))

        try:
            return response.json()
        except Exception:
            return {}

    def get_cities(self):
        result = self._request('GET', '/cities')
        return result.get('data', [])

    def get_patients(self):
        result = self._request('GET', '/users')
        data = result.get('data', [])
        return [u for u in data if u.get('role') == 'PATIENT']

    def create_patient(self, vals):
        return self._request('POST', '/users', data=vals)

    def update_patient(self, user_id, vals):
        return self._request('PUT', '/users/%s' % user_id, data=vals)

    def delete_patient(self, user_id):
        return self._request('DELETE', '/users/%s' % user_id)

    def test_connection(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('rehalife.jwt_token', '')
        ICP.set_param('rehalife.jwt_token_expiry', '')
        self._login()
        return True

    def get_patients(self):
        """GET /users/rol/PATIENT — Retorna lista de pacientes."""
        result = self._request('GET', '/users/rol/PATIENT')
        return result.get('data', [])

    def get_cities(self):
        """GET /cities — Retorna lista de ciudades."""
        result = self._request('GET', '/cities')
        return result.get('data', [])

    def get_city(self, city_id):
        """GET /cities/:id — Retorna una ciudad por su ID externo."""
        result = self._request('GET', '/cities/%s' % city_id)
        return result.get('data', {})

    def create_city(self, vals):
        """POST /cities — Crea una ciudad en el backend."""
        return self._request('POST', '/cities', data=vals)

    def update_city(self, city_id, vals):
        """PUT /cities/:id — Actualiza una ciudad en el backend."""
        return self._request('PUT', '/cities/%s' % city_id, data=vals)

    def delete_city(self, city_id):
        """DELETE /cities/:id — Elimina una ciudad del backend."""
        return self._request('DELETE', '/cities/%s' % city_id)

    """Registro del pago de na reserva"""

    def register_payment(self, reservation_id, paid_amount, invoiced):
        """
        PATCH /reservations/register-payment/{reservationId}
        """
        return self._request(
            'PATCH',
            '/reservations/register-payment/%s' % reservation_id,
            data={
                'paid': True,
                'invoiced': invoiced,
                'paidAmount': str(round(paid_amount, 2)),
            }
        )

    def get_completed_reservations(self, date_from, date_to):
        """GET /reservations?startDate=...&endDate=...&status=COMPLETED"""
        endpoint = '/reservations?startDate=%s&endDate=%s&status=COMPLETED' % (date_from, date_to)
        result = self._request('GET', endpoint)
        return result.get('data', [])