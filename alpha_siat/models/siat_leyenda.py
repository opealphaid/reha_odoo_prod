import logging
from odoo import models, fields, api
import random

_logger = logging.getLogger(__name__)


class SiatLeyenda(models.Model):
    _name = "alpha.siat.leyenda"
    _description = "SIAT - Leyendas para Facturas"
    _order = "codigo_actividad, id"
    _rec_name = "descripcion_leyenda"

    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
        string="Company"
    )

    codigo_actividad = fields.Char(
        string="Código Actividad (CAEB)",
        required=True,
        index=True,
        help="Código de Actividad Económica de Bolivia"
    )

    actividad_id = fields.Many2one(
        "alpha.siat.actividad",
        string="Actividad Económica",
        compute="_compute_actividad_id",
        store=True,
        help="Relación con la actividad económica"
    )

    descripcion_leyenda = fields.Text(
        string="Descripción Leyenda",
        required=True,
        help="Texto de la leyenda que debe aparecer en la factura"
    )

    active = fields.Boolean(
        default=True,
        help="Si está inactivo, significa que ya no existe en SIAT"
    )

    ultima_sincronizacion = fields.Datetime(
        string="Última Sincronización",
        readonly=True,
        help="Fecha y hora de la última sincronización con SIAT"
    )

    # No unique constraint because same activity can have multiple different legends

    @api.depends('codigo_actividad', 'company_id')
    def _compute_actividad_id(self):
        """Link to alpha.siat.actividad if exists"""
        for record in self:
            if record.codigo_actividad and record.company_id:
                actividad = self.env['alpha.siat.actividad'].search([
                    ('codigo_caeb', '=', record.codigo_actividad),
                    ('company_id', '=', record.company_id.id)
                ], limit=1)
                record.actividad_id = actividad.id if actividad else False
            else:
                record.actividad_id = False

    def name_get(self):
        """Display format: [Activity] Legend (truncated)"""
        result = []
        for record in self:
            legend = record.descripcion_leyenda[:60] + '...' if len(
                record.descripcion_leyenda) > 60 else record.descripcion_leyenda
            name = f"[{record.codigo_actividad}] {legend}"
            result.append((record.id, name))
        return result

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow searching by activity code or legend text"""
        args = args or []
        if name:
            args = ['|',
                    ('codigo_actividad', operator, name),
                    ('descripcion_leyenda', operator, name)] + args
        return self._search(args, limit=limit, access_rights_uid=name_get_uid)

    @api.model
    def get_random_leyenda_for_actividad(self, codigo_actividad, company_id=None):
        """
        Get a random legend for a given activity code.
        According to Bolivian regulations, one legend must be randomly selected
        from the available legends for the activity and printed on each invoice.

        :param codigo_actividad: CAEB activity code
        :param company_id: Company ID (uses current company if not provided)
        :return: legend text string or False
        """
        if not company_id:
            company_id = self.env.company.id

        leyendas = self.search([
            ('codigo_actividad', '=', codigo_actividad),
            ('company_id', '=', company_id),
            ('active', '=', True)
        ])

        if not leyendas:
            _logger.warning(
                "No legends found for activity %s and company %s",
                codigo_actividad, company_id
            )
            return False

        # Randomly select one legend
        selected = random.choice(leyendas)
        return selected.descripcion_leyenda

    @api.model
    def sync_from_siat_response(self, company, leyendas_list):
        """
        Synchronize legends from SIAT response

        :param company: res.company record
        :param leyendas_list: list of dicts with codigoActividad, descripcionLeyenda
        :return: dict with statistics
        """
        if not leyendas_list:
            _logger.warning("No legends to synchronize")
            return {'created': 0, 'updated': 0, 'deactivated': 0}

        created = 0
        updated = 0
        sync_time = fields.Datetime.now()

        # Get all existing legends for this company
        existing_records = self.search([('company_id', '=', company.id)])

        # Build a map of existing legends by (activity, description)
        # Since there's no unique constraint, we need to match by both fields
        existing_map = {}
        for rec in existing_records:
            key = (rec.codigo_actividad, rec.descripcion_leyenda)
            if key not in existing_map:
                existing_map[key] = []
            existing_map[key].append(rec)

        synced_keys = set()

        for ley_data in leyendas_list:
            codigo_act = ley_data.get('codigoActividad', '').strip()
            desc_ley = ley_data.get('descripcionLeyenda', '').strip()

            if not codigo_act or not desc_ley:
                continue

            key = (codigo_act, desc_ley)
            synced_keys.add(key)

            vals = {
                'company_id': company.id,
                'codigo_actividad': codigo_act,
                'descripcion_leyenda': desc_ley,
                'ultima_sincronizacion': sync_time,
                'active': True,
            }

            if key in existing_map:
                # Update existing record(s) - take the first one if there are duplicates
                existing_rec = existing_map[key][0]
                if not existing_rec.active:
                    existing_rec.write(vals)
                    updated += 1
                else:
                    # Just update sync time
                    existing_rec.write({'ultima_sincronizacion': sync_time})

                # If there are duplicate records in DB (shouldn't happen but handle it)
                # mark the rest as inactive
                if len(existing_map[key]) > 1:
                    for dup_rec in existing_map[key][1:]:
                        if dup_rec.active:
                            dup_rec.write({'active': False, 'ultima_sincronizacion': sync_time})
            else:
                # Create new record
                self.create(vals)
                created += 1

        # Deactivate legends that are no longer in SIAT
        keys_to_deactivate = set(existing_map.keys()) - synced_keys
        deactivated = 0
        if keys_to_deactivate:
            for key in keys_to_deactivate:
                for rec in existing_map[key]:
                    if rec.active:
                        rec.write({
                            'active': False,
                            'ultima_sincronizacion': sync_time
                        })
                        deactivated += 1

        _logger.info(
            "SIAT Legends sync completed for %s: %d created, %d updated, %d deactivated",
            company.name, created, updated, deactivated
        )

        return {
            'created': created,
            'updated': updated,
            'deactivated': deactivated,
            'total_synced': len(synced_keys)
        }