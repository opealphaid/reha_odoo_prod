# -*- coding: utf-8 -*-
import base64
import json
import logging
from datetime import datetime, timedelta

import requests

from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Margen usado cuando no se puede decodificar el 'exp' del JWT devuelto por el
# banco (ver _decode_jwt_expiry). No asumimos una vigencia larga por defecto.
TOKEN_FALLBACK_MARGIN_MINUTES = 20


class GanaderoAPI(models.AbstractModel):
    _name = 'ganadero.api'
    _description = 'Servicio API QR Banco Ganadero'

    # ── Configuracion ────────────────────────────────────────────────────
    def _get_base_url(self):
        url = self.env['ir.config_parameter'].sudo().get_param('ganadero.api_url', '')
        if not url:
            raise UserError('La URL del servicio de pago QR no esta configurada.')
        return url.rstrip('/')

    def _get_credentials(self):
        ICP = self.env['ir.config_parameter'].sudo()
        user = ICP.get_param('ganadero.user', '')
        password = ICP.get_param('ganadero.password', '')
        if not user or not password:
            raise UserError('Las credenciales del servicio de pago QR no estan configuradas.')
        return user, password

    def _get_api_key(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param('ganadero.api_key', '')
        if not api_key:
            raise UserError('El API Key del servicio de pago QR no esta configurado.')
        return api_key

    def _get_username_ordenes(self):
        ICP = self.env['ir.config_parameter'].sudo()
        username = ICP.get_param('ganadero.username_ordenes', '') or ICP.get_param('ganadero.user', '')
        if not username:
            raise UserError('El usuario para ordenes del servicio de pago QR no esta configurado.')
        return username

    def _get_account_reference(self):
        ref = self.env['ir.config_parameter'].sudo().get_param('ganadero.account_reference', '')
        if not ref:
            raise UserError('La cuenta (accountReference) del servicio de pago QR no esta configurada.')
        return ref

    # ── El sandbox real no respeta el "COD000" documentado en el PDF: usa
    #    COD200/COD201 segun el endpoint. Tratamos como exito cualquier
    #    codigo que empiece con "COD2" (ver banco-ganadero-qr-spec.md). ────
    @api.model
    def _is_success(self, result_code):
        return bool(result_code) and str(result_code).upper().startswith('COD2')

    # ── Token JWT: cacheado en ir.config_parameter ──────────────────────────
    def _decode_jwt_expiry(self, token):
        """Intenta leer el claim 'exp' del JWT sin validar la firma."""
        try:
            payload_b64 = token.split('.')[1]
            padding = '=' * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
            exp = payload.get('exp')
            if exp:
                # fromtimestamp (no utcfromtimestamp): 'exp' es epoch UTC y lo
                # comparamos contra datetime.now() (hora local naive).
                return datetime.fromtimestamp(exp)
        except Exception:
            _logger.warning(
                'Banco Ganadero: no se pudo decodificar el "exp" del JWT, '
                'se usara un margen conservador de %s minutos.',
                TOKEN_FALLBACK_MARGIN_MINUTES,
            )
        return None

    def _get_token(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('ganadero.jwt_token', '')
        expiry_str = ICP.get_param('ganadero.jwt_token_expiry', '')
        if token and expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                if datetime.now() < expiry - timedelta(minutes=1):
                    return token
            except (ValueError, TypeError):
                pass
        return self._login()

    def _login(self):
        base_url = self._get_base_url()
        user, password = self._get_credentials()
        api_key = self._get_api_key()
        try:
            response = requests.post(
                '%s/service/v1/qrcode/access' % base_url,
                json={'userName': user, 'password': password},
                headers={'X-Api-Key': api_key, 'Content-Type': 'application/json'},
                timeout=15,
            )
        except requests.exceptions.ConnectionError:
            raise UserError('No se pudo conectar con el servicio de pago QR: %s' % base_url)
        except requests.exceptions.Timeout:
            raise UserError('Tiempo de espera agotado al conectar con el servicio de pago QR.')

        try:
            data = response.json()
        except ValueError:
            data = {}

        if not response.ok or not self._is_success(data.get('result')):
            message = data.get('message') or 'Error desconocido (%s)' % (data.get('result') or response.status_code)
            raise UserError('Error de autenticacion con el servicio de pago QR: %s' % message)

        token = data.get('token')
        if not token:
            raise UserError('El servicio de pago QR no devolvio un token valido.')

        expiry = self._decode_jwt_expiry(token) or (
            datetime.now() + timedelta(minutes=TOKEN_FALLBACK_MARGIN_MINUTES)
        )

        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ganadero.jwt_token', token)
        ICP.set_param('ganadero.jwt_token_expiry', expiry.isoformat())

        _logger.info('Banco Ganadero: login exitoso. Token vigente hasta %s', expiry)
        return token

    def _get_headers(self):
        # El banco espera el token en el header "token", NO "Authorization".
        token = self._get_token()
        return {
            'token': token,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _request(self, endpoint, payload, retry=True):
        base_url = self._get_base_url()
        url = '%s%s' % (base_url, endpoint)
        headers = self._get_headers()
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
        except requests.exceptions.ConnectionError:
            raise UserError('No se pudo conectar con el servicio de pago QR: %s' % base_url)
        except requests.exceptions.Timeout:
            raise UserError('Tiempo de espera agotado al conectar con el servicio de pago QR.')
        except requests.exceptions.RequestException as e:
            raise UserError('Error inesperado al conectar con el servicio de pago QR: %s' % str(e))

        try:
            data = response.json()
        except ValueError:
            data = {}

        # Token vencido/invalido: forzar nuevo login y reintentar una sola vez
        if response.status_code == 401 and retry:
            ICP = self.env['ir.config_parameter'].sudo()
            ICP.set_param('ganadero.jwt_token', '')
            ICP.set_param('ganadero.jwt_token_expiry', '')
            return self._request(endpoint, payload, retry=False)

        result_code = data.get('result')
        if not response.ok or not self._is_success(result_code):
            message = data.get('message') or 'Error desconocido'
            _logger.warning('Servicio de pago QR: %s devolvio %s - %s', endpoint, result_code, message)
            raise UserError('Error del servicio de pago QR (%s): %s' % (result_code or response.status_code, message))

        return data

    # ── Operaciones QR ──────────────────────────────────────────────────────
    def create_qr_order(self, amount, reference, transaction_id, currency='BOB', expiration_minutes=2):
        """
        POST /service/v1/qrcode/collections
        Devuelve {'qr_id': ..., 'qr_image_base64': ...} (sin el prefijo data:image/...).
        """
        expiration_date = (datetime.now() + timedelta(minutes=expiration_minutes)).strftime('%d%m%Y')
        payload = {
            'accountReference': self._get_account_reference(),
            'amount': round(float(amount), 2),
            'currency': currency,
            # reference: max 10 caracteres · transactionId: max 12 caracteres (spec del banco)
            'reference': (reference or '')[:10],
            'transactionId': (transaction_id or '')[:12],
            'gloss': 'Cobro POS %s' % (reference or ''),
            'expirationDate': expiration_date,
            'singleUse': 1,
            'userName': self._get_username_ordenes(),
            'apiKey': self._get_api_key(),
        }
        data = self._request('/service/v1/qrcode/collections', payload)
        return {
            'qr_id': data.get('qrId'),
            'qr_image_base64': data.get('qrImage'),
        }

    def get_qr_status(self, qr_id):
        """
        POST /service/v1/qrcode/status
        orderState: '1' Registrado (pendiente) · '2' Pagado · '3' Anulado.
        """
        payload = {
            'qrId': qr_id,
            'userName': self._get_username_ordenes(),
            'apiKey': self._get_api_key(),
        }
        data = self._request('/service/v1/qrcode/status', payload)
        return {
            'order_state': data.get('orderState'),
            'transaction_number': data.get('transactionNumber'),
            'pay_date': data.get('payday') or data.get('payDate'),
            'pay_hour': data.get('payHour'),
        }

    def cancel_qr_order(self, qr_id):
        """
        POST /service/v1/qrcode/cancellations
        Solo se puede anular si el QR no fue pagado (orderState = 1).
        """
        payload = {
            'qrId': qr_id,
            'userName': self._get_username_ordenes(),
            'apiKey': self._get_api_key(),
        }
        self._request('/service/v1/qrcode/cancellations', payload)
        return True

    def test_connection(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ganadero.jwt_token', '')
        ICP.set_param('ganadero.jwt_token_expiry', '')
        self._login()
        return True
