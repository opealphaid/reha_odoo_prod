# -*- coding: utf-8 -*-
import logging
from datetime import date
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def _parse_backend_date(value):
    """Convierte la fecha del backend a date. Acepta 'YYYY-MM-DD' y datetime ISO
    ('...T00:00:00', con milisegundos, 'Z' u offset). Devuelve False si no hay
    valor o no se puede parsear (nunca lanza excepcion)."""
    if not value:
        return False
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        _logger.warning('Rehalife: fecha invalida recibida del backend: %r', value)
        return False


class ResPartner(models.Model):
    _inherit = 'res.partner'

    es_paciente = fields.Boolean(string='Es Paciente', default=False, tracking=True)
    rehalife_first_name = fields.Char(string='Nombre', tracking=True)
    rehalife_last_name = fields.Char(string='Apellido Paterno', tracking=True)
    mother_last_name = fields.Char(string='Apellido Materno', tracking=True)
    birth_date = fields.Date(string='Fecha de Nacimiento', tracking=True)
    rehalife_city_id = fields.Many2one(
        comodel_name='rehalife.city', string='Ciudad', tracking=True,
    )
    rehalife_external_id = fields.Char(
        string='ID Externo Rehalife', copy=False, readonly=True, index=True,
    )
    rehalife_sync_state = fields.Selection(
        selection=[
            ('draft', 'No sincronizado'),
            ('synced', 'Sincronizado'),
            ('error', 'Error'),
        ],
        string='Estado Sync', default='draft', readonly=True,
    )
    rehalife_sync_error = fields.Text(string='Error de Sync', readonly=True)
    rehalife_last_sync = fields.Datetime(string='Ultima Sincronizacion', readonly=True)

    @api.onchange('rehalife_first_name', 'rehalife_last_name', 'mother_last_name')
    def _onchange_rehalife_name(self):
        if self.es_paciente:
            parts = [self.rehalife_first_name, self.rehalife_last_name, self.mother_last_name]
            full_name = ' '.join(p for p in parts if p)
            if full_name:
                self.name = full_name

    @api.onchange('es_paciente')
    def _onchange_es_paciente(self):
        if not self.es_paciente:
            self.rehalife_sync_state = 'draft'

    def _get_paciente_missing_fields(self):
        """Etiquetas de los campos obligatorios de paciente que estan vacios.
        Usado por la constraint y por la importacion desde el backend."""
        self.ensure_one()
        missing = []
        if not self.rehalife_first_name:
            missing.append('Nombre')
        if not self.rehalife_last_name:
            missing.append('Apellido Paterno')
        if not self.email:
            missing.append('Email')
        if not self.vat:
            missing.append('NIT/CI')
        if not self.siat_tipo_documento_identidad_id:
            missing.append('Tipo de Documento')
        if not self.rehalife_city_id:
            missing.append('Ciudad')
        return missing

    @api.constrains('es_paciente', 'email', 'vat',
                    'siat_tipo_documento_identidad_id',
                    'rehalife_first_name', 'rehalife_last_name', 'rehalife_city_id')
    def _check_paciente_required_fields(self):
        # La importacion desde el backend (fuente de verdad) no se bloquea;
        # los faltantes se registran en rehalife_sync_error.
        if self.env.context.get('skip_rehalife_sync'):
            return
        for rec in self:
            if rec.es_paciente:
                errors = rec._get_paciente_missing_fields()
                if errors:
                    raise ValidationError(
                        'Campos obligatorios para pacientes Rehalife:\n%s'
                        % '\n'.join('- %s' % e for e in errors)
                    )

    def _build_rehalife_payload(self, is_create=False):
        self.ensure_one()
        api_service = self.env['rehalife.api']
        admin_user_id = api_service._get_admin_user_id()

        payload = {
            'firstName': self.rehalife_first_name or '',
            'lastName': self.rehalife_last_name or '',
            'motherLastName': self.mother_last_name or '',
            'email': self.email or '',
            'phone': self.phone or '',
            'documentNumber': self.vat or '',
            'complemento': self.siat_complemento or '',
            'cityId': self.rehalife_city_id.external_id if self.rehalife_city_id else '',
            'userId': admin_user_id,
        }
        # Sin fecha se omite la clave. Ojo: en PUT el backend la borra igual
        # (omitida, "" o null); _sync_update protege ese caso.
        if self.birth_date:
            payload['birthDate'] = self.birth_date.isoformat()
        if is_create:
            payload['password'] = 'Alpha123!'
            payload['role'] = 'PATIENT'
        else:
            payload['status'] = self.active
        return payload

    def write(self, vals):
        result = super().write(vals)
        return result

    def unlink(self):
        api_service = self.env['rehalife.api']
        for record in self.filtered(lambda r: r.es_paciente and r.rehalife_external_id):
            try:
                api_service.delete_patient(record.rehalife_external_id)
            except UserError as e:
                raise UserError(
                    'No se pudo eliminar "%s" del backend:\n%s' % (record.name, e)
                )
        return super().unlink()

    def _sync_create(self):
        self.ensure_one()
        api_service = self.env['rehalife.api']
        try:
            payload = self._build_rehalife_payload(is_create=True)
            _logger.info('Rehalife: Creando paciente: %s', payload.get('email'))
            result = api_service.create_patient(payload)
            patient_data = result.get('data', {})
            ext_id = patient_data.get('id') if isinstance(patient_data, dict) else None
            self.env.cr.execute(
                """UPDATE res_partner SET
                    rehalife_external_id = %s,
                    rehalife_sync_state = 'synced',
                    rehalife_sync_error = NULL,
                    rehalife_last_sync = NOW()
                WHERE id = %s""",
                (ext_id, self.id)
            )
            self.invalidate_recordset()
        except UserError as e:
            self.env.cr.execute(
                """UPDATE res_partner SET
                    rehalife_sync_state = 'error',
                    rehalife_sync_error = %s
                WHERE id = %s""",
                (str(e), self.id)
            )
            self.invalidate_recordset()
            raise

    def _sync_update(self):
        self.ensure_one()
        api_service = self.env['rehalife.api']
        try:
            payload = self._build_rehalife_payload(is_create=False)
            if not self.birth_date:
                # El PUT del backend reemplaza el registro completo: sin
                # birthDate borraria la fecha que tenga alla. Se consulta antes
                # y, si falla la consulta, NO se hace el PUT.
                try:
                    backend_data = api_service.get_patient(self.rehalife_external_id)
                except UserError as e:
                    raise UserError(
                        'No se actualizo el paciente en el backend: no se pudo '
                        'consultar su fecha de nacimiento actual (se evita '
                        'borrarla).\n%s' % e
                    )
                backend_birth = _parse_backend_date(backend_data.get('birthDate'))
                if backend_birth:
                    payload['birthDate'] = backend_birth.isoformat()
                    self.with_context(skip_rehalife_sync=True).write(
                        {'birth_date': backend_birth}
                    )
            _logger.info('Rehalife: Actualizando paciente %s payload: %s',
                         self.rehalife_external_id, payload)
            api_service.update_patient(self.rehalife_external_id, payload)
            self.env.cr.execute(
                """UPDATE res_partner SET
                    rehalife_sync_state = 'synced',
                    rehalife_sync_error = NULL,
                    rehalife_last_sync = NOW()
                WHERE id = %s""",
                (self.id,)
            )
            self.invalidate_recordset()
        except UserError as e:
            self.env.cr.execute(
                """UPDATE res_partner SET
                    rehalife_sync_state = 'error',
                    rehalife_sync_error = %s
                WHERE id = %s""",
                (str(e), self.id)
            )
            self.invalidate_recordset()
            raise

    def action_sync_rehalife(self):
        """Boton: Sincronizar / Actualizar en el backend Rehalife."""
        self.ensure_one()
        if not self.es_paciente:
            raise UserError('Este contacto no es un paciente Rehalife.')

        is_new = not self.rehalife_external_id

        if is_new:
            self._sync_create()
            titulo = 'Paciente creado'
            mensaje = 'El paciente fue enviado al backend Rehalife correctamente.'
        else:
            self._sync_update()
            titulo = 'Paciente actualizado'
            mensaje = 'Los datos del paciente fueron actualizados en el backend Rehalife.'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': titulo,
                'message': mensaje,
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def sync_patients_from_backend(self):
        """Importa y actualiza todos los pacientes desde el backend."""
        api_service = self.env['rehalife.api']
        patients_data = api_service.get_patients()

        # Precargar todos los tipos de documento para evitar N+1 queries
        tipos_doc = self.env['alpha.siat.tipo.documento.identidad'].search(
            [('active', '=', True)]
        )
        tipos_dict = {t.codigo_clasificador: t.id for t in tipos_doc}

        created = updated = skipped = incomplete = 0

        for p in patients_data:
            ext_id = p.get('id')
            if not ext_id:
                skipped += 1
                continue

            # Buscar ciudad local
            city = False
            city_data = p.get('city')
            if city_data and city_data.get('id'):
                city = self.env['rehalife.city'].search(
                    [('external_id', '=', city_data['id'])], limit=1
                )

            # Fecha de nacimiento (opcional en el backend)
            birth_date = _parse_backend_date(p.get('birthDate'))

            first_name = p.get('firstName', '')
            last_name = p.get('lastName', '')
            mother_last = p.get('motherLastName', '')
            full_name = ' '.join(x for x in [first_name, last_name, mother_last] if x)

            # Tipo de documento: usar el codigo del backend o CI (codigo 1) por defecto
            doc_type_code = p.get('documentTypeCode') or 1
            tipo_doc_id = tipos_dict.get(doc_type_code) or tipos_dict.get(1) or False

            vals = {
                'es_paciente': True,
                'rehalife_external_id': ext_id,
                'rehalife_first_name': first_name,
                'rehalife_last_name': last_name,
                'mother_last_name': mother_last,
                'email': p.get('email', ''),
                'phone': p.get('phone', ''),
                'vat': p.get('documentNumber', ''),
                'siat_tipo_documento_identidad_id': tipo_doc_id,
                'siat_complemento': p.get('complemento', '') or False,
                'birth_date': birth_date,
                'active': p.get('status', True),
                'rehalife_sync_state': 'synced',
                'rehalife_last_sync': fields.Datetime.now(),
                'name': full_name or first_name,
            }
            if city:
                vals['rehalife_city_id'] = city.id

            existing = self.search(
                [('rehalife_external_id', '=', ext_id)], limit=1
            )

            # Usar contexto skip_rehalife_sync para evitar que write()
            # dispare la sincronizacion de vuelta al backend
            ctx = {'skip_rehalife_sync': True}

            # Savepoint por paciente: un error no aborta todo el lote
            try:
                with self.env.cr.savepoint():
                    if existing:
                        partner = existing.with_context(**ctx)
                        partner.write(vals)
                    else:
                        partner = self.with_context(**ctx).create(vals)
                    missing = partner._get_paciente_missing_fields()
                    partner.write({
                        'rehalife_sync_error': (
                            'Datos incompletos en backend: %s' % ', '.join(missing)
                        ) if missing else False,
                    })
            except Exception as e:
                _logger.error('Rehalife sync: error importando paciente %s: %s', ext_id, e)
                skipped += 1
                continue

            if existing:
                updated += 1
            else:
                created += 1
            if missing:
                incomplete += 1

        _logger.info('Rehalife sync: %d creados, %d actualizados, %d omitidos, '
                     '%d incompletos.', created, updated, skipped, incomplete)
        return {'created': created, 'updated': updated, 'skipped': skipped,
                'incomplete': incomplete}
