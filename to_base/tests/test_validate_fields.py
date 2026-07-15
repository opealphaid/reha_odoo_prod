from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestValidateIrModelFields(TransactionCase):

    def test_01_validate_ir_model_fields(self):
        """Validate all Html fields after installation to avoid errors "Unsupported tracking on field"
        """
        supported_tracking = ['integer', 'float', 'char', 'text', 'date', 'datetime', 'monetary', 'boolean', 'selection', 'many2one', 'one2many', 'many2many']
        fields = self.env['ir.model.fields'].search([('ttype', 'not in', supported_tracking), ('tracking', '>', 0)])
        if fields:
            msg = ''
            for f in fields:
                msg += f'module {f.modules}, model {f.model}, field {f.name} (type {f.ttype})'
            self.fail('Unsupported tracking on field:\n%s' % msg)
