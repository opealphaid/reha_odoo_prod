# -*- coding: utf-8 -*-
import logging

from odoo import models, api

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ── Puente RPC para el POS: el JS nunca llama directo a ganadero.api ni
    #    conoce apiKey/usuario/token del banco, todo eso vive en Python. ────
    @api.model
    def ganadero_create_qr_order(self, amount, reference, transaction_id, currency='BOB', expiration_minutes=2):
        return self.env['ganadero.api'].create_qr_order(
            amount=amount,
            reference=reference,
            transaction_id=transaction_id,
            currency=currency,
            expiration_minutes=expiration_minutes,
        )

    @api.model
    def ganadero_get_qr_status(self, qr_id):
        return self.env['ganadero.api'].get_qr_status(qr_id)

    @api.model
    def ganadero_cancel_qr_order(self, qr_id):
        return self.env['ganadero.api'].cancel_qr_order(qr_id)
