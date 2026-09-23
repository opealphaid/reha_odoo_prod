# -*- coding: utf-8 -*-
from odoo import models


class RehalifeApiSeguros(models.AbstractModel):
    _inherit = 'rehalife.api'

    def get_insurance_providers(self):
        """GET /insurance-providers — Retorna lista de aseguradoras activas."""
        result = self._request('GET', '/insurance-providers')
        return result.get('data', [])

    def create_insurance_provider(self, name):
        """POST /insurance-providers — Crea una aseguradora solo con el nombre
        (único campo obligatorio según CREAR.bru; el backend responde 400 si
        ya existe una activa con ese nombre)."""
        return self._request('POST', '/insurance-providers', data={'name': name})

    def get_patient_insurances_by_provider(self, provider_id):
        """GET /patient-insurances/insurance-provider/:id — Pacientes
        afiliados a una aseguradora. No existe un endpoint que liste TODAS
        las afiliaciones, por eso el sync recorre las aseguradoras conocidas
        una por una (ver rehalife_seguros_res_partner.py)."""
        result = self._request(
            'GET', '/patient-insurances/insurance-provider/%s' % provider_id
        )
        return result.get('data', [])
