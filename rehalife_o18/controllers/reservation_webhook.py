# -*- coding: utf-8 -*-
import logging
import json
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

WEBHOOK_TOKEN_KEY = 'rehalife.webhook_token'


class RehalifeReservationController(http.Controller):

    def _check_token(self):
        """Valida Bearer token contra ir.config_parameter."""
        auth_header = request.httprequest.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '').strip()
        if not token:
            return False
        expected = request.env['ir.config_parameter'].sudo().get_param(
            WEBHOOK_TOKEN_KEY, ''
        )
        return bool(expected) and token == expected

    # ─── PING — para verificar que el controller responde ────────────────────
    @http.route(
        '/rehalife/ping',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def ping(self, **kwargs):
        return request.make_json_response({'ok': True, 'module': 'rehalife_o18'})

    # ─── Webhook: sincronizar reserva (POST JSON) ─────────────────────────────
    @http.route(
        '/rehalife/reservation/sync',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def sync_reservation(self, **kwargs):
        if not self._check_token():
            return request.make_json_response(
                {'success': False, 'message': 'No autorizado'}, status=401
            )
        try:
            body = json.loads(request.httprequest.data or '{}')
            _logger.info('[Webhook] Reserva recibida: %s', body.get('external_id'))
            result = request.env['rehalife.reservation'].sudo().sync_from_nextjs(body)
            return request.make_json_response({'success': True, **result})
        except Exception as e:
            _logger.error('[Webhook] Error sync reserva: %s', str(e))
            return request.make_json_response(
                {'success': False, 'message': str(e)}, status=500
            )

    # ─── Endpoint: estado de una reserva (GET) ────────────────────────────────
    @http.route(
        '/rehalife/reservation/<string:external_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def get_reservation_status(self, external_id, **kwargs):
        if not self._check_token():
            return request.make_json_response(
                {'success': False, 'message': 'No autorizado'}, status=401
            )
        try:
            reservation = request.env['rehalife.reservation'].sudo().search(
                [('external_id', '=', external_id)], limit=1,
            )
            if not reservation:
                return request.make_json_response(
                    {'success': False, 'message': 'Reserva no encontrada'}, status=404
                )
            return request.make_json_response({
                'success': True,
                'id': reservation.id,
                'external_id': reservation.external_id,
                'status': reservation.status,
                'invoice_status': reservation.invoice_status,
                'invoice_id': reservation.invoice_id.id if reservation.invoice_id else None,
                'invoice_name': reservation.invoice_id.name if reservation.invoice_id else None,
            })
        except Exception as e:
            _logger.error('[Webhook] Error consultando reserva %s: %s', external_id, str(e))
            return request.make_json_response(
                {'success': False, 'message': str(e)}, status=500
            )

    # ─── SIAT: tipos de documento (GET) ──────────────────────────────────────
    @http.route(
        '/rehalife/siat/tipos-documento',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def get_tipos_documento(self, **kwargs):
        if not self._check_token():
            return request.make_json_response(
                {'success': False, 'message': 'No autorizado'}, status=401
            )
        try:
            tipos = request.env['alpha.siat.tipo.documento.identidad'].sudo().search(
                [('active', '=', True)]
            )
            result = [
                {
                    'id': t.id,
                    'codigo': t.codigo_clasificador,
                    'descripcion': t.descripcion,
                }
                for t in tipos
            ]
            return request.make_json_response(result)
        except Exception as e:
            _logger.error('[SIAT] Error listando tipos documento: %s', str(e))
            return request.make_json_response(
                {'success': False, 'message': str(e)}, status=500
            )

    # ─── SIAT: datos del partner por external_id (GET) ────────────────────────
    @http.route(
        '/rehalife/partner/<string:external_id>/siat-data',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def get_partner_siat_data(self, external_id, **kwargs):
        if not self._check_token():
            return request.make_json_response(
                {'success': False, 'message': 'No autorizado'}, status=401
            )
        try:
            partner = request.env['res.partner'].sudo().search(
                [('rehalife_external_id', '=', external_id)], limit=1
            )
            if not partner:
                return request.make_json_response(
                    {'success': False, 'message': 'Paciente no encontrado'}, status=404
                )
            data = partner.get_siat_customer_data()
            return request.make_json_response({'success': True, **data})
        except Exception as e:
            _logger.error('[SIAT] Error obteniendo datos partner %s: %s', external_id, str(e))
            return request.make_json_response(
                {'success': False, 'message': str(e)}, status=500
            )

    # ─── Webhook: sincronizar estado de pago (POST) ───────────────────────────
    @http.route(
        '/rehalife/reservation/payment-status',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def sync_payment_status(self, **kwargs):
        if not self._check_token():
            return request.make_json_response(
                {'success': False, 'message': 'No autorizado'}, status=401
            )
        try:
            body = json.loads(request.httprequest.data or '{}')
            external_id = body.get('external_id')
            Reservation = request.env['rehalife.reservation'].sudo()
            if external_id:
                reservations = Reservation.search([('external_id', '=', external_id)])
            else:
                reservations = Reservation.search([
                    ('invoice_id', '!=', False),
                    ('invoice_status', 'not in', ['paid', 'cancelled']),
                ])
            reservations._sync_invoice_payment_state()
            return request.make_json_response({'success': True, 'updated': len(reservations)})
        except Exception as e:
            _logger.error('[Webhook] Error sync payment: %s', str(e))
            return request.make_json_response(
                {'success': False, 'message': str(e)}, status=500
            )