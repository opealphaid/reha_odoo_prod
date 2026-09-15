# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    nota_conformidad_ids = fields.One2many(
        'rehalife.nota.conformidad', 'factura_id', string='Notas de Conformidad',
    )
    nota_conformidad_count = fields.Integer(
        string='Cant. Notas de Conformidad', compute='_compute_nota_conformidad_count',
    )

    def _compute_nota_conformidad_count(self):
        for move in self:
            move.nota_conformidad_count = len(move.nota_conformidad_ids)

    def action_view_notas_conformidad(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Notas de Conformidad',
            'res_model': 'rehalife.nota.conformidad',
            'view_mode': 'list,form',
            'domain': [('factura_id', '=', self.id)],
        }

    # ── Ciclo de vida de las NC según el estado de la factura ──────────────
    # Decisión confirmada con el usuario (2026-09-08): 'facturada' no se
    # dispara al generar la factura (queda en borrador con la NC en su
    # estado previo — ver rehalife.nota.conformidad._generar_factura, que
    # crea una factura individual por NC aprobada, 2026-09-11), sino al
    # publicarla; 'pagada' es un hecho aparte y posterior, cuando se cobra.
    def action_post(self):
        result = super().action_post()
        for move in self:
            if move.move_type != 'out_invoice' or not move.nota_conformidad_ids:
                continue
            pendientes = move.nota_conformidad_ids.filtered(
                lambda n: n.estado in ('pendiente', 'aprobada')
            )
            if pendientes:
                pendientes.write({'estado': 'facturada'})
        return result

    def _compute_payment_state(self):
        super()._compute_payment_state()
        for move in self:
            if move.payment_state != 'paid' or not move.nota_conformidad_ids:
                continue
            facturadas = move.nota_conformidad_ids.filtered(
                lambda n: n.estado == 'facturada'
            )
            if facturadas:
                facturadas.write({'estado': 'pagada'})
