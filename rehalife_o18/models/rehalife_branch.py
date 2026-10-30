# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class RehalifeBranch(models.Model):
    """Sucursal del backend Rehalife (espejo, solo referencia).

    El backend es la fuente de verdad: aquí solo se guarda id + nombre para
    poder vincular cada reserva a una sucursal real. Modelo simple a propósito:
    más adelante alpha.siat.sucursal tendrá un Many2one hacia este modelo.
    """
    _name = 'rehalife.branch'
    _description = 'Sucursal Rehalife'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True, index=True)
    external_id = fields.Char(
        string='ID Externo (Backend)',
        index=True,
        copy=False,
    )
    active = fields.Boolean(string='Activo', default=True)

    # PDV SIAT vinculados a esta sucursal (alpha.siat.sucursal.rehalife_branch_id).
    siat_sucursal_ids = fields.One2many(
        'alpha.siat.sucursal', 'rehalife_branch_id',
        string='Sucursales SIAT', readonly=True,
    )

    reservation_count = fields.Integer(
        string='Reservas',
        compute='_compute_reservation_count',
    )

    # UNIQUE en Postgres permite varios NULL: las sucursales sin ID externo no chocan.
    _sql_constraints = [
        ('external_id_uniq', 'UNIQUE(external_id)',
         'Ya existe una sucursal con ese ID externo.'),
    ]

    def _compute_reservation_count(self):
        counts = {}
        if self.ids:
            groups = self.env['rehalife.reservation']._read_group(
                [('branch_id', 'in', self.ids)], ['branch_id'], ['__count'],
            )
            counts = {branch.id: count for branch, count in groups}
        for branch in self:
            branch.reservation_count = counts.get(branch.id, 0)

    def action_view_reservations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reservas de %s' % self.name,
            'res_model': 'rehalife.reservation',
            'view_mode': 'list,form',
            'domain': [('branch_id', '=', self.id)],
        }

    # ──────────────────────────────────────────────
    #  Resolución desde los payloads de Next.js / backend
    # ──────────────────────────────────────────────

    @api.model
    def _get_or_create_from_external(self, external_id, name):
        """Devuelve la sucursal (recordset, puede ser vacío) para un UUID/nombre.

        - Con external_id: busca por él; si no existe la crea (nombre = name o,
          si viene vacío, el propio external_id); si existe y llega un name
          distinto no vacío, lo actualiza.
        - Sin external_id pero con name: búsqueda EXACTA por nombre; solo se
          devuelve si hay exactamente una coincidencia. Nunca crea por nombre.
        Nunca lanza excepción por datos faltantes.
        """
        Branch = self.with_context(active_test=False)
        external_id = str(external_id).strip() if external_id else ''
        name = (name or '').strip()

        if external_id:
            branch = Branch.search([('external_id', '=', external_id)], limit=1)
            if not branch:
                branch = Branch.create({
                    'name': name or external_id,
                    'external_id': external_id,
                })
                _logger.info('[Branch] Sucursal creada: %s (%s)', branch.name, external_id)
            elif name and branch.name != name:
                _logger.info(
                    '[Branch] Sucursal %s renombrada: "%s" -> "%s"',
                    external_id, branch.name, name,
                )
                branch.write({'name': name})
            return branch

        if name:
            branches = Branch.search([('name', '=', name)], limit=2)
            if len(branches) == 1:
                return branches

        return self.browse()

    # ──────────────────────────────────────────────
    #  SYNC: Backend → Odoo
    # ──────────────────────────────────────────────

    @api.model
    def sync_from_backend(self):
        """Importa/actualiza las sucursales del backend (upsert por external_id).

        Devuelve {'created': n, 'updated': n}. Las sucursales que ya no vienen
        del backend NO se borran ni se archivan. Igual que rehalife.city: los
        errores de conexión/credenciales llegan como UserError legible desde
        rehalife.api (_get_base_url, _get_credentials, _request).
        """
        branches_data = self.env['rehalife.api'].get_branches()
        Branch = self.with_context(active_test=False)
        created = updated = 0
        for branch_data in branches_data:
            ext_id = branch_data.get('id')
            if not ext_id:
                continue
            name = (branch_data.get('name') or '').strip()
            existing = Branch.search([('external_id', '=', str(ext_id))], limit=1)
            if not existing:
                created += 1
            elif name and existing.name != name:
                updated += 1
            self._get_or_create_from_external(ext_id, name)

        _logger.info('[Branch] Sincronización: %d creadas, %d actualizadas.', created, updated)
        return {'created': created, 'updated': updated}

    @api.model
    def backfill_reservations(self):
        """Asigna branch_id a reservas antiguas a partir de branch_name."""
        return self.env['rehalife.reservation']._backfill_branch_id()

    @api.model
    def _backfill_notification_params(self, result):
        """Parámetros de display_notification para el resultado del backfill.

        Amarilla y fija si quedaron nombres sin match. Se reusa desde
        rehalife.config (Configuración > Herramientas).
        """
        message = '%d reserva(s) actualizada(s). %d sin sucursal coincidente.' % (
            result['actualizadas'], result['sin_match'],
        )
        if result['nombres_sin_match']:
            message += (
                '\nNombres sin coincidencia: %s.\n'
                'Crea o corrige esas sucursales y vuelve a ejecutar esta acción.'
                % ', '.join(result['nombres_sin_match'])
            )
        return {
            'title': 'Asignación de sucursales',
            'message': message,
            'type': 'warning' if result['sin_match'] else 'success',
            'sticky': bool(result['sin_match']),
        }

    # Botones de la cabecera de la lista: SIN @api.model, porque un
    # <button type="object"> siempre pasa los ids (aunque sea una lista vacía).
    def action_sync_from_backend(self):
        result = self.sync_from_backend()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sucursales sincronizadas',
                'message': '%d creada(s), %d actualizada(s).' % (result['created'], result['updated']),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_backfill_reservations(self):
        params = self._backfill_notification_params(self.backfill_reservations())
        params['next'] = {'type': 'ir.actions.client', 'tag': 'soft_reload'}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }
